"""
结算管理数据序列化工具
提供结算方式记录、变更日志等对象的JSON序列化功能
"""

from typing import Any, Dict, List, Optional

from models.pilot import Settlement, SettlementChangeLog
from utils.timezone_helper import utc_to_local


def serialize_settlement(settlement: Settlement) -> Dict[str, Any]:
    """序列化单个结算方式记录"""
    return {
        'id': str(settlement.id),
        'pilot_id': str(settlement.pilot_id.id) if settlement.pilot_id else None,
        'effective_date': utc_to_local(settlement.effective_date).strftime('%Y-%m-%d') if settlement.effective_date else None,
        'settlement_type': settlement.settlement_type.value if settlement.settlement_type else None,
        'settlement_type_display': settlement.settlement_type_display,
        'remark': settlement.remark,
        'is_active': settlement.is_active,
        'created_at': utc_to_local(settlement.created_at).isoformat() if settlement.created_at else None,
        'updated_at': utc_to_local(settlement.updated_at).isoformat() if settlement.updated_at else None,
    }


def serialize_settlement_list(settlements: List[Settlement]) -> List[Dict[str, Any]]:
    """序列化结算方式记录列表"""
    return [serialize_settlement(s) for s in settlements]


def serialize_settlement_change_log(log: SettlementChangeLog) -> Dict[str, Any]:
    """序列化单个结算方式变更记录"""
    return {
        'id': str(log.id),
        'settlement_id': str(log.settlement_id.id) if log.settlement_id else None,
        'field_name': log.field_name,
        'field_display_name': log.field_display_name,
        'old_value': log.old_value,
        'new_value': log.new_value,
        'user': {
            'id': str(log.user_id.id),
            'nickname': log.user_id.nickname,
        } if log.user_id else None,
        'ip_address': log.ip_address,
        'change_time': utc_to_local(log.change_time).isoformat() if log.change_time else None,
    }


def serialize_settlement_change_log_list(logs: List[SettlementChangeLog]) -> List[Dict[str, Any]]:
    """序列化结算方式变更记录列表"""
    return [serialize_settlement_change_log(log) for log in logs]


def create_success_response(data: Any, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建成功响应格式"""
    return {"success": True, "data": data, "error": None, "meta": meta or {}}


def create_error_response(code: str, message: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建错误响应格式"""
    return {"success": False, "data": None, "error": {"code": code, "message": message}, "meta": meta or {}}
