# -*- coding: utf-8 -*-
"""通告模块序列化与统一响应工具。"""

from typing import Any, Dict, Iterable, List, Optional

from mongoengine.errors import DoesNotExist

from models.announcement import Announcement, AnnouncementChangeLog
from utils.timezone_helper import format_local_datetime, utc_to_local


def _format_datetime(dt, fmt: str = '%Y-%m-%d %H:%M') -> Optional[str]:
    """将UTC时间格式化为指定格式，若值为空返回None。"""
    if not dt:
        return None
    return format_local_datetime(dt, fmt)


def serialize_pilot_basic_info(announcement: Announcement) -> Dict[str, Any]:
    """提取用于列表展示的主播基础信息。"""
    pilot = announcement.pilot
    owner = pilot.owner if pilot and pilot.owner else None
    try:
        gender_value = pilot.gender.value if pilot and pilot.gender is not None else None
    except AttributeError:
        gender_value = None

    return {
        'id': str(pilot.id) if pilot else None,
        'nickname': getattr(pilot, 'nickname', ''),
        'real_name': getattr(pilot, 'real_name', '') or '',
        'rank': pilot.rank.value if getattr(pilot, 'rank', None) else '',
        'status': pilot.status.value if getattr(pilot, 'status', None) else '',
        'gender': gender_value,
        'age': getattr(pilot, 'age', None),
        'owner': {
            'id': str(owner.id),
            'display_name': owner.nickname or owner.username,
        } if owner else None,
        'platform': pilot.platform.value if getattr(pilot, 'platform', None) else '',
    }


def serialize_announcement_summary(announcement: Announcement) -> Dict[str, Any]:
    """序列化列表所需的通告摘要信息。"""
    local_start = utc_to_local(announcement.start_time) if announcement.start_time else None
    local_created = utc_to_local(announcement.created_at) if announcement.created_at else None

    parent_indicator = ''
    has_parent = False
    try:
        if announcement.parent_announcement:
            parent_indicator = '循环事件'
            has_parent = True
    except DoesNotExist:
        has_parent = False

    if not has_parent and announcement.recurrence_type and announcement.recurrence_type.name != 'NONE':
        parent_indicator = '循环组'

    return {
        'id': str(announcement.id),
        'pilot': serialize_pilot_basic_info(announcement),
        'start_time': {
            'iso': local_start.isoformat() if local_start else None,
            'display': _format_datetime(announcement.start_time, '%m-%d %H:%M'),
        },
        'duration': {
            'hours': announcement.duration_hours,
            'display': announcement.duration_display,
        },
        'coordinates': {
            'x': announcement.x_coord,
            'y': announcement.y_coord,
            'z': announcement.z_coord,
            'display': f"{announcement.x_coord}-{announcement.y_coord}-{announcement.z_coord}",
        },
        'recurrence': {
            'type': announcement.recurrence_type.name if announcement.recurrence_type else 'NONE',
            'value': announcement.recurrence_type.value if announcement.recurrence_type else '无重复',
            'display': announcement.recurrence_display,
            'has_parent': has_parent,
            'is_group': announcement.recurrence_type.name != 'NONE' if announcement.recurrence_type else False,
            'indicator': parent_indicator,
        },
        'created_at': {
            'iso': local_created.isoformat() if local_created else None,
            'display': _format_datetime(announcement.created_at, '%Y-%m-%d %H:%M'),
        },
    }


def serialize_related_announcements(announcements: Iterable[Announcement], current_id: str) -> List[Dict[str, Any]]:
    """序列化相关循环事件列表。"""
    items: List[Dict[str, Any]] = []
    for ann in announcements:
        items.append({
            'id': str(ann.id),
            'start_time': _format_datetime(ann.start_time, '%m-%d %H:%M'),
            'duration': ann.duration_display,
            'is_current': str(ann.id) == str(current_id),
        })
    return items


def serialize_announcement_detail(announcement: Announcement, related: Optional[Iterable[Announcement]] = None) -> Dict[str, Any]:
    """序列化通告详情。"""
    local_start = _format_datetime(announcement.start_time)
    local_end = _format_datetime(announcement.end_time)
    local_created = _format_datetime(announcement.created_at, '%Y-%m-%d %H:%M:%S')
    local_updated = _format_datetime(announcement.updated_at, '%Y-%m-%d %H:%M:%S')
    recurrence_end = _format_datetime(announcement.recurrence_end)

    created_by = announcement.created_by

    return {
        'id': str(announcement.id),
        'pilot': serialize_pilot_basic_info(announcement),
        'coordinates': {
            'x': announcement.x_coord,
            'y': announcement.y_coord,
            'z': announcement.z_coord,
            'display': f"{announcement.x_coord}-{announcement.y_coord}-{announcement.z_coord}",
            'battle_area_id': str(announcement.battle_area.id) if announcement.battle_area else None,
        },
        'time': {
            'start': local_start,
            'end': local_end,
            'duration': announcement.duration_display,
            'duration_hours': announcement.duration_hours,
            'start_iso': _format_datetime(announcement.start_time, '%Y-%m-%dT%H:%M'),
        },
        'recurrence': {
            'type': announcement.recurrence_type.name if announcement.recurrence_type else 'NONE',
            'value': announcement.recurrence_type.value if announcement.recurrence_type else '无重复',
            'display': announcement.recurrence_display,
            'end': recurrence_end,
            'is_in_group': announcement.is_in_recurrence_group,
        },
        'audit': {
            'created_at': local_created,
            'updated_at': local_updated,
            'created_by': {
                'id': str(created_by.id),
                'display_name': created_by.nickname or created_by.username,
            } if created_by else None,
        },
        'related_announcements': serialize_related_announcements(related or [], str(announcement.id)),
    }


def serialize_change_logs(change_logs: Iterable[AnnouncementChangeLog]) -> List[Dict[str, Any]]:
    """序列化通告变更记录。"""
    items: List[Dict[str, Any]] = []
    for change in change_logs:
        items.append({
            'field_name': change.field_display_name,
            'old_value': change.old_value or '',
            'new_value': change.new_value or '',
            'change_time': _format_datetime(change.change_time, '%Y-%m-%d %H:%M:%S'),
            'user_name': (change.user_id.nickname or change.user_id.username) if change.user_id else '未知用户',
            'ip_address': change.ip_address or '未知',
        })
    return items


def create_success_response(data: Any = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """统一成功响应格式。"""
    return {'success': True, 'data': data, 'error': None, 'meta': meta or {}}


def create_error_response(code: str, message: str, *, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """统一失败响应格式。"""
    return {'success': False, 'data': None, 'error': {'code': code, 'message': message}, 'meta': meta or {}}
