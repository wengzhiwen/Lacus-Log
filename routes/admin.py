# pylint: disable=no-member
from flask import (Blueprint, abort, flash, redirect, render_template, url_for)
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
    return render_template('users/list.html')


@admin_bp.route('/users/new', methods=['GET'])
@roles_required('gicho')
def users_new():
    """新增运营。"""
    return render_template('users/new.html')


@admin_bp.route('/users/<user_id>/edit', methods=['GET'])
@roles_required('gicho')
def users_edit(user_id: str):  # pylint: disable=unused-argument
    """编辑用户基本信息（昵称、邮箱）。"""
    return render_template('users/edit.html')


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
def users_detail(user_id: str):  # pylint: disable=unused-argument
    """用户详情页面。"""
    return render_template('users/detail.html')


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
