# pylint: disable=no-member

from typing import Any, Dict, List, Optional

from models.user import User, Role
from utils.timezone_helper import utc_to_local


def serialize_user(user: User, include_login_info: bool = False) -> Dict[str, Any]:
    """序列化用户对象为字典格式。
    
    Args:
        user: 用户对象
        include_login_info: 是否包含登录追踪信息
        
    Returns:
        序列化后的用户字典
    """
    # 基础信息
    user_data = {
        'id': str(user.id),
        'username': user.username,
        'nickname': user.nickname or '',
        'email': user.email or '',
        'active': user.active,
        'created_at': utc_to_local(user.created_at).isoformat() if user.created_at else None,
        'roles': [role.name for role in user.roles]
    }
    
    # 登录追踪信息（可选）
    if include_login_info:
        user_data.update({
            'last_login_at': utc_to_local(user.last_login_at).isoformat() if user.last_login_at else None,
            'current_login_at': utc_to_local(user.current_login_at).isoformat() if user.current_login_at else None,
            'last_login_ip': user.last_login_ip or '',
            'current_login_ip': user.current_login_ip or '',
            'login_count': user.login_count or 0
        })
    
    return user_data


def serialize_user_list(users: List[User], include_login_info: bool = False) -> List[Dict[str, Any]]:
    """序列化用户列表。
    
    Args:
        users: 用户对象列表
        include_login_info: 是否包含登录追踪信息
        
    Returns:
        序列化后的用户字典列表
    """
    return [serialize_user(user, include_login_info) for user in users]


def serialize_role(role: Role) -> Dict[str, Any]:
    """序列化角色对象为字典格式。
    
    Args:
        role: 角色对象
        
    Returns:
        序列化后的角色字典
    """
    return {
        'id': str(role.id),
        'name': role.name,
        'description': role.description or '',
        'permissions': role.permissions or []
    }


def create_api_response(success: bool = True, data: Any = None, error: Optional[Dict[str, str]] = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建统一的API响应格式。
    
    Args:
        success: 请求是否成功
        data: 成功时返回的数据
        error: 失败时的错误信息，格式：{"code": "ERROR_CODE", "message": "错误描述"}
        meta: 额外的元信息，如分页信息
        
    Returns:
        统一的API响应字典
    """
    response = {
        'success': success,
        'data': data,
        'error': error,
        'meta': meta or {}
    }
    return response


def create_error_response(error_code: str, message: str) -> Dict[str, Any]:
    """创建错误响应。
    
    Args:
        error_code: 错误代码
        message: 错误描述
        
    Returns:
        错误响应字典
    """
    return create_api_response(
        success=False,
        data=None,
        error={'code': error_code, 'message': message}
    )


def create_success_response(data: Any = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建成功响应。
    
    Args:
        data: 返回的数据
        meta: 额外的元信息
        
    Returns:
        成功响应字典
    """
    return create_api_response(
        success=True,
        data=data,
        error=None,
        meta=meta
    )
