"""
主播结算管理 REST API 路由
提供结算方式的读写接口，遵循统一响应结构与权限策略
"""
# pylint: disable=no-member
from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_security import current_user
from mongoengine import DoesNotExist, ValidationError

from models.pilot import Pilot, Settlement, SettlementChangeLog, SettlementType
from utils.jwt_roles import jwt_roles_accepted
from utils.logging_setup import get_logger
from utils.settlement_serializers import (create_error_response, create_success_response, serialize_settlement, serialize_settlement_change_log_list)
from utils.timezone_helper import (get_current_local_time, get_current_utc_time, local_to_utc, utc_to_local)

logger = get_logger('settlement')
settlements_api_bp = Blueprint('settlements_api', __name__)


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


@settlements_api_bp.route('/api/settlements/<pilot_id>', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def list_settlements(pilot_id):
    """获取主播的结算方式记录列表及当前生效信息"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)

        page = max(int(request.args.get('page', 1) or 1), 1)
        page_size = min(max(int(request.args.get('page_size', 20) or 20), 1), 100)

        qs = Settlement.objects(pilot_id=pilot).order_by('-effective_date')
        total = qs.count()
        items = [serialize_settlement(s) for s in qs.skip((page - 1) * page_size).limit(page_size)]

        # 获取当前生效的结算方式
        current_local = get_current_local_time()
        current_local_utc = local_to_utc(current_local.replace(hour=0, minute=0, second=0, microsecond=0))

        effective_settlement = Settlement.objects(pilot_id=pilot, effective_date__lte=current_local_utc, is_active=True).order_by('-effective_date').first()

        current_settlement = {
            'settlement_type': 'none',
            'settlement_type_display': '无底薪',
            'effective_date': None,
            'remark': None,
        }
        if effective_settlement:
            current_settlement = {
                'settlement_type': effective_settlement.settlement_type.value,
                'settlement_type_display': effective_settlement.settlement_type_display,
                'effective_date': utc_to_local(effective_settlement.effective_date).strftime('%Y-%m-%d'),
                'remark': effective_settlement.remark,
            }

        meta = {'page': page, 'page_size': page_size, 'total': total}
        return jsonify(create_success_response({'items': items, 'current_settlement': current_settlement}, meta))
    except DoesNotExist:
        return jsonify(create_error_response('PILOT_NOT_FOUND', '主播不存在')), 404
    except Exception as e:  # noqa: BLE001
        logger.error('获取结算方式列表失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取结算方式列表失败')), 500


@settlements_api_bp.route('/api/settlements/<pilot_id>', methods=['POST'])
@jwt_roles_accepted('gicho', 'kancho')
def create_settlement(pilot_id):
    """创建新的结算方式记录"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)
        data = request.get_json() or {}

        effective_date_str = _safe_strip(data.get('effective_date'))
        if not effective_date_str:
            return jsonify(create_error_response('VALIDATION_ERROR', '生效日期为必填项')), 400

        try:
            effective_date_local = datetime.strptime(effective_date_str, '%Y-%m-%d')
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '生效日期格式应为YYYY-MM-DD')), 400

        settlement_type_str = _safe_strip(data.get('settlement_type'))
        if not settlement_type_str:
            return jsonify(create_error_response('VALIDATION_ERROR', '结算方式为必填项')), 400

        try:
            settlement_type = SettlementType(settlement_type_str)
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '结算方式值无效')), 400

        remark = _safe_strip(data.get('remark'))

        settlement = Settlement(
            pilot_id=pilot,
            effective_date=local_to_utc(effective_date_local),
            settlement_type=settlement_type,
            remark=remark,
            is_active=True,
            created_at=get_current_utc_time(),
        )

        settlement.clean()
        settlement.save()

        # 写变更日志
        change_log = SettlementChangeLog(
            settlement_id=settlement,
            user_id=current_user,
            field_name='created',
            old_value='',
            new_value=f'{settlement_type.value}',
            ip_address=_get_client_ip(),
        )
        change_log.save()

        logger.info('创建结算方式记录成功，pilot_id=%s, record_id=%s', pilot_id, str(settlement.id))
        return jsonify(create_success_response(serialize_settlement(settlement))), 201
    except ValidationError as e:
        logger.error('创建结算方式记录验证失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('VALIDATION_ERROR', f'数据验证失败：{str(e)}')), 400
    except DoesNotExist:
        return jsonify(create_error_response('PILOT_NOT_FOUND', '主播不存在')), 404
    except ValueError as e:
        logger.error('创建结算方式记录验证错误: %s', str(e))
        return jsonify(create_error_response('VALIDATION_ERROR', str(e))), 400
    except Exception as e:  # noqa: BLE001
        logger.error('创建结算方式记录失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '创建结算方式记录失败')), 500


@settlements_api_bp.route('/api/settlements/<record_id>', methods=['PUT'])
@jwt_roles_accepted('gicho', 'kancho')
def update_settlement(record_id):
    """更新结算方式记录"""
    try:
        settlement = Settlement.objects.get(id=record_id)
        data = request.get_json() or {}

        fields_changed = []

        if 'settlement_type' in data:
            new_type_str = _safe_strip(data.get('settlement_type'))
            if new_type_str:
                try:
                    new_type = SettlementType(new_type_str)
                    if settlement.settlement_type != new_type:
                        fields_changed.append(('settlement_type', settlement.settlement_type.value, new_type.value))
                        settlement.settlement_type = new_type
                except ValueError:
                    return jsonify(create_error_response('VALIDATION_ERROR', '结算方式值无效')), 400

        if 'remark' in data:
            new_remark = _safe_strip(data.get('remark'))
            if (settlement.remark or '') != (new_remark or ''):
                fields_changed.append(('remark', settlement.remark or '', new_remark or ''))
                settlement.remark = new_remark

        if 'is_active' in data:
            new_active = bool(data.get('is_active'))
            if settlement.is_active != new_active:
                fields_changed.append(('is_active', str(settlement.is_active), str(new_active)))
                settlement.is_active = new_active

        settlement.clean()
        settlement.save()

        # 写变更日志
        for field_name, old_value, new_value in fields_changed:
            SettlementChangeLog(
                settlement_id=settlement,
                user_id=current_user,
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                ip_address=_get_client_ip(),
            ).save()

        logger.info('更新结算方式记录成功，record_id=%s', record_id)
        return jsonify(create_success_response(serialize_settlement(settlement)))
    except ValidationError as e:
        logger.error('更新结算方式记录验证失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('VALIDATION_ERROR', f'数据验证失败：{str(e)}')), 400
    except DoesNotExist:
        return jsonify(create_error_response('RECORD_NOT_FOUND', '结算方式记录不存在')), 404
    except Exception as e:  # noqa: BLE001
        logger.error('更新结算方式记录失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '更新结算方式记录失败')), 500


@settlements_api_bp.route('/api/settlements/<record_id>', methods=['DELETE'])
@jwt_roles_accepted('gicho', 'kancho')
def deactivate_settlement(record_id):
    """软删除结算方式记录"""
    try:
        settlement = Settlement.objects.get(id=record_id)

        if settlement.is_active:
            settlement.is_active = False
            settlement.save()

            SettlementChangeLog(
                settlement_id=settlement,
                user_id=current_user,
                field_name='is_active',
                old_value='true',
                new_value='false',
                ip_address=_get_client_ip(),
            ).save()

            logger.info('软删除结算方式记录成功，record_id=%s', record_id)

        return jsonify(create_success_response({'message': '删除成功'}))
    except DoesNotExist:
        return jsonify(create_error_response('RECORD_NOT_FOUND', '结算方式记录不存在')), 404
    except Exception as e:  # noqa: BLE001
        logger.error('删除结算方式记录失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '删除结算方式记录失败')), 500


@settlements_api_bp.route('/api/settlements/<pilot_id>/effective', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def get_effective_settlement(pilot_id):
    """查询指定日期主播的生效结算方式"""
    try:
        # 验证pilot_id参数有效性
        if not pilot_id or pilot_id == 'undefined' or pilot_id == 'null':
            return jsonify(create_error_response('INVALID_PILOT_ID', '无效的主播ID')), 400

        # 验证ObjectId格式
        from bson import ObjectId
        try:
            ObjectId(pilot_id)
        except Exception:
            return jsonify(create_error_response('INVALID_PILOT_ID', '无效的主播ID格式')), 400

        pilot = Pilot.objects.get(id=pilot_id)
        date_str = request.args.get('date')

        if not date_str:
            return jsonify(create_error_response('VALIDATION_ERROR', '日期参数为必填项')), 400

        try:
            query_date = datetime.strptime(date_str, '%Y-%m-%d')
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '日期格式应为YYYY-MM-DD')), 400

        # 转换为UTC的该天开始时间
        query_date_utc = local_to_utc(query_date)

        # 查找生效日期<=查询日期的最新有效记录
        effective_settlement = Settlement.objects(pilot_id=pilot, effective_date__lte=query_date_utc, is_active=True).order_by('-effective_date').first()

        settlement_data = {
            'settlement_type': 'none',
            'settlement_type_display': '无底薪',
            'effective_date': None,
        }
        if effective_settlement:
            settlement_data = {
                'settlement_type': effective_settlement.settlement_type.value,
                'settlement_type_display': effective_settlement.settlement_type_display,
                'effective_date': utc_to_local(effective_settlement.effective_date).strftime('%Y-%m-%d'),
            }

        return jsonify(create_success_response(settlement_data))
    except DoesNotExist:
        return jsonify(create_error_response('PILOT_NOT_FOUND', '主播不存在')), 404
    except Exception as e:  # noqa: BLE001
        logger.error('查询生效结算方式失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '查询生效结算方式失败')), 500


@settlements_api_bp.route('/api/settlements/<record_id>/changes', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def list_settlement_changes(record_id):
    """获取单条结算方式记录的变更日志"""
    try:
        settlement = Settlement.objects.get(id=record_id)
        logs = SettlementChangeLog.objects(settlement_id=settlement).order_by('-change_time').limit(100)
        data = serialize_settlement_change_log_list(logs)
        return jsonify(create_success_response({'items': data}))
    except DoesNotExist:
        return jsonify(create_error_response('RECORD_NOT_FOUND', '结算方式记录不存在')), 404
    except Exception as e:  # noqa: BLE001
        logger.error('获取结算方式变更记录失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取变更记录失败')), 500
