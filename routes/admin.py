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


@admin_bp.route('/users/<user_id>')
@roles_required('gicho')
def users_detail(user_id: str):  # pylint: disable=unused-argument
    """用户详情页面。"""
    return render_template('users/detail.html')
