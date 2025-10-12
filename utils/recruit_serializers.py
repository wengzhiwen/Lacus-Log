# -*- coding: utf-8 -*-
"""
招募数据序列化工具
提供招募、变更记录等对象的JSON序列化功能
"""

from datetime import datetime
from typing import Any, Dict, List, Optional

from models.recruit import Recruit, RecruitChangeLog
from utils.timezone_helper import utc_to_local


def _safe_get_enum_value(enum_field):
    """Safely get the value from an enum field, handling strings."""
    if not enum_field:
        return None
    if isinstance(enum_field, str):
        return enum_field
    return enum_field.value


def _convert_datetime_fields_in_change_log(value: str, field_name: str) -> str:
    """
    转换变更记录中的日期时间字段为GMT+8格式

    Args:
        value: 字段值（可能是UTC ISO格式字符串）
        field_name: 字段名称

    Returns:
        str: 转换后的值（如果是时间字段则转换为GMT+8格式，否则返回原值）
    """
    if not value:
        return value

    # 定义需要时间转换的字段
    datetime_fields = {
        'appointment_time', 'scheduled_training_time', 'scheduled_broadcast_time', 'training_time', 'interview_decision_time', 'training_decision_time',
        'broadcast_decision_time', 'scheduled_training_decision_time', 'scheduled_broadcast_decision_time', 'training_decision_time_old', 'final_decision_time'
    }

    # 如果不是时间字段，直接返回原值
    if field_name not in datetime_fields:
        return value

    # 尝试解析ISO格式时间并转换为GMT+8
    try:
        # 尝试解析ISO格式时间字符串
        utc_time = datetime.fromisoformat(value.replace('Z', '+00:00'))
        # 转换为GMT+8并格式化为易读格式
        local_time = utc_to_local(utc_time)
        return local_time.strftime('%Y-%m-%d %H:%M:%S')
    except (ValueError, AttributeError):
        # 如果解析失败，返回原值
        return value


def serialize_recruit(recruit: Recruit) -> Dict[str, Any]:
    """序列化单个招募对象"""
    return {
        'id':
        str(recruit.id),
        'pilot': {
            'id': str(recruit.pilot.id),
            'nickname': recruit.pilot.nickname,
            'real_name': recruit.pilot.real_name,
            'status': _safe_get_enum_value(recruit.pilot.status),
            'rank': _safe_get_enum_value(recruit.pilot.rank),
        } if recruit.pilot else None,
        'recruiter': {
            'id': str(recruit.recruiter.id),
            'nickname': recruit.recruiter.nickname,
            'username': recruit.recruiter.username,
        } if recruit.recruiter else None,
        'appointment_time':
        utc_to_local(recruit.appointment_time).isoformat() if recruit.appointment_time else None,
        'channel':
        _safe_get_enum_value(recruit.channel),
        'introduction_fee':
        float(recruit.introduction_fee) if recruit.introduction_fee else 0.0,
        'remarks':
        recruit.remarks if recruit.remarks else '',
        'status':
        _safe_get_enum_value(recruit.status),
        'effective_status':
        _safe_get_enum_value(recruit.get_effective_status()),

        # 面试决策相关
        'interview_decision':
        _safe_get_enum_value(recruit.interview_decision),
        'interview_decision_maker': {
            'id': str(recruit.interview_decision_maker.id),
            'nickname': recruit.interview_decision_maker.nickname,
        } if recruit.interview_decision_maker else None,
        'interview_decision_time':
        utc_to_local(recruit.interview_decision_time).isoformat() if recruit.interview_decision_time else None,
        'effective_interview_decision':
        _safe_get_enum_value(recruit.get_effective_interview_decision()),
        'effective_interview_decision_maker': {
            'id': str(recruit.get_effective_interview_decision_maker().id),
            'nickname': recruit.get_effective_interview_decision_maker().nickname,
        } if recruit.get_effective_interview_decision_maker() else None,
        'effective_interview_decision_time':
        utc_to_local(recruit.get_effective_interview_decision_time()).isoformat() if recruit.get_effective_interview_decision_time() else None,

        # 预约试播相关
        'scheduled_training_time':
        utc_to_local(recruit.scheduled_training_time).isoformat() if recruit.scheduled_training_time else None,
        'scheduled_training_decision_maker': {
            'id': str(recruit.scheduled_training_decision_maker.id),
            'nickname': recruit.scheduled_training_decision_maker.nickname,
        } if recruit.scheduled_training_decision_maker else None,
        'scheduled_training_decision_time':
        utc_to_local(recruit.scheduled_training_decision_time).isoformat() if recruit.scheduled_training_decision_time else None,
        'effective_scheduled_training_time':
        utc_to_local(recruit.get_effective_scheduled_training_time()).isoformat() if recruit.get_effective_scheduled_training_time() else None,
        'effective_scheduled_training_decision_maker': {
            'id': str(recruit.get_effective_scheduled_training_decision_maker().id),
            'nickname': recruit.get_effective_scheduled_training_decision_maker().nickname,
        } if recruit.get_effective_scheduled_training_decision_maker() else None,
        'effective_scheduled_training_decision_time':
        utc_to_local(recruit.get_effective_scheduled_training_decision_time()).isoformat()
        if recruit.get_effective_scheduled_training_decision_time() else None,

        # 试播决策相关
        'training_decision':
        _safe_get_enum_value(recruit.training_decision),
        'training_decision_maker': {
            'id': str(recruit.training_decision_maker.id),
            'nickname': recruit.training_decision_maker.nickname,
        } if recruit.training_decision_maker else None,
        'training_decision_time':
        utc_to_local(recruit.training_decision_time).isoformat() if recruit.training_decision_time else None,
        'effective_training_decision':
        _safe_get_enum_value(recruit.get_effective_training_decision()),
        'effective_training_decision_maker': {
            'id': str(recruit.get_effective_training_decision_maker().id),
            'nickname': recruit.get_effective_training_decision_maker().nickname,
        } if recruit.get_effective_training_decision_maker() else None,
        'effective_training_decision_time':
        utc_to_local(recruit.get_effective_training_decision_time()).isoformat() if recruit.get_effective_training_decision_time() else None,

        # 预约开播相关
        'scheduled_broadcast_time':
        utc_to_local(recruit.scheduled_broadcast_time).isoformat() if recruit.scheduled_broadcast_time else None,
        'scheduled_broadcast_decision_maker': {
            'id': str(recruit.scheduled_broadcast_decision_maker.id),
            'nickname': recruit.scheduled_broadcast_decision_maker.nickname,
        } if recruit.scheduled_broadcast_decision_maker else None,
        'scheduled_broadcast_decision_time':
        utc_to_local(recruit.scheduled_broadcast_decision_time).isoformat() if recruit.scheduled_broadcast_decision_time else None,
        'effective_scheduled_broadcast_time':
        utc_to_local(recruit.get_effective_scheduled_broadcast_time()).isoformat() if recruit.get_effective_scheduled_broadcast_time() else None,
        'effective_scheduled_broadcast_decision_maker': {
            'id': str(recruit.get_effective_scheduled_broadcast_decision_maker().id),
            'nickname': recruit.get_effective_scheduled_broadcast_decision_maker().nickname,
        } if recruit.get_effective_scheduled_broadcast_decision_maker() else None,
        'effective_scheduled_broadcast_decision_time':
        utc_to_local(recruit.get_effective_scheduled_broadcast_decision_time()).isoformat()
        if recruit.get_effective_scheduled_broadcast_decision_time() else None,

        # 开播决策相关
        'broadcast_decision':
        _safe_get_enum_value(recruit.broadcast_decision),
        'broadcast_decision_maker': {
            'id': str(recruit.broadcast_decision_maker.id),
            'nickname': recruit.broadcast_decision_maker.nickname,
        } if recruit.broadcast_decision_maker else None,
        'broadcast_decision_time':
        utc_to_local(recruit.broadcast_decision_time).isoformat() if recruit.broadcast_decision_time else None,
        'effective_broadcast_decision':
        _safe_get_enum_value(recruit.get_effective_broadcast_decision()),
        'effective_broadcast_decision_maker': {
            'id': str(recruit.get_effective_broadcast_decision_maker().id),
            'nickname': recruit.get_effective_broadcast_decision_maker().nickname,
        } if recruit.get_effective_broadcast_decision_maker() else None,
        'effective_broadcast_decision_time':
        utc_to_local(recruit.get_effective_broadcast_decision_time()).isoformat() if recruit.get_effective_broadcast_decision_time() else None,

        # 历史字段（兼容性）
        'training_time':
        utc_to_local(recruit.training_time).isoformat() if recruit.training_time else None,
        'training_decision_old':
        _safe_get_enum_value(recruit.training_decision_old),
        'final_decision':
        _safe_get_enum_value(recruit.final_decision),
        'created_at':
        utc_to_local(recruit.created_at).isoformat() if recruit.created_at else None,
        'updated_at':
        utc_to_local(recruit.updated_at).isoformat() if recruit.updated_at else None,
    }


def serialize_recruit_list(recruits: List[Recruit]) -> List[Dict[str, Any]]:
    """序列化招募列表"""
    return [serialize_recruit(recruit) for recruit in recruits]


def serialize_change_log(change_log: RecruitChangeLog) -> Dict[str, Any]:
    """序列化单个变更记录"""
    # 处理时间字段的GMT+8显示
    old_value = _convert_datetime_fields_in_change_log(change_log.old_value, change_log.field_name)
    new_value = _convert_datetime_fields_in_change_log(change_log.new_value, change_log.field_name)

    return {
        'id': str(change_log.id),
        'field_name': change_log.field_name,
        'field_display_name': change_log.field_display_name,
        'old_value': old_value,
        'new_value': new_value,
        'user': {
            'id': str(change_log.user_id.id),
            'nickname': change_log.user_id.nickname,
            'username': change_log.user_id.username
        } if change_log.user_id else None,
        'ip_address': change_log.ip_address,
        'created_at': utc_to_local(change_log.change_time).isoformat() if change_log.change_time else None,
    }


def serialize_change_log_list(change_logs: List[RecruitChangeLog]) -> List[Dict[str, Any]]:
    """序列化变更记录列表"""
    return [serialize_change_log(log) for log in change_logs]


def serialize_recruit_grouped(recruits: List[Recruit]) -> Dict[str, List[Dict[str, Any]]]:
    """序列化分组的招募数据"""
    from routes.recruit import _group_recruits

    grouped_recruits = _group_recruits(recruits)
    return {
        'pending_interview': serialize_recruit_list(grouped_recruits.get('pending_interview', [])),
        'pending_training_schedule': serialize_recruit_list(grouped_recruits.get('pending_training_schedule', [])),
        'pending_training': serialize_recruit_list(grouped_recruits.get('pending_training', [])),
        'pending_broadcast_schedule': serialize_recruit_list(grouped_recruits.get('pending_broadcast_schedule', [])),
        'pending_broadcast': serialize_recruit_list(grouped_recruits.get('pending_broadcast', [])),
        'overdue': serialize_recruit_list(grouped_recruits.get('overdue', [])),
        'ended': serialize_recruit_list(grouped_recruits.get('ended', [])),
    }


def create_success_response(data: Any, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建成功响应格式"""
    return {"success": True, "data": data, "error": None, "meta": meta or {}}


def create_error_response(code: str, message: str) -> Dict[str, Any]:
    """创建错误响应格式"""
    return {"success": False, "data": None, "error": {"code": code, "message": message}, "meta": {}}
