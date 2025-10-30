# pylint: disable=no-member
"""
招募管理模板路由
只负责渲染HTML模板，所有CRUD操作通过REST API进行
"""

from datetime import datetime, timedelta

from flask import Blueprint, abort, redirect, render_template, url_for
from flask_security import current_user, roles_accepted
from mongoengine import DoesNotExist

from models.pilot import Pilot
from models.recruit import Recruit, RecruitStatus
from models.user import Role, User
from utils.logging_setup import get_logger
from utils.timezone_helper import get_current_utc_time

logger = get_logger('recruit')

recruit_bp = Blueprint('recruit', __name__)


def _group_recruits(recruits):
    """
    对招募列表进行分组和排序
    
    根据状态和时间条件将招募分为不同的组，并按照规定的规则排序
    """
    now = get_current_utc_time()
    overdue_24h = now - timedelta(hours=24)
    overdue_7d = now - timedelta(days=7)

    grouped = {
        'pending_interview': [],
        'pending_training_schedule': [],
        'pending_training': [],
        'pending_broadcast_schedule': [],
        'pending_broadcast': [],
        'overdue': [],
        'ended': []
    }

    for recruit in recruits:
        effective_status = recruit.get_effective_status()

        # 已结束分组
        if effective_status == RecruitStatus.ENDED:
            grouped['ended'].append(recruit)
            continue

        # 判断是否超时（鸽）
        is_overdue = False

        if effective_status == RecruitStatus.PENDING_INTERVIEW:
            if recruit.appointment_time and recruit.appointment_time < overdue_24h:
                is_overdue = True
        elif effective_status == RecruitStatus.PENDING_TRAINING_SCHEDULE:
            if recruit.interview_decision_time and recruit.interview_decision_time < overdue_7d:
                is_overdue = True
        elif effective_status == RecruitStatus.PENDING_TRAINING:
            scheduled_time = recruit.get_effective_scheduled_training_time()
            if scheduled_time and scheduled_time < overdue_24h:
                is_overdue = True
        elif effective_status == RecruitStatus.PENDING_BROADCAST_SCHEDULE:
            if recruit.training_decision_time and recruit.training_decision_time < overdue_7d:
                is_overdue = True
        elif effective_status == RecruitStatus.PENDING_BROADCAST:
            scheduled_time = recruit.get_effective_scheduled_broadcast_time()
            if scheduled_time and scheduled_time < overdue_24h:
                is_overdue = True

        # 分配到相应的组
        if is_overdue:
            grouped['overdue'].append(recruit)
        elif effective_status == RecruitStatus.PENDING_INTERVIEW:
            grouped['pending_interview'].append(recruit)
        elif effective_status == RecruitStatus.PENDING_TRAINING_SCHEDULE:
            grouped['pending_training_schedule'].append(recruit)
        elif effective_status == RecruitStatus.PENDING_TRAINING:
            grouped['pending_training'].append(recruit)
        elif effective_status == RecruitStatus.PENDING_BROADCAST_SCHEDULE:
            grouped['pending_broadcast_schedule'].append(recruit)
        elif effective_status == RecruitStatus.PENDING_BROADCAST:
            grouped['pending_broadcast'].append(recruit)

    # 排序
    # 待面试：按预约时间升序
    grouped['pending_interview'].sort(key=lambda r: r.appointment_time or datetime.max)

    # 待预约试播：按面试决策时间逆序
    grouped['pending_training_schedule'].sort(key=lambda r: r.interview_decision_time or datetime.min, reverse=True)

    # 待试播：按预约试播时间升序
    grouped['pending_training'].sort(key=lambda r: r.get_effective_scheduled_training_time() or datetime.max)

    # 待预约开播：按试播决策时间逆序
    grouped['pending_broadcast_schedule'].sort(key=lambda r: r.training_decision_time or datetime.min, reverse=True)

    # 待开播：按预约开播时间升序
    grouped['pending_broadcast'].sort(key=lambda r: r.get_effective_scheduled_broadcast_time() or datetime.max)

    # 鸽：先按状态顺序，再按最后更新时间逆序，最多100条
    status_order = {
        RecruitStatus.PENDING_INTERVIEW: 1,
        RecruitStatus.PENDING_TRAINING_SCHEDULE: 2,
        RecruitStatus.PENDING_TRAINING: 3,
        RecruitStatus.PENDING_BROADCAST_SCHEDULE: 4,
        RecruitStatus.PENDING_BROADCAST: 5,
    }
    grouped['overdue'].sort(key=lambda r: (status_order.get(r.get_effective_status(), 999), -(r.updated_at.timestamp() if r.updated_at else 0)))
    grouped['overdue'] = grouped['overdue'][:100]

    # 已结束：按最后更新时间逆序，最多100条
    grouped['ended'].sort(key=lambda r: r.updated_at or datetime.min, reverse=True)
    grouped['ended'] = grouped['ended'][:100]

    return grouped


def _get_recruiter_choices():
    """获取招募负责人选择列表"""
    role_docs = list(Role.objects.filter(name__in=['gicho', 'kancho']).only('id'))
    users = User.objects.filter(roles__in=role_docs).all()
    choices = []

    if current_user.has_role('kancho') or current_user.has_role('gicho'):
        label = current_user.nickname or current_user.username
        if current_user.has_role('gicho'):
            label = f"{label} [管理员]"
        elif current_user.has_role('kancho'):
            label = f"{label} [运营]"
        choices.append((str(current_user.id), label))

    active_users = [u for u in users if u.active and u.id != current_user.id]
    active_users.sort(key=lambda x: x.nickname or x.username)
    for user in active_users:
        label = user.nickname or user.username
        if user.has_role('gicho'):
            label = f"{label} [管理员]"
        elif user.has_role('kancho'):
            label = f"{label} [运营]"
        choices.append((str(user.id), label))

    return choices


@recruit_bp.route('/')
@roles_accepted('gicho', 'kancho', 'gunsou')
def list_recruits():
    """招募列表页面"""
    return render_template('recruits/list.html')


@recruit_bp.route('/start/<pilot_id>')
@roles_accepted('gicho', 'kancho', 'gunsou')
def start_recruit_page(pilot_id):
    """启动招募页面"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)
    except DoesNotExist:
        abort(404)

    if pilot.status.value != '未招募':
        abort(400, '只有未招募状态的主播才能启动招募')

    logger.debug('打开启动招募页面：主播=%s', pilot.nickname)

    return render_template('recruits/start.html', pilot_id=pilot_id)


@recruit_bp.route('/<recruit_id>')
@roles_accepted('gicho', 'kancho', 'gunsou')
def detail_recruit(recruit_id):
    """招募详情页面"""
    # The page is now rendered dynamically via API.
    # We just need to pass the recruit_id to the template.
    return render_template('recruits/detail.html', recruit_id=recruit_id)


@recruit_bp.route('/<recruit_id>/edit')
@roles_accepted('gicho', 'kancho', 'gunsou')
def edit_recruit_page(recruit_id):
    """编辑招募页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    logger.debug('打开编辑招募页面：ID=%s，主播=%s', recruit_id, recruit.pilot.nickname)

    return render_template('recruits/edit.html', recruit_id=recruit_id)


@recruit_bp.route('/<recruit_id>/interview')
@roles_accepted('gicho', 'kancho', 'gunsou')
def interview_recruit_page(recruit_id):
    """面试决策页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_INTERVIEW:
        abort(400, '只能对待面试状态的招募执行面试决策')

    logger.debug('打开面试决策页面：ID=%s，主播=%s', recruit_id, recruit.pilot.nickname)

    return render_template('recruits/interview.html', recruit_id=recruit_id)


@recruit_bp.route('/<recruit_id>/schedule-training')
@roles_accepted('gicho', 'kancho', 'gunsou')
def schedule_training_page(recruit_id):
    """预约试播页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_TRAINING_SCHEDULE:
        abort(400, '只能对待预约试播状态的招募执行预约试播')

    return render_template('recruits/schedule_training.html', recruit_id=recruit_id)


@recruit_bp.route('/<recruit_id>/training-decision')
@roles_accepted('gicho', 'kancho', 'gunsou')
def training_decision_page(recruit_id):
    """试播决策页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_TRAINING:
        abort(400, '只能对待试播状态的招募执行试播决策')

    logger.debug('打开试播决策页面：ID=%s，主播=%s', recruit_id, recruit.pilot.nickname)

    return render_template('recruits/training_decision.html', recruit_id=recruit_id)


@recruit_bp.route('/<recruit_id>/schedule-broadcast')
@roles_accepted('gicho', 'kancho', 'gunsou')
def schedule_broadcast_page(recruit_id):
    """预约开播页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_BROADCAST_SCHEDULE:
        abort(400, '只能对待预约开播状态的招募执行预约开播')

    logger.debug('打开预约开播页面：ID=%s，主播=%s', recruit_id, recruit.pilot.nickname)

    return render_template('recruits/schedule_broadcast.html', recruit_id=recruit_id)


@recruit_bp.route('/<recruit_id>/broadcast-decision')
@roles_accepted('gicho', 'kancho', 'gunsou')
def broadcast_decision_page(recruit_id):
    """开播决策页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_BROADCAST:
        abort(400, '只能对待开播状态的招募执行开播决策')

    logger.debug('打开开播决策页面：ID=%s，主播=%s', recruit_id, recruit.pilot.nickname)

    return render_template('recruits/broadcast_decision.html', recruit_id=recruit_id)


@recruit_bp.route('/<recruit_id>/changes')
@roles_accepted('gicho', 'kancho', 'gunsou')
def recruit_changes(recruit_id):
    """招募变更记录页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    logger.debug('打开招募变更记录页面：ID=%s，主播=%s', recruit_id, recruit.pilot.nickname)

    return render_template('recruits/changes.html', recruit=recruit)


# 兼容性路由 - 重定向到新的REST API
@recruit_bp.route('/export')
@roles_accepted('gicho', 'kancho', 'gunsou')
def export_recruits():
    """导出招募数据 - 重定向到REST API"""
    return redirect(url_for('recruits_api.export_recruits'))


# 兼容性路由 - 重定向到新的REST API
@recruit_bp.route('/options')
@roles_accepted('gicho', 'kancho', 'gunsou')
def recruit_options():
    """获取招募选项 - 重定向到REST API"""
    return redirect(url_for('recruits_api.get_recruit_options'))
