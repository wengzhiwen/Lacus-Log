# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""
主播管理 REST API 路由
提供完整的主播管理REST接口，支持列表、详情、创建、更新、状态调整等功能
"""

import csv
import io
from datetime import datetime
from decimal import Decimal

from flask import Blueprint, Response, jsonify, request
from flask_security import current_user, roles_accepted
from mongoengine import DoesNotExist, Q, ValidationError

from models.pilot import (Gender, Pilot, PilotChangeLog, Platform, Rank,
                          Status, WorkMode)
from models.user import User
from utils.csrf_helper import CSRFError, validate_csrf_header
from utils.logging_setup import get_logger
from utils.pilot_serializers import (create_error_response,
                                     create_success_response,
                                     serialize_change_log_list,
                                     serialize_pilot)
from utils.timezone_helper import get_current_utc_time, utc_to_local

logger = get_logger('pilot')
pilots_api_bp = Blueprint('pilots_api', __name__)


def safe_strip(value):
    """安全地去除字符串两端空格，处理None值"""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return None


def _record_changes(pilot, old_data, user, changes_summary):
    """记录主播字段变更"""
    changes = []
    field_mapping = {
        'nickname': pilot.nickname,
        'real_name': pilot.real_name,
        'gender': pilot.gender.value if pilot.gender else None,
        'hometown': pilot.hometown,
        'birth_year': pilot.birth_year,
        'owner': str(pilot.owner.id) if pilot.owner else None,
        'platform': pilot.platform.value if pilot.platform else None,
        'work_mode': pilot.work_mode.value if pilot.work_mode else None,
        'rank': pilot.rank.value if pilot.rank else None,
        'status': pilot.status.value if pilot.status else None,
    }

    for field_name, new_value in field_mapping.items():
        old_value = old_data.get(field_name)
        if str(old_value) != str(new_value):
            change_log = PilotChangeLog(pilot_id=pilot,
                                        user_id=user,
                                        field_name=field_name,
                                        old_value=str(old_value) if old_value is not None else '',
                                        new_value=str(new_value) if new_value is not None else '',
                                        ip_address=request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR'))
            changes.append(change_log)

    if changes:
        PilotChangeLog.objects.insert(changes)
        logger.info('记录主播变更：%s，共%d个字段', pilot.nickname, len(changes))


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


@pilots_api_bp.route('/api/pilots', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_pilots():
    """获取主播列表"""
    try:
        # 获取筛选参数
        owner_ids = request.args.getlist('owner_id')
        rank_filters = request.args.getlist('rank')
        status_filters = request.args.getlist('status')
        platform_filters = request.args.getlist('platform')
        work_mode_filters = request.args.getlist('work_mode')
        created_from = request.args.get('created_from')
        created_to = request.args.get('created_to')
        q = request.args.get('q', '').strip()

        # 分页参数
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 500))

        # 排序参数
        sort_param = request.args.get('sort', '-created_at')

        # 初始化查询
        query = Pilot.objects

        # 直属运营筛选
        if owner_ids:
            try:
                owner_objects = User.objects(id__in=owner_ids)
                query = query.filter(owner__in=owner_objects)
            except ValidationError:
                logger.warning('无效的直属运营ID: %s', owner_ids)

        # 主播分类筛选（包含兼容逻辑：旧值与新值映射）
        if rank_filters:
            valid_ranks = []
            for rank_value in rank_filters:
                if _has_enum_value(Rank, rank_value):
                    rank_enum = Rank(rank_value)
                    # 兼容逻辑：同时匹配新旧值
                    if rank_enum == Rank.CANDIDATE:
                        valid_ranks.extend([Rank.CANDIDATE, Rank.CANDIDATE_OLD])
                    elif rank_enum == Rank.TRAINEE:
                        valid_ranks.extend([Rank.TRAINEE, Rank.TRAINEE_OLD])
                    elif rank_enum == Rank.INTERN:
                        valid_ranks.extend([Rank.INTERN, Rank.INTERN_OLD])
                    elif rank_enum == Rank.OFFICIAL:
                        valid_ranks.extend([Rank.OFFICIAL, Rank.OFFICIAL_OLD])
                    else:
                        valid_ranks.append(rank_enum)
            if valid_ranks:
                query = query.filter(rank__in=valid_ranks)

        # 状态筛选（包含兼容逻辑：旧值与新值映射）
        if status_filters:
            valid_statuses = []
            for status_value in status_filters:
                if _has_enum_value(Status, status_value):
                    status_enum = Status(status_value)
                    if status_enum == Status.NOT_RECRUITED:
                        valid_statuses.extend([Status.NOT_RECRUITED, Status.NOT_RECRUITED_OLD])
                    elif status_enum == Status.NOT_RECRUITING:
                        valid_statuses.extend([Status.NOT_RECRUITING, Status.NOT_RECRUITING_OLD])
                    elif status_enum == Status.RECRUITED:
                        valid_statuses.extend([Status.RECRUITED, Status.RECRUITED_OLD])
                    elif status_enum == Status.FALLEN:
                        valid_statuses.extend([Status.FALLEN, Status.FALLEN_OLD])
                    else:
                        valid_statuses.append(status_enum)
            if valid_statuses:
                query = query.filter(status__in=valid_statuses)

        # 平台筛选
        if platform_filters:
            valid_platforms = [Platform(v) for v in platform_filters if _has_enum_value(Platform, v)]
            if valid_platforms:
                query = query.filter(platform__in=valid_platforms)

        # 开播方式筛选
        if work_mode_filters:
            valid_work_modes = [WorkMode(v) for v in work_mode_filters if _has_enum_value(WorkMode, v)]
            if valid_work_modes:
                query = query.filter(work_mode__in=valid_work_modes)

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
                # created_to包含当日 23:59:59
                created_to_date = created_to_date.replace(hour=23, minute=59, second=59)
                query = query.filter(created_at__lte=created_to_date)
            except ValueError:
                logger.warning('无效的创建结束时间: %s', created_to)

        # 搜索功能（昵称和真实姓名的模糊搜索）
        if q:
            query = query.filter(Q(nickname__icontains=q) | Q(real_name__icontains=q))

        # 排序处理
        if sort_param.startswith('-'):
            sort_field = sort_param[1:]
            if sort_field in ['created_at', 'updated_at', 'nickname']:
                query = query.order_by('-created_at')
            else:
                query = query.order_by('-created_at')
        else:
            sort_field = sort_param
            if sort_field in ['created_at', 'updated_at', 'nickname']:
                # MongoEngine 升序使用字段名本身
                query = query.order_by('created_at')
            else:
                query = query.order_by('-created_at')

        # 分页查询
        total_items = query.count()
        pilots = query.skip((page - 1) * page_size).limit(page_size).all()
        total_pages = (total_items + page_size - 1) // page_size

        # 统计信息
        stats = {'total': total_items, 'rank_stats': {}, 'status_stats': {}, 'platform_stats': {}, 'owner_stats': {}}

        # 计算各维度的统计
        for pilot in pilots:
            # 主播分类统计
            rank_value = pilot.rank.value if pilot.rank else 'None'
            stats['rank_stats'][rank_value] = stats['rank_stats'].get(rank_value, 0) + 1

            # 状态统计
            status_value = pilot.status.value if pilot.status else 'None'
            stats['status_stats'][status_value] = stats['status_stats'].get(status_value, 0) + 1

            # 平台统计
            platform_value = pilot.platform.value if pilot.platform else 'None'
            stats['platform_stats'][platform_value] = stats['platform_stats'].get(platform_value, 0) + 1

            # 直属运营统计
            owner_nickname = pilot.owner.nickname if pilot.owner else '无'
            stats['owner_stats'][owner_nickname] = stats['owner_stats'].get(owner_nickname, 0) + 1

        # 序列化数据
        data = {'items': [serialize_pilot(pilot) for pilot in pilots], 'aggregations': stats}

        meta = {'pagination': {'page': page, 'page_size': page_size, 'total_items': total_items, 'total_pages': total_pages}}

        logger.info('获取主播列表成功：第%d页，共%d条记录', page, len(pilots))
        return jsonify(create_success_response(data, meta))

    except Exception as e:
        logger.error('获取主播列表失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取主播列表失败')), 500


@pilots_api_bp.route('/api/pilots/<pilot_id>', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_pilot_detail(pilot_id):
    """获取主播详情（不包含分成分数据，分成分数据通过独立的commission API获取）"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)

        # 获取最近的变更记录（不超总记录，给展示用）
        recent_changes = PilotChangeLog.objects(pilot_id=pilot).order_by('-change_time').limit(5)

        # 序列化基本信息
        pilot_data = serialize_pilot(pilot)
        pilot_data['recent_changes'] = [{
            'field_name': change.field_name,
            'old_value': change.old_value,
            'new_value': change.new_value,
            'created_at': utc_to_local(change.change_time).isoformat() if change.change_time else None,
            'user_nickname': change.user_id.nickname if change.user_id else '未知用户',
            'changes_summary': getattr(change, 'changes_summary', '')
        } for change in recent_changes]

        logger.info('获取主播详情成功：%s', pilot.nickname)
        return jsonify(create_success_response(pilot_data))

    except DoesNotExist:
        return jsonify(create_error_response('PILOT_NOT_FOUND', '主播不存在')), 404
    except Exception as e:
        logger.error('获取主播详情失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取主播详情失败')), 500


@pilots_api_bp.route('/api/pilots', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def create_pilot():
    """创建主播"""
    try:
        # CSRF令牌验证
        try:
            validate_csrf_header()
        except CSRFError as exc:
            return jsonify(create_error_response(exc.code, exc.message)), 401

        data = request.get_json()
        if not data:
            return jsonify(create_error_response('INVALID_DATA', '请求数据格式错误')), 400

        # 数据验证
        nickname = safe_strip(data.get('nickname'))
        if not nickname:
            return jsonify(create_error_response('VALIDATION_ERROR', '昵称为必填项')), 400

        # 检查昵称是否已存在
        if Pilot.objects(nickname=nickname).first():
            return jsonify(create_error_response('VALIDATION_ERROR', '该昵称已存在')), 400

        # 创建主播对象
        pilot = Pilot(nickname=nickname)

        # 赋值其他字段
        pilot.real_name = safe_strip(data.get('real_name'))
        pilot.gender = try_enum(Gender, data.get('gender'))
        pilot.hometown = safe_strip(data.get('hometown'))
        pilot.birth_year = data.get('birth_year')
        pilot.platform = try_enum(Platform, data.get('platform'))
        pilot.work_mode = try_enum(WorkMode, data.get('work_mode'))
        pilot.rank = try_enum(Rank, data.get('rank'))
        pilot.status = try_enum(Status, data.get('status'))

        # 设置直属运营
        owner_id = data.get('owner_id')
        if owner_id:
            try:
                owner = User.objects.get(id=owner_id)
                pilot.owner = owner
            except DoesNotExist:
                return jsonify(create_error_response('INVALID_OWNER', '指定的直属运营不存在')), 400
        elif current_user.has_role('kancho') and not current_user.has_role('gicho'):
            # 运营用户默认指定自己为直属运营
            pilot.owner = current_user

        # 保存主播
        pilot.created_at = pilot.updated_at = get_current_utc_time()
        pilot.save()

        # 记录变更日志
        create_log = PilotChangeLog(pilot_id=pilot,
                                    user_id=current_user,
                                    field_name='status',
                                    old_value='',
                                    new_value='created',
                                    ip_address=request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR'))
        create_log.save()

        logger.info('创建主播成功：%s', pilot.nickname)
        serializer_data = serialize_pilot(pilot)
        meta = {'message': '主播创建成功'}
        return jsonify(create_success_response(serializer_data, meta)), 201

    except ValueError as e:
        logger.warning('创建主播业务验证失败: %s', str(e))
        return jsonify(create_error_response('VALIDATION_ERROR', str(e))), 400
    except ValidationError as e:
        logger.warning('创建主播验证失败: %s', str(e))
        return jsonify(create_error_response('VALIDATION_ERROR', f'数据验证失败：{str(e)}')), 400
    except Exception as e:
        logger.error('创建主播失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '创建主播失败')), 500


@pilots_api_bp.route('/api/pilots/<pilot_id>', methods=['PUT'])
@roles_accepted('gicho', 'kancho')
def update_pilot(pilot_id):
    """更新主播（整体更新）"""
    try:
        # CSRF令牌验证
        try:
            validate_csrf_header()
        except CSRFError as exc:
            return jsonify(create_error_response(exc.code, exc.message)), 401

        pilot = Pilot.objects.get(id=pilot_id)

        # 记录修改前的数据状态
        old_data = {
            'nickname': pilot.nickname,
            'real_name': pilot.real_name,
            'gender': pilot.gender.value if pilot.gender else None,
            'hometown': pilot.hometown,
            'birth_year': pilot.birth_year,
            'owner': str(pilot.owner.id) if pilot.owner else None,
            'platform': pilot.platform.value if pilot.platform else None,
            'work_mode': pilot.work_mode.value if pilot.work_mode else None,
            'rank': pilot.rank.value if pilot.rank else None,
            'status': pilot.status.value if pilot.status else None,
        }

        data = request.get_json()
        if not data:
            return jsonify(create_error_response('INVALID_DATA', '请求数据格式错误')), 400

        # 验证昵称
        nickname = safe_strip(data.get('nickname'))
        if not nickname:
            return jsonify(create_error_response('VALIDATION_ERROR', '昵称为必填项')), 400

        # 检查昵称冲突
        existing_pilot = Pilot.objects(nickname=nickname).first()
        if existing_pilot and existing_pilot.id != pilot.id:
            return jsonify(create_error_response('VALIDATION_ERROR', '该昵称已存在')), 400

        # 更新字段
        pilot.nickname = nickname
        pilot.real_name = safe_strip(data.get('real_name'))
        pilot.gender = try_enum(Gender, data.get('gender'))
        pilot.hometown = safe_strip(data.get('hometown'))
        pilot.birth_year = data.get('birth_year')
        pilot.platform = try_enum(Platform, data.get('platform'))
        pilot.work_mode = try_enum(WorkMode, data.get('work_mode'))
        pilot.rank = try_enum(Rank, data.get('rank'))
        pilot.status = try_enum(Status, data.get('status'))

        # 更新直属运营
        owner_id = data.get('owner_id')
        if owner_id:
            try:
                pilot.owner = User.objects.get(id=owner_id)
            except DoesNotExist:
                return jsonify(create_error_response('INVALID_OWNER', '指定的直属运营不存在')), 400
        else:
            pilot.owner = None

        # 保存并记录变更
        pilot.updated_at = get_current_utc_time()
        pilot.save()
        _record_changes(pilot, old_data, current_user, '主播信息更新')

        logger.info('更新主播成功：%s', pilot.nickname)
        serializer_data = serialize_pilot(pilot)
        meta = {'message': '主播信息已更新'}
        return jsonify(create_success_response(serializer_data, meta))

    except DoesNotExist:
        return jsonify(create_error_response('PILOT_NOT_FOUND', '主播不存在')), 404
    except ValueError as e:
        logger.warning('更新主播业务验证失败: %s', str(e))
        return jsonify(create_error_response('VALIDATION_ERROR', str(e))), 400
    except ValidationError as e:
        logger.warning('更新主播验证失败: %s', str(e))
        return jsonify(create_error_response('VALIDATION_ERROR', f'数据验证失败：{str(e)}')), 400
    except Exception as e:
        logger.error('更新主播失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '更新主播失败')), 500


@pilots_api_bp.route('/api/pilots/<pilot_id>/status', methods=['PATCH'])
@roles_accepted('gicho', 'kancho')
def update_pilot_status(pilot_id):
    """调整主播状态"""
    try:
        # CSRF令牌验证
        try:
            validate_csrf_header()
        except CSRFError as exc:
            return jsonify(create_error_response(exc.code, exc.message)), 401

        pilot = Pilot.objects.get(id=pilot_id)

        data = request.get_json()
        if not data:
            return jsonify(create_error_response('INVALID_DATA', '请求数据格式错误')), 400

        new_status = data.get('status')
        if not new_status:
            return jsonify(create_error_response('VALIDATION_ERROR', '状态参数缺失')), 400

        if not _has_enum_value(Status, new_status):
            return jsonify(create_error_response('VALIDATION_ERROR', '无效的状态值')), 400

        old_status = pilot.status.value if pilot.status else None
        pilot.status = Status(new_status)
        pilot.updated_at = get_current_utc_time()

        # 记录变更日志
        change_log = PilotChangeLog(pilot_id=pilot,
                                    user_id=current_user,
                                    field_name='status',
                                    old_value=str(old_status) if old_status else '',
                                    new_value=str(new_status),
                                    ip_address=request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR'))
        change_log.save()

        logger.info('调整主播状态成功：%s (%s -> %s)', pilot.nickname, old_status, new_status)
        serializer_data = serialize_pilot(pilot)
        meta = {'message': f'状态已更新为 {new_status}'}
        return jsonify(create_success_response(serializer_data, meta))

    except DoesNotExist:
        return jsonify(create_error_response('PILOT_NOT_FOUND', '主播不存在')), 404
    except Exception as e:
        logger.error('调整主播状态失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '调整主播状态失败')), 500


@pilots_api_bp.route('/api/pilots/<pilot_id>/changes', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_pilot_changes(pilot_id):
    """获取主播变更记录"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)

        # 分页参数
        page = int(request.args.get('page', 1))
        page_size = int(request.args.get('page_size', 500))

        # 获取变更记录
        changes_query = PilotChangeLog.objects(pilot_id=pilot).order_by('-change_time')
        total_changes = changes_query.count()
        changes = changes_query.skip((page - 1) * page_size).limit(page_size).all()

        total_pages = (total_changes + page_size - 1) // page_size

        # 返回变更信息
        changes_data = serialize_change_log_list(changes)

        meta = {'pagination': {'page': page, 'page_size': page_size, 'total_items': total_changes, 'total_pages': total_pages}}

        return jsonify(create_success_response(changes_data, meta))

    except DoesNotExist:
        return jsonify(create_error_response('PILOT_NOT_FOUND', '主播不存在')), 404
    except Exception as e:
        logger.error('获取主播变更记录失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取主播变更记录失败')), 500


@pilots_api_bp.route('/api/pilots/options', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_pilot_options():
    """获取主播筛选器枚举选项
    
    注意：直属运营列表已迁移到用户管理模块，请使用 GET /api/users/operators
    """
    try:
        # 枚举字典
        enum_dict = {
            'gender': {
                option.value: option.value
                for option in Gender
            },
            'platform': {
                option.value: option.value
                for option in Platform
            },
            'work_mode': {
                option.value: option.value
                for option in WorkMode
            },
            'rank': {
                option.value: option.value
                for option in Rank
            },
            'status': {
                option.value: option.value
                for option in Status
            }
        }

        data = {'enums': enum_dict}

        return jsonify(create_success_response(data))

    except Exception as e:
        logger.error('获取主播选项数据失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取选项数据失败')), 500


@pilots_api_bp.route('/api/pilots/<pilot_id>/performance', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_pilot_performance(pilot_id):
    """获取主播业绩数据"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)

        # 计算主播业绩数据
        from utils.pilot_performance import calculate_pilot_performance_stats
        performance_data = calculate_pilot_performance_stats(pilot)

        # 序列化主播基本信息
        if pilot.gender == Gender.MALE:
            gender_icon = '♂'
        elif pilot.gender == Gender.FEMALE:
            gender_icon = '♀'
        else:
            gender_icon = '?'

        pilot_info = {
            'nickname': pilot.nickname,
            'real_name': pilot.real_name,
            'age': pilot.age,
            'gender_icon': gender_icon,
            'hometown': pilot.hometown,
            'owner': pilot.owner.nickname if pilot.owner else None,
            'rank': pilot.rank.value if pilot.rank else None,
            'status': pilot.status.value if pilot.status else None
        }

        # 序列化最近开播记录
        recent_records = []
        for record in performance_data['recent_records']:
            recent_records.append({
                'id': str(record.id),
                'start_time': utc_to_local(record.start_time).isoformat() if record.start_time else None,
                'duration_hours': float(record.duration_hours) if record.duration_hours else 0,
                'revenue_amount': float(record.revenue_amount),
                'base_salary': float(record.base_salary) if record.base_salary else 0
            })

        # 转换Decimal为float
        def convert_decimal_to_float(data):
            if isinstance(data, dict):
                return {k: convert_decimal_to_float(v) for k, v in data.items()}
            if isinstance(data, list):
                return [convert_decimal_to_float(item) for item in data]
            if isinstance(data, Decimal):
                return float(data)
            return data

        month_stats = convert_decimal_to_float(performance_data['month_stats'])
        week_stats = convert_decimal_to_float(performance_data['week_stats'])
        three_day_stats = convert_decimal_to_float(performance_data['three_day_stats'])

        response_data = {
            'pilot_info': pilot_info,
            'month_stats': month_stats,
            'week_stats': week_stats,
            'three_day_stats': three_day_stats,
            'recent_records': recent_records
        }

        logger.info('获取主播业绩数据成功：%s', pilot.nickname)
        return jsonify(create_success_response(response_data))

    except DoesNotExist:
        return jsonify(create_error_response('PILOT_NOT_FOUND', '主播不存在')), 404
    except Exception as e:
        logger.error('获取主播业绩数据失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取主播业绩数据失败')), 500


@pilots_api_bp.route('/api/pilots/export', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def export_pilots():
    """导出主播数据"""
    logger.info('%s 请求导出主播数据', current_user.username)

    try:
        # 获取筛选参数（复用列表接口的筛选逻辑）
        rank_filters = request.args.getlist('rank')
        status_filters = request.args.getlist('status')
        owner_ids = request.args.getlist('owner_id')
        platform_filters = request.args.getlist('platform')
        work_mode_filters = request.args.getlist('work_mode')

        # 构建查询（复用列表接口的逻辑）
        query = Pilot.objects

        if rank_filters:
            rank_enums = []
            for rank_value in rank_filters:
                if _has_enum_value(Rank, rank_value):
                    rank_enums.append(Rank(rank_value))
            if rank_enums:
                query = query.filter(rank__in=rank_enums)

        if status_filters:
            status_enums = []
            for status_value in status_filters:
                if _has_enum_value(Status, status_value):
                    status_enums.append(Status(status_value))
            if status_enums:
                query = query.filter(status__in=status_enums)

        if owner_ids:
            try:
                owner_objects = User.objects(id__in=owner_ids)
                query = query.filter(owner__in=owner_objects)
            except ValidationError:
                pass

        if platform_filters:
            platform_enums = [Platform(v) for v in platform_filters if _has_enum_value(Platform, v)]
            if platform_enums:
                query = query.filter(platform__in=platform_enums)

        if work_mode_filters:
            work_mode_enums = [WorkMode(v) for v in work_mode_filters if _has_enum_value(WorkMode, v)]
            if work_mode_enums:
                query = query.filter(work_mode__in=work_mode_enums)

        pilots = query.order_by('-created_at').all()

        # 创建CSV文件
        output = io.StringIO()
        writer = csv.writer(output)

        # CSV头部
        writer.writerow(['ID', '昵称', '真实姓名', '性别', '家乡', '出生年', '年龄', '直属运营', '平台', '开播方式', '分类', '状态', '创建时间', '更新时间'])

        # 写入数据行
        for pilot in pilots:
            writer.writerow([
                str(pilot.id), pilot.nickname, pilot.real_name or '', pilot.gender.value if pilot.gender else '', pilot.hometown or '', pilot.birth_year or '',
                pilot.age or '', pilot.owner.nickname if pilot.owner else '', pilot.platform.value if pilot.platform else '',
                pilot.work_mode.value if pilot.work_mode else '', pilot.rank.value if pilot.rank else '', pilot.status.value if pilot.status else '',
                utc_to_local(pilot.created_at).strftime('%Y-%m-%d %H:%M:%S') if pilot.created_at else '',
                utc_to_local(pilot.updated_at).strftime('%Y-%m-%d %H:%M:%S') if pilot.updated_at else ''
            ])

        output.seek(0)

        # 准备CSV内容
        csv_content = output.getvalue()

        # 添加BOM以支持Excel正确显示中文
        csv_with_bom = '\ufeff' + csv_content

        response = Response(csv_with_bom.encode('utf-8'),
                            mimetype='text/csv',
                            headers={
                                'Content-Disposition': 'attachment; filename="pilot_export.csv"',
                                'Content-Type': 'text/csv; charset=utf-8',
                                'Cache-Control': 'no-cache'
                            })

        logger.info('导出主播数据成功：导出 %d 条记录', len(pilots))
        return response

    except Exception as e:
        logger.error('导出主播数据失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '导出数据失败')), 500
