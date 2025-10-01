# pylint: disable=no-member
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)
from flask_security import roles_required
from flask_security.utils import hash_password
from mongoengine import DoesNotExist

from models.user import Role, User
from utils.logging_setup import get_logger

logger = get_logger('admin')

admin_bp = Blueprint('admin', __name__)


@admin_bp.route('/users')
@roles_required('gicho')
def users_list():
    """用户列表（仅管理员可见）。"""
    role = request.args.get('role')
    query = User.objects
    if role:
        try:
            role_obj = Role.objects.get(name=role)
            query = query.filter(roles=role_obj)
        except DoesNotExist:
            query = User.objects.none()
    users = query.order_by('-created_at').all()
    return render_template('users/list.html', users=users, selected_role=role)


@admin_bp.route('/users/new', methods=['GET', 'POST'])
@roles_required('gicho')
def users_new():
    """新增运营。"""
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        nickname = request.form.get('nickname', '').strip()
        password = request.form.get('password', '').strip()
        email = request.form.get('email', '').strip()

        if not username or not password:
            flash('用户名与密码为必填项', 'error')
            return render_template('users/new.html', form=request.form)

        if len(username) < 3 or len(username) > 20:
            flash('用户名长度应在3-20个字符之间', 'error')
            return render_template('users/new.html', form=request.form)

        if len(password) < 6:
            flash('密码长度至少6个字符', 'error')
            return render_template('users/new.html', form=request.form)

        if not username.replace('_', '').replace('-', '').isalnum():
            flash('用户名只能包含字母、数字、下划线和连字符', 'error')
            return render_template('users/new.html', form=request.form)

        if User.objects(username=username).first():
            flash('该用户名已存在', 'error')
            return render_template('users/new.html', form=request.form)

        kancho = Role.objects(name='kancho').first()
        if kancho is None:
            flash('系统缺少角色：运营', 'error')
            return render_template('users/new.html', form=request.form)

        user = User(username=username,
                    nickname=nickname,
                    password=hash_password(password),
                    email=(email or None),
                    roles=[kancho],
                    active=True)
        user.save()
        flash('创建运营成功', 'success')
        logger.info('管理员创建运营：%s', username)
        return redirect(url_for('admin.users_list'))

    return render_template('users/new.html')


@admin_bp.route('/users/<user_id>/edit', methods=['GET', 'POST'])
@roles_required('gicho')
def users_edit(user_id: str):
    """编辑用户基本信息（昵称、邮箱）。"""
    try:
        user = User.objects.get(id=user_id)
    except DoesNotExist:
        abort(404)

    if request.method == 'POST':
        nickname = request.form.get('nickname', '').strip()
        email = request.form.get('email', '').strip()

        user.nickname = nickname
        user.email = (email or None)
        user.save()
        flash('已更新用户信息', 'success')
        logger.info('更新用户信息：%s', user.username)
        return redirect(url_for('admin.users_detail', user_id=user_id))

    return render_template('users/edit.html', user=user)


@admin_bp.route('/users/<user_id>/toggle', methods=['POST'])
@roles_required('gicho')
def users_toggle_active(user_id: str):
    """切换用户激活状态。"""
    try:
        user = User.objects.get(id=user_id)

        if user.has_role('gicho') and not user.active:
            gicho_role = Role.objects(name='gicho').first()
            active_gicho_count = User.objects(roles=gicho_role,
                                              active=True).count()
            if active_gicho_count <= 1:
                flash('不能停用最后一个管理员', 'error')
                return redirect(url_for('admin.users_list'))

        user.active = not user.active
        user.save()
        flash('已更新用户状态', 'success')
        logger.info('更新用户状态：%s -> %s', user.username, user.active)
    except DoesNotExist:
        abort(404)
    return redirect(url_for('admin.users_list'))


@admin_bp.route('/users/<user_id>')
@roles_required('gicho')
def users_detail(user_id: str):
    """用户详情页面。"""
    try:
        user = User.objects.get(id=user_id)
        return render_template('users/detail.html', user=user)
    except DoesNotExist:
        abort(404)


@admin_bp.route('/users/<user_id>/reset', methods=['POST'])
@roles_required('gicho')
def users_reset_password(user_id: str):
    """重置用户密码为临时密码 123456（仅演示，生产需改进）。"""
    try:
        user = User.objects.get(id=user_id)
        user.password = hash_password('123456')
        user.save()
        flash('已重置密码为 123456，请通知用户尽快修改', 'success')
        logger.info('重置用户密码：%s', user.username)
    except DoesNotExist:
        abort(404)
    return redirect(url_for('admin.users_detail', user_id=user_id))
