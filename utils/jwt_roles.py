"""JWT角色权限装饰器

提供基于JWT认证的角色权限控制，用于REST API接口。
与Flask-Security-Too的角色系统兼容。

JWT token来源：
1. Authorization Header: Bearer <token>
2. Cookie: access_token_cookie (传统表单登录后自动设置)
"""
from functools import wraps

from flask import jsonify
from flask_jwt_extended import get_jwt_identity, verify_jwt_in_request

from models.user import User


def jwt_roles_required(*roles: str):
    """JWT角色权限装饰器 - 要求用户拥有所有指定角色
    
    JWT token自动从以下位置获取：
    1. Authorization Header: Bearer <token>
    2. Cookie: access_token_cookie
    
    用法：
        @app.route('/api/resource')
        @jwt_roles_required('gicho')
        def protected_route():
            return jsonify({'msg': 'Success'})
    
    Args:
        *roles: 必需的角色列表
        
    Returns:
        如果用户没有权限，返回403响应
    """

    def wrapper(fn):

        @wraps(fn)
        def decorator(*args, **kwargs):
            # 验证JWT token（会自动从Header或Cookie中获取）
            try:
                verify_jwt_in_request()
            except Exception:  # pylint: disable=broad-except
                return jsonify({'success': False, 'data': None, 'error': {'code': 'UNAUTHORIZED', 'message': '未认证'}, 'meta': {}}), 401

            # 获取用户身份并从数据库加载
            identity = get_jwt_identity()
            try:
                user = User.objects.get(fs_uniquifier=identity)  # pylint: disable=no-member
            except Exception:  # pylint: disable=broad-except
                return jsonify({'success': False, 'data': None, 'error': {'code': 'USER_NOT_FOUND', 'message': '用户不存在'}, 'meta': {}}), 404

            # 检查用户是否激活
            if not user.active:
                return jsonify({'success': False, 'data': None, 'error': {'code': 'ACCOUNT_DISABLED', 'message': '账户已停用'}, 'meta': {}}), 403

            # 检查角色权限
            user_roles = {role.name for role in user.roles}
            required_roles = set(roles)
            if not required_roles.issubset(user_roles):
                return jsonify({'success': False, 'data': None, 'error': {'code': 'FORBIDDEN', 'message': '权限不足'}, 'meta': {}}), 403

            # 权限检查通过，执行原函数
            return fn(*args, **kwargs)

        return decorator

    return wrapper


def jwt_roles_accepted(*roles: str):
    """JWT角色权限装饰器 - 要求用户拥有任一指定角色
    
    JWT token自动从以下位置获取：
    1. Authorization Header: Bearer <token>
    2. Cookie: access_token_cookie
    
    用法：
        @app.route('/api/resource')
        @jwt_roles_accepted('gicho', 'kancho')
        def protected_route():
            return jsonify({'msg': 'Success'})
    
    Args:
        *roles: 允许的角色列表（满足其中之一即可）
        
    Returns:
        如果用户没有权限，返回403响应
    """

    def wrapper(fn):

        @wraps(fn)
        def decorator(*args, **kwargs):
            # 验证JWT token（会自动从Header或Cookie中获取）
            try:
                verify_jwt_in_request()
            except Exception:  # pylint: disable=broad-except
                return jsonify({'success': False, 'data': None, 'error': {'code': 'UNAUTHORIZED', 'message': '未认证'}, 'meta': {}}), 401

            # 获取用户身份并从数据库加载
            identity = get_jwt_identity()
            try:
                user = User.objects.get(fs_uniquifier=identity)  # pylint: disable=no-member
            except Exception:  # pylint: disable=broad-except
                return jsonify({'success': False, 'data': None, 'error': {'code': 'USER_NOT_FOUND', 'message': '用户不存在'}, 'meta': {}}), 404

            # 检查用户是否激活
            if not user.active:
                return jsonify({'success': False, 'data': None, 'error': {'code': 'ACCOUNT_DISABLED', 'message': '账户已停用'}, 'meta': {}}), 403

            # 检查角色权限（满足其中之一即可）
            user_roles = {role.name for role in user.roles}
            allowed_roles = set(roles)
            if not user_roles.intersection(allowed_roles):
                return jsonify({'success': False, 'data': None, 'error': {'code': 'FORBIDDEN', 'message': '权限不足'}, 'meta': {}}), 403

            # 权限检查通过，执行原函数
            return fn(*args, **kwargs)

        return decorator

    return wrapper


def get_jwt_user() -> User | None:
    """获取当前JWT认证的用户对象
    
    注意：必须在@jwt_required()或jwt_roles_*装饰的函数中调用
    
    Returns:
        User对象，如果无法获取则返回None
    """
    try:
        identity = get_jwt_identity()
        if not identity:
            return None
        return User.objects.get(fs_uniquifier=identity)  # pylint: disable=no-member
    except Exception:  # pylint: disable=broad-except
        return None
