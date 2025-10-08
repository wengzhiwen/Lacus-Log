# -*- coding: utf-8 -*-
# pylint: disable=no-member,too-many-return-statements,too-many-branches,too-many-locals
"""通告管理 REST API 路由集合。"""

import calendar
import csv
import io
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

from flask import Blueprint, jsonify, make_response, request, url_for
from flask_security import current_user, roles_accepted
from mongoengine import DoesNotExist, ValidationError

from models.announcement import (Announcement, AnnouncementChangeLog,
                                 RecurrenceType)
from models.battle_area import BattleArea
from models.pilot import Pilot, Rank, Status
from models.user import User
from routes.announcement import _get_client_ip, _record_changes
from utils.announcement_serializers import (create_error_response,
                                            create_success_response,
                                            serialize_announcement_detail,
                                            serialize_announcement_summary,
                                            serialize_change_logs)
from utils.filter_state import persist_and_restore_filters
from utils.jwt_roles import jwt_roles_accepted, jwt_roles_required
from utils.logging_setup import get_logger
from utils.timezone_helper import (format_local_datetime,
                                   get_current_local_time, local_to_utc,
                                   parse_local_date_to_end_datetime,
                                   parse_local_datetime, utc_to_local)

announcements_api_bp = Blueprint('announcements_api', __name__)

logger = get_logger('announcement_api')


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
        {
            'value': 'month_end',
            'label': '月底为止'
        },
        {
            'value': 'next_month',
            'label': '次月'
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
    elif time_scope == 'month_end':
        last_day = calendar.monthrange(current_local.year, current_local.month)[1]
        month_end_local = current_local.replace(day=last_day, hour=23, minute=59, second=59, microsecond=999999)
        next_day_local_start = month_end_local + timedelta(microseconds=1)
        range_start_utc = local_to_utc(today_local_start)
        range_end_utc = local_to_utc(next_day_local_start)
    elif time_scope == 'next_month':
        if current_local.month == 12:
            next_month_start = current_local.replace(year=current_local.year + 1, month=1, day=1, hour=0, minute=0, second=0, microsecond=0)
            next_month_end = next_month_start.replace(month=2, day=1)
        else:
            next_month_start = current_local.replace(month=current_local.month + 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            if current_local.month == 11:
                next_month_end = next_month_start.replace(year=current_local.year + 1, month=1, day=1)
            else:
                next_month_end = next_month_start.replace(month=current_local.month + 2, day=1)
        range_start_utc = local_to_utc(next_month_start)
        range_end_utc = local_to_utc(next_month_end)
    else:
        return query

    return query.filter(start_time__gte=range_start_utc, start_time__lt=range_end_utc)


@announcements_api_bp.route('/announcements/api/announcements', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
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

        announcements = list(query.limit(500))
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
@jwt_roles_accepted('gicho', 'kancho')
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
@jwt_roles_accepted('gicho', 'kancho')
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
@jwt_roles_accepted('gicho', 'kancho')
def create_announcement_api():
    """创建通告。"""
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
@jwt_roles_accepted('gicho', 'kancho')
def update_announcement_api(announcement_id: str):
    """更新通告。"""
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


def _cleanup_orphaned_references(announcement_id):
    """清理指向已删除通告的孤立引用"""
    child_announcements = Announcement.objects(parent_announcement=announcement_id)
    for child in child_announcements:
        child.parent_announcement = None
        child.save()


@announcements_api_bp.route('/announcements/api/announcements/<announcement_id>', methods=['DELETE'])
@jwt_roles_accepted('gicho', 'kancho')
def delete_announcement_api(announcement_id: str):
    """删除通告。"""
    payload = request.get_json(silent=True) or {}
    delete_scope = payload.get('delete_scope', 'this_only')

    try:
        announcement = Announcement.objects.get(id=announcement_id)

        if delete_scope == 'future_all' and announcement.is_in_recurrence_group:
            future_announcements = announcement.get_future_announcements_in_group(include_self=True)
            count = len(future_announcements)
            for ann in future_announcements:
                _cleanup_orphaned_references(ann.id)
                ann.delete()
            logger.info('用户%s删除未来循环通告：%s（共%d个）', current_user.username, announcement.id, count)
            meta = {'message': f'删除未来循环通告成功（共{count}个）', 'deleted_count': count}
            return jsonify(create_success_response({'deleted': True}, meta))

        _cleanup_orphaned_references(announcement.id)
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
@jwt_roles_accepted('gicho', 'kancho')
def get_announcement_changes_api(announcement_id: str):
    """获取通告变更记录。"""
    try:
        announcement = Announcement.objects.get(id=announcement_id)
        changes = AnnouncementChangeLog.objects(announcement_id=announcement).order_by('-change_time').limit(500)
        data = {'items': serialize_change_logs(changes)}
        return jsonify(create_success_response(data))
    except DoesNotExist:
        return jsonify(create_error_response('ANNOUNCEMENT_NOT_FOUND', '通告不存在')), 404
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取通告变更记录失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取通告变更记录失败')), 500


@announcements_api_bp.route('/api/announcements/options', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def get_announcement_filter_options():
    """获取通告筛选选项（统一接口）。
    
    返回运营、基地坐标、时间范围等所有筛选选项。
    """
    try:
        options = _build_filter_options()
        return jsonify(create_success_response(options))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取筛选选项失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取筛选选项失败')), 500


@announcements_api_bp.route('/announcements/api/areas/options', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
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
@jwt_roles_accepted('gicho', 'kancho')
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
@jwt_roles_accepted('gicho', 'kancho')
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
@jwt_roles_accepted('gicho', 'kancho')
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
@jwt_roles_accepted('gicho', 'kancho')
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
@jwt_roles_accepted('gicho', 'kancho')
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


@announcements_api_bp.route('/announcements/api/cleanup/fallen-pilots', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def get_cleanup_list_api():
    """获取有未来通告的流失主播列表 API。"""
    try:
        current_local = get_current_local_time()
        tomorrow_local_start = current_local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        tomorrow_utc_start = local_to_utc(tomorrow_local_start)

        future_announcements = Announcement.objects(start_time__gte=tomorrow_utc_start).only('pilot')
        pilot_id_to_count = {}
        for ann in future_announcements:
            if ann.pilot:
                pid = str(ann.pilot.id)
                pilot_id_to_count[pid] = pilot_id_to_count.get(pid, 0) + 1

        pilots = Pilot.objects(id__in=list(pilot_id_to_count.keys()), status__in=[Status.FALLEN, Status.FALLEN_OLD])

        items = []
        for p in pilots:
            owner_name = p.owner.nickname or p.owner.username if p.owner else '无所属'
            items.append({
                'id': str(p.id),
                'nickname': p.nickname,
                'real_name': p.real_name or '',
                'owner_name': owner_name,
                'future_count': pilot_id_to_count.get(str(p.id), 0)
            })

        items.sort(key=lambda x: x['nickname'])
        return jsonify(create_success_response({'items': items}))
    except Exception as exc:
        logger.error('获取待清理通告列表失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取待清理通告列表失败')), 500


@announcements_api_bp.route('/announcements/api/cleanup/by-pilot/<pilot_id>', methods=['DELETE'])
@jwt_roles_accepted('gicho', 'kancho')
def cleanup_delete_future_api(pilot_id: str):
    """删除指定主播从明天开始的所有通告 API。"""
    try:
        current_local = get_current_local_time()
        tomorrow_local_start = current_local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        tomorrow_utc_start = local_to_utc(tomorrow_local_start)

        anns = Announcement.objects(pilot=pilot_id, start_time__gte=tomorrow_utc_start)
        count = anns.count()
        if count > 0:
            for ann in anns:
                _cleanup_orphaned_references(ann.id)
            anns.delete()

        logger.info('用户%s清理通告：pilot=%s，从明天开始删除共%d条', current_user.username, pilot_id, count)
        meta = {'message': f'已删除该主播明天开始的所有通告，共{count}条', 'deleted_count': count}
        return jsonify(create_success_response({'deleted': True}, meta))
    except Exception as exc:
        logger.error('清理通告失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '清理通告失败')), 500


def _get_pilot_choices_for_export():
    """获取机师选择列表（用于导出页面）"""
    pilots = Pilot.objects(status__in=['已招募', '已签约']).order_by('owner', 'rank', 'nickname')

    owner_groups = {}
    no_owner_pilots = []

    for pilot in pilots:
        if pilot.owner:
            owner_key = pilot.owner.nickname or pilot.owner.username
            if owner_key not in owner_groups:
                owner_groups[owner_key] = []
            owner_groups[owner_key].append(pilot)
        else:
            no_owner_pilots.append(pilot)

    choices = []

    for owner_name in sorted(owner_groups.keys()):
        pilots_in_group = owner_groups[owner_name]
        pilots_in_group.sort(key=lambda p: (p.rank.value, p.nickname))
        for pilot in pilots_in_group:
            choices.append({'id': str(pilot.id), 'nickname': pilot.nickname, 'real_name': pilot.real_name or '', 'owner': owner_name, 'rank': pilot.rank.value})

    if no_owner_pilots:
        no_owner_pilots.sort(key=lambda p: (p.rank.value, p.nickname))
        for pilot in no_owner_pilots:
            choices.append({'id': str(pilot.id), 'nickname': pilot.nickname, 'real_name': pilot.real_name or '', 'owner': '无所属', 'rank': pilot.rank.value})

    return choices


def _get_monthly_announcements_for_export(pilot_id, year, month):
    """获取指定机师在指定月份的通告数据"""
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)

    start_utc = local_to_utc(start_date)
    end_utc = local_to_utc(end_date)

    announcements = Announcement.objects(pilot=pilot_id, start_time__gte=start_utc, start_time__lt=end_utc).order_by('start_time')

    return list(announcements)


def _generate_export_table_data(pilot, year, month):
    """生成导出表格数据"""
    announcements = _get_monthly_announcements_for_export(pilot.id, year, month)

    venue_coords = set()

    announcements_by_date = {}
    for announcement in announcements:
        if announcement.x_coord:
            venue_coords.add(announcement.x_coord)

        local_time = utc_to_local(announcement.start_time)
        date_key = local_time.date()
        if date_key not in announcements_by_date:
            announcements_by_date[date_key] = []
        announcements_by_date[date_key].append(announcement)

    venue_info = ', '.join(sorted(venue_coords)) if venue_coords else None

    table_data = []
    days_in_month = calendar.monthrange(year, month)[1]

    for day in range(1, days_in_month + 1):
        date_obj = datetime(year, month, day).date()
        weekday_names = ['一', '二', '三', '四', '五', '六', '日']
        weekday = weekday_names[date_obj.weekday()]

        date_str = f"{month:02d}/{day:02d} 星期{weekday}"

        day_announcements = announcements_by_date.get(date_obj, [])

        if day_announcements:
            start_times = []
            durations = []
            equipments = []

            for ann in day_announcements:
                local_start = utc_to_local(ann.start_time)
                start_times.append(local_start.strftime('%H:%M'))
                durations.append(f"{ann.duration_hours}小时")

                equipment = f"{ann.y_coord}-{ann.z_coord}"
                if equipment not in equipments:
                    equipments.append(equipment)

            row_data = {
                'date': date_str,
                'time': ', '.join(start_times),  # 通告时间
                'equipment': ', '.join(equipments),  # 设备（Y-Z坐标）
                'duration': ', '.join(durations),  # 通告时长
                'work_content': '弹幕游戏直播'  # 固定工作内容
            }
        else:
            row_data = {'date': date_str, 'time': '', 'equipment': '', 'duration': '', 'work_content': ''}

        table_data.append(row_data)

    return table_data, venue_info


@announcements_api_bp.route('/announcements/api/export/pilots', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def get_export_pilot_options_api():
    """获取导出功能所需的主播选项 API。"""
    try:
        pilots = _get_pilot_choices_for_export()
        return jsonify(create_success_response({'pilots': pilots}))
    except Exception as exc:
        logger.error('获取导出主播选项失败：%s', str(exc), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取导出主播选项失败')), 500


@announcements_api_bp.route('/announcements/api/export', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def export_announcements_api():
    """导出指定月份的通告为 CSV 文件。"""
    try:
        pilot_id = request.args.get('pilot_id')
        year_str = request.args.get('year')
        month_str = request.args.get('month')

        if not all([pilot_id, year_str, month_str]):
            return make_response("错误：缺少 pilot_id, year, 或 month 参数", 400)

        year = int(year_str)
        month = int(month_str)

        pilot = Pilot.objects.get(id=pilot_id)

        table_data, venue_info = _generate_export_table_data(pilot, year, month)

        output = io.StringIO()
        writer = csv.writer(output)

        # 写入文件头和主播信息
        writer.writerow([f'{year}年{month}月 通告'])
        writer.writerow(['主播', pilot.nickname])
        if pilot.real_name:
            writer.writerow(['姓名', pilot.real_name])
        if venue_info:
            writer.writerow(['开播地点', venue_info])
        writer.writerow([])  # 空行

        # 写入表头
        headers = ['日期', '通告时间', '设备', '通告时长', '工作内容']
        writer.writerow(headers)

        # 写入数据行
        for row in table_data:
            writer.writerow([row['date'], row['time'], row['equipment'], row['duration'], row['work_content']])

        output.seek(0)
        csv_content = output.getvalue()

        # 添加UTF-8 BOM，确保Excel正确识别编码
        csv_bytes = '\ufeff'.encode('utf-8') + csv_content.encode('utf-8')

        response = make_response(csv_bytes)

        # 使用URL编码处理中文文件名，避免HTTP头编码错误
        from urllib.parse import quote
        filename = f"announcements_{pilot.nickname}_{year}_{month}.csv"
        encoded_filename = quote(filename)
        response.headers["Content-Disposition"] = f"attachment; filename*=UTF-8''{encoded_filename}"
        response.headers["Content-Type"] = "text/csv; charset=utf-8"

        logger.info('用户 %s 导出了主播 %s (%s年%s月) 的通告', current_user.username, pilot.nickname, year, month)

        return response

    except DoesNotExist:
        return make_response("错误：指定的主播不存在", 404)
    except ValueError:
        return make_response("错误：year 和 month 必须是有效的数字", 400)
    except Exception as e:
        logger.error('导出通告CSV失败: %s', str(e), exc_info=True)
        return make_response(f"服务器内部错误: {str(e)}", 500)


@announcements_api_bp.route('/announcements/api/export-data', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def get_export_data_api():
    """为打印视图提供通告导出数据。"""
    try:
        pilot_id = request.args.get('pilot_id')
        year_str = request.args.get('year')
        month_str = request.args.get('month')

        if not all([pilot_id, year_str, month_str]):
            return jsonify(create_error_response('INVALID_PARAMS', '缺少 pilot_id, year, 或 month 参数')), 400

        year = int(year_str)
        month = int(month_str)

        pilot = Pilot.objects.get(id=pilot_id)

        table_data, venue_info = _generate_export_table_data(pilot, year, month)

        pilot_info = {
            'nickname': pilot.nickname,
            'real_name': pilot.real_name or '',
            'owner_name': pilot.owner.nickname or pilot.owner.username if pilot.owner else '无所属'
        }

        response_data = {'pilot': pilot_info, 'year': year, 'month': month, 'table_data': table_data, 'venue_info': venue_info}

        return jsonify(create_success_response(response_data))

    except DoesNotExist:
        return jsonify(create_error_response('RESOURCE_NOT_FOUND', '指定的主播不存在')), 404
    except ValueError:
        return jsonify(create_error_response('INVALID_PARAMS', 'year 和 month 必须是有效的数字')), 400
    except Exception as e:
        logger.error('获取导出数据失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', f'服务器内部错误: {str(e)}')), 500
