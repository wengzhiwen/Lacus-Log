# -*- coding: utf-8 -*-
"""
主播数据序列化工具
提供主播、变更记录等对象的JSON序列化功能
"""

from typing import Any, Dict, List, Optional
from models.pilot import Pilot, PilotChangeLog
from utils.timezone_helper import utc_to_local


def serialize_pilot(pilot: Pilot) -> Dict[str, Any]:
    """序列化单个主播对象"""
    return {
        'id': str(pilot.id),
        'nickname': pilot.nickname,
        'real_name': pilot.real_name,
        'gender': pilot.gender.value if pilot.gender else None,
        'hometown': pilot.hometown,
        'birth_year': pilot.birth_year,
        'age': pilot.age,
        'owner': {
            'id': str(pilot.owner.id),
            'nickname': pilot.owner.nickname
        } if pilot.owner else None,
        'platform': pilot.platform.value if pilot.platform else None,
        'work_mode': pilot.work_mode.value if pilot.work_mode else None,
        'rank': pilot.rank.value if pilot.rank else None,
        'status': pilot.status.value if pilot.status else None,
        'created_at': utc_to_local(pilot.created_at).isoformat() if pilot.created_at else None,
        'updated_at': utc_to_local(pilot.updated_at).isoformat() if pilot.updated_at else None,
    }


def serialize_pilot_list(pilots: List[Pilot]) -> List[Dict[str, Any]]:
    """序列化主播列表"""
    return [serialize_pilot(pilot) for pilot in pilots]


def serialize_change_log(change_log: PilotChangeLog) -> Dict[str, Any]:
    """序列化单个变更记录"""
    return {
        'id': str(change_log.id),
        'field_name': change_log.field_name,
        'old_value': change_log.old_value,
        'new_value': change_log.new_value,
        'operation_type': getattr(change_log, 'operation_type', ''),
        'changes_summary': getattr(change_log, 'changes_summary', ''),
        'user': {
            'id': str(change_log.user_id.id),
            'nickname': change_log.user_id.nickname,
            'username': change_log.user_id.username
        } if change_log.user_id else None,
        'ip_address': change_log.ip_address,
        'created_at': utc_to_local(change_log.change_time).isoformat() if change_log.change_time else None,
    }


def serialize_change_log_list(change_logs: List[PilotChangeLog]) -> List[Dict[str, Any]]:
    """序列化变更记录列表"""
    return [serialize_change_log(log) for log in change_logs]


def create_success_response(data: Any, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建成功响应格式"""
    return {"success": True, "data": data, "error": None, "meta": meta or {}}


def create_error_response(code: str, message: str) -> Dict[str, Any]:
    """创建错误响应格式"""
    return {"success": False, "data": None, "error": {"code": code, "message": message}, "meta": {}}
