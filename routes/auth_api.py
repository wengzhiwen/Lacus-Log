"""REST 认证 API。

提供登录、登出、token 刷新、CSRF token 获取等接口。
"""
from flask import Blueprint, jsonify, make_response, request
from flask_login import logout_user as flask_logout_user
from flask_jwt_extended import (create_access_token, create_refresh_token, get_jwt_identity, jwt_required, set_access_cookies, set_refresh_cookies,
                                unset_jwt_cookies)
from flask_wtf.csrf import generate_csrf
from mongoengine import DoesNotExist

from models.user import User
from utils.csrf_helper import CSRFError, validate_csrf_header
from utils.logging_setup import get_logger

logger = get_logger('auth_api')
auth_api_bp = Blueprint('auth_api', __name__)


def create_success_response(data=None, meta=None):
    """创建成功响应。"""
    return {'success': True, 'data': data or {}, 'error': None, 'meta': meta or {}}


def create_error_response(code, message, meta=None):
    """创建错误响应。"""
    return {'success': False, 'data': None, 'error': {'code': code, 'message': message}, 'meta': meta or {}}


@auth_api_bp.route('/api/auth/login', methods=['POST'])
def login():
    """用户登录（REST API）。
    
    请求体：
        {
            "username": "admin",
            "password": "password123"
        }
    
    响应：
        {
            "success": true,
            "data": {
                "access_token": "eyJ...",
                "user": {
                    "id": "...",
                    "username": "admin",
                    "nickname": "管理员",
                    "roles": ["gicho"]
                }
            },
            "meta": {
                "csrf_token": "..."
            }
        }
    
    同时设置以下 cookie：
        - access_token_cookie (httpOnly)
        - refresh_token_cookie (httpOnly)
        - csrf_token (非 httpOnly，供前端读取)
    """
    payload = request.get_json(silent=True) or {}
    username = payload.get('username', '').strip()
    password = payload.get('password', '')

    if not username or not password:
        return jsonify(create_error_response('INVALID_PARAMS', '用户名和密码不能为空')), 400

    try:
        user = User.objects.get(username=username)  # pylint: disable=no-member
    except DoesNotExist:
        logger.warning('登录失败：用户不存在，username=%s，IP=%s', username, request.remote_addr)
        return jsonify(create_error_response('INVALID_CREDENTIALS', '用户名或密码错误')), 401

    if not user.active:
        logger.warning('登录失败：账户已停用，username=%s，IP=%s', username, request.remote_addr)
        return jsonify(create_error_response('ACCOUNT_DISABLED', '账户已停用')), 403

    if not user.verify_and_update_password(password):
        logger.warning('登录失败：密码错误，username=%s，IP=%s', username, request.remote_addr)
        return jsonify(create_error_response('INVALID_CREDENTIALS', '用户名或密码错误')), 401

    # 更新登录统计（与 Flask-Security-Too 保持一致）
    from utils.timezone_helper import get_current_utc_time
    user.last_login_at = user.current_login_at
    user.current_login_at = get_current_utc_time()
    user.last_login_ip = user.current_login_ip
    user.current_login_ip = request.remote_addr
    user.login_count = (user.login_count or 0) + 1
    user.save()

    # 建立 Flask-Security-Too Session（让 @login_required 能识别）
    from flask_login import login_user
    # REST 登录不强制长记住，避免产生 remember_token 导致 /login 自动认为已登录
    login_user(user, remember=False)
    logger.debug('已为用户建立Flask-Security Session（remember=False）：username=%s', username)

    # 创建 JWT token（直接传User对象，JWT回调会提取fs_uniquifier）
    access_token = create_access_token(identity=user)
    refresh_token = create_refresh_token(identity=user)

    # 生成 CSRF token
    csrf_token = generate_csrf()

    # 构造响应
    user_data = {
        'id': str(user.id),
        'username': user.username,
        'nickname': user.nickname or user.username,
        'roles': [role.name for role in user.roles],
    }

    response_data = create_success_response(data={'access_token': access_token, 'user': user_data}, meta={'csrf_token': csrf_token})

    response = make_response(jsonify(response_data), 200)

    # 设置 JWT cookie（httpOnly，防止 XSS）
    set_access_cookies(response, access_token)
    set_refresh_cookies(response, refresh_token)

    # 设置 CSRF cookie（非 httpOnly，供前端读取）
    response.set_cookie('csrf_token', csrf_token, httponly=False, secure=request.is_secure, samesite='Lax')

    logger.info('用户登录成功（REST API + Session）：username=%s，IP=%s', username, request.remote_addr)
    return response


@auth_api_bp.route('/api/auth/logout', methods=['POST'])
@jwt_required()
def logout():
    """用户登出。
    
    清除 JWT 和 CSRF cookie。
    """
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    response = make_response(jsonify(create_success_response(meta={'message': '登出成功'})), 200)

    # 清除所有认证相关的 cookie
    unset_jwt_cookies(response)
    response.set_cookie('csrf_token', '', expires=0)

    identity = get_jwt_identity()
    logger.info('用户登出成功（REST API）：identity=%s，IP=%s', identity, request.remote_addr)
    return response


@auth_api_bp.route('/api/auth/refresh', methods=['POST'])
@jwt_required(refresh=True)
def refresh():
    """刷新 Access Token。
    
    使用 Refresh Token 获取新的 Access Token 和 CSRF Token。
    """
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    identity = get_jwt_identity()
    access_token = create_access_token(identity=identity)
    csrf_token = generate_csrf()

    response_data = create_success_response(data={'access_token': access_token}, meta={'csrf_token': csrf_token})

    response = make_response(jsonify(response_data), 200)

    set_access_cookies(response, access_token)

    response.set_cookie('csrf_token', csrf_token, httponly=False, secure=request.is_secure, samesite='Lax')

    logger.info('Token 刷新成功：identity=%s，IP=%s', identity, request.remote_addr)
    return response


@auth_api_bp.route('/api/auth/csrf', methods=['GET'])
def get_csrf_token():
    """获取CSRF令牌（匿名访问）。
    
    响应：
        {
            "success": true,
            "data": {
                "csrf_token": "..."
            }
        }
    """
    csrf_token = generate_csrf()
    return jsonify(create_success_response(data={'csrf_token': csrf_token}))


@auth_api_bp.route('/api/auth/me', methods=['GET'])
@jwt_required()
def get_current_user():
    """获取当前登录用户信息。
    
    响应：
        {
            "success": true,
            "data": {
                "user": {
                    "id": "...",
                    "username": "admin",
                    "nickname": "管理员",
                    "roles": ["gicho"]
                }
            }
        }
    """
    identity = get_jwt_identity()

    try:
        user = User.objects.get(fs_uniquifier=identity)  # pylint: disable=no-member
    except DoesNotExist:
        logger.warning('获取当前用户信息失败：用户不存在，identity=%s', identity)
        return jsonify(create_error_response('USER_NOT_FOUND', '用户不存在')), 404

    user_data = {
        'id': str(user.id),
        'username': user.username,
        'nickname': user.nickname or user.username,
        'roles': [role.name for role in user.roles],
        'email': user.email,
        'active': user.active,
    }

    return jsonify(create_success_response(data={'user': user_data}))


@auth_api_bp.route('/logout-with-jwt', methods=['GET'])
def logout_with_jwt():
    """传统页面的登出（GET方法）
    
    清除JWT Cookie并重定向到登录页。
    这个路由用于替代Flask-Security-Too的默认logout路由。
    """
    from flask import redirect, url_for, session
    
    response = make_response(redirect(url_for('security.login')))
    
    # 先登出 Flask-Login / Flask-Security 会话
    try:
        flask_logout_user()
    except Exception:  # pylint: disable=broad-except
        pass

    # 清理服务端会话内容（防止已登录状态导致/login跳回首页）
    try:
        session.clear()
    except Exception:  # pylint: disable=broad-except
        pass

    # 清除所有JWT相关的cookie
    unset_jwt_cookies(response)
    
    # 同步清除 Flask-Login/Flask-Security 相关Cookie（浏览器侧）
    try:
        # 删除 remember_token / session 等浏览器端 Cookie
        response.set_cookie('remember_token', '', expires=0)
        response.set_cookie('session', '', expires=0)
    except Exception:  # pylint: disable=broad-except
        pass

    # 同时清除CSRF token cookie
    response.set_cookie('csrf_token', '', expires=0)
    
    logger.info('用户登出（传统页面）：IP=%s', request.remote_addr)
    return response
