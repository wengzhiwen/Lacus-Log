# -*- coding: utf-8 -*-
"""仪表盘统一响应格式工具。"""

from typing import Any, Dict, Optional


def create_success_response(data: Any, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """构建成功响应。"""
    return {"success": True, "data": data, "error": None, "meta": meta or {}}


def create_error_response(code: str, message: str) -> Dict[str, Any]:
    """构建错误响应。"""
    return {"success": False, "data": None, "error": {"code": code, "message": message}, "meta": {}}
