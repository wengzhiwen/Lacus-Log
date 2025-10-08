# -*- coding: utf-8 -*-
# pylint: disable=no-member,too-many-return-statements,too-many-locals
"""开播地点管理 REST API 路由。"""

from typing import Dict, List, Tuple

from flask import Blueprint, jsonify, request
from flask_security import current_user, roles_accepted
from mongoengine import DoesNotExist, ValidationError
from mongoengine.errors import NotUniqueError

from models.battle_area import Availability, BattleArea
from utils.battle_area_serializers import (create_error_response,
                                           create_success_response,
                                           serialize_battle_area,
                                           serialize_battle_area_list)
from utils.csrf_helper import CSRFError, validate_csrf_header
from utils.filter_state import persist_and_restore_filters
from utils.jwt_roles import jwt_roles_accepted, jwt_roles_required
from utils.logging_setup import get_logger

logger = get_logger('battle_area_api')

battle_areas_api_bp = Blueprint('battle_areas_api', __name__)


def safe_strip(value) -> str:
    """安全地去除前后空白。"""
    if value is None:
        return ''
    if isinstance(value, str):
        return value.strip()
    return str(value).strip()


def _collect_choices(x_filter: str) -> Dict[str, List[str]]:
    """收集筛选选项。"""
    x_choices = sorted({area.x_coord for area in BattleArea.objects.only('x_coord')})
    if x_filter:
        y_queryset = BattleArea.objects(x_coord=x_filter).only('y_coord')
    else:
        y_queryset = BattleArea.objects.only('y_coord')
    y_choices = sorted({area.y_coord for area in y_queryset})
    availability_choices = [availability.value for availability in Availability]
    return {
        'x_choices': x_choices,
        'y_choices': y_choices,
        'availability_choices': availability_choices,
    }


@battle_areas_api_bp.route('/api/battle-areas', methods=['GET'])
@jwt_roles_accepted('gicho')
def get_battle_areas():
    """获取开播地点列表。"""
    try:
        filters = persist_and_restore_filters(
            'battle_areas_list',
            allowed_keys=['x', 'y', 'availability'],
            default_filters={
                'x': '',
                'y': '',
                'availability': Availability.ENABLED.value
            },
        )

        x_filter = safe_strip(filters.get('x')) or ''
        y_filter = safe_strip(filters.get('y')) or ''
        availability_filter = safe_strip(filters.get('availability')) or ''

        query = BattleArea.objects

        if x_filter:
            query = query.filter(x_coord=x_filter)
        if y_filter:
            query = query.filter(y_coord=y_filter)

        if availability_filter:
            try:
                query = query.filter(availability=Availability(availability_filter))
            except ValueError:
                logger.warning('忽略无效可用性筛选值：%s', availability_filter)
        else:
            query = query.filter(availability=Availability.ENABLED)

        areas = list(query.order_by('x_coord', 'y_coord', 'z_coord'))
        items = serialize_battle_area_list(areas)

        choices = _collect_choices(x_filter)
        meta = {
            'filters': {
                'x': x_filter,
                'y': y_filter,
                'availability': availability_filter,
            },
            'options': choices,
            'total': len(items),
        }

        return jsonify(create_success_response({'items': items}, meta))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取开播地点列表失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@battle_areas_api_bp.route('/api/battle-areas/<area_id>', methods=['GET'])
@jwt_roles_accepted('gicho')
def get_battle_area(area_id: str):
    """获取单个开播地点详情。"""
    try:
        area = BattleArea.objects.get(id=area_id)
        return jsonify(create_success_response(serialize_battle_area(area)))
    except DoesNotExist:
        return jsonify(create_error_response('BATTLE_AREA_NOT_FOUND', '开播地点不存在')), 404
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取开播地点详情失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@battle_areas_api_bp.route('/api/battle-areas/options', methods=['GET'])
@jwt_roles_accepted('gicho')
def get_battle_area_options():
    """获取筛选器可选项。"""
    try:
        x_filter = safe_strip(request.args.get('x'))
        choices = _collect_choices(x_filter)
        data = {
            'options': choices,
            'default_filters': {
                'x': '',
                'y': '',
                'availability': Availability.ENABLED.value,
            },
        }
        return jsonify(create_success_response(data))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取开播地点筛选选项失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@battle_areas_api_bp.route('/api/battle-areas', methods=['POST'])
@jwt_roles_accepted('gicho')
def create_battle_area():
    """创建开播地点。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    payload = request.get_json(silent=True) or {}

    x_coord = safe_strip(payload.get('x_coord'))
    y_coord = safe_strip(payload.get('y_coord'))
    z_coord = safe_strip(payload.get('z_coord'))
    availability_value = safe_strip(payload.get('availability')) or Availability.ENABLED.value

    if not x_coord or not y_coord or not z_coord:
        return jsonify(create_error_response('MISSING_FIELDS', '基地/场地/坐席均为必填项')), 400

    try:
        availability = Availability(availability_value)
    except ValueError:
        return jsonify(create_error_response('INVALID_AVAILABILITY', '可用性参数无效')), 400

    try:
        if BattleArea.objects(x_coord=x_coord, y_coord=y_coord, z_coord=z_coord).first():
            return jsonify(create_error_response('DUPLICATED_COORDINATE', '同一基地+场地+坐席的开播地点已存在')), 409

        area = BattleArea(x_coord=x_coord, y_coord=y_coord, z_coord=z_coord, availability=availability)
        area.save()

        logger.info('用户%s创建开播地点：%s-%s-%s', current_user.username, x_coord, y_coord, z_coord)
        return jsonify(create_success_response(serialize_battle_area(area))), 201
    except (ValidationError, NotUniqueError) as exc:
        logger.warning('创建开播地点失败（校验问题）：%s', str(exc))
        return jsonify(create_error_response('VALIDATION_ERROR', '数据验证失败')), 400
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('创建开播地点失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@battle_areas_api_bp.route('/api/battle-areas/<area_id>', methods=['PUT'])
@jwt_roles_accepted('gicho')
def update_battle_area(area_id: str):
    """更新开播地点信息。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    payload = request.get_json(silent=True) or {}

    x_coord = safe_strip(payload.get('x_coord'))
    y_coord = safe_strip(payload.get('y_coord'))
    z_coord = safe_strip(payload.get('z_coord'))
    availability_value = safe_strip(payload.get('availability'))

    if not x_coord or not y_coord or not z_coord:
        return jsonify(create_error_response('MISSING_FIELDS', '基地/场地/坐席均为必填项')), 400

    try:
        availability = Availability(availability_value) if availability_value else None
    except ValueError:
        return jsonify(create_error_response('INVALID_AVAILABILITY', '可用性参数无效')), 400

    try:
        area = BattleArea.objects.get(id=area_id)
    except DoesNotExist:
        return jsonify(create_error_response('BATTLE_AREA_NOT_FOUND', '开播地点不存在')), 404

    try:
        existing = BattleArea.objects(x_coord=x_coord, y_coord=y_coord, z_coord=z_coord).first()
        if existing and existing.id != area.id:
            return jsonify(create_error_response('DUPLICATED_COORDINATE', '同一基地+场地+坐席的开播地点已存在')), 409

        area.x_coord = x_coord
        area.y_coord = y_coord
        area.z_coord = z_coord
        if availability is not None:
            area.availability = availability
        area.save()

        logger.info('用户%s更新开播地点：%s-%s-%s', current_user.username, x_coord, y_coord, z_coord)
        return jsonify(create_success_response(serialize_battle_area(area)))
    except (ValidationError, NotUniqueError) as exc:
        logger.warning('更新开播地点失败（校验问题）：%s', str(exc))
        return jsonify(create_error_response('VALIDATION_ERROR', '数据验证失败')), 400
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('更新开播地点失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@battle_areas_api_bp.route('/api/battle-areas/bulk-generate', methods=['POST'])
@jwt_roles_accepted('gicho')
def bulk_generate_battle_areas():
    """基于源开播地点批量生成新的坐席。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    payload = request.get_json(silent=True) or {}

    source_id = safe_strip(payload.get('source_id'))
    z_start_raw = safe_strip(payload.get('z_start'))
    z_end_raw = safe_strip(payload.get('z_end'))

    if not source_id:
        return jsonify(create_error_response('MISSING_SOURCE', '缺少源开播地点标识')), 400

    if not z_start_raw.isdigit() or not z_end_raw.isdigit():
        return jsonify(create_error_response('INVALID_RANGE', '坐席起止必须为数字')), 400

    z_start = int(z_start_raw)
    z_end = int(z_end_raw)
    if z_start >= z_end:
        return jsonify(create_error_response('INVALID_RANGE_ORDER', '坐席开始必须小于结束')), 400

    try:
        src = BattleArea.objects.get(id=source_id)
    except DoesNotExist:
        return jsonify(create_error_response('BATTLE_AREA_NOT_FOUND', '开播地点不存在')), 404

    will_create = [{'x': src.x_coord, 'y': src.y_coord, 'z': str(z)} for z in range(z_start, z_end + 1)]

    duplicates = []
    for item in will_create:
        if BattleArea.objects(x_coord=item['x'], y_coord=item['y'], z_coord=item['z']).first():
            duplicates.append(item)

    if duplicates:
        meta = {'duplicates': duplicates}
        return jsonify(create_error_response('DUPLICATED_COORDINATE', '存在已存在的开播地点，未执行生成', meta=meta)), 409

    created: List[BattleArea] = []
    try:
        for item in will_create:
            area = BattleArea(x_coord=item['x'], y_coord=item['y'], z_coord=item['z'], availability=Availability.ENABLED)
            area.save()
            created.append(area)

        logger.info('用户%s批量创建开播地点：%s-%s 坐席%s-%s 共%d个', current_user.username, src.x_coord, src.y_coord, z_start, z_end, len(created))

        data = {
            'source': serialize_battle_area(src),
            'created': serialize_battle_area_list(created),
        }
        meta = {'count': len(created)}
        return jsonify(create_success_response(data, meta)), 201
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('批量生成开播地点失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500
