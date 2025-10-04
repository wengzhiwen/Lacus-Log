# -*- coding: utf-8 -*-
# pylint: disable=no-member,too-many-return-statements,too-many-branches,too-many-locals
"""通告管理 REST API 路由集合。"""

import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, request, url_for
from flask_security import current_user, roles_accepted
from flask_wtf.csrf import ValidationError as CSRFValidationError, validate_csrf
from mongoengine import DoesNotExist, ValidationError

from models.announcement import Announcement, AnnouncementChangeLog, RecurrenceType
from models.battle_area import BattleArea
from models.pilot import Pilot, Rank, Status
from models.user import User
from routes.announcement import _get_client_ip, _record_changes
from utils.announcement_serializers import (create_error_response, create_success_response, serialize_announcement_detail, serialize_announcement_summary,
                                            serialize_change_logs)
from utils.filter_state import persist_and_restore_filters
from utils.logging_setup import get_logger
from utils.timezone_helper import (format_local_datetime, get_current_local_time, local_to_utc, parse_local_date_to_end_datetime, parse_local_datetime,
                                   utc_to_local)

announcements_api_bp = Blueprint('announcements_api', __name__)

logger = get_logger('announcement_api')


def _validate_csrf_header() -> Tuple[bool, str]:
    """验证请求头中的 CSRF Token。"""
    token = request.headers.get('X-CSRFToken')
    if not token:
        return False, '缺少 CSRF 令牌'

    try:
        validate_csrf(token)
        return True, ''
    except CSRFValidationError as exc:  # pylint: disable=raise-missing-from
        logger.warning('CSRF 校验失败：%s', str(exc))
        return False, 'CSRF 令牌无效'


def _safe_strip(value: Optional[str]) -> str:
    return (value or '').strip()


def _build_filter_options() -> Dict[str, List[Dict[str, str]]]:
    """构建列表筛选器选项。"""
    pilots = Pilot.objects.all()
    areas = BattleArea.objects.all()

    owner_set = set()
    for pilot in pilots:
        if pilot.owner:
            owner_set.add((str(pilot.owner.id), pilot.owner.nickname or pilot.owner.username))

    owner_options = [{'value': '', 'label': '全部所属'}]
    owner_options.extend([{'value': owner_id, 'label': owner_name} for owner_id, owner_name in sorted(owner_set, key=lambda item: item[1])])

    x_coords = sorted({area.x_coord for area in areas})
    x_options = [{'value': '', 'label': '全部基地'}]
    x_options.extend([{'value': x, 'label': x} for x in x_coords])

    time_options = [
        {
            'value': 'two_days',
            'label': '这两天'
        },
        {
            'value': 'seven_days',
            'label': '近7天'
        },
        {
            'value': 'today',
            'label': '今天'
        },
    ]

    return {
        'owners': owner_options,
        'x_coords': x_options,
        'time_ranges': time_options,
    }


def _persist_filters_from_request() -> Dict[str, str]:
    return persist_and_restore_filters(
        'announcements_list',
        allowed_keys=['owner', 'x', 'time'],
        default_filters={
            'owner': '',
            'x': '',
            'time': 'two_days'
        },
    )


def _apply_owner_filter(query, owner_filter: str):
    if not owner_filter:
        return query
    try:
        owner_user = User.objects.get(id=owner_filter)
        owner_pilots = Pilot.objects(owner=owner_user)
        pilot_ids = [pilot.id for pilot in owner_pilots]
        return query.filter(pilot__in=pilot_ids)
    except DoesNotExist:
        return query


def _apply_time_filter(query, time_scope: str):
    current_local = get_current_local_time()
    today_local_start = current_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if time_scope == 'two_days':
        yesterday_local_start = today_local_start - timedelta(days=1)
        day_after_tomorrow_local_start = today_local_start + timedelta(days=2)
        range_start_utc = local_to_utc(yesterday_local_start)
        range_end_utc = local_to_utc(day_after_tomorrow_local_start)
    elif time_scope == 'today':
        tomorrow_local_start = today_local_start + timedelta(days=1)
        range_start_utc = local_to_utc(today_local_start)
        range_end_utc = local_to_utc(tomorrow_local_start)
    elif time_scope == 'seven_days':
        seven_days_later_local_start = today_local_start + timedelta(days=7)
        range_start_utc = local_to_utc(today_local_start)
        range_end_utc = local_to_utc(seven_days_later_local_start)
    else:
        return query

    return query.filter(start_time__gte=range_start_utc, start_time__lt=range_end_utc)


@announcements_api_bp.route('/announcements/api/announcements', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def list_announcements_api():
    """通告列表 API。"""
    try:
        filters = _persist_filters_from_request()
        owner_filter = _safe_strip(filters.get('owner'))
        x_filter = _safe_strip(filters.get('x'))
        time_scope = (filters.get('time') or 'two_days').strip()

        query = Announcement.objects
        query = _apply_owner_filter(query, owner_filter)

        if x_filter:
            query = query.filter(x_coord=x_filter)

        query = _apply_time_filter(query, time_scope)

        announcements = list(query.limit(100))
        announcements.sort(key=lambda a: (
            utc_to_local(a.start_time).date() if a.start_time else datetime.min.date(),
            (a.pilot.nickname or '') if a.pilot else '',
        ))

        items = [serialize_announcement_summary(item) for item in announcements]

        meta = {
            'filters': {
                'owner': owner_filter,
                'x': x_filter,
                'time': time_scope or 'two_days',
            },
            'options': _build_filter_options(),
            'total': len(items),
        }

        return jsonify(create_success_response({'items': items}, meta))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取通告列表失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@announcements_api_bp.route('/announcements/api/announcements/<announcement_id>', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_announcement_detail_api(announcement_id: str):
    """通告详情 API。"""
    try:
        announcement = Announcement.objects.get(id=announcement_id)

        if announcement.parent_announcement:
            related_announcements = Announcement.objects(parent_announcement=announcement.parent_announcement).order_by('start_time')
        elif announcement.recurrence_type != RecurrenceType.NONE:
            related_announcements = Announcement.objects(parent_announcement=announcement).order_by('start_time')
        else:
            related_announcements = []

        detail_data = serialize_announcement_detail(announcement, related_announcements)

        meta = {
            'links': {
                'edit_this_only': url_for('announcement.edit_announcement', announcement_id=announcement.id, edit_scope='this_only'),
                'edit_future_all': url_for('announcement.edit_announcement', announcement_id=announcement.id, edit_scope='future_all'),
                'battle_record_new': url_for('battle_record.new_battle_record', announcement_id=announcement.id),
                'pilot_detail': url_for('pilot.pilot_detail', pilot_id=announcement.pilot.id) if announcement.pilot else None,
            },
        }

        return jsonify(create_success_response(detail_data, meta))
    except DoesNotExist:
        return jsonify(create_error_response('ANNOUNCEMENT_NOT_FOUND', '通告不存在')), 404
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取通告详情失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


def _prepare_recurrence_pattern(recurrence_type: str, recurrence_pattern: Dict) -> Tuple[Optional[RecurrenceType], Optional[str]]:
    if not recurrence_type or recurrence_type == 'NONE':
        return RecurrenceType.NONE, None

    try:
        recurrence_enum = RecurrenceType[recurrence_type]
    except KeyError as exc:
        raise ValueError('无效的循环类型') from exc

    pattern = dict(recurrence_pattern or {})
    if 'type' not in pattern:
        pattern['type'] = recurrence_enum.value.lower()

    return recurrence_enum, json.dumps(pattern)


def _create_planned_instances(instances: List[Announcement]) -> List[Dict[str, str]]:
    planned = []
    for instance in instances:
        planned.append({
            'pilot_name': instance.pilot.nickname if instance.pilot else '',
            'start_time': format_local_datetime(instance.start_time, '%Y-%m-%d %H:%M') if instance.start_time else '',
            'duration': f"{instance.duration_hours}小时" if instance.duration_hours else '',
            'coords': f"{instance.x_coord} - {instance.y_coord} - {instance.z_coord}",
        })
    return planned


def _aggregate_conflicts(instances: List[Announcement], exclude_ids: Optional[List[str]] = None) -> List[Dict[str, str]]:
    conflicts_payload: List[Dict[str, str]] = []
    for instance in instances:
        conflicts = instance.check_conflicts(exclude_self=bool(instance.id), exclude_ids=exclude_ids)
        for conflict in conflicts['area_conflicts']:
            announcement = conflict['announcement']
            conflicts_payload.append({
                'type': '开播地点冲突',
                'instance_time': format_local_datetime(instance.start_time, '%Y-%m-%d %H:%M') if instance.start_time else '',
                'announcement_id': str(announcement.id),
                'pilot_name': announcement.pilot.nickname if announcement.pilot else '',
                'start_time': format_local_datetime(announcement.start_time, '%Y-%m-%d %H:%M') if announcement.start_time else '',
                'duration': announcement.duration_display,
                'coords': f"{announcement.x_coord} - {announcement.y_coord} - {announcement.z_coord}",
            })
        for conflict in conflicts['pilot_conflicts']:
            announcement = conflict['announcement']
            conflicts_payload.append({
                'type': '主播冲突',
                'instance_time': format_local_datetime(instance.start_time, '%Y-%m-%d %H:%M') if instance.start_time else '',
                'announcement_id': str(announcement.id),
                'pilot_name': announcement.pilot.nickname if announcement.pilot else '',
                'start_time': format_local_datetime(announcement.start_time, '%Y-%m-%d %H:%M') if announcement.start_time else '',
                'duration': announcement.duration_display,
                'coords': f"{announcement.x_coord} - {announcement.y_coord} - {announcement.z_coord}",
            })
    return conflicts_payload


@announcements_api_bp.route('/announcements/api/check-conflicts', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def check_conflicts_api():
    """通告冲突检查。"""
    try:
        payload = request.get_json(silent=True) or {}

        pilot_id = payload.get('pilot_id')
        battle_area_id = payload.get('battle_area_id')
        start_time_str = payload.get('start_time')
        duration_hours = payload.get('duration_hours')
        exclude_id = payload.get('exclude_id')
        edit_scope = payload.get('edit_scope', 'this_only')
        recurrence_type = payload.get('recurrence_type', 'NONE')
        recurrence_pattern = payload.get('recurrence_pattern', {})
        recurrence_end_date = payload.get('recurrence_end_date')

        if not all([pilot_id, battle_area_id, start_time_str, duration_hours]):
            return jsonify(create_error_response('INVALID_PARAMS', '缺少必要参数')), 400

        try:
            pilot = Pilot.objects.get(id=pilot_id)
            battle_area = BattleArea.objects.get(id=battle_area_id)
        except DoesNotExist as exc:
            return jsonify(create_error_response('RESOURCE_NOT_FOUND', f'参数错误：{str(exc)}')), 400

        start_time = parse_local_datetime(start_time_str)
        if start_time is None:
            return jsonify(create_error_response('INVALID_START_TIME', '时间格式错误')), 400

        recurrence_end = None
        if recurrence_end_date:
            recurrence_end = parse_local_date_to_end_datetime(recurrence_end_date)
            if recurrence_end is None:
                return jsonify(create_error_response('INVALID_RECURRENCE_END', '重复结束日期格式错误')), 400

        temp = Announcement(
            pilot=pilot,
            battle_area=battle_area,
            start_time=start_time,
            duration_hours=float(duration_hours),
            recurrence_end=recurrence_end,
            x_coord=battle_area.x_coord,
            y_coord=battle_area.y_coord,
            z_coord=battle_area.z_coord,
        )

        recurrence_enum, recurrence_pattern_str = _prepare_recurrence_pattern(recurrence_type, recurrence_pattern)
        temp.recurrence_type = recurrence_enum
        if recurrence_pattern_str:
            temp.recurrence_pattern = recurrence_pattern_str

        if exclude_id:
            temp.id = exclude_id  # type: ignore[assignment]

        instances: List[Announcement] = []
        planned_instances: List[Announcement] = []

        if edit_scope == 'future_all' and exclude_id:
            try:
                origin = Announcement.objects.get(id=exclude_id)
                if origin.is_in_recurrence_group:
                    future_list = origin.get_future_announcements_in_group(include_self=True)
                    parsed_start = parse_local_datetime(start_time_str)

                    for ann in future_list:
                        cloned = Announcement(
                            pilot=pilot,
                            battle_area=battle_area,
                            start_time=ann.start_time,
                            duration_hours=float(duration_hours),
                            x_coord=battle_area.x_coord,
                            y_coord=battle_area.y_coord,
                            z_coord=battle_area.z_coord,
                        )
                        if parsed_start:
                            if ann.id != origin.id:
                                new_time = parsed_start.time()
                                cloned.start_time = ann.start_time.replace(hour=new_time.hour, minute=new_time.minute, second=new_time.second)
                            else:
                                cloned.start_time = parsed_start
                        instances.append(cloned)
                        planned_instances.append(cloned)
                else:
                    instances = [temp]
                    planned_instances = [temp]
            except DoesNotExist:
                instances = [temp]
                planned_instances = [temp]
        else:
            if recurrence_enum and recurrence_enum != RecurrenceType.NONE:
                instances = Announcement.generate_recurrence_instances(temp)
            else:
                instances = [temp]
            planned_instances = instances

        exclude_ids = []
        if edit_scope == 'future_all' and exclude_id:
            try:
                origin = Announcement.objects.get(id=exclude_id)
                if origin.is_in_recurrence_group:
                    future_list = origin.get_future_announcements_in_group(include_self=True)
                    exclude_ids = [str(ann.id) for ann in future_list]
            except DoesNotExist:
                exclude_ids = []

        conflicts_payload = _aggregate_conflicts(instances, exclude_ids)
        planned_payload = _create_planned_instances(planned_instances)

        data = {
            'has_conflicts': len(conflicts_payload) > 0,
            'conflicts': conflicts_payload,
            'planned_instances': planned_payload,
        }

        return jsonify(create_success_response(data))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('冲突检查失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '冲突检查失败')), 500


@announcements_api_bp.route('/announcements/api/announcements', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def create_announcement_api():
    """创建通告。"""
    is_valid_csrf, csrf_error = _validate_csrf_header()
    if not is_valid_csrf:
        return jsonify(create_error_response('CSRF_ERROR', csrf_error)), 401

    payload = request.get_json(silent=True) or {}

    try:
        pilot_id = payload.get('pilot_id')
        battle_area_id = payload.get('battle_area_id')
        start_time_str = payload.get('start_time')
        duration_hours = payload.get('duration_hours')
        recurrence_type = payload.get('recurrence_type', 'NONE')
        recurrence_pattern = payload.get('recurrence_pattern', {})
        recurrence_end_date = payload.get('recurrence_end_date')

        if not all([pilot_id, battle_area_id, start_time_str, duration_hours]):
            return jsonify(create_error_response('INVALID_PARAMS', '缺少必要参数')), 400

        pilot = Pilot.objects.get(id=pilot_id)
        battle_area = BattleArea.objects.get(id=battle_area_id)

        start_time = parse_local_datetime(start_time_str)
        if start_time is None:
            return jsonify(create_error_response('INVALID_START_TIME', '时间格式错误')), 400

        recurrence_end = None
        if recurrence_end_date:
            recurrence_end = parse_local_date_to_end_datetime(recurrence_end_date)
            if recurrence_end is None:
                return jsonify(create_error_response('INVALID_RECURRENCE_END', '重复结束日期格式错误')), 400

        recurrence_enum, recurrence_pattern_str = _prepare_recurrence_pattern(recurrence_type, recurrence_pattern)

        announcement = Announcement(
            pilot=pilot,
            battle_area=battle_area,
            x_coord=battle_area.x_coord,
            y_coord=battle_area.y_coord,
            z_coord=battle_area.z_coord,
            start_time=start_time,
            duration_hours=float(duration_hours),
            recurrence_type=recurrence_enum,
            recurrence_pattern=recurrence_pattern_str,
            recurrence_end=recurrence_end,
            created_by=current_user,
        )

        announcement.save()

        instances = Announcement.generate_recurrence_instances(announcement)
        conflicts_payload = _aggregate_conflicts(instances)

        if conflicts_payload:
            announcement.delete()
            for instance in instances[1:]:
                try:
                    instance.delete()
                except Exception:  # pylint: disable=broad-except
                    pass
            return jsonify(create_error_response('ANNOUNCEMENT_CONFLICT', '存在时间冲突，无法创建通告', meta={'conflicts': conflicts_payload})), 409

        for instance in instances[1:]:
            instance.save()

        logger.info('用户%s创建通告：主播%s，时间%s', current_user.username, pilot.nickname, start_time)

        meta = {
            'message': '创建通告成功',
            'redirect_url': url_for('announcement.list_announcements'),
        }
        return jsonify(create_success_response({'id': str(announcement.id)}, meta)), 201
    except DoesNotExist as exc:
        logger.warning('创建通告失败（资源不存在）：%s', str(exc))
        return jsonify(create_error_response('RESOURCE_NOT_FOUND', str(exc))), 404
    except (ValueError, ValidationError) as exc:
        logger.warning('创建通告失败（参数错误）：%s', str(exc))
        return jsonify(create_error_response('VALIDATION_ERROR', str(exc))), 400
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('创建通告失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


def _serialize_old_data(announcement: Announcement) -> Dict[str, Optional[str]]:
    return {
        'battle_area': str(announcement.battle_area.id) if announcement.battle_area else None,
        'x_coord': announcement.x_coord,
        'y_coord': announcement.y_coord,
        'z_coord': announcement.z_coord,
        'start_time': announcement.start_time.isoformat() if announcement.start_time else None,
        'duration_hours': str(announcement.duration_hours) if announcement.duration_hours else None,
        'recurrence_type': announcement.recurrence_type.value if announcement.recurrence_type else None,
        'recurrence_pattern': announcement.recurrence_pattern,
        'recurrence_end': announcement.recurrence_end.isoformat() if announcement.recurrence_end else None,
    }


@announcements_api_bp.route('/announcements/api/announcements/<announcement_id>', methods=['PATCH'])
@roles_accepted('gicho', 'kancho')
def update_announcement_api(announcement_id: str):
    """更新通告。"""
    is_valid_csrf, csrf_error = _validate_csrf_header()
    if not is_valid_csrf:
        return jsonify(create_error_response('CSRF_ERROR', csrf_error)), 401

    payload = request.get_json(silent=True) or {}

    try:
        announcement = Announcement.objects.get(id=announcement_id)
        edit_scope = payload.get('edit_scope', 'this_only')

        battle_area_id = payload.get('battle_area_id')
        start_time_str = payload.get('start_time')
        duration_hours = payload.get('duration_hours')

        if not battle_area_id or not start_time_str or duration_hours is None:
            return jsonify(create_error_response('INVALID_PARAMS', '缺少必要参数')), 400

        battle_area = BattleArea.objects.get(id=battle_area_id)

        if edit_scope == 'future_all':
            start_date = payload.get('start_date')
            start_hour = payload.get('start_hour')
            start_minute = payload.get('start_minute')
            if not start_date or not start_hour or not start_minute:
                return jsonify(create_error_response('INVALID_PARAMS', '请填写完整的时间')), 400
            start_time_combined = f"{start_date}T{start_hour}:{start_minute}"
            start_time = parse_local_datetime(start_time_combined)
        else:
            start_time = parse_local_datetime(start_time_str)

        if start_time is None:
            return jsonify(create_error_response('INVALID_START_TIME', '时间格式错误')), 400

        old_data = _serialize_old_data(announcement)

        if edit_scope == 'future_all' and announcement.is_in_recurrence_group:
            future_announcements = announcement.split_recurrence_group_from_current()
            parsed_start_time = start_time

            for ann in future_announcements:
                ann.battle_area = battle_area
                ann.x_coord = battle_area.x_coord
                ann.y_coord = battle_area.y_coord
                ann.z_coord = battle_area.z_coord
                ann.duration_hours = float(duration_hours)

                if ann.id != announcement.id:
                    new_time = parsed_start_time.time()
                    ann.start_time = ann.start_time.replace(hour=new_time.hour, minute=new_time.minute, second=new_time.second)
                else:
                    ann.start_time = parsed_start_time

            conflicts = _aggregate_conflicts(future_announcements)
            if conflicts:
                return jsonify(create_error_response('ANNOUNCEMENT_CONFLICT', '存在时间冲突，无法保存修改', meta={'conflicts': conflicts})), 409

            for ann in future_announcements:
                ann.save()
                _record_changes(ann, old_data, current_user, _get_client_ip())

            logger.info('用户%s更新未来循环通告：%s（共%d个）', current_user.username, announcement.id, len(future_announcements))
        else:
            announcement.battle_area = battle_area
            announcement.x_coord = battle_area.x_coord
            announcement.y_coord = battle_area.y_coord
            announcement.z_coord = battle_area.z_coord
            announcement.start_time = start_time
            announcement.duration_hours = float(duration_hours)

            conflicts = _aggregate_conflicts([announcement])
            if conflicts:
                return jsonify(create_error_response('ANNOUNCEMENT_CONFLICT', '存在时间冲突，无法保存修改', meta={'conflicts': conflicts})), 409

            announcement.save()
            _record_changes(announcement, old_data, current_user, _get_client_ip())

            logger.info('用户%s更新通告：%s', current_user.username, announcement.id)

        redirect_url = url_for('announcement.announcement_detail', announcement_id=announcement_id)
        meta = {
            'message': '更新通告成功',
            'redirect_url': redirect_url,
        }
        return jsonify(create_success_response({'id': announcement_id}, meta))
    except DoesNotExist as exc:
        return jsonify(create_error_response('RESOURCE_NOT_FOUND', str(exc))), 404
    except (ValueError, ValidationError) as exc:
        return jsonify(create_error_response('VALIDATION_ERROR', str(exc))), 400
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('更新通告失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@announcements_api_bp.route('/announcements/api/announcements/<announcement_id>', methods=['DELETE'])
@roles_accepted('gicho', 'kancho')
def delete_announcement_api(announcement_id: str):
    """删除通告。"""
    is_valid_csrf, csrf_error = _validate_csrf_header()
    if not is_valid_csrf:
        return jsonify(create_error_response('CSRF_ERROR', csrf_error)), 401

    payload = request.get_json(silent=True) or {}
    delete_scope = payload.get('delete_scope', 'this_only')

    try:
        announcement = Announcement.objects.get(id=announcement_id)

        if delete_scope == 'future_all' and announcement.is_in_recurrence_group:
            future_announcements = announcement.get_future_announcements_in_group(include_self=True)
            count = len(future_announcements)
            for ann in future_announcements:
                ann.delete()
            logger.info('用户%s删除未来循环通告：%s（共%d个）', current_user.username, announcement.id, count)
            meta = {'message': f'删除未来循环通告成功（共{count}个）', 'deleted_count': count}
            return jsonify(create_success_response({'deleted': True}, meta))

        announcement.delete()
        logger.info('用户%s删除通告：%s', current_user.username, announcement.id)
        meta = {'message': '删除通告成功', 'deleted_count': 1}
        return jsonify(create_success_response({'deleted': True}, meta))
    except DoesNotExist:
        return jsonify(create_error_response('ANNOUNCEMENT_NOT_FOUND', '通告不存在')), 404
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('删除通告失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@announcements_api_bp.route('/announcements/api/announcements/<announcement_id>/changes', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_announcement_changes_api(announcement_id: str):
    """获取通告变更记录。"""
    try:
        announcement = Announcement.objects.get(id=announcement_id)
        changes = AnnouncementChangeLog.objects(announcement_id=announcement).order_by('-change_time').limit(100)
        data = {'items': serialize_change_logs(changes)}
        return jsonify(create_success_response(data))
    except DoesNotExist:
        return jsonify(create_error_response('ANNOUNCEMENT_NOT_FOUND', '通告不存在')), 404
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取通告变更记录失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取通告变更记录失败')), 500


@announcements_api_bp.route('/announcements/api/areas/options', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_battle_area_options_api():
    """获取可选基地列表。"""
    try:
        areas = BattleArea.objects(availability='可用').only('x_coord', 'y_coord', 'z_coord').order_by('x_coord', 'y_coord', 'z_coord')
        x_coords = sorted({area.x_coord for area in areas})
        data = {
            'x_coords': x_coords,
            'default_x': x_coords[0] if x_coords else '',
        }
        return jsonify(create_success_response(data))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取开播地点选项失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取开播地点选项失败')), 500


@announcements_api_bp.route('/announcements/api/areas/<x_coord>', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_area_y_options_api(x_coord: str):
    """根据基地获取场地选项。"""
    try:
        areas = BattleArea.objects(x_coord=x_coord, availability='可用').only('y_coord')
        y_coords = sorted({area.y_coord for area in areas})
        return jsonify(create_success_response({'y_coords': y_coords}))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取场地选项失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取场地选项失败')), 500


@announcements_api_bp.route('/announcements/api/areas/<x_coord>/<y_coord>', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_area_z_options_api(x_coord: str, y_coord: str):
    """根据基地与场地获取坐席选项。"""
    try:
        areas = BattleArea.objects(x_coord=x_coord, y_coord=y_coord, availability='可用').order_by('z_coord')
        result = [{'id': str(area.id), 'z_coord': area.z_coord} for area in areas]
        return jsonify(create_success_response({'areas': result}))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取坐席选项失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取坐席选项失败')), 500


@announcements_api_bp.route('/announcements/api/pilot-filters', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_pilot_filter_options_api():
    """获取主播筛选器选项。"""
    try:
        pilots = Pilot.objects(status__in=['已征召', '已签约', '已招募'])

        owner_set = set()
        for pilot in pilots:
            if pilot.owner:
                owner_set.add((str(pilot.owner.id), pilot.owner.nickname or pilot.owner.username))

        owner_options = [{'id': owner_id, 'name': owner_name} for owner_id, owner_name in sorted(owner_set, key=lambda item: item[1])]

        rank_options = [
            Rank.CANDIDATE.value,
            Rank.TRAINEE.value,
            Rank.INTERN.value,
            Rank.OFFICIAL.value,
        ]

        return jsonify(create_success_response({'owners': owner_options, 'ranks': rank_options}))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取主播筛选器选项失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取主播筛选器选项失败')), 500


def _apply_rank_filter(query, rank_value: str):
    try:
        rank_enum = Rank(rank_value)
    except ValueError:
        return query

    if rank_enum == Rank.CANDIDATE:
        return query.filter(rank__in=[Rank.CANDIDATE, Rank.CANDIDATE_OLD])
    if rank_enum == Rank.TRAINEE:
        return query.filter(rank__in=[Rank.TRAINEE, Rank.TRAINEE_OLD])
    if rank_enum == Rank.INTERN:
        return query.filter(rank__in=[Rank.INTERN, Rank.INTERN_OLD])
    if rank_enum == Rank.OFFICIAL:
        return query.filter(rank__in=[Rank.OFFICIAL, Rank.OFFICIAL_OLD])
    return query.filter(rank=rank_enum)


@announcements_api_bp.route('/announcements/api/pilots-filtered', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_filtered_pilots_api():
    """根据条件筛选主播列表。"""
    try:
        owner_id = request.args.get('owner')
        rank = request.args.get('rank')

        query = Pilot.objects(status__in=['已招募', '已签约', '已征召'])

        if owner_id:
            try:
                owner = User.objects.get(id=owner_id)
                query = query.filter(owner=owner)
            except DoesNotExist:
                query = query.filter(owner=None)  # 返回空

        if rank:
            query = _apply_rank_filter(query, rank)

        pilots = query.order_by('owner', 'rank', 'nickname')

        result = []
        for pilot in pilots:
            owner_name = pilot.owner.nickname or pilot.owner.username if pilot.owner else '无所属'
            try:
                gender_value = pilot.gender.value
            except Exception:  # pylint: disable=broad-except
                gender_value = None

            result.append({
                'id': str(pilot.id),
                'nickname': pilot.nickname,
                'real_name': pilot.real_name or '',
                'age': pilot.age or '',
                'gender': gender_value,
                'rank': pilot.rank.value if pilot.rank else '',
                'owner': owner_name,
                'status': pilot.status.value if pilot.status else '',
            })

        return jsonify(create_success_response({'pilots': result}))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取筛选主播失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取筛选主播失败')), 500


@announcements_api_bp.route('/announcements/api/pilots/by-owner/<owner_id>', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def get_pilots_by_owner_api(owner_id: str):
    """根据直属运营获取主播列表。"""
    try:
        allowed_status = [Status.RECRUITED.value, Status.RECRUITED_OLD.value, Status.CONTRACTED.value]
        if owner_id == 'none':
            pilots = Pilot.objects(owner=None, status__in=allowed_status).order_by('rank', 'nickname')
        else:
            owner = User.objects.get(id=owner_id)
            pilots = Pilot.objects(owner=owner, status__in=allowed_status).order_by('rank', 'nickname')

        result = [{
            'id': str(pilot.id),
            'nickname': pilot.nickname,
            'real_name': pilot.real_name or '',
            'rank': pilot.rank.value if pilot.rank else ''
        } for pilot in pilots]

        return jsonify(create_success_response({'pilots': result}))
    except DoesNotExist:
        return jsonify(create_error_response('OWNER_NOT_FOUND', '运营不存在')), 404
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('根据所属获取主播失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '根据所属获取主播失败')), 500
