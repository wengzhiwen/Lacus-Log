# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""
招募管理 REST API 路由
提供完整的招募管理REST接口，支持列表、详情、创建、更新、状态调整等功能
"""

from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import Blueprint, Response, jsonify, request
from flask_security import current_user, roles_accepted
from flask_wtf.csrf import ValidationError as CSRFValidationError
from flask_wtf.csrf import validate_csrf
from mongoengine import DoesNotExist, Q, ValidationError

from models.pilot import Pilot, Platform, Rank, Status, WorkMode
from models.recruit import (BroadcastDecision, InterviewDecision, Recruit,
                            RecruitChangeLog, RecruitChannel, RecruitStatus,
                            TrainingDecision)
from models.user import Role, User
from utils.logging_setup import get_logger
from utils.recruit_serializers import (create_error_response,
                                       create_success_response,
                                       serialize_change_log_list,
                                       serialize_recruit,
                                       serialize_recruit_grouped,
                                       serialize_recruit_list)
from utils.timezone_helper import (get_current_utc_time, local_to_utc,
                                   utc_to_local)

logger = get_logger('recruit')
recruits_api_bp = Blueprint('recruits_api', __name__)


def _get_overdue_recruits_query():
    """
    构建用于查询“鸽”状态招募的查询集。
    “鸽”定义为：处于非“已结束”状态，且超过约定时间未进入下一步。
    """
    now = get_current_utc_time()
    overdue_24h = now - timedelta(hours=24)
    overdue_7d = now - timedelta(days=7)

    # 1. 待面试，但预约时间已过24小时
    q1 = Q(status=RecruitStatus.PENDING_INTERVIEW) & Q(appointment_time__lt=overdue_24h)

    # 2. 待预约试播，但面试决策已超过7天
    q2 = Q(status=RecruitStatus.PENDING_TRAINING_SCHEDULE) & Q(interview_decision_time__lt=overdue_7d)

    # 3. 待试播，但预约的试播时间已过24小时
    q3 = Q(status=RecruitStatus.PENDING_TRAINING) & Q(scheduled_training_time__lt=overdue_24h)

    # 4. 待预约开播，但试播决策已超过7天
    q4 = Q(status=RecruitStatus.PENDING_BROADCAST_SCHEDULE) & Q(training_decision_time__lt=overdue_7d)

    # 5. 待开播，但预约的开播时间已过24小时
    q5 = Q(status=RecruitStatus.PENDING_BROADCAST) & Q(scheduled_broadcast_time__lt=overdue_24h)

    overdue_query = (q1 | q2 | q3 | q4 | q5)

    return Recruit.objects.filter(overdue_query)


def safe_strip(value):
    """安全地去除字符串两端空格，处理None值"""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return None


def validate_csrf_token():
    """验证CSRF令牌"""
    csrf_token = request.headers.get('X-CSRFToken')
    if not csrf_token:
        return False, '缺少CSRF令牌'
    try:
        validate_csrf(csrf_token)
        return True, None
    except CSRFValidationError as e:
        logger.warning('CSRF令牌验证失败: %s', str(e))
        return False, 'CSRF令牌无效'


def _record_changes(recruit, old_data, user, ip_address):
    """记录招募字段变更"""
    changes = []
    field_mapping = {
        'pilot': str(recruit.pilot.id) if recruit.pilot else None,
        'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
        'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
        'channel': recruit.channel.value if hasattr(recruit.channel, 'value') else recruit.channel,
        'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
        'remarks': recruit.remarks,
        'status': recruit.status.value if hasattr(recruit.status, 'value') else recruit.status,
        'scheduled_training_time': recruit.scheduled_training_time.isoformat() if getattr(recruit, 'scheduled_training_time', None) else None,
        'scheduled_broadcast_time': recruit.scheduled_broadcast_time.isoformat() if getattr(recruit, 'scheduled_broadcast_time', None) else None,
    }

    for field_name, new_value in field_mapping.items():
        old_value = old_data.get(field_name)
        if str(old_value) != str(new_value):
            change_log = RecruitChangeLog(recruit_id=recruit,
                                          user_id=user,
                                          field_name=field_name,
                                          old_value=str(old_value) if old_value is not None else '',
                                          new_value=str(new_value) if new_value is not None else '',
                                          ip_address=ip_address)
            changes.append(change_log)

    if changes:
        RecruitChangeLog.objects.insert(changes)
        logger.info('记录招募变更：主播%s，共%d个字段', recruit.pilot.nickname if recruit.pilot else 'N/A', len(changes))


def _get_client_ip():
    """获取客户端IP地址"""
    return request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR')


def _has_enum_value(enum_class, value):
    """检查值是否为枚举类的有效值"""
    if not value:
        return False
    try:
        enum_class(value)
        return True
    except ValueError:
        return False


def try_enum(enum_class, value, default=None):
    """安全地转换枚举值"""
    if not value:
        return default
    try:
        return enum_class(value)
    except (ValueError, AttributeError):
        return default


@recruits_api_bp.route('/api/recruits', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_recruits():
    """获取招募列表"""
    try:
        # 获取筛选参数
        status_filter = request.args.get('status', '进行中')
        recruiter_ids = request.args.getlist('recruiter_id')
        channel_filters = request.args.getlist('channel')
        created_from = request.args.get('created_from')
        created_to = request.args.get('created_to')
        q = request.args.get('q', '').strip()

        # 分页参数
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))

        # 排序参数
        sort_param = request.args.get('sort', '-created_at')

        # 初始化查询
        query = Recruit.objects

        # 状态筛选
        if status_filter == '进行中':
            # "进行中" = not "已结束" AND not "鸽"
            overdue_ids = [r.id for r in _get_overdue_recruits_query()]
            query = query.filter(status__ne=RecruitStatus.ENDED, id__nin=overdue_ids)
        elif status_filter == '鸽':
            # 超时逻辑
            query = _get_overdue_recruits_query()
        elif status_filter == '已结束':
            query = query.filter(status=RecruitStatus.ENDED)
        else:
            try:
                status_enum = RecruitStatus(status_filter)
                query = query.filter(status=status_enum)
            except ValueError:
                pass

        # 招募负责人筛选
        recruiter_ids = [rid for rid in recruiter_ids if rid]
        if recruiter_ids:
            try:
                query = query.filter(recruiter__in=recruiter_ids)
            except ValidationError:
                logger.warning('无效的招募负责人ID: %s', recruiter_ids)

        # 渠道筛选
        if channel_filters:
            valid_channels = [RecruitChannel(v) for v in channel_filters if _has_enum_value(RecruitChannel, v)]
            if valid_channels:
                query = query.filter(channel__in=valid_channels)

        # 创建时间范围筛选
        if created_from:
            try:
                created_from_date = datetime.fromisoformat(created_from.replace('Z', '+00:00'))
                query = query.filter(created_at__gte=created_from_date)
            except ValueError:
                logger.warning('无效的创建起始时间: %s', created_from)

        if created_to:
            try:
                created_to_date = datetime.fromisoformat(created_to.replace('Z', '+00:00'))
                created_to_date = created_to_date.replace(hour=23, minute=59, second=59)
                query = query.filter(created_at__lte=created_to_date)
            except ValueError:
                logger.warning('无效的创建结束时间: %s', created_to)

        # 搜索功能（主播昵称和真实姓名的模糊搜索）
        if q:
            query = query.filter(Q(pilot__nickname__icontains=q) | Q(pilot__real_name__icontains=q))

        # 排序处理
        if sort_param.startswith('-'):
            sort_field = sort_param[1:]
            if sort_field in ['created_at', 'updated_at', 'appointment_time']:
                query = query.order_by('-created_at')
            else:
                query = query.order_by('-created_at')
        else:
            sort_field = sort_param
            if sort_field in ['created_at', 'updated_at', 'appointment_time']:
                query = query.order_by('created_at')
            else:
                query = query.order_by('-created_at')

        # 分页查询
        total_items = query.count()
        recruits = query.skip((page - 1) * page_size).limit(page_size).all()
        total_pages = (total_items + page_size - 1) // page_size

        # 统计信息
        stats = {'total': total_items, 'status_stats': {}, 'channel_stats': {}, 'recruiter_stats': {}}

        # 计算各维度的统计
        for recruit in recruits:
            # 状态统计
            status_value = recruit.get_effective_status().value if recruit.get_effective_status() else 'None'
            stats['status_stats'][status_value] = stats['status_stats'].get(status_value, 0) + 1

            # 渠道统计
            channel_value = recruit.channel.value if recruit.channel else 'None'
            stats['channel_stats'][channel_value] = stats['channel_stats'].get(channel_value, 0) + 1

            # 招募负责人统计
            recruiter_nickname = recruit.recruiter.nickname if recruit.recruiter else '无'
            stats['recruiter_stats'][recruiter_nickname] = stats['recruiter_stats'].get(recruiter_nickname, 0) + 1

        # 序列化数据
        data = {'items': serialize_recruit_list(recruits), 'aggregations': stats}

        meta = {'pagination': {'page': page, 'page_size': page_size, 'total_items': total_items, 'total_pages': total_pages}}

        logger.info('获取招募列表成功：第%d页，共%d条记录', page, len(recruits))
        return jsonify(create_success_response(data, meta))

    except Exception as e:
        logger.error('获取招募列表失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取招募列表失败')), 500


@recruits_api_bp.route('/api/recruits/grouped', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_recruits_grouped():
    """获取分组的招募列表（用于首页展示）"""
    try:
        status_filter = request.args.get('status', '进行中')

        query = Recruit.objects

        if status_filter == '进行中':
            # "进行中" = not "已结束" AND not "鸽"
            overdue_ids = [r.id for r in _get_overdue_recruits_query()]
            query = query.filter(status__ne=RecruitStatus.ENDED, id__nin=overdue_ids)
        elif status_filter == '鸽':
            query = _get_overdue_recruits_query()
        elif status_filter == '已结束':
            query = query.filter(status=RecruitStatus.ENDED)
        else:
            try:
                status_enum = RecruitStatus(status_filter)
                query = query.filter(status=status_enum)
            except ValueError:
                pass

        all_recruits = list(query)
        grouped_data = serialize_recruit_grouped(all_recruits)

        logger.info('获取分组招募列表成功：共%d条记录', len(all_recruits))
        return jsonify(create_success_response(grouped_data))

    except Exception as e:
        logger.error('获取分组招募列表失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取分组招募列表失败')), 500


@recruits_api_bp.route('/api/recruits/<recruit_id>', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_recruit_detail(recruit_id):
    """获取招募详情"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)

        # 获取最近的变更记录
        recent_changes = RecruitChangeLog.objects(recruit_id=recruit).order_by('-change_time').limit(5)

        # 序列化基本信息
        recruit_data = serialize_recruit(recruit)
        recruit_data['recent_changes'] = [{
            'field_name': change.field_name,
            'field_display_name': change.field_display_name,
            'old_value': change.old_value,
            'new_value': change.new_value,
            'created_at': utc_to_local(change.change_time).isoformat() if change.change_time else None,
            'user_nickname': change.user_id.nickname if change.user_id else '未知用户',
        } for change in recent_changes]

        logger.info('获取招募详情成功：ID=%s，主播=%s', recruit_id, recruit.pilot.nickname)
        return jsonify(create_success_response(recruit_data))

    except DoesNotExist:
        return jsonify(create_error_response('RECRUIT_NOT_FOUND', '招募记录不存在')), 404
    except Exception as e:
        logger.error('获取招募详情失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取招募详情失败')), 500


@recruits_api_bp.route('/api/recruits/<recruit_id>/changes', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_recruit_changes(recruit_id):
    """获取招募变更记录"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)

        # 分页参数
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 20))

        # 获取变更记录
        changes_query = RecruitChangeLog.objects(recruit_id=recruit).order_by('-change_time')
        total_changes = changes_query.count()
        changes = changes_query.skip((page - 1) * page_size).limit(page_size).all()

        total_pages = (total_changes + page_size - 1) // page_size

        # 返回变更信息
        changes_data = serialize_change_log_list(changes)

        meta = {'pagination': {'page': page, 'page_size': page_size, 'total_items': total_changes, 'total_pages': total_pages}}

        return jsonify(create_success_response(changes_data, meta))

    except DoesNotExist:
        return jsonify(create_error_response('RECRUIT_NOT_FOUND', '招募记录不存在')), 404
    except Exception as e:
        logger.error('获取招募变更记录失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取招募变更记录失败')), 500


@recruits_api_bp.route('/api/recruits/options', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_recruit_options():
    """获取招募筛选器枚举选项"""
    try:
        # 枚举字典
        enum_dict = {
            'channel': {
                option.value: option.value
                for option in RecruitChannel
            },
            'status': {
                option.value: option.value
                for option in RecruitStatus
            },
            'interview_decision': {
                option.value: option.value
                for option in InterviewDecision if not option.name.endswith('_OLD')
            },
            'training_decision': {
                option.value: option.value
                for option in TrainingDecision if not option.name.endswith('_OLD')
            },
            'broadcast_decision': {
                option.value: option.value
                for option in BroadcastDecision if not option.name.endswith('_OLD')
            }
        }

        # 获取招募负责人选项
        role_docs = list(Role.objects.filter(name__in=['gicho', 'kancho']).only('id'))
        users = User.objects.filter(roles__in=role_docs).all()

        recruiter_choices = []
        if current_user.has_role('kancho') or current_user.has_role('gicho'):
            label = current_user.nickname or current_user.username
            if current_user.has_role('gicho'):
                label = f"{label} [管理员]"
            elif current_user.has_role('kancho'):
                label = f"{label} [运营]"
            recruiter_choices.append({'value': str(current_user.id), 'label': label})

        active_users = [u for u in users if u.active and u.id != current_user.id]
        active_users.sort(key=lambda x: x.nickname or x.username)
        for user in active_users:
            label = user.nickname or user.username
            if user.has_role('gicho'):
                label = f"{label} [管理员]"
            elif user.has_role('kancho'):
                label = f"{label} [运营]"
            recruiter_choices.append({'value': str(user.id), 'label': label})

        data = {'enums': enum_dict, 'recruiter_choices': recruiter_choices}

        return jsonify(create_success_response(data))

    except Exception as e:
        logger.error('获取招募选项数据失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取选项数据失败')), 500


@recruits_api_bp.route('/api/recruits/export', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def export_recruits():
    """导出招募数据"""
    logger.info('%s 请求导出招募数据', current_user.username)

    try:
        import csv
        import io

        # 获取筛选参数（复用列表接口的筛选逻辑）
        status_filter = request.args.get('status', '进行中')
        recruiter_ids = request.args.getlist('recruiter_id')
        channel_filters = request.args.getlist('channel')

        # 构建查询（复用列表接口的逻辑）
        query = Recruit.objects

        if status_filter == '进行中':
            # "进行中" = not "已结束" AND not "鸽"
            overdue_ids = [r.id for r in _get_overdue_recruits_query()]
            query = query.filter(status__ne=RecruitStatus.ENDED, id__nin=overdue_ids)
        elif status_filter == '鸽':
            query = _get_overdue_recruits_query()
        elif status_filter == '已结束':
            query = query.filter(status=RecruitStatus.ENDED)
        else:
            try:
                status_enum = RecruitStatus(status_filter)
                query = query.filter(status=status_enum)
            except ValueError:
                pass

        if recruiter_ids:
            try:
                recruiter_objects = User.objects(id__in=recruiter_ids)
                query = query.filter(recruiter__in=recruiter_objects)
            except ValidationError:
                pass

        if channel_filters:
            valid_channels = [RecruitChannel(v) for v in channel_filters if _has_enum_value(RecruitChannel, v)]
            if valid_channels:
                query = query.filter(channel__in=valid_channels)

        recruits = query.order_by('-created_at').all()

        # 创建CSV文件
        output = io.StringIO()
        writer = csv.writer(output)

        # CSV头部
        writer.writerow(['ID', '主播昵称', '主播真实姓名', '招募负责人', '预约时间', '渠道', '介绍费', '备注', '状态', '面试决策', '预约试播时间', '试播决策', '预约开播时间', '开播决策', '创建时间', '更新时间'])

        # 写入数据行
        for recruit in recruits:
            writer.writerow([
                str(recruit.id), recruit.pilot.nickname if recruit.pilot else '', recruit.pilot.real_name if recruit.pilot else '',
                recruit.recruiter.nickname if recruit.recruiter else '',
                utc_to_local(recruit.appointment_time).strftime('%Y-%m-%d %H:%M:%S') if recruit.appointment_time else '',
                recruit.channel.value if recruit.channel else '',
                float(recruit.introduction_fee) if recruit.introduction_fee else 0.0, recruit.remarks or '',
                recruit.get_effective_status().value if recruit.get_effective_status() else '',
                recruit.get_effective_interview_decision().value if recruit.get_effective_interview_decision() else '',
                utc_to_local(recruit.get_effective_scheduled_training_time()).strftime('%Y-%m-%d %H:%M:%S')
                if recruit.get_effective_scheduled_training_time() else '',
                recruit.get_effective_training_decision().value if recruit.get_effective_training_decision() else '',
                utc_to_local(recruit.get_effective_scheduled_broadcast_time()).strftime('%Y-%m-%d %H:%M:%S')
                if recruit.get_effective_scheduled_broadcast_time() else '',
                recruit.get_effective_broadcast_decision().value if recruit.get_effective_broadcast_decision() else '',
                utc_to_local(recruit.created_at).strftime('%Y-%m-%d %H:%M:%S') if recruit.created_at else '',
                utc_to_local(recruit.updated_at).strftime('%Y-%m-%d %H:%M:%S') if recruit.updated_at else ''
            ])

        output.seek(0)

        # 准备CSV内容
        csv_content = output.getvalue()

        # 添加BOM以支持Excel正确显示中文
        csv_with_bom = '\ufeff' + csv_content

        response = Response(csv_with_bom.encode('utf-8'),
                            mimetype='text/csv',
                            headers={
                                'Content-Disposition': 'attachment; filename="recruit_export.csv"',
                                'Content-Type': 'text/csv; charset=utf-8',
                                'Cache-Control': 'no-cache'
                            })

        logger.info('导出招募数据成功：导出 %d 条记录', len(recruits))
        return response

    except Exception as e:
        logger.error('导出招募数据失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '导出数据失败')), 500


@recruits_api_bp.route('/api/recruits', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def create_recruit():
    """创建招募"""
    try:
        # CSRF令牌验证
        csrf_valid, csrf_error = validate_csrf_token()
        if not csrf_valid:
            return jsonify(create_error_response('CSRF_ERROR', csrf_error)), 401

        data = request.get_json()
        if not data:
            return jsonify(create_error_response('INVALID_DATA', '请求数据格式错误')), 400

        # 数据验证
        pilot_id = data.get('pilot_id')
        if not pilot_id:
            return jsonify(create_error_response('VALIDATION_ERROR', '主播ID为必填项')), 400

        try:
            pilot = Pilot.objects.get(id=pilot_id)
        except DoesNotExist:
            return jsonify(create_error_response('PILOT_NOT_FOUND', '主播不存在')), 404

        if pilot.status != Status.NOT_RECRUITED:
            return jsonify(create_error_response('VALIDATION_ERROR', '只有未招募状态的主播才能启动招募')), 400

        existing_recruit = Recruit.objects.filter(pilot=pilot, status__in=['进行中', '鸽']).first()
        if existing_recruit:
            return jsonify(create_error_response('VALIDATION_ERROR', '该主播已有正在进行的招募')), 400

        recruiter_id = data.get('recruiter_id')
        if not recruiter_id:
            return jsonify(create_error_response('VALIDATION_ERROR', '招募负责人为必填项')), 400

        try:
            recruiter = User.objects.get(id=recruiter_id)
            if not (recruiter.has_role('kancho') or recruiter.has_role('gicho')):
                return jsonify(create_error_response('VALIDATION_ERROR', '招募负责人必须是运营或管理员')), 400
        except DoesNotExist:
            return jsonify(create_error_response('VALIDATION_ERROR', '无效的招募负责人')), 400

        appointment_time_str = data.get('appointment_time')
        if not appointment_time_str:
            return jsonify(create_error_response('VALIDATION_ERROR', '预约时间为必填项')), 400

        try:
            appointment_time_local = datetime.fromisoformat(appointment_time_str.replace('T', ' '))
            appointment_time_utc = local_to_utc(appointment_time_local)
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '预约时间格式不正确')), 400

        channel = data.get('channel')
        if not channel:
            return jsonify(create_error_response('VALIDATION_ERROR', '招募渠道为必填项')), 400

        try:
            channel_enum = RecruitChannel(channel)
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '无效的招募渠道')), 400

        introduction_fee = data.get('introduction_fee', 0)
        try:
            introduction_fee_decimal = Decimal(str(introduction_fee)).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                return jsonify(create_error_response('VALIDATION_ERROR', '介绍费不能为负数')), 400
        except (ValueError, InvalidOperation):
            return jsonify(create_error_response('VALIDATION_ERROR', '介绍费格式不正确')), 400

        remarks = safe_strip(data.get('remarks'))

        # 创建招募对象
        recruit = Recruit(pilot=pilot,
                          recruiter=recruiter,
                          appointment_time=appointment_time_utc,
                          channel=channel_enum,
                          introduction_fee=introduction_fee_decimal,
                          remarks=remarks,
                          status=RecruitStatus.PENDING_INTERVIEW)

        recruit.save()

        logger.info('启动招募：主播=%s，负责人=%s，预约时间=%s', pilot.nickname, recruiter.nickname or recruiter.username, appointment_time_utc)

        serializer_data = serialize_recruit(recruit)
        meta = {'message': '招募已成功启动'}
        return jsonify(create_success_response(serializer_data, meta)), 201

    except ValidationError as e:
        logger.error('创建招募验证失败：%s', str(e))
        return jsonify(create_error_response('VALIDATION_ERROR', f'数据验证失败：{str(e)}')), 400
    except Exception as e:
        logger.error('创建招募失败：%s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '创建招募失败')), 500


@recruits_api_bp.route('/api/recruits/<recruit_id>', methods=['PUT'])
@roles_accepted('gicho', 'kancho')
def update_recruit(recruit_id):
    """更新招募（整体更新）"""
    try:
        # CSRF令牌验证
        csrf_valid, csrf_error = validate_csrf_token()
        if not csrf_valid:
            return jsonify(create_error_response('CSRF_ERROR', csrf_error)), 401

        recruit = Recruit.objects.get(id=recruit_id)

        # 记录修改前的数据状态
        old_data = {
            'pilot': str(recruit.pilot.id) if recruit.pilot else None,
            'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
            'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
            'channel': recruit.channel.value if recruit.channel else None,
            'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
            'remarks': recruit.remarks,
            'status': recruit.status.value if recruit.status else None,
            'scheduled_training_time': recruit.scheduled_training_time.isoformat() if recruit.scheduled_training_time else None,
            'scheduled_broadcast_time': recruit.scheduled_broadcast_time.isoformat() if recruit.scheduled_broadcast_time else None,
        }

        data = request.get_json()
        if not data:
            return jsonify(create_error_response('INVALID_DATA', '请求数据格式错误')), 400

        # 验证招募负责人
        recruiter_id = data.get('recruiter_id')
        if not recruiter_id:
            return jsonify(create_error_response('VALIDATION_ERROR', '招募负责人为必填项')), 400

        try:
            recruiter = User.objects.get(id=recruiter_id)
            if not (recruiter.has_role('kancho') or recruiter.has_role('gicho')):
                return jsonify(create_error_response('VALIDATION_ERROR', '招募负责人必须是运营或管理员')), 400
        except DoesNotExist:
            return jsonify(create_error_response('VALIDATION_ERROR', '无效的招募负责人')), 400

        # 验证预约时间
        appointment_time_str = data.get('appointment_time')
        if not appointment_time_str:
            return jsonify(create_error_response('VALIDATION_ERROR', '预约时间为必填项')), 400

        try:
            appointment_time_local = datetime.fromisoformat(appointment_time_str.replace('T', ' '))
            appointment_time_utc = local_to_utc(appointment_time_local)
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '预约时间格式不正确')), 400

        # 验证渠道
        channel = data.get('channel')
        if not channel:
            return jsonify(create_error_response('VALIDATION_ERROR', '招募渠道为必填项')), 400

        try:
            channel_enum = RecruitChannel(channel)
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '无效的招募渠道')), 400

        # 验证介绍费
        introduction_fee = data.get('introduction_fee', 0)
        try:
            introduction_fee_decimal = Decimal(str(introduction_fee)).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                return jsonify(create_error_response('VALIDATION_ERROR', '介绍费不能为负数')), 400
        except (ValueError, InvalidOperation):
            return jsonify(create_error_response('VALIDATION_ERROR', '介绍费格式不正确')), 400

        remarks = safe_strip(data.get('remarks'))

        # 更新字段
        recruit.recruiter = recruiter
        recruit.appointment_time = appointment_time_utc
        recruit.channel = channel_enum
        recruit.introduction_fee = introduction_fee_decimal
        recruit.remarks = remarks

        # 处理预约时间相关字段
        effective_status = recruit.get_effective_status()
        scheduled_training_time_utc = recruit.scheduled_training_time
        scheduled_broadcast_time_utc = recruit.scheduled_broadcast_time

        scheduled_training_time_str = data.get('scheduled_training_time')
        if effective_status in [RecruitStatus.PENDING_TRAINING, RecruitStatus.PENDING_BROADCAST_SCHEDULE, RecruitStatus.PENDING_BROADCAST]:
            if scheduled_training_time_str:
                try:
                    _local = datetime.fromisoformat(scheduled_training_time_str.replace('T', ' '))
                    scheduled_training_time_utc = local_to_utc(_local)
                except ValueError:
                    return jsonify(create_error_response('VALIDATION_ERROR', '预约训练时间格式不正确')), 400
            elif scheduled_training_time_str == '':
                scheduled_training_time_utc = None

        scheduled_broadcast_time_str = data.get('scheduled_broadcast_time')
        if effective_status in [RecruitStatus.PENDING_BROADCAST]:
            if scheduled_broadcast_time_str:
                try:
                    _local_b = datetime.fromisoformat(scheduled_broadcast_time_str.replace('T', ' '))
                    scheduled_broadcast_time_utc = local_to_utc(_local_b)
                except ValueError:
                    return jsonify(create_error_response('VALIDATION_ERROR', '预约开播时间格式不正确')), 400
            elif scheduled_broadcast_time_str == '':
                scheduled_broadcast_time_utc = None

        if effective_status in [RecruitStatus.PENDING_TRAINING, RecruitStatus.PENDING_BROADCAST_SCHEDULE, RecruitStatus.PENDING_BROADCAST]:
            recruit.scheduled_training_time = scheduled_training_time_utc
        if effective_status in [RecruitStatus.PENDING_BROADCAST]:
            recruit.scheduled_broadcast_time = scheduled_broadcast_time_utc

        # 保存并记录变更
        recruit.updated_at = get_current_utc_time()
        recruit.save()
        _record_changes(recruit, old_data, current_user, _get_client_ip())

        logger.info('更新招募：ID=%s，主播=%s', recruit_id, recruit.pilot.nickname)
        serializer_data = serialize_recruit(recruit)
        meta = {'message': '招募信息已更新'}
        return jsonify(create_success_response(serializer_data, meta))

    except DoesNotExist:
        return jsonify(create_error_response('RECRUIT_NOT_FOUND', '招募记录不存在')), 404
    except ValidationError as e:
        logger.error('更新招募验证失败：%s', str(e))
        return jsonify(create_error_response('VALIDATION_ERROR', f'数据验证失败：{str(e)}')), 400
    except Exception as e:
        logger.error('更新招募失败：%s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '更新招募失败')), 500


@recruits_api_bp.route('/api/recruits/<recruit_id>/interview-decision', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def interview_decision(recruit_id):
    """执行面试决策"""
    try:
        # CSRF令牌验证
        csrf_valid, csrf_error = validate_csrf_token()
        if not csrf_valid:
            return jsonify(create_error_response('CSRF_ERROR', csrf_error)), 401

        recruit = Recruit.objects.get(id=recruit_id)

        effective_status = recruit.get_effective_status()
        if effective_status != RecruitStatus.PENDING_INTERVIEW:
            return jsonify(create_error_response('VALIDATION_ERROR', '只能对待面试状态的招募执行面试决策')), 400

        data = request.get_json()
        if not data:
            return jsonify(create_error_response('INVALID_DATA', '请求数据格式错误')), 400

        interview_decision_value = data.get('interview_decision')
        if not interview_decision_value:
            return jsonify(create_error_response('VALIDATION_ERROR', '面试决策为必填项')), 400

        try:
            interview_decision_enum = InterviewDecision(interview_decision_value)
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '无效的面试决策')), 400

        introduction_fee = data.get('introduction_fee', 0)
        try:
            introduction_fee_decimal = Decimal(str(introduction_fee)).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                return jsonify(create_error_response('VALIDATION_ERROR', '介绍费不能为负数')), 400
        except (ValueError, InvalidOperation):
            return jsonify(create_error_response('VALIDATION_ERROR', '介绍费格式不正确')), 400

        remarks = safe_strip(data.get('remarks'))

        # 验证预约试播时的必填字段
        if interview_decision_enum == InterviewDecision.SCHEDULE_TRAINING:
            real_name = safe_strip(data.get('real_name'))
            if not real_name:
                return jsonify(create_error_response('VALIDATION_ERROR', '预约试播时必须填写真实姓名')), 400

            birth_year_str = data.get('birth_year')
            if not birth_year_str:
                return jsonify(create_error_response('VALIDATION_ERROR', '预约试播时必须填写出生年')), 400

            try:
                birth_year = int(birth_year_str)
                current_year = datetime.now().year
                if birth_year < current_year - 60 or birth_year > current_year - 10:
                    return jsonify(create_error_response('VALIDATION_ERROR', '出生年必须在距今60年前到距今10年前之间')), 400
            except ValueError:
                return jsonify(create_error_response('VALIDATION_ERROR', '出生年格式不正确')), 400

        # 记录修改前的数据状态
        old_recruit_data = {
            'pilot': str(recruit.pilot.id) if recruit.pilot else None,
            'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
            'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
            'channel': recruit.channel.value if hasattr(recruit.channel, 'value') else recruit.channel,
            'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
            'remarks': recruit.remarks,
            'status': recruit.status.value if hasattr(recruit.status, 'value') else recruit.status,
        }

        old_pilot_data = {
            'nickname': recruit.pilot.nickname,
            'real_name': recruit.pilot.real_name,
            'gender': recruit.pilot.gender.value if hasattr(recruit.pilot.gender, 'value') else recruit.pilot.gender,
            'birth_year': recruit.pilot.birth_year,
            'owner': str(recruit.pilot.owner.id) if recruit.pilot.owner else None,
            'platform': recruit.pilot.platform.value if hasattr(recruit.pilot.platform, 'value') else recruit.pilot.platform,
            'work_mode': recruit.pilot.work_mode.value if hasattr(recruit.pilot.work_mode, 'value') else recruit.pilot.work_mode,
            'rank': recruit.pilot.rank.value if hasattr(recruit.pilot.rank, 'value') else recruit.pilot.rank,
            'status': recruit.pilot.status.value if hasattr(recruit.pilot.status, 'value') else recruit.pilot.status,
        }

        # 更新招募信息
        recruit.interview_decision = interview_decision_enum
        recruit.interview_decision_maker = current_user
        recruit.interview_decision_time = get_current_utc_time()
        recruit.introduction_fee = introduction_fee_decimal
        recruit.remarks = remarks

        if interview_decision_enum == InterviewDecision.SCHEDULE_TRAINING:
            recruit.status = RecruitStatus.PENDING_TRAINING_SCHEDULE

            # 更新主播信息
            recruit.pilot.real_name = real_name
            recruit.pilot.birth_year = birth_year
            recruit.pilot.rank = Rank.TRAINEE
            recruit.pilot.status = Status.RECRUITED
            recruit.pilot.save()
        else:
            recruit.status = RecruitStatus.ENDED

            recruit.pilot.status = Status.NOT_RECRUITING
            recruit.pilot.save()

        recruit.save()

        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        # 记录主播变更
        from routes.pilots_api import _record_changes as record_pilot_changes
        record_pilot_changes(recruit.pilot, old_pilot_data, current_user, _get_client_ip())

        if interview_decision_enum == InterviewDecision.SCHEDULE_TRAINING:
            logger.info('面试决策成功：ID=%s，主播=%s，预约试播', recruit_id, recruit.pilot.nickname)
            message = '面试决策成功，主播已进入待预约试播阶段'
        else:
            logger.info('面试决策完成：ID=%s，主播=%s，不招募', recruit_id, recruit.pilot.nickname)
            message = '面试决策完成，已决定不招募该主播'

        serializer_data = serialize_recruit(recruit)
        meta = {'message': message}
        return jsonify(create_success_response(serializer_data, meta))

    except DoesNotExist:
        return jsonify(create_error_response('RECRUIT_NOT_FOUND', '招募记录不存在')), 404
    except ValidationError as e:
        logger.error('面试决策验证失败：%s', str(e))
        return jsonify(create_error_response('VALIDATION_ERROR', f'数据验证失败：{str(e)}')), 400
    except Exception as e:
        logger.error('面试决策失败：%s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '面试决策失败')), 500


@recruits_api_bp.route('/api/recruits/<recruit_id>/schedule-training', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def schedule_training(recruit_id):
    """执行预约试播"""
    try:
        # CSRF令牌验证
        csrf_valid, csrf_error = validate_csrf_token()
        if not csrf_valid:
            return jsonify(create_error_response('CSRF_ERROR', csrf_error)), 401

        recruit = Recruit.objects.get(id=recruit_id)

        effective_status = recruit.get_effective_status()
        if effective_status != RecruitStatus.PENDING_TRAINING_SCHEDULE:
            return jsonify(create_error_response('VALIDATION_ERROR', '只能对待预约试播状态的招募执行预约试播')), 400

        data = request.get_json()
        if not data:
            return jsonify(create_error_response('INVALID_DATA', '请求数据格式错误')), 400

        scheduled_training_time_str = data.get('scheduled_training_time')
        if not scheduled_training_time_str:
            return jsonify(create_error_response('VALIDATION_ERROR', '预约试播时间为必填项')), 400

        try:
            scheduled_training_time_local = datetime.fromisoformat(scheduled_training_time_str.replace('T', ' '))
            scheduled_training_time_utc = local_to_utc(scheduled_training_time_local)
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '预约试播时间格式不正确')), 400

        work_mode = data.get('work_mode')
        if not work_mode:
            return jsonify(create_error_response('VALIDATION_ERROR', '开播方式为必填项')), 400

        try:
            WorkMode(work_mode)  # 验证开播方式值是否有效
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '无效的开播方式选择')), 400

        introduction_fee = data.get('introduction_fee', 0)
        try:
            introduction_fee_decimal = Decimal(str(introduction_fee)).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                return jsonify(create_error_response('VALIDATION_ERROR', '介绍费不能为负数')), 400
        except (ValueError, InvalidOperation):
            return jsonify(create_error_response('VALIDATION_ERROR', '介绍费格式不正确')), 400

        remarks = safe_strip(data.get('remarks'))

        # 记录修改前的数据状态
        old_recruit_data = {
            'pilot': str(recruit.pilot.id) if recruit.pilot else None,
            'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
            'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
            'channel': recruit.channel.value if hasattr(recruit.channel, 'value') else recruit.channel,
            'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
            'remarks': recruit.remarks,
            'status': recruit.status.value if hasattr(recruit.status, 'value') else recruit.status,
        }

        old_pilot_data = {
            'nickname': recruit.pilot.nickname,
            'real_name': recruit.pilot.real_name,
            'gender': recruit.pilot.gender.value if hasattr(recruit.pilot.gender, 'value') else recruit.pilot.gender,
            'birth_year': recruit.pilot.birth_year,
            'owner': str(recruit.pilot.owner.id) if recruit.pilot.owner else None,
            'platform': recruit.pilot.platform.value if hasattr(recruit.pilot.platform, 'value') else recruit.pilot.platform,
            'work_mode': recruit.pilot.work_mode.value if hasattr(recruit.pilot.work_mode, 'value') else recruit.pilot.work_mode,
            'rank': recruit.pilot.rank.value if hasattr(recruit.pilot.rank, 'value') else recruit.pilot.rank,
            'status': recruit.pilot.status.value if hasattr(recruit.pilot.status, 'value') else recruit.pilot.status,
        }

        # 更新招募信息
        recruit.scheduled_training_time = scheduled_training_time_utc
        recruit.scheduled_training_decision_maker = current_user
        recruit.scheduled_training_decision_time = get_current_utc_time()
        recruit.introduction_fee = introduction_fee_decimal
        recruit.remarks = remarks
        recruit.status = RecruitStatus.PENDING_TRAINING

        # 更新主播信息
        recruit.pilot.work_mode = WorkMode(work_mode)
        recruit.pilot.save()

        recruit.save()

        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        # 记录主播变更
        from routes.pilots_api import _record_changes as record_pilot_changes
        record_pilot_changes(recruit.pilot, old_pilot_data, current_user, _get_client_ip())

        logger.info('预约试播成功：ID=%s，主播=%s，试播时间=%s', recruit_id, recruit.pilot.nickname, scheduled_training_time_utc)

        serializer_data = serialize_recruit(recruit)
        meta = {'message': '预约试播成功，主播已进入待试播阶段'}
        return jsonify(create_success_response(serializer_data, meta))

    except DoesNotExist:
        return jsonify(create_error_response('RECRUIT_NOT_FOUND', '招募记录不存在')), 404
    except ValidationError as e:
        logger.error('预约试播验证失败：%s', str(e))
        return jsonify(create_error_response('VALIDATION_ERROR', f'数据验证失败：{str(e)}')), 400
    except Exception as e:
        logger.error('预约试播失败：%s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '预约试播失败')), 500


@recruits_api_bp.route('/api/recruits/<recruit_id>/training-decision', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def training_decision(recruit_id):
    """执行试播决策"""
    try:
        # CSRF令牌验证
        csrf_valid, csrf_error = validate_csrf_token()
        if not csrf_valid:
            return jsonify(create_error_response('CSRF_ERROR', csrf_error)), 401

        recruit = Recruit.objects.get(id=recruit_id)

        effective_status = recruit.get_effective_status()
        if effective_status != RecruitStatus.PENDING_TRAINING:
            return jsonify(create_error_response('VALIDATION_ERROR', '只能对待试播状态的招募执行试播决策')), 400

        data = request.get_json()
        if not data:
            return jsonify(create_error_response('INVALID_DATA', '请求数据格式错误')), 400

        training_decision_value = data.get('training_decision')
        if not training_decision_value:
            return jsonify(create_error_response('VALIDATION_ERROR', '试播决策为必填项')), 400

        try:
            training_decision_enum = TrainingDecision(training_decision_value)
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '无效的试播决策')), 400

        introduction_fee = data.get('introduction_fee', 0)
        try:
            introduction_fee_decimal = Decimal(str(introduction_fee)).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                return jsonify(create_error_response('VALIDATION_ERROR', '介绍费不能为负数')), 400
        except (ValueError, InvalidOperation):
            return jsonify(create_error_response('VALIDATION_ERROR', '介绍费格式不正确')), 400

        remarks = safe_strip(data.get('remarks'))

        # 记录修改前的数据状态
        old_recruit_data = {
            'pilot': str(recruit.pilot.id) if recruit.pilot else None,
            'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
            'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
            'channel': recruit.channel.value if recruit.channel else None,
            'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
            'remarks': recruit.remarks,
            'status': recruit.status.value if recruit.status else None,
        }

        old_pilot_data = {
            'nickname': recruit.pilot.nickname,
            'real_name': recruit.pilot.real_name,
            'gender': recruit.pilot.gender.value if recruit.pilot.gender else None,
            'birth_year': recruit.pilot.birth_year,
            'owner': str(recruit.pilot.owner.id) if recruit.pilot.owner else None,
            'platform': recruit.pilot.platform.value if recruit.pilot.platform else None,
            'work_mode': recruit.pilot.work_mode.value if recruit.pilot.work_mode else None,
            'rank': recruit.pilot.rank.value if recruit.pilot.rank else None,
            'status': recruit.pilot.status.value if recruit.pilot.status else None,
        }

        # 更新招募信息
        recruit.training_decision = training_decision_enum
        recruit.training_decision_maker = current_user
        recruit.training_decision_time = get_current_utc_time()
        recruit.introduction_fee = introduction_fee_decimal
        recruit.remarks = remarks

        if training_decision_enum == TrainingDecision.SCHEDULE_BROADCAST:
            recruit.status = RecruitStatus.PENDING_BROADCAST_SCHEDULE
        else:
            recruit.status = RecruitStatus.ENDED
            recruit.pilot.status = Status.NOT_RECRUITING
            recruit.pilot.save()

        recruit.save()

        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        # 记录主播变更（仅在不招募时）
        if training_decision_enum == TrainingDecision.NOT_RECRUIT:
            from routes.pilots_api import \
                _record_changes as record_pilot_changes
            record_pilot_changes(recruit.pilot, old_pilot_data, current_user, _get_client_ip())

        if training_decision_enum == TrainingDecision.SCHEDULE_BROADCAST:
            logger.info('试播决策成功：ID=%s，主播=%s，预约开播', recruit_id, recruit.pilot.nickname)
            message = '试播决策成功，主播已进入待预约开播阶段'
        else:
            logger.info('试播决策完成：ID=%s，主播=%s，不招募', recruit_id, recruit.pilot.nickname)
            message = '试播决策完成，已决定不招募该主播'

        serializer_data = serialize_recruit(recruit)
        meta = {'message': message}
        return jsonify(create_success_response(serializer_data, meta))

    except DoesNotExist:
        return jsonify(create_error_response('RECRUIT_NOT_FOUND', '招募记录不存在')), 404
    except ValidationError as e:
        logger.error('试播决策验证失败：%s', str(e))
        return jsonify(create_error_response('VALIDATION_ERROR', f'数据验证失败：{str(e)}')), 400
    except Exception as e:
        logger.error('试播决策失败：%s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '试播决策失败')), 500


@recruits_api_bp.route('/api/recruits/<recruit_id>/schedule-broadcast', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def schedule_broadcast(recruit_id):
    """执行预约开播"""
    try:
        # CSRF令牌验证
        csrf_valid, csrf_error = validate_csrf_token()
        if not csrf_valid:
            return jsonify(create_error_response('CSRF_ERROR', csrf_error)), 401

        recruit = Recruit.objects.get(id=recruit_id)

        effective_status = recruit.get_effective_status()
        if effective_status != RecruitStatus.PENDING_BROADCAST_SCHEDULE:
            return jsonify(create_error_response('VALIDATION_ERROR', '只能对待预约开播状态的招募执行预约开播')), 400

        data = request.get_json()
        if not data:
            return jsonify(create_error_response('INVALID_DATA', '请求数据格式错误')), 400

        scheduled_broadcast_time_str = data.get('scheduled_broadcast_time')
        if not scheduled_broadcast_time_str:
            return jsonify(create_error_response('VALIDATION_ERROR', '预约开播时间为必填项')), 400

        try:
            scheduled_broadcast_time_local = datetime.fromisoformat(scheduled_broadcast_time_str.replace('T', ' '))
            scheduled_broadcast_time_utc = local_to_utc(scheduled_broadcast_time_local)
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '预约开播时间格式不正确')), 400

        introduction_fee = data.get('introduction_fee', 0)
        try:
            introduction_fee_decimal = Decimal(str(introduction_fee)).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                return jsonify(create_error_response('VALIDATION_ERROR', '介绍费不能为负数')), 400
        except (ValueError, InvalidOperation):
            return jsonify(create_error_response('VALIDATION_ERROR', '介绍费格式不正确')), 400

        remarks = safe_strip(data.get('remarks'))

        # 记录修改前的数据状态
        old_recruit_data = {
            'pilot': str(recruit.pilot.id) if recruit.pilot else None,
            'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
            'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
            'channel': recruit.channel.value if recruit.channel else None,
            'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
            'remarks': recruit.remarks,
            'status': recruit.status.value if recruit.status else None,
        }

        # 更新招募信息
        recruit.scheduled_broadcast_time = scheduled_broadcast_time_utc
        recruit.scheduled_broadcast_decision_maker = current_user
        recruit.scheduled_broadcast_decision_time = get_current_utc_time()
        recruit.introduction_fee = introduction_fee_decimal
        recruit.remarks = remarks
        recruit.status = RecruitStatus.PENDING_BROADCAST

        recruit.save()

        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        logger.info('预约开播成功：ID=%s，主播=%s，开播时间=%s', recruit_id, recruit.pilot.nickname, scheduled_broadcast_time_utc)

        serializer_data = serialize_recruit(recruit)
        meta = {'message': '预约开播成功，主播已进入待开播阶段'}
        return jsonify(create_success_response(serializer_data, meta))

    except DoesNotExist:
        return jsonify(create_error_response('RECRUIT_NOT_FOUND', '招募记录不存在')), 404
    except ValidationError as e:
        logger.error('预约开播验证失败：%s', str(e))
        return jsonify(create_error_response('VALIDATION_ERROR', f'数据验证失败：{str(e)}')), 400
    except Exception as e:
        logger.error('预约开播失败：%s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '预约开播失败')), 500


@recruits_api_bp.route('/api/recruits/<recruit_id>/broadcast-decision', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def broadcast_decision(recruit_id):
    """执行开播决策"""
    try:
        # CSRF令牌验证
        csrf_valid, csrf_error = validate_csrf_token()
        if not csrf_valid:
            return jsonify(create_error_response('CSRF_ERROR', csrf_error)), 401

        recruit = Recruit.objects.get(id=recruit_id)

        effective_status = recruit.get_effective_status()
        if effective_status != RecruitStatus.PENDING_BROADCAST:
            return jsonify(create_error_response('VALIDATION_ERROR', '只能对待开播状态的招募执行开播决策')), 400

        data = request.get_json()
        if not data:
            return jsonify(create_error_response('INVALID_DATA', '请求数据格式错误')), 400

        broadcast_decision_value = data.get('broadcast_decision')
        if not broadcast_decision_value:
            return jsonify(create_error_response('VALIDATION_ERROR', '开播决策为必填项')), 400

        try:
            broadcast_decision_enum = BroadcastDecision(broadcast_decision_value)
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '无效的开播决策')), 400

        introduction_fee = data.get('introduction_fee', 0)
        try:
            introduction_fee_decimal = Decimal(str(introduction_fee)).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                return jsonify(create_error_response('VALIDATION_ERROR', '介绍费不能为负数')), 400
        except (ValueError, InvalidOperation):
            return jsonify(create_error_response('VALIDATION_ERROR', '介绍费格式不正确')), 400

        remarks = safe_strip(data.get('remarks'))

        # 验证招募成功时的必填字段
        if broadcast_decision_enum in [BroadcastDecision.OFFICIAL, BroadcastDecision.INTERN]:
            owner_id = data.get('owner_id')
            if not owner_id:
                return jsonify(create_error_response('VALIDATION_ERROR', '招募成功时必须选择所属')), 400

            platform = data.get('platform')
            if not platform:
                return jsonify(create_error_response('VALIDATION_ERROR', '招募成功时必须选择开播平台')), 400

            try:
                Platform(platform)  # 验证开播平台值是否有效
            except ValueError:
                return jsonify(create_error_response('VALIDATION_ERROR', '无效的开播平台选择')), 400

            try:
                owner_user = User.objects.get(id=owner_id)
                if not (owner_user.has_role('kancho') or owner_user.has_role('gicho')):
                    return jsonify(create_error_response('VALIDATION_ERROR', '直属运营必须是运营或管理员')), 400
            except DoesNotExist:
                return jsonify(create_error_response('VALIDATION_ERROR', '无效的所属选择')), 400

        # 记录修改前的数据状态
        old_recruit_data = {
            'pilot': str(recruit.pilot.id) if recruit.pilot else None,
            'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
            'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
            'channel': recruit.channel.value if recruit.channel else None,
            'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
            'remarks': recruit.remarks,
            'status': recruit.status.value if recruit.status else None,
        }

        old_pilot_data = {
            'nickname': recruit.pilot.nickname,
            'real_name': recruit.pilot.real_name,
            'gender': recruit.pilot.gender.value if recruit.pilot.gender else None,
            'birth_year': recruit.pilot.birth_year,
            'owner': str(recruit.pilot.owner.id) if recruit.pilot.owner else None,
            'platform': recruit.pilot.platform.value if recruit.pilot.platform else None,
            'work_mode': recruit.pilot.work_mode.value if recruit.pilot.work_mode else None,
            'rank': recruit.pilot.rank.value if recruit.pilot.rank else None,
            'status': recruit.pilot.status.value if recruit.pilot.status else None,
        }

        # 更新招募信息
        recruit.broadcast_decision = broadcast_decision_enum
        recruit.broadcast_decision_maker = current_user
        recruit.broadcast_decision_time = get_current_utc_time()
        recruit.introduction_fee = introduction_fee_decimal
        recruit.remarks = remarks
        recruit.status = RecruitStatus.ENDED

        # 更新主播信息
        if broadcast_decision_enum in [BroadcastDecision.OFFICIAL, BroadcastDecision.INTERN]:
            recruit.pilot.owner = User.objects.get(id=owner_id)
            recruit.pilot.platform = Platform(platform)
            recruit.pilot.status = Status.RECRUITED

            if broadcast_decision_enum == BroadcastDecision.OFFICIAL:
                recruit.pilot.rank = Rank.OFFICIAL
            else:
                recruit.pilot.rank = Rank.INTERN

            recruit.pilot.save()
        else:
            recruit.pilot.status = Status.NOT_RECRUITING
            recruit.pilot.save()

        recruit.save()

        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        # 记录主播变更
        from routes.pilots_api import _record_changes as record_pilot_changes
        record_pilot_changes(recruit.pilot, old_pilot_data, current_user, _get_client_ip())

        if broadcast_decision_enum in [BroadcastDecision.OFFICIAL, BroadcastDecision.INTERN]:
            logger.info('开播决策成功：ID=%s，主播=%s，招募为%s', recruit_id, recruit.pilot.nickname, broadcast_decision_enum.value)
            message = f'开播决策成功，主播已被招募为{broadcast_decision_enum.value}'
        else:
            logger.info('开播决策完成：ID=%s，主播=%s，不招募', recruit_id, recruit.pilot.nickname)
            message = '开播决策完成，已决定不招募该主播'

        serializer_data = serialize_recruit(recruit)
        meta = {'message': message}
        return jsonify(create_success_response(serializer_data, meta))

    except DoesNotExist:
        return jsonify(create_error_response('RECRUIT_NOT_FOUND', '招募记录不存在')), 404
    except ValidationError as e:
        logger.error('开播决策验证失败：%s', str(e))
        return jsonify(create_error_response('VALIDATION_ERROR', f'数据验证失败：{str(e)}')), 400
    except Exception as e:
        logger.error('开播决策失败：%s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '开播决策失败')), 500
