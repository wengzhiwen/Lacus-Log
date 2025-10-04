# -*- coding: utf-8 -*-
"""开播地点模块序列化工具与通用响应结构。"""

from typing import Any, Dict, List, Optional

from models.battle_area import BattleArea
from utils.timezone_helper import utc_to_local


def serialize_battle_area(area: BattleArea) -> Dict[str, Any]:
    """序列化单个开播地点对象。"""
    return {
        'id': str(area.id),
        'x_coord': area.x_coord,
        'y_coord': area.y_coord,
        'z_coord': area.z_coord,
        'availability': area.availability.value if area.availability else None,
        'availability_key': area.availability.name if area.availability else None,
        'created_at': utc_to_local(area.created_at).isoformat() if area.created_at else None,
        'updated_at': utc_to_local(area.updated_at).isoformat() if area.updated_at else None,
    }


def serialize_battle_area_list(areas: List[BattleArea]) -> List[Dict[str, Any]]:
    """序列化开播地点列表。"""
    return [serialize_battle_area(area) for area in areas]


def create_success_response(data: Any = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """统一成功响应结构。"""
    return {'success': True, 'data': data, 'error': None, 'meta': meta or {}}


def create_error_response(code: str, message: str, *, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """统一错误响应结构。"""
    return {'success': False, 'data': None, 'error': {'code': code, 'message': message}, 'meta': meta or {}}
