"""
底薪申请管理 REST API 路由
提供底薪申请的读写与状态管理接口
"""
# pylint: disable=no-member

import csv
import io
from datetime import datetime
from urllib.parse import quote

from flask import Blueprint, jsonify, request, Response
from flask_security import current_user
from mongoengine import DoesNotExist, ValidationError

from models.battle_record import (BaseSalaryApplication, BaseSalaryApplicationChangeLog, BaseSalaryApplicationStatus, BattleRecord)
from models.pilot import Pilot
from utils.base_salary_application_serializers import (create_error_response, create_success_response, serialize_base_salary_application,
                                                       serialize_base_salary_application_change_log_list)
from utils.jwt_roles import jwt_roles_accepted
from utils.logging_setup import get_logger
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)

logger = get_logger('base_salary_application')
base_salary_applications_api_bp = Blueprint('base_salary_applications_api', __name__)


def _safe_strip(value):
    """安全的字符串strip操作"""
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    return None


def _get_client_ip() -> str:
    """获取客户端IP地址"""
    return request.headers.get('X-Forwarded-For') or request.remote_addr or '未知'


@base_salary_applications_api_bp.route('/api/base-salary-applications/stats', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def get_base_salary_applications_stats():
    """获取底薪申请统计数据（按日期筛选）"""
    try:
        date_str = request.args.get('date')

        query_filter = {}

        if date_str:
            try:
                query_date = datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                return jsonify(create_error_response('VALIDATION_ERROR', '日期格式应为YYYY-MM-DD')), 400

            # 查询该天创建的申请
            start_of_day = local_to_utc(query_date.replace(hour=0, minute=0, second=0, microsecond=0))
            end_of_day = local_to_utc(query_date.replace(hour=23, minute=59, second=59, microsecond=999999))

            query_filter['created_at__gte'] = start_of_day
            query_filter['created_at__lte'] = end_of_day

        # 获取所有符合条件的申请
        applications = BaseSalaryApplication.objects(**query_filter)

        # 统计数据
        total_amount = 0
        approved_amount = 0
        rejected_amount = 0
        pending_amount = 0

        for app in applications:
            amount = float(app.base_salary_amount or 0)
            total_amount += amount

            if app.status == BaseSalaryApplicationStatus.APPROVED:
                approved_amount += amount
            elif app.status == BaseSalaryApplicationStatus.REJECTED:
                rejected_amount += amount
            elif app.status == BaseSalaryApplicationStatus.PENDING:
                pending_amount += amount

        stats = {'total_amount': total_amount, 'approved_amount': approved_amount, 'rejected_amount': rejected_amount, 'pending_amount': pending_amount}

        return jsonify(create_success_response(stats))
    except Exception as e:  # noqa: BLE001
        logger.error('获取底薪申请统计失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取底薪申请统计失败')), 500


@base_salary_applications_api_bp.route('/api/base-salary-applications', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def list_base_salary_applications():
    """获取底薪申请列表（按日期筛选）"""
    try:
        date_str = request.args.get('date')
        page = max(int(request.args.get('page', 1) or 1), 1)
        page_size = min(max(int(request.args.get('page_size', 20) or 20), 1), 100)

        query_filter = {}

        if date_str:
            try:
                query_date = datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                return jsonify(create_error_response('VALIDATION_ERROR', '日期格式应为YYYY-MM-DD')), 400

            # 查询该天创建的申请
            start_of_day = local_to_utc(query_date.replace(hour=0, minute=0, second=0, microsecond=0))
            end_of_day = local_to_utc(query_date.replace(hour=23, minute=59, second=59, microsecond=999999))

            query_filter['created_at__gte'] = start_of_day
            query_filter['created_at__lte'] = end_of_day

        qs = BaseSalaryApplication.objects(**query_filter).order_by('-created_at')
        total = qs.count()
        items = [serialize_base_salary_application(app) for app in qs.skip((page - 1) * page_size).limit(page_size)]

        meta = {'page': page, 'page_size': page_size, 'total': total}
        return jsonify(create_success_response({'items': items}, meta))
    except Exception as e:  # noqa: BLE001
        logger.error('获取底薪申请列表失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取底薪申请列表失败')), 500


@base_salary_applications_api_bp.route('/api/base-salary-applications', methods=['POST'])
@jwt_roles_accepted('gicho', 'kancho')
def create_base_salary_application():
    """创建新的底薪申请"""
    try:
        data = request.get_json() or {}

        pilot_id = _safe_strip(data.get('pilot_id'))
        if not pilot_id:
            return jsonify(create_error_response('VALIDATION_ERROR', '主播ID为必填项')), 400

        try:
            pilot = Pilot.objects.get(id=pilot_id)
        except DoesNotExist:
            return jsonify(create_error_response('PILOT_NOT_FOUND', '主播不存在')), 404

        battle_record_id = _safe_strip(data.get('battle_record_id'))
        if not battle_record_id:
            return jsonify(create_error_response('VALIDATION_ERROR', '开播记录ID为必填项')), 400

        try:
            battle_record = BattleRecord.objects.get(id=battle_record_id)
        except DoesNotExist:
            return jsonify(create_error_response('BATTLE_RECORD_NOT_FOUND', '开播记录不存在')), 404

        settlement_type = _safe_strip(data.get('settlement_type'))
        if not settlement_type:
            return jsonify(create_error_response('VALIDATION_ERROR', '结算方式为必填项')), 400

        base_salary_amount_str = _safe_strip(data.get('base_salary_amount'))
        if base_salary_amount_str is None:
            return jsonify(create_error_response('VALIDATION_ERROR', '底薪金额为必填项')), 400

        try:
            from decimal import Decimal
            base_salary_amount = Decimal(base_salary_amount_str)
        except Exception:  # noqa: BLE001
            return jsonify(create_error_response('VALIDATION_ERROR', '底薪金额格式错误')), 400

        application = BaseSalaryApplication(
            pilot_id=pilot,
            battle_record_id=battle_record,
            settlement_type=settlement_type,
            base_salary_amount=base_salary_amount,
            applicant_id=current_user,
            status=BaseSalaryApplicationStatus.PENDING,
            created_at=get_current_utc_time(),
        )

        application.clean()
        application.save()

        # 写变更日志
        change_log = BaseSalaryApplicationChangeLog(
            application_id=application,
            user_id=current_user,
            field_name='created',
            old_value='',
            new_value=BaseSalaryApplicationStatus.PENDING.value,
            change_time=get_current_utc_time(),
            ip_address=_get_client_ip(),
        )
        change_log.save()

        logger.info('创建底薪申请成功，pilot_id=%s, battle_record_id=%s, application_id=%s', pilot_id, battle_record_id, str(application.id))
        return jsonify(create_success_response(serialize_base_salary_application(application))), 201
    except ValidationError as e:
        logger.error('创建底薪申请验证失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('VALIDATION_ERROR', f'数据验证失败：{str(e)}')), 400
    except Exception as e:  # noqa: BLE001
        logger.error('创建底薪申请失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '创建底薪申请失败')), 500


@base_salary_applications_api_bp.route('/api/base-salary-applications/<application_id>', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def get_base_salary_application(application_id):
    """获取单个底薪申请详情"""
    try:
        application = BaseSalaryApplication.objects.get(id=application_id)
        return jsonify(create_success_response(serialize_base_salary_application(application)))
    except DoesNotExist:
        return jsonify(create_error_response('APPLICATION_NOT_FOUND', '底薪申请不存在')), 404
    except Exception as e:  # noqa: BLE001
        logger.error('获取底薪申请详情失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取底薪申请详情失败')), 500


@base_salary_applications_api_bp.route('/api/base-salary-applications/<application_id>/status', methods=['PATCH'])
@jwt_roles_accepted('gicho', 'kancho')
def update_base_salary_application_status(application_id):
    """更新底薪申请状态"""
    try:
        application = BaseSalaryApplication.objects.get(id=application_id)
        data = request.get_json() or {}

        new_status_str = _safe_strip(data.get('status'))
        if not new_status_str:
            return jsonify(create_error_response('VALIDATION_ERROR', '状态为必填项')), 400

        try:
            new_status = BaseSalaryApplicationStatus(new_status_str)
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '状态值无效')), 400

        if application.status == new_status:
            return jsonify(create_success_response(serialize_base_salary_application(application)))

        old_status = application.status
        application.status = new_status
        application.save()

        # 写变更日志
        remark = _safe_strip(data.get('remark')) or ''
        change_log = BaseSalaryApplicationChangeLog(
            application_id=application,
            user_id=current_user,
            field_name='status',
            old_value=old_status.value,
            new_value=new_status.value,
            remark=remark,
            change_time=get_current_utc_time(),
            ip_address=_get_client_ip(),
        )
        change_log.save()

        logger.info('更新底薪申请状态成功，application_id=%s, old_status=%s, new_status=%s', application_id, old_status.value, new_status.value)
        return jsonify(create_success_response(serialize_base_salary_application(application)))
    except DoesNotExist:
        return jsonify(create_error_response('APPLICATION_NOT_FOUND', '底薪申请不存在')), 404
    except Exception as e:  # noqa: BLE001
        logger.error('更新底薪申请状态失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '更新底薪申请状态失败')), 500


@base_salary_applications_api_bp.route('/api/base-salary-applications/<application_id>/changes', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def list_base_salary_application_changes(application_id):
    """获取单个底薪申请的变更日志"""
    try:
        application = BaseSalaryApplication.objects.get(id=application_id)
        logs = BaseSalaryApplicationChangeLog.objects(application_id=application).order_by('-change_time').limit(100)
        data = serialize_base_salary_application_change_log_list(logs)
        return jsonify(create_success_response({'items': data}))
    except DoesNotExist:
        return jsonify(create_error_response('APPLICATION_NOT_FOUND', '底薪申请不存在')), 404
    except Exception as e:  # noqa: BLE001
        logger.error('获取底薪申请变更记录失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取变更记录失败')), 500


@base_salary_applications_api_bp.route('/api/base-salary-applications/export', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def export_base_salary_applications():
    """导出底薪申请为CSV"""
    try:
        date_str = request.args.get('date')

        query_filter = {}

        if date_str:
            try:
                query_date = datetime.strptime(date_str, '%Y-%m-%d')
            except ValueError:
                return jsonify(create_error_response('VALIDATION_ERROR', '日期格式应为YYYY-MM-DD')), 400

            start_of_day = local_to_utc(query_date.replace(hour=0, minute=0, second=0, microsecond=0))
            end_of_day = local_to_utc(query_date.replace(hour=23, minute=59, second=59, microsecond=999999))

            query_filter['created_at__gte'] = start_of_day
            query_filter['created_at__lte'] = end_of_day

        applications = BaseSalaryApplication.objects(**query_filter).order_by('-created_at')

        # 生成CSV
        output = io.StringIO()
        writer = csv.writer(output)

        # 添加BOM以确保Excel兼容性
        output.write('\ufeff')

        # 写入表头
        headers = ['主播昵称', '真实姓名', '直属运营', '申请人', '开播时间', '时长', '结算方式', '流水金额', '申请底薪', '申请时间', '状态']
        writer.writerow(headers)

        for app in applications:
            try:
                pilot = app.pilot_id
                pilot_nickname = pilot.nickname if pilot else '未知'
                pilot_real_name = pilot.real_name if pilot else '未知'
                owner_nickname = pilot.owner.nickname if pilot and pilot.owner else '未知'

                battle_record = app.battle_record_id
                if battle_record:
                    start_time_str = utc_to_local(battle_record.start_time).strftime('%Y-%m-%d %H:%M')
                    duration_hours = battle_record.duration_hours or 0
                    revenue_amount = battle_record.revenue_amount or '0.00'
                else:
                    start_time_str = '未知'
                    duration_hours = 0
                    revenue_amount = '0.00'

                applicant_nickname = app.applicant_id.nickname if app.applicant_id else '未知'
                created_at_str = utc_to_local(app.created_at).strftime('%Y-%m-%d %H:%M')
                status_display = app.status_display
                settlement_type_display = app.settlement_type_display

                row = [
                    pilot_nickname, pilot_real_name, owner_nickname, applicant_nickname, start_time_str, duration_hours, settlement_type_display, revenue_amount,
                    str(app.base_salary_amount), created_at_str, status_display
                ]
                writer.writerow(row)
            except Exception:  # noqa: BLE001
                continue

        csv_content = output.getvalue()
        output.close()

        filename = f'底薪申请_{date_str or "全部"}.csv'
        encoded_filename = quote(filename.encode('utf-8'))

        response = Response(csv_content,
                            mimetype='text/csv; charset=utf-8',
                            headers={'Content-Disposition': f'attachment; filename*=UTF-8\'\'{encoded_filename}'})

        return response
    except Exception as e:  # noqa: BLE001
        logger.error('导出底薪申请失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '导出底薪申请失败')), 500
