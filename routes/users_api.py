# pylint: disable=no-member

from flask import Blueprint, jsonify, request
from flask_security.utils import hash_password
from mongoengine import DoesNotExist, ValidationError

from models.user import Role, User
from utils.csrf_helper import CSRFError, validate_csrf_header
from utils.jwt_roles import jwt_roles_accepted, jwt_roles_required
from utils.logging_setup import get_logger
from utils.user_serializers import (create_error_response,
                                    create_success_response, serialize_user,
                                    serialize_user_list)

logger = get_logger('admin')

users_api_bp = Blueprint('users_api', __name__)


def safe_strip(value):
    """安全地去除字符串两端空格，处理None值"""
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped if stripped else None
    return None


@users_api_bp.route('/api/users', methods=['GET'])
@jwt_roles_required('gicho')
def get_users():
    """获取用户列表。
    
    支持参数：
    - role: 角色筛选（gicho/kancho）
    - active: 激活状态筛选（true/false）
    - page: 页码（默认1）
    - per_page: 每页数量（默认20）
    """
    try:
        # 获取查询参数
        role_filter = request.args.get('role')
        active_filter = request.args.get('active')
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 20)), 100)  # 限制最大100条

        # 构建查询
        query = User.objects

        # 角色筛选
        if role_filter:
            try:
                role_obj = Role.objects.get(name=role_filter)
                query = query.filter(roles=role_obj)
            except DoesNotExist:
                return jsonify(create_error_response('ROLE_NOT_FOUND', '角色不存在')), 404

        # 激活状态筛选
        if active_filter is not None:
            active_bool = active_filter.lower() == 'true'
            query = query.filter(active=active_bool)

        # 分页
        total = query.count()
        users = query.order_by('-created_at').skip((page - 1) * per_page).limit(per_page)

        # 序列化数据
        users_data = serialize_user_list(users, include_login_info=False)

        # 分页信息
        meta = {'pagination': {'page': page, 'per_page': per_page, 'total': total, 'pages': (total + per_page - 1) // per_page}}

        return jsonify(create_success_response(users_data, meta))

    except Exception as e:
        logger.error('获取用户列表失败: %s', str(e))
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@users_api_bp.route('/api/users/<user_id>', methods=['GET'])
@jwt_roles_required('gicho')
def get_user(user_id: str):
    """获取用户详情。"""
    try:
        user = User.objects.get(id=user_id)
        user_data = serialize_user(user, include_login_info=True)
        return jsonify(create_success_response(user_data))

    except DoesNotExist:
        return jsonify(create_error_response('USER_NOT_FOUND', '用户不存在')), 404
    except Exception as e:
        logger.error('获取用户详情失败: %s', str(e))
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@users_api_bp.route('/api/users', methods=['POST'])
@jwt_roles_required('gicho')
def create_user():
    """创建运营账户。"""
    try:
        # 验证CSRF令牌
        try:
            validate_csrf_header()
        except CSRFError as exc:
            return jsonify(create_error_response(exc.code, exc.message)), 401

        data = request.get_json()
        if not data:
            return jsonify(create_error_response('INVALID_REQUEST', '请求数据格式错误')), 400

        # 获取必需字段
        username = safe_strip(data.get('username'))
        password = safe_strip(data.get('password'))
        nickname = safe_strip(data.get('nickname'))
        email = safe_strip(data.get('email'))
        role = safe_strip(data.get('role'))

        # 验证必需字段
        if not username or not password or not role:
            return jsonify(create_error_response('MISSING_FIELDS', '用户名、密码与角色为必填项')), 400

        # 验证角色
        # 验证角色是否有效
        valid_roles = ['gicho', 'kancho']
        if role not in valid_roles:
            return jsonify(create_error_response('INVALID_ROLE', f'无效的角色: {role}，有效角色为: {", ".join(valid_roles)}')), 400

        # 获取指定角色
        target_role = Role.objects(name=role).first()
        if not target_role:
            return jsonify(create_error_response('ROLE_NOT_FOUND', f'角色 {role} 不存在')), 500

        # 验证用户名长度
        if len(username) < 3 or len(username) > 20:
            return jsonify(create_error_response('INVALID_USERNAME_LENGTH', '用户名长度应在3-20个字符之间')), 400

        # 验证密码长度
        if len(password) < 6:
            return jsonify(create_error_response('INVALID_PASSWORD_LENGTH', '密码长度至少6个字符')), 400

        # 验证用户名格式
        if not username.replace('_', '').replace('-', '').isalnum():
            return jsonify(create_error_response('INVALID_USERNAME_FORMAT', '用户名只能包含字母、数字、下划线和连字符')), 400

        # 检查用户名是否已存在
        if User.objects(username=username).first():
            return jsonify(create_error_response('USERNAME_EXISTS', '该用户名已存在')), 409

        # 创建用户
        user = User(username=username, nickname=nickname, password=hash_password(password), email=email or None, roles=[target_role], active=True)
        user.save()

        logger.info('管理员创建运营：%s', username)
        user_data = serialize_user(user)
        return jsonify(create_success_response(user_data)), 201

    except ValidationError as e:
        logger.error('用户数据验证失败: %s', str(e))
        return jsonify(create_error_response('VALIDATION_ERROR', '数据验证失败')), 400
    except Exception as e:
        logger.error('创建用户失败: %s', str(e))
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@users_api_bp.route('/api/users/<user_id>', methods=['DELETE'])
@jwt_roles_required('gicho')
def delete_user(user_id: str):
    """删除用户。"""
    try:
        # 验证CSRF令牌
        try:
            validate_csrf_header()
        except CSRFError as exc:
            return jsonify(create_error_response(exc.code, exc.message)), 401

        user = User.objects.get(id=user_id)

        # 检查是否尝试删除最后一个管理员
        if user.has_role('gicho'):
            gicho_role = Role.objects(name='gicho').first()
            active_gicho_count = User.objects(roles=gicho_role, active=True).count()
            if active_gicho_count <= 1:
                return jsonify(create_error_response('CANNOT_DELETE_LAST_ADMIN', '不能删除最后一个管理员')), 409

        username = user.username
        user.delete()

        logger.info('删除用户：%s', username)
        data = {'message': f'用户 {username} 已删除'}
        return jsonify(create_success_response(data))

    except DoesNotExist:
        return jsonify(create_error_response('USER_NOT_FOUND', '用户不存在')), 404
    except Exception as e:
        logger.error('删除用户失败: %s', str(e))
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@users_api_bp.route('/api/users/<user_id>', methods=['PUT'])
@jwt_roles_required('gicho')
def update_user(user_id: str):
    """更新用户信息。"""
    try:
        # 验证CSRF令牌
        try:
            validate_csrf_header()
        except CSRFError as exc:
            return jsonify(create_error_response(exc.code, exc.message)), 401

        user = User.objects.get(id=user_id)
        data = request.get_json()

        if not data:
            return jsonify(create_error_response('INVALID_REQUEST', '请求数据格式错误')), 400

        # 只允许更新特定字段
        if 'nickname' in data:
            user.nickname = data['nickname'].strip()

        if 'email' in data:
            user.email = data['email'].strip() or None

        if 'roles' in data:
            # 验证角色
            role_names = data['roles']
            if not isinstance(role_names, list):
                return jsonify(create_error_response('INVALID_ROLES', '角色必须是数组')), 400

            roles = []
            for role_name in role_names:
                try:
                    role = Role.objects.get(name=role_name)
                    roles.append(role)
                except DoesNotExist:
                    return jsonify(create_error_response('ROLE_NOT_FOUND', f'角色 {role_name} 不存在')), 400

            user.roles = roles

        user.save()
        logger.info('更新用户信息：%s', user.username)

        user_data = serialize_user(user, include_login_info=True)
        return jsonify(create_success_response(user_data))

    except DoesNotExist:
        return jsonify(create_error_response('USER_NOT_FOUND', '用户不存在')), 404
    except ValidationError as e:
        logger.error('用户数据验证失败: %s', str(e))
        return jsonify(create_error_response('VALIDATION_ERROR', '数据验证失败')), 400
    except Exception as e:
        logger.error('更新用户失败: %s', str(e))
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@users_api_bp.route('/api/users/<user_id>/activation', methods=['PATCH'])
@jwt_roles_required('gicho')
def toggle_user_activation(user_id: str):
    """切换用户激活状态。"""
    try:
        # 验证CSRF令牌
        try:
            validate_csrf_header()
        except CSRFError as exc:
            return jsonify(create_error_response(exc.code, exc.message)), 401

        user = User.objects.get(id=user_id)
        data = request.get_json()

        if not data or 'active' not in data:
            return jsonify(create_error_response('MISSING_FIELDS', '缺少active字段')), 400

        new_active = data['active']
        if not isinstance(new_active, bool):
            return jsonify(create_error_response('INVALID_ACTIVE_VALUE', 'active字段必须是布尔值')), 400

        # 检查是否尝试停用最后一个管理员
        if user.has_role('gicho') and not new_active:
            gicho_role = Role.objects(name='gicho').first()
            active_gicho_count = User.objects(roles=gicho_role, active=True).count()
            if active_gicho_count <= 1:
                return jsonify(create_error_response('CANNOT_DEACTIVATE_LAST_ADMIN', '不能停用最后一个管理员')), 409

        user.active = new_active
        user.save()

        logger.info('更新用户状态：%s -> %s', user.username, user.active)
        user_data = serialize_user(user)
        return jsonify(create_success_response(user_data))

    except DoesNotExist:
        return jsonify(create_error_response('USER_NOT_FOUND', '用户不存在')), 404
    except Exception as e:
        logger.error('切换用户状态失败: %s', str(e))
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@users_api_bp.route('/api/users/<user_id>/reset-password', methods=['POST'])
@jwt_roles_required('gicho')
def reset_user_password(user_id: str):
    """重置用户密码。"""
    try:
        # 验证CSRF令牌
        try:
            validate_csrf_header()
        except CSRFError as exc:
            return jsonify(create_error_response(exc.code, exc.message)), 401

        user = User.objects.get(id=user_id)

        # 重置为临时密码
        temp_password = '123456'
        user.password = hash_password(temp_password)
        user.save()

        logger.info('重置用户密码：%s', user.username)

        # 返回重置信息
        data = {'user_id': str(user.id), 'username': user.username, 'temp_password': temp_password, 'message': '密码已重置为 123456，请通知用户尽快修改'}

        return jsonify(create_success_response(data))

    except DoesNotExist:
        return jsonify(create_error_response('USER_NOT_FOUND', '用户不存在')), 404
    except Exception as e:
        logger.error('重置用户密码失败: %s', str(e))
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@users_api_bp.route('/api/users/operators', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def get_operators():
    """获取运营和管理员列表（用于下拉选择等）
    
    返回所有激活状态的运营(kancho)和管理员(gicho)，
    供主播管理等模块的直属运营筛选器使用。
    """
    try:
        # 先尝试获取角色对象
        try:
            gicho_role = Role.objects.get(name='gicho')
            kancho_role = Role.objects.get(name='kancho')
            target_roles = [gicho_role, kancho_role]
            logger.debug('找到角色对象: gicho=%s, kancho=%s', gicho_role.id, kancho_role.id)
        except DoesNotExist as e:
            logger.warning('角色不存在: %s，将返回所有激活用户', str(e))
            target_roles = None

        # 获取用户
        if target_roles:
            operators = User.objects(active=True, roles__in=target_roles).order_by('nickname')
            logger.info('按角色筛选，找到 %d 个运营/管理员', operators.count())
        else:
            operators = User.objects(active=True).order_by('nickname')
            logger.info('返回所有激活用户，共 %d 个', operators.count())

        # 简化序列化，只返回必要字段
        operators_data = [{
            'id': str(user.id),
            'username': user.username,
            'nickname': user.nickname or user.username,
            'roles': [role.name for role in user.roles] if user.roles else []
        } for user in operators]

        logger.debug('返回运营数据: %s', [{'id': u['id'], 'nickname': u['nickname']} for u in operators_data])

        return jsonify(create_success_response(operators_data))

    except Exception as e:
        logger.error('获取运营列表失败: %s', str(e), exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@users_api_bp.route('/api/users/emails', methods=['GET'])
@jwt_roles_required('gicho')
def get_user_emails():
    """查询角色可用邮箱。"""
    try:
        role_name = request.args.get('role')
        only_active = request.args.get('only_active', 'true').lower() == 'true'

        emails = User.get_emails_by_role(role_name, only_active)

        data = {'emails': emails, 'role': role_name, 'only_active': only_active, 'count': len(emails)}

        return jsonify(create_success_response(data))

    except Exception as e:
        logger.error('获取用户邮箱失败: %s', str(e))
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@users_api_bp.route('/api/auth/csrf', methods=['GET'])
@jwt_roles_required('gicho')
def get_csrf_token():
    """获取CSRF令牌。"""
    try:
        from flask_wtf.csrf import generate_csrf
        token = generate_csrf()

        data = {'token': token}
        return jsonify(create_success_response(data))

    except Exception as e:
        logger.error('获取CSRF令牌失败: %s', str(e))
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@users_api_bp.route('/api/errors/frontend', methods=['POST'])
@jwt_roles_required('gicho')
def log_frontend_error():
    """记录前端错误到后端日志。"""
    try:
        data = request.get_json()
        if not data:
            return jsonify(create_error_response('INVALID_REQUEST', '请求数据格式错误')), 400

        error_type = data.get('type', 'unknown')
        error_message = data.get('message', '')
        error_stack = data.get('stack', '')
        url = data.get('url', '')
        user_agent = data.get('userAgent', '')

        # 记录前端错误到日志
        logger.error('前端错误 [%s]: %s', error_type, error_message)
        if error_stack:
            logger.error('错误堆栈: %s', error_stack)
        if url:
            logger.error('错误URL: %s', url)
        if user_agent:
            logger.error('用户代理: %s', user_agent)

        return jsonify(create_success_response({'logged': True}))

    except Exception as e:
        logger.error('记录前端错误失败: %s', str(e))
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500
