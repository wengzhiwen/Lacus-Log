# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""
主播管理路由 - REST化版本
所有核心功能已迁移到API驱动，这里只保留简单的模板渲染路由
"""

from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_security import roles_accepted
from mongoengine import DoesNotExist
from models.pilot import Pilot, PilotChangeLog  # pylint: disable=no-member
from utils.logging_setup import get_logger

logger = get_logger('pilot')
pilot_bp = Blueprint('pilot', __name__)


@pilot_bp.route('/')
@roles_accepted('gicho', 'kancho')
def list_pilots():
    """主播列表页面 - REST化版本"""
    return render_template('pilots/list.html')


@pilot_bp.route('/<pilot_id>')
@roles_accepted('gicho', 'kancho')
def pilot_detail(pilot_id):  # pylint: disable=unused-argument
    """主播详情页面 - REST化版本"""
    return render_template('pilots/detail.html')


@pilot_bp.route('/new', methods=['GET', 'POST'])
@roles_accepted('gicho', 'kancho')
def new_pilot():
    """新建主播页面 - REST化版本"""
    return render_template('pilots/new.html')


@pilot_bp.route('/<pilot_id>/edit', methods=['GET', 'POST'])
@roles_accepted('gicho', 'kancho')
def edit_pilot(pilot_id):  # pylint: disable=unused-argument
    """编辑主播页面 - REST化版本"""
    return render_template('pilots/edit.html')


# ============ 以下为非核心功能的传统实现（commission, performance等） ============


@pilot_bp.route('/<pilot_id>/changes')
@roles_accepted('gicho', 'kancho')
def pilot_changes(pilot_id):
    """主播变更记录页面"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)  # pylint: disable=no-member
    except DoesNotExist:
        flash('主播不存在', 'error')
        return redirect(url_for('pilot.list_pilots'))

    # 获取最近的变更记录
    changes = PilotChangeLog.objects(pilot=pilot).order_by('-created_at').limit(100)  # pylint: disable=no-member

    return render_template('pilots/changes.html', pilot=pilot, changes=changes)


@pilot_bp.route('/<pilot_id>/commission/')
@roles_accepted('gicho', 'kancho')
def pilot_commission_index(pilot_id):
    """主播分成管理首页"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)  # pylint: disable=no-member
    except DoesNotExist:
        flash('主播不存在', 'error')
        return redirect(url_for('pilot.list_pilots'))

    return render_template(
        'pilots/commission/index.html',
        pilot=pilot,
    )


@pilot_bp.route('/<pilot_id>/commission/new', methods=['GET', 'POST'])
@roles_accepted('gicho', 'kancho')
def pilot_commission_new(pilot_id):
    """新建主播分成"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)  # pylint: disable=no-member
    except DoesNotExist:
        flash('主播不存在', 'error')
        return redirect(url_for('pilot.list_pilots'))

    return render_template('pilots/commission/new.html', pilot=pilot)


@pilot_bp.route('/<pilot_id>/performance')
@roles_accepted('gicho', 'kancho')
def pilot_performance(pilot_id):
    """主播绩效页面"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)
    except DoesNotExist:
        flash('主播不存在', 'error')
        return redirect(url_for('pilot.list_pilots'))

    return render_template('pilots/performance.html', pilot=pilot)


@pilot_bp.route('/export')
@roles_accepted('gicho', 'kancho')
def pilot_export():
    """兼容旧模板的导出入口：重定向到 REST 导出接口，保留查询串。"""
    query = request.query_string.decode() if request.query_string else ''
    target = '/api/pilots/export'
    if query:
        target = f"{target}?{query}"
    return redirect(target)
