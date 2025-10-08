# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""
主播分成管理 REST API 路由
提供机师分成的只读与写入接口，遵循 pilots_api 的统一响应结构与权限策略。
"""

from datetime import datetime
from typing import Any, Dict

from flask import Blueprint, jsonify, request
from flask_security import current_user
from mongoengine import DoesNotExist, ValidationError

from models.pilot import Pilot, PilotCommission, PilotCommissionChangeLog
from utils.commission_helper import (calculate_commission_distribution,
                                     get_pilot_commission_rate_for_date)
from utils.csrf_helper import CSRFError, validate_csrf_header
from utils.jwt_roles import jwt_roles_accepted
from utils.logging_setup import get_logger
from utils.pilot_serializers import (create_error_response,
                                     create_success_response)
from utils.timezone_helper import (get_current_utc_time, local_to_utc,
                                   utc_to_local)

logger = get_logger('commission')
commissions_api_bp = Blueprint('commissions_api', __name__)


def _safe_strip(value):
    if value is None:
        return None
    if isinstance(value, str):
        s = value.strip()
        return s if s else None
    return None


def _serialize_commission(c: PilotCommission) -> Dict[str, Any]:
    return {
        'id': str(c.id),
        'pilot_id': str(c.pilot_id.id) if c.pilot_id else None,
        'adjustment_date': utc_to_local(c.adjustment_date).isoformat() if c.adjustment_date else None,
        'commission_rate': c.commission_rate,
        'remark': c.remark,
        'is_active': c.is_active,
        'created_at': utc_to_local(c.created_at).isoformat() if c.created_at else None,
        'updated_at': utc_to_local(c.updated_at).isoformat() if c.updated_at else None,
    }


def _serialize_commission_change(log: PilotCommissionChangeLog) -> Dict[str, Any]:
    return {
        'id': str(log.id),
        'field_name': log.field_name,
        'old_value': log.old_value,
        'new_value': log.new_value,
        'user': {
            'id': str(log.user_id.id),
            'nickname': getattr(log.user_id, 'nickname', '')
        } if log.user_id else None,
        'ip_address': log.ip_address,
        'change_time': utc_to_local(log.change_time).isoformat() if log.change_time else None,
    }


@commissions_api_bp.route('/api/pilots/<pilot_id>/commission/current', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def get_current_commission(pilot_id):
    """获取主播当前分成与计算信息"""
    try:
        _ = Pilot.objects.get(id=pilot_id)

        # 使用GMT+8的今天进行计算，确保分成生效时间准确
        from utils.timezone_helper import get_current_local_time
        today_local = get_current_local_time().date()
        commission_rate, effective_date, remark = get_pilot_commission_rate_for_date(pilot_id, today_local)
        calc = calculate_commission_distribution(commission_rate)

        data = {
            'current_rate': commission_rate,
            'effective_date': utc_to_local(effective_date).isoformat() if effective_date else None,
            'remark': remark,
            'calculation_info': calc,
        }

        logger.info('获取当前分成成功，pilot_id=%s，基于GMT+8日期=%s', pilot_id, today_local)
        return jsonify(create_success_response(data))
    except DoesNotExist:
        return jsonify(create_error_response('PILOT_NOT_FOUND', '主播不存在')), 404
    except Exception as e:  # noqa: BLE001 - 需要完整记录
        logger.error('获取当前分成失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取当前分成失败')), 500


@commissions_api_bp.route('/api/pilots/<pilot_id>/commission/records', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def list_commission_records(pilot_id):
    """分页获取分成调整记录"""
    try:
        _ = Pilot.objects.get(id=pilot_id)

        page = max(int(request.args.get('page', 1) or 1), 1)
        page_size = min(max(int(request.args.get('page_size', 20) or 20), 1), 100)

        qs = PilotCommission.objects(pilot_id=pilot_id).order_by('-adjustment_date')
        total = qs.count()
        items = [_serialize_commission(c) for c in qs.skip((page - 1) * page_size).limit(page_size)]

        meta = {'page': page, 'page_size': page_size, 'total': total}
        return jsonify(create_success_response({'items': items}, meta))
    except DoesNotExist:
        return jsonify(create_error_response('PILOT_NOT_FOUND', '主播不存在')), 404
    except Exception as e:  # noqa: BLE001
        logger.error('获取分成记录失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取分成记录失败')), 500


@commissions_api_bp.route('/api/pilots/<pilot_id>/commission/records', methods=['POST'])
@jwt_roles_accepted('gicho', 'kancho')
def create_commission_record(pilot_id):
    """创建分成调整记录"""
    try:
        try:
            validate_csrf_header()
        except CSRFError as exc:
            return jsonify(create_error_response(exc.code, exc.message)), 401

        pilot = Pilot.objects.get(id=pilot_id)
        data = request.get_json() or {}

        adjustment_date_local = _safe_strip(data.get('adjustment_date'))  # 期望格式 YYYY-MM-DD
        if not adjustment_date_local:
            return jsonify(create_error_response('VALIDATION_ERROR', '调整日期为必填项')), 400
        try:
            dt_local = datetime.strptime(adjustment_date_local, '%Y-%m-%d')
        except ValueError:
            return jsonify(create_error_response('VALIDATION_ERROR', '调整日期格式应为YYYY-MM-DD')), 400

        commission_rate = data.get('commission_rate')
        if commission_rate is None:
            return jsonify(create_error_response('VALIDATION_ERROR', '分成比例为必填项')), 400

        remark = _safe_strip(data.get('remark'))

        record = PilotCommission(
            pilot_id=pilot,
            adjustment_date=local_to_utc(dt_local),
            commission_rate=float(commission_rate),
            remark=remark,
            is_active=True,
            created_at=get_current_utc_time(),
            updated_at=get_current_utc_time(),
        )

        record.clean()
        record.save()

        # 写变更日志（创建）
        change_log = PilotCommissionChangeLog(
            commission_id=record,
            user_id=current_user,
            field_name='created',
            old_value='',
            new_value=f'{record.commission_rate}',
            ip_address=request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR'),
        )
        change_log.save()

        logger.info('创建分成记录成功，pilot_id=%s, record_id=%s', pilot_id, str(record.id))
        return jsonify(create_success_response(_serialize_commission(record), {'message': '创建成功'})), 201
    except ValueError as e:
        return jsonify(create_error_response('VALIDATION_ERROR', str(e))), 400
    except ValidationError as e:
        return jsonify(create_error_response('VALIDATION_ERROR', f'数据验证失败：{str(e)}')), 400
    except DoesNotExist:
        return jsonify(create_error_response('PILOT_NOT_FOUND', '主播不存在')), 404
    except Exception as e:  # noqa: BLE001
        logger.error('创建分成记录失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '创建分成记录失败')), 500


@commissions_api_bp.route('/api/pilots/<pilot_id>/commission/records/<record_id>', methods=['PUT'])
@jwt_roles_accepted('gicho', 'kancho')
def update_commission_record(pilot_id, record_id):
    """更新分成调整记录"""
    try:
        try:
            validate_csrf_header()
        except CSRFError as exc:
            return jsonify(create_error_response(exc.code, exc.message)), 401

        _ = Pilot.objects.get(id=pilot_id)
        record = PilotCommission.objects.get(id=record_id, pilot_id=pilot_id)

        data = request.get_json() or {}

        fields_changed = []

        if 'adjustment_date' in data:
            new_date_str = _safe_strip(data.get('adjustment_date'))
            if new_date_str:
                try:
                    dt_local = datetime.strptime(new_date_str, '%Y-%m-%d')
                except ValueError:
                    return jsonify(create_error_response('VALIDATION_ERROR', '调整日期格式应为YYYY-MM-DD')), 400
                if record.adjustment_date != local_to_utc(dt_local):
                    fields_changed.append(
                        ('adjustment_date', record.adjustment_date.isoformat() if record.adjustment_date else '', local_to_utc(dt_local).isoformat()))
                    record.adjustment_date = local_to_utc(dt_local)

        if 'commission_rate' in data and data.get('commission_rate') is not None:
            new_rate = float(data.get('commission_rate'))
            if record.commission_rate != new_rate:
                fields_changed.append(('commission_rate', str(record.commission_rate), str(new_rate)))
                record.commission_rate = new_rate

        if 'remark' in data:
            new_remark = _safe_strip(data.get('remark'))
            if (record.remark or '') != (new_remark or ''):
                fields_changed.append(('remark', record.remark or '', new_remark or ''))
                record.remark = new_remark

        record.clean()
        record.save()

        for field_name, old_value, new_value in fields_changed:
            PilotCommissionChangeLog(
                commission_id=record,
                user_id=current_user,
                field_name=field_name,
                old_value=old_value,
                new_value=new_value,
                ip_address=request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR'),
            ).save()

        logger.info('更新分成记录成功，pilot_id=%s, record_id=%s', pilot_id, record_id)
        return jsonify(create_success_response(_serialize_commission(record), {'message': '更新成功'}))
    except ValueError as e:
        return jsonify(create_error_response('VALIDATION_ERROR', str(e))), 400
    except ValidationError as e:
        return jsonify(create_error_response('VALIDATION_ERROR', f'数据验证失败：{str(e)}')), 400
    except DoesNotExist:
        return jsonify(create_error_response('RECORD_NOT_FOUND', '分成记录不存在')), 404
    except Exception as e:  # noqa: BLE001
        logger.error('更新分成记录失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '更新分成记录失败')), 500


@commissions_api_bp.route('/api/pilots/<pilot_id>/commission/records/<record_id>/deactivate', methods=['POST'])
@jwt_roles_accepted('gicho', 'kancho')
def deactivate_commission_record(pilot_id, record_id):
    """软删除分成记录"""
    try:
        try:
            validate_csrf_header()
        except CSRFError as exc:
            return jsonify(create_error_response(exc.code, exc.message)), 401

        _ = Pilot.objects.get(id=pilot_id)
        record = PilotCommission.objects.get(id=record_id, pilot_id=pilot_id)
        if record.is_active:
            record.is_active = False
            record.save()
            PilotCommissionChangeLog(
                commission_id=record,
                user_id=current_user,
                field_name='is_active',
                old_value='True',
                new_value='False',
                ip_address=request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR'),
            ).save()
        return jsonify(create_success_response(_serialize_commission(record), {'message': '已停用'}))
    except DoesNotExist:
        return jsonify(create_error_response('RECORD_NOT_FOUND', '分成记录不存在')), 404
    except Exception as e:  # noqa: BLE001
        logger.error('停用分成记录失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '停用分成记录失败')), 500


@commissions_api_bp.route('/api/pilots/<pilot_id>/commission/records/<record_id>/activate', methods=['POST'])
@jwt_roles_accepted('gicho', 'kancho')
def activate_commission_record(pilot_id, record_id):
    """恢复分成记录"""
    try:
        try:
            validate_csrf_header()
        except CSRFError as exc:
            return jsonify(create_error_response(exc.code, exc.message)), 401

        _ = Pilot.objects.get(id=pilot_id)
        record = PilotCommission.objects.get(id=record_id, pilot_id=pilot_id)
        if not record.is_active:
            record.is_active = True
            record.save()
            PilotCommissionChangeLog(
                commission_id=record,
                user_id=current_user,
                field_name='is_active',
                old_value='False',
                new_value='True',
                ip_address=request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR'),
            ).save()
        return jsonify(create_success_response(_serialize_commission(record), {'message': '已恢复'}))
    except DoesNotExist:
        return jsonify(create_error_response('RECORD_NOT_FOUND', '分成记录不存在')), 404
    except Exception as e:  # noqa: BLE001
        logger.error('恢复分成记录失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '恢复分成记录失败')), 500


@commissions_api_bp.route('/api/pilots/<pilot_id>/commission/records/<record_id>/changes', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def list_commission_changes(pilot_id, record_id):
    """获取单条分成记录的变更日志"""
    try:
        _ = Pilot.objects.get(id=pilot_id)
        record = PilotCommission.objects.get(id=record_id, pilot_id=pilot_id)
        logs = PilotCommissionChangeLog.objects(commission_id=record).order_by('-change_time').limit(100)
        data = [_serialize_commission_change(x) for x in logs]
        return jsonify(create_success_response({'items': data}))
    except DoesNotExist:
        return jsonify(create_error_response('RECORD_NOT_FOUND', '分成记录不存在')), 404
    except Exception as e:  # noqa: BLE001
        logger.error('获取分成变更记录失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取变更记录失败')), 500
