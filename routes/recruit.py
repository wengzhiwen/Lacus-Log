# pylint: disable=no-member
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for)
from flask_security import current_user, roles_accepted
from mongoengine import DoesNotExist, ValidationError

from models.pilot import Pilot, Rank, Status
from models.recruit import (BroadcastDecision, InterviewDecision, Recruit, RecruitChangeLog, RecruitChannel, RecruitStatus, TrainingDecision, TrainingDecisionOld)
from models.user import Role, User
from utils.filter_state import persist_and_restore_filters
from utils.logging_setup import get_logger
from utils.timezone_helper import local_to_utc, utc_to_local

logger = get_logger('recruit')

recruit_bp = Blueprint('recruit', __name__)


def _get_client_ip():
    """获取客户端IP地址"""
    return request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR')


def _record_changes(recruit, old_data, user, ip_address):
    """记录招募字段变更"""
    changes = []
    field_mapping = {
        'pilot': str(recruit.pilot.id) if recruit.pilot else None,
        'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
        'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
        'channel': recruit.channel.value if hasattr(recruit.channel, 'value') else recruit.channel,
        'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
        'remarks': recruit.remarks,
        'status': recruit.status.value if hasattr(recruit.status, 'value') else recruit.status,
        'scheduled_training_time': recruit.scheduled_training_time.isoformat() if getattr(recruit, 'scheduled_training_time', None) else None,
        'scheduled_broadcast_time': recruit.scheduled_broadcast_time.isoformat() if getattr(recruit, 'scheduled_broadcast_time', None) else None,
    }

    for field_name, new_value in field_mapping.items():
        old_value = old_data.get(field_name)
        if str(old_value) != str(new_value):
            change_log = RecruitChangeLog(recruit_id=recruit,
                                          user_id=user,
                                          field_name=field_name,
                                          old_value=str(old_value) if old_value is not None else '',
                                          new_value=str(new_value) if new_value is not None else '',
                                          ip_address=ip_address)
            changes.append(change_log)

    if changes:
        RecruitChangeLog.objects.insert(changes)
        logger.info('记录招募变更：主播%s，共%d个字段', recruit.pilot.nickname if recruit.pilot else 'N/A', len(changes))


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


def _get_overdue_recruits_query():
    """获取超时招募记录的查询"""
    from mongoengine import Q

    from utils.timezone_helper import get_current_utc_time

    current_local = utc_to_local(get_current_utc_time())

    twenty_four_hours_ago_local = current_local - timedelta(hours=24)
    twenty_four_hours_ago_utc = local_to_utc(twenty_four_hours_ago_local)

    seven_days_ago_local = current_local - timedelta(days=7)
    seven_days_ago_utc = local_to_utc(seven_days_ago_local)

    overdue_query = (Q(status=RecruitStatus.PENDING_INTERVIEW, appointment_time__lt=twenty_four_hours_ago_utc)
                     | Q(status__in=["待预约试播", "待预约训练"], interview_decision_time__lt=seven_days_ago_utc)
                     | Q(status=RecruitStatus.PENDING_TRAINING, scheduled_training_time__lt=twenty_four_hours_ago_utc)
                     | Q(status=RecruitStatus.PENDING_BROADCAST_SCHEDULE, training_decision_time__lt=seven_days_ago_utc)
                     | Q(status=RecruitStatus.PENDING_BROADCAST, scheduled_broadcast_time__lt=twenty_four_hours_ago_utc)
                     | Q(status__in=["试播招募中", "训练征召中"], training_time__lt=twenty_four_hours_ago_utc))

    return Recruit.objects.filter(overdue_query)


def _group_recruits(recruits, exclude_overdue=False):
    """将招募记录按状态和时间条件分组"""
    from utils.timezone_helper import get_current_utc_time

    current_local = utc_to_local(get_current_utc_time())
    twenty_four_hours_ago_local = current_local - timedelta(hours=24)
    twenty_four_hours_ago_utc = local_to_utc(twenty_four_hours_ago_local)
    seven_days_ago_local = current_local - timedelta(days=7)
    seven_days_ago_utc = local_to_utc(seven_days_ago_local)

    groups = {
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

        is_overdue = False

        if effective_status == RecruitStatus.PENDING_INTERVIEW:
            if recruit.appointment_time and recruit.appointment_time < twenty_four_hours_ago_utc:
                is_overdue = True
            else:
                groups['pending_interview'].append(recruit)
        elif effective_status == RecruitStatus.PENDING_TRAINING_SCHEDULE:
            interview_time = recruit.get_effective_interview_decision_time()
            if interview_time and interview_time < seven_days_ago_utc:
                is_overdue = True
            else:
                groups['pending_training_schedule'].append(recruit)
        elif effective_status == RecruitStatus.PENDING_TRAINING:
            scheduled_time = recruit.get_effective_scheduled_training_time()
            if scheduled_time and scheduled_time < twenty_four_hours_ago_utc:
                is_overdue = True
            else:
                groups['pending_training'].append(recruit)
        elif effective_status == RecruitStatus.PENDING_BROADCAST_SCHEDULE:
            training_time = recruit.get_effective_training_decision_time()
            if training_time and training_time < seven_days_ago_utc:
                is_overdue = True
            else:
                groups['pending_broadcast_schedule'].append(recruit)
        elif effective_status == RecruitStatus.PENDING_BROADCAST:
            scheduled_time = recruit.get_effective_scheduled_broadcast_time()
            if scheduled_time and scheduled_time < twenty_four_hours_ago_utc:
                is_overdue = True
            else:
                groups['pending_broadcast'].append(recruit)
        elif effective_status == RecruitStatus.ENDED:
            groups['ended'].append(recruit)

        if is_overdue and not exclude_overdue:
            groups['overdue'].append(recruit)

    _sort_group(groups['pending_interview'], 'appointment_time', ascending=True)
    _sort_group(groups['pending_training_schedule'], 'interview_decision_time', ascending=False)
    _sort_group(groups['pending_training'], 'scheduled_training_time', ascending=True)
    _sort_group(groups['pending_broadcast_schedule'], 'training_decision_time', ascending=False)
    _sort_group(groups['pending_broadcast'], 'scheduled_broadcast_time', ascending=True)
    _sort_group(groups['overdue'], 'status', ascending=True, secondary_field='updated_at', secondary_ascending=False)
    _sort_group(groups['ended'], 'updated_at', ascending=False)

    groups['overdue'] = groups['overdue'][:100]
    groups['ended'] = groups['ended'][:100]

    return groups


def _sort_group(group, field, ascending=True, secondary_field=None, secondary_ascending=True):
    """对分组进行排序"""
    if not group:
        return

    def get_sort_key(recruit):
        import enum as _enum

        def _normalize_value(value, is_time_hint=False):
            """将值转换为可比较的简单类型。
            - Enum → 其 value（字符串）
            - datetime → datetime 本身（可比较）
            - None → 根据是否时间字段给默认极小值
            - 其他 → 原值
            """
            if isinstance(value, _enum.Enum):
                return value.value
            if hasattr(value, 'timestamp') and hasattr(value, 'year'):
                return value
            if value is None:
                return datetime.min if is_time_hint else ''
            return value

        primary_value = getattr(recruit, field, None)
        if primary_value is None:
            if field == 'appointment_time':
                primary_value = recruit.appointment_time
            elif field == 'interview_decision_time':
                primary_value = recruit.get_effective_interview_decision_time()
            elif field == 'scheduled_training_time':
                primary_value = recruit.get_effective_scheduled_training_time()
            elif field == 'training_decision_time':
                primary_value = recruit.get_effective_training_decision_time()
            elif field == 'scheduled_broadcast_time':
                primary_value = recruit.get_effective_scheduled_broadcast_time()
            elif field == 'updated_at':
                primary_value = recruit.updated_at

        primary_is_time = field.endswith('_time') or field in ('updated_at', 'appointment_time')
        primary_key = _normalize_value(primary_value, is_time_hint=primary_is_time)

        if secondary_field:
            secondary_value = getattr(recruit, secondary_field, None)
            if secondary_value is None:
                secondary_value = recruit.updated_at

            secondary_is_time = secondary_field.endswith('_time') or secondary_field in ('updated_at', 'appointment_time')
            secondary_key = _normalize_value(secondary_value, is_time_hint=secondary_is_time)

            if not secondary_ascending:
                if hasattr(secondary_key, 'timestamp') and hasattr(secondary_key, 'year'):
                    secondary_key = -secondary_key.timestamp()
                elif isinstance(secondary_key, (int, float)):
                    secondary_key = -secondary_key

            return (primary_key, secondary_key)
        else:
            return primary_key

    reverse = not ascending
    if secondary_field:
        group.sort(key=get_sort_key, reverse=reverse)
    else:
        group.sort(key=get_sort_key, reverse=reverse)


@recruit_bp.route('/')
@roles_accepted('gicho', 'kancho')
def list_recruits():
    """招募列表页面"""
    filters = persist_and_restore_filters(
        'recruits_list',
        allowed_keys=['status'],
        default_filters={'status': '进行中'},
    )
    status_filter = filters.get('status') or '进行中'

    query = Recruit.objects

    if status_filter in ['进行中', '鸽']:
        query = query.filter(status__ne=RecruitStatus.ENDED)
    elif status_filter == '已结束':
        query = query.filter(status=RecruitStatus.ENDED)
    else:
        try:
            status_enum = RecruitStatus(status_filter)
            query = query.filter(status=status_enum)
        except ValueError:
            pass

    all_recruits = list(query)

    grouped_recruits = _group_recruits(all_recruits)

    final_groups = {}
    if status_filter == '进行中':
        final_groups = {k: v for k, v in grouped_recruits.items() if k not in ['overdue', 'ended'] and v}
    elif status_filter == '鸽':
        if grouped_recruits.get('overdue'):
            final_groups['overdue'] = grouped_recruits['overdue']
    elif status_filter == '已结束':
        if grouped_recruits.get('ended'):
            final_groups['ended'] = grouped_recruits['ended']
    else:
        final_groups = {k: v for k, v in grouped_recruits.items() if v}

    status_choices = [
        ('进行中', '进行中'),
        ('鸽', '鸽'),
        ('已结束', '已结束'),
    ]

    from utils.timezone_helper import get_current_utc_time
    current_utc = get_current_utc_time()

    logger.debug('招募列表查询：状态=%s，结果数量=%d', status_filter, len(all_recruits))

    return render_template('recruits/list.html',
                           grouped_recruits=final_groups,
                           current_status=status_filter,
                           status_choices=status_choices,
                           current_utc=current_utc)


@recruit_bp.route('/<recruit_id>')
@roles_accepted('gicho', 'kancho')
def detail_recruit(recruit_id):
    """招募详情页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    logger.debug('查看招募详情：ID=%s，主播=%s', recruit_id, recruit.pilot.nickname)

    return render_template('recruits/detail.html', recruit=recruit)


@recruit_bp.route('/start/<pilot_id>')
@roles_accepted('gicho', 'kancho')
def start_recruit(pilot_id):
    """启动招募页面"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)
    except DoesNotExist:
        abort(404)

    if pilot.status != Status.NOT_RECRUITED:
        flash('只有未招募状态的主播才能启动招募', 'error')
        return redirect(url_for('pilot.pilot_detail', pilot_id=pilot_id))

    existing_recruit = Recruit.objects.filter(pilot=pilot, status__in=['进行中', '鸽']).first()
    if existing_recruit:
        flash('该主播已有正在进行的招募', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=existing_recruit.id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    recruiter_choices = _get_recruiter_choices()
    channel_choices = [(c.value, c.value) for c in RecruitChannel]

    return render_template('recruits/start.html',
                           pilot=pilot,
                           recruiter_choices=recruiter_choices,
                           channel_choices=channel_choices,
                           default_appointment_time=Recruit.get_default_appointment_time())


@recruit_bp.route('/start/<pilot_id>', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def create_recruit(pilot_id):
    """创建招募"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)
    except DoesNotExist:
        abort(404)

    if pilot.status != Status.NOT_RECRUITED:
        flash('只有未招募状态的主播才能启动招募', 'error')
        return redirect(url_for('pilot.pilot_detail', pilot_id=pilot_id))

    existing_recruit = Recruit.objects.filter(pilot=pilot, status__in=['进行中', '鸽']).first()
    if existing_recruit:
        flash('该主播已有正在进行的招募', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=existing_recruit.id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    try:
        recruiter_id = request.form.get('recruiter')
        appointment_time_str = request.form.get('appointment_time')
        channel = request.form.get('channel')
        introduction_fee = request.form.get('introduction_fee', '0')
        remarks = request.form.get('remarks', '')

        if not recruiter_id:
            flash('请选择招募负责人', 'error')
            return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))

        if not appointment_time_str:
            flash('请选择预约时间', 'error')
            return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))

        if not channel:
            flash('请选择招募渠道', 'error')
            return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))

        try:
            recruiter = User.objects.get(id=recruiter_id)
            if not (recruiter.has_role('kancho') or recruiter.has_role('gicho')):
                flash('招募负责人必须是运营或管理员', 'error')
                return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))
        except DoesNotExist:
            flash('无效的招募负责人', 'error')
            return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))

        appointment_time_local = datetime.fromisoformat(appointment_time_str.replace('T', ' '))
        appointment_time_utc = local_to_utc(appointment_time_local)

        try:
            channel_enum = RecruitChannel(channel)
        except ValueError:
            flash('无效的招募渠道', 'error')
            return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))

        try:
            introduction_fee_decimal = Decimal(introduction_fee).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                flash('介绍费不能为负数', 'error')
                return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))
        except (ValueError, InvalidOperation):
            flash('介绍费格式不正确', 'error')
            return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))

        recruit = Recruit(pilot=pilot,
                          recruiter=recruiter,
                          appointment_time=appointment_time_utc,
                          channel=channel_enum,
                          introduction_fee=introduction_fee_decimal,
                          remarks=remarks,
                          status=RecruitStatus.PENDING_INTERVIEW)

        recruit.save()

        logger.info('启动招募：主播=%s，负责人=%s，预约时间=%s', pilot.nickname, recruiter.nickname or recruiter.username, appointment_time_utc)

        flash('招募已成功启动', 'success')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit.id))

    except ValidationError as e:
        logger.error('创建招募验证失败：%s', str(e))
        flash('数据验证失败，请检查输入', 'error')
        return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))
    except Exception as e:
        logger.error('创建招募失败：%s', str(e))
        flash('创建招募失败，请重试', 'error')
        return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))


@recruit_bp.route('/<recruit_id>/edit')
@roles_accepted('gicho', 'kancho')
def edit_recruit(recruit_id):
    """编辑征召页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    recruiter_choices = _get_recruiter_choices()
    channel_choices = [(c.value, c.value) for c in RecruitChannel]

    return render_template('recruits/edit.html', recruit=recruit, recruiter_choices=recruiter_choices, channel_choices=channel_choices)


@recruit_bp.route('/<recruit_id>/edit', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def update_recruit(recruit_id):
    """更新征召"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    old_data = {
        'pilot': str(recruit.pilot.id) if recruit.pilot else None,
        'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
        'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
        'channel': recruit.channel.value if recruit.channel else None,
        'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
        'remarks': recruit.remarks,
        'status': recruit.status.value if recruit.status else None,
        'training_time': recruit.training_time.isoformat() if recruit.training_time else None,
        'scheduled_training_time': recruit.scheduled_training_time.isoformat() if recruit.scheduled_training_time else None,
        'scheduled_broadcast_time': recruit.scheduled_broadcast_time.isoformat() if recruit.scheduled_broadcast_time else None,
    }

    try:
        recruiter_id = request.form.get('recruiter')
        appointment_time_str = request.form.get('appointment_time')
        channel = request.form.get('channel')
        introduction_fee = request.form.get('introduction_fee', '0')
        remarks = request.form.get('remarks', '')
        training_time_str = request.form.get('training_time')
        scheduled_training_time_str = request.form.get('scheduled_training_time')
        scheduled_broadcast_time_str = request.form.get('scheduled_broadcast_time')

        if not recruiter_id:
            flash('请选择征召负责人', 'error')
            return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))

        if not appointment_time_str:
            flash('请选择预约时间', 'error')
            return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))

        if not channel:
            flash('请选择征召渠道', 'error')
            return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))

        try:
            recruiter = User.objects.get(id=recruiter_id)
            if not (recruiter.has_role('kancho') or recruiter.has_role('gicho')):
                flash('招募负责人必须是运营或管理员', 'error')
                return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))
        except DoesNotExist:
            flash('无效的征召负责人', 'error')
            return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))

        appointment_time_local = datetime.fromisoformat(appointment_time_str.replace('T', ' '))
        appointment_time_utc = local_to_utc(appointment_time_local)

        try:
            channel_enum = RecruitChannel(channel)
        except ValueError:
            flash('无效的征召渠道', 'error')
            return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))

        try:
            introduction_fee_decimal = Decimal(introduction_fee).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                flash('介绍费不能为负数', 'error')
                return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))
        except (ValueError, InvalidOperation):
            flash('介绍费格式不正确', 'error')
            return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))

        if recruit.status == RecruitStatus.TRAINING_RECRUITING:
            if training_time_str:
                try:
                    training_time_local = datetime.fromisoformat(training_time_str.replace('T', ' '))
                    training_time_utc = local_to_utc(training_time_local)
                except ValueError:
                    flash('训练时间格式不正确', 'error')
                    return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))
            else:
                training_time_utc = None
        else:
            training_time_utc = recruit.training_time  # 保持原值，不在非训练征召中状态下编辑

        effective_status = recruit.get_effective_status()
        scheduled_training_time_utc = recruit.scheduled_training_time
        scheduled_broadcast_time_utc = recruit.scheduled_broadcast_time

        if effective_status in [RecruitStatus.PENDING_TRAINING, RecruitStatus.PENDING_BROADCAST_SCHEDULE, RecruitStatus.PENDING_BROADCAST]:
            if scheduled_training_time_str:
                try:
                    _local = datetime.fromisoformat(scheduled_training_time_str.replace('T', ' '))
                    scheduled_training_time_utc = local_to_utc(_local)
                except ValueError:
                    flash('预约训练时间格式不正确', 'error')
                    return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))
            elif scheduled_training_time_str == '':
                scheduled_training_time_utc = None

        if effective_status in [RecruitStatus.PENDING_BROADCAST]:
            if scheduled_broadcast_time_str:
                try:
                    _local_b = datetime.fromisoformat(scheduled_broadcast_time_str.replace('T', ' '))
                    scheduled_broadcast_time_utc = local_to_utc(_local_b)
                except ValueError:
                    flash('预约开播时间格式不正确', 'error')
                    return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))
            elif scheduled_broadcast_time_str == '':
                scheduled_broadcast_time_utc = None

        recruit.recruiter = recruiter
        recruit.appointment_time = appointment_time_utc
        recruit.channel = channel_enum
        recruit.introduction_fee = introduction_fee_decimal
        recruit.remarks = remarks
        if recruit.status == RecruitStatus.TRAINING_RECRUITING:
            recruit.training_time = training_time_utc
        if effective_status in [RecruitStatus.PENDING_TRAINING, RecruitStatus.PENDING_BROADCAST_SCHEDULE, RecruitStatus.PENDING_BROADCAST]:
            recruit.scheduled_training_time = scheduled_training_time_utc
        if effective_status in [RecruitStatus.PENDING_BROADCAST]:
            recruit.scheduled_broadcast_time = scheduled_broadcast_time_utc

        recruit.save()

        _record_changes(recruit, old_data, current_user, _get_client_ip())

        logger.info('更新征召：ID=%s，机师=%s', recruit_id, recruit.pilot.nickname)

        flash('征召信息已更新', 'success')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    except ValidationError as e:
        logger.error('更新征召验证失败：%s', str(e))
        flash('数据验证失败，请检查输入', 'error')
        return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))
    except Exception as e:
        logger.error('更新征召失败：%s', str(e))
        flash('更新征召失败，请重试', 'error')
        return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))


@recruit_bp.route('/<recruit_id>/interview')
@roles_accepted('gicho', 'kancho')
def interview_decision_page(recruit_id):
    """面试决策页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_INTERVIEW:
        flash('只能对待面试状态的招募执行面试决策', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    active_decisions = [d for d in InterviewDecision if not d.name.endswith('_OLD')]
    interview_decision_choices = [(d.value, d.value) for d in active_decisions]

    current_year = datetime.now().year

    return render_template('recruits/interview.html', recruit=recruit, interview_decision_choices=interview_decision_choices, current_year=current_year)


@recruit_bp.route('/<recruit_id>/interview', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def interview_decision(recruit_id):
    """执行面试决策"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_INTERVIEW:
        flash('只能对待面试状态的征召执行面试决策', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    try:
        interview_decision_value = request.form.get('interview_decision')
        introduction_fee = request.form.get('introduction_fee', '0')
        remarks = request.form.get('remarks', '')

        real_name = request.form.get('real_name', '').strip()
        birth_year_str = request.form.get('birth_year', '')

        if not interview_decision_value:
            flash('请选择面试决策', 'error')
            return redirect(url_for('recruit.interview_decision_page', recruit_id=recruit_id))

        try:
            interview_decision_enum = InterviewDecision(interview_decision_value)
        except ValueError:
            flash('无效的面试决策', 'error')
            return redirect(url_for('recruit.interview_decision_page', recruit_id=recruit_id))

        if interview_decision_enum == InterviewDecision.SCHEDULE_TRAINING:
            if not real_name:
                flash('预约试播时必须填写真实姓名', 'error')
                return redirect(url_for('recruit.interview_decision_page', recruit_id=recruit_id))

            if not birth_year_str:
                flash('预约试播时必须填写出生年', 'error')
                return redirect(url_for('recruit.interview_decision_page', recruit_id=recruit_id))

            try:
                birth_year = int(birth_year_str)
                current_year = datetime.now().year
                if birth_year < current_year - 60 or birth_year > current_year - 10:
                    flash('出生年必须在距今60年前到距今10年前之间', 'error')
                    return redirect(url_for('recruit.interview_decision_page', recruit_id=recruit_id))
            except ValueError:
                flash('出生年格式不正确', 'error')
                return redirect(url_for('recruit.interview_decision_page', recruit_id=recruit_id))

        try:
            introduction_fee_decimal = Decimal(introduction_fee).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                flash('介绍费不能为负数', 'error')
                return redirect(url_for('recruit.interview_decision_page', recruit_id=recruit_id))
        except (ValueError, InvalidOperation):
            flash('介绍费格式不正确', 'error')
            return redirect(url_for('recruit.interview_decision_page', recruit_id=recruit_id))

        old_recruit_data = {
            'pilot': str(recruit.pilot.id) if recruit.pilot else None,
            'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
            'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
            'channel': recruit.channel.value if hasattr(recruit.channel, 'value') else recruit.channel,
            'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
            'remarks': recruit.remarks,
            'status': recruit.status.value if hasattr(recruit.status, 'value') else recruit.status,
        }

        old_pilot_data = {
            'nickname': recruit.pilot.nickname,
            'real_name': recruit.pilot.real_name,
            'gender': recruit.pilot.gender.value if hasattr(recruit.pilot.gender, 'value') else recruit.pilot.gender,
            'birth_year': recruit.pilot.birth_year,
            'owner': str(recruit.pilot.owner.id) if recruit.pilot.owner else None,
            'platform': recruit.pilot.platform.value if hasattr(recruit.pilot.platform, 'value') else recruit.pilot.platform,
            'work_mode': recruit.pilot.work_mode.value if hasattr(recruit.pilot.work_mode, 'value') else recruit.pilot.work_mode,
            'rank': recruit.pilot.rank.value if hasattr(recruit.pilot.rank, 'value') else recruit.pilot.rank,
            'status': recruit.pilot.status.value if hasattr(recruit.pilot.status, 'value') else recruit.pilot.status,
        }

        from utils.timezone_helper import get_current_utc_time

        recruit.interview_decision = interview_decision_enum
        recruit.interview_decision_maker = current_user
        recruit.interview_decision_time = get_current_utc_time()
        recruit.introduction_fee = introduction_fee_decimal
        recruit.remarks = remarks

        if interview_decision_enum == InterviewDecision.SCHEDULE_TRAINING:
            recruit.status = RecruitStatus.PENDING_TRAINING_SCHEDULE

            recruit.pilot.real_name = real_name
            recruit.pilot.birth_year = birth_year
            recruit.pilot.rank = Rank.TRAINEE
            recruit.pilot.status = Status.RECRUITED
            recruit.pilot.save()
        else:
            recruit.status = RecruitStatus.ENDED

            recruit.pilot.status = Status.NOT_RECRUITING
            recruit.pilot.save()

        recruit.save()

        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        from routes.pilot import _record_changes as record_pilot_changes
        record_pilot_changes(recruit.pilot, old_pilot_data, current_user, _get_client_ip())

        if interview_decision_enum == InterviewDecision.SCHEDULE_TRAINING:
            logger.info('面试决策成功：ID=%s，主播=%s，预约试播', recruit_id, recruit.pilot.nickname)
            flash('面试决策成功，主播已进入待预约试播阶段', 'success')
        else:
            logger.info('面试决策完成：ID=%s，主播=%s，不招募', recruit_id, recruit.pilot.nickname)
            flash('面试决策完成，已决定不招募该主播', 'success')

        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit.id))

    except ValidationError as e:
        logger.error('面试决策验证失败：%s', str(e))
        flash('数据验证失败，请检查输入', 'error')
        return redirect(url_for('recruit.interview_decision_page', recruit_id=recruit_id))
    except Exception as e:
        logger.error('面试决策失败：%s', str(e))
        flash('面试决策失败，请重试', 'error')
        return redirect(url_for('recruit.interview_decision_page', recruit_id=recruit_id))


@recruit_bp.route('/<recruit_id>/confirm')
@roles_accepted('gicho', 'kancho')
def confirm_recruit_page(recruit_id):
    """确认征召页面（废弃，保留用于历史兼容）"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_INTERVIEW:
        flash('只能对待面试状态的征召执行确认征召', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    return render_template('recruits/confirm.html', recruit=recruit)


@recruit_bp.route('/<recruit_id>/schedule-training')
@roles_accepted('gicho', 'kancho')
def schedule_training_page(recruit_id):
    """预约试播页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_TRAINING_SCHEDULE:
        flash('只能对待预约试播状态的招募执行预约试播', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    from models.pilot import WorkMode
    work_mode_choices = [(w.value, w.value) for w in WorkMode if w != WorkMode.UNKNOWN]

    now_utc = datetime.utcnow()
    now_gmt8 = utc_to_local(now_utc)

    current_minute = now_gmt8.minute
    if current_minute < 30:
        default_time_gmt8 = now_gmt8.replace(minute=30, second=0, microsecond=0)
    else:
        default_time_gmt8 = now_gmt8.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    default_time_str = default_time_gmt8.strftime('%Y-%m-%dT%H:%M')

    return render_template('recruits/schedule_training.html', recruit=recruit, work_mode_choices=work_mode_choices, default_time=default_time_str)


@recruit_bp.route('/<recruit_id>/schedule-training', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def schedule_training(recruit_id):
    """执行预约试播"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_TRAINING_SCHEDULE:
        flash('只能对待预约试播状态的招募执行预约试播', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    try:
        scheduled_training_time_str = request.form.get('scheduled_training_time')
        work_mode = request.form.get('work_mode', '')
        introduction_fee = request.form.get('introduction_fee', '0')
        remarks = request.form.get('remarks', '')

        if not scheduled_training_time_str:
            flash('请选择预约试播时间', 'error')
            return redirect(url_for('recruit.schedule_training_page', recruit_id=recruit_id))

        if not work_mode:
            flash('请选择开播方式', 'error')
            return redirect(url_for('recruit.schedule_training_page', recruit_id=recruit_id))

        try:
            scheduled_training_time_local = datetime.fromisoformat(scheduled_training_time_str.replace('T', ' '))
            scheduled_training_time_utc = local_to_utc(scheduled_training_time_local)
        except ValueError:
            flash('预约试播时间格式不正确', 'error')
            return redirect(url_for('recruit.schedule_training_page', recruit_id=recruit_id))

        try:
            from models.pilot import WorkMode
            WorkMode(work_mode)  # 验证开播方式值是否有效
        except ValueError:
            flash('无效的开播方式选择', 'error')
            return redirect(url_for('recruit.schedule_training_page', recruit_id=recruit_id))

        try:
            introduction_fee_decimal = Decimal(introduction_fee).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                flash('介绍费不能为负数', 'error')
                return redirect(url_for('recruit.schedule_training_page', recruit_id=recruit_id))
        except (ValueError, InvalidOperation):
            flash('介绍费格式不正确', 'error')
            return redirect(url_for('recruit.schedule_training_page', recruit_id=recruit_id))

        old_recruit_data = {
            'pilot': str(recruit.pilot.id) if recruit.pilot else None,
            'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
            'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
            'channel': recruit.channel.value if hasattr(recruit.channel, 'value') else recruit.channel,
            'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
            'remarks': recruit.remarks,
            'status': recruit.status.value if hasattr(recruit.status, 'value') else recruit.status,
        }

        old_pilot_data = {
            'nickname': recruit.pilot.nickname,
            'real_name': recruit.pilot.real_name,
            'gender': recruit.pilot.gender.value if hasattr(recruit.pilot.gender, 'value') else recruit.pilot.gender,
            'birth_year': recruit.pilot.birth_year,
            'owner': str(recruit.pilot.owner.id) if recruit.pilot.owner else None,
            'platform': recruit.pilot.platform.value if hasattr(recruit.pilot.platform, 'value') else recruit.pilot.platform,
            'work_mode': recruit.pilot.work_mode.value if hasattr(recruit.pilot.work_mode, 'value') else recruit.pilot.work_mode,
            'rank': recruit.pilot.rank.value if hasattr(recruit.pilot.rank, 'value') else recruit.pilot.rank,
            'status': recruit.pilot.status.value if hasattr(recruit.pilot.status, 'value') else recruit.pilot.status,
        }

        from utils.timezone_helper import get_current_utc_time

        recruit.scheduled_training_time = scheduled_training_time_utc
        recruit.scheduled_training_decision_maker = current_user
        recruit.scheduled_training_decision_time = get_current_utc_time()
        recruit.introduction_fee = introduction_fee_decimal
        recruit.remarks = remarks

        recruit.status = RecruitStatus.PENDING_TRAINING

        recruit.pilot.work_mode = WorkMode(work_mode)
        recruit.pilot.save()

        recruit.save()

        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        from routes.pilot import _record_changes as record_pilot_changes
        record_pilot_changes(recruit.pilot, old_pilot_data, current_user, _get_client_ip())

        logger.info('预约试播成功：ID=%s，主播=%s，试播时间=%s', recruit_id, recruit.pilot.nickname, scheduled_training_time_utc)
        flash('预约试播成功，主播已进入待试播阶段', 'success')

        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    except ValidationError as e:
        logger.error('预约试播验证失败：%s', str(e))
        flash('数据验证失败，请检查输入', 'error')
        return redirect(url_for('recruit.schedule_training_page', recruit_id=recruit_id))
    except Exception as e:
        logger.error('预约试播失败：%s', str(e))
        flash('预约试播失败，请重试', 'error')
        return redirect(url_for('recruit.schedule_training_page', recruit_id=recruit_id))


@recruit_bp.route('/<recruit_id>/training-decision')
@roles_accepted('gicho', 'kancho')
def training_decision_page(recruit_id):
    """试播决策页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_TRAINING:
        flash('只能对待试播状态的招募执行试播决策', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    active_decisions = [d for d in TrainingDecision if not d.name.endswith('_OLD')]
    training_decision_choices = [(d.value, d.value) for d in active_decisions]

    return render_template('recruits/training_decision.html', recruit=recruit, training_decision_choices=training_decision_choices)


@recruit_bp.route('/<recruit_id>/training-decision', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def training_decision(recruit_id):
    """执行试播决策"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_TRAINING:
        flash('只能对待试播状态的招募执行试播决策', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    try:
        training_decision_value = request.form.get('training_decision')
        introduction_fee = request.form.get('introduction_fee', '0')
        remarks = request.form.get('remarks', '')

        if not training_decision_value:
            flash('请选择试播决策', 'error')
            return redirect(url_for('recruit.training_decision_page', recruit_id=recruit_id))

        try:
            training_decision_enum = TrainingDecision(training_decision_value)
        except ValueError:
            flash('无效的试播决策', 'error')
            return redirect(url_for('recruit.training_decision_page', recruit_id=recruit_id))

        try:
            introduction_fee_decimal = Decimal(introduction_fee).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                flash('介绍费不能为负数', 'error')
                return redirect(url_for('recruit.training_decision_page', recruit_id=recruit_id))
        except (ValueError, InvalidOperation):
            flash('介绍费格式不正确', 'error')
            return redirect(url_for('recruit.training_decision_page', recruit_id=recruit_id))

        old_recruit_data = {
            'pilot': str(recruit.pilot.id) if recruit.pilot else None,
            'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
            'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
            'channel': recruit.channel.value if recruit.channel else None,
            'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
            'remarks': recruit.remarks,
            'status': recruit.status.value if recruit.status else None,
        }

        old_pilot_data = {
            'nickname': recruit.pilot.nickname,
            'real_name': recruit.pilot.real_name,
            'gender': recruit.pilot.gender.value if recruit.pilot.gender else None,
            'birth_year': recruit.pilot.birth_year,
            'owner': str(recruit.pilot.owner.id) if recruit.pilot.owner else None,
            'platform': recruit.pilot.platform.value if recruit.pilot.platform else None,
            'work_mode': recruit.pilot.work_mode.value if recruit.pilot.work_mode else None,
            'rank': recruit.pilot.rank.value if recruit.pilot.rank else None,
            'status': recruit.pilot.status.value if recruit.pilot.status else None,
        }

        from utils.timezone_helper import get_current_utc_time

        recruit.training_decision = training_decision_enum
        recruit.training_decision_maker = current_user
        recruit.training_decision_time = get_current_utc_time()
        recruit.introduction_fee = introduction_fee_decimal
        recruit.remarks = remarks

        if training_decision_enum == TrainingDecision.SCHEDULE_BROADCAST:
            recruit.status = RecruitStatus.PENDING_BROADCAST_SCHEDULE
        else:
            recruit.status = RecruitStatus.ENDED

            recruit.pilot.status = Status.NOT_RECRUITING
            recruit.pilot.save()

        recruit.save()

        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        if training_decision_enum == TrainingDecision.NOT_RECRUIT:
            from routes.pilot import _record_changes as record_pilot_changes
            record_pilot_changes(recruit.pilot, old_pilot_data, current_user, _get_client_ip())

        if training_decision_enum == TrainingDecision.SCHEDULE_BROADCAST:
            logger.info('试播决策成功：ID=%s，主播=%s，预约开播', recruit_id, recruit.pilot.nickname)
            flash('试播决策成功，主播已进入待预约开播阶段', 'success')
        else:
            logger.info('试播决策完成：ID=%s，主播=%s，不招募', recruit_id, recruit.pilot.nickname)
            flash('试播决策完成，已决定不招募该主播', 'success')

        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    except ValidationError as e:
        logger.error('试播决策验证失败：%s', str(e))
        flash('数据验证失败，请检查输入', 'error')
        return redirect(url_for('recruit.training_decision_page', recruit_id=recruit_id))
    except Exception as e:
        logger.error('试播决策失败：%s', str(e))
        flash('试播决策失败，请重试', 'error')
        return redirect(url_for('recruit.training_decision_page', recruit_id=recruit_id))


@recruit_bp.route('/<recruit_id>/schedule-broadcast')
@roles_accepted('gicho', 'kancho')
def schedule_broadcast_page(recruit_id):
    """预约开播页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_BROADCAST_SCHEDULE:
        flash('只能对待预约开播状态的征召执行预约开播', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    now_utc = datetime.utcnow()
    now_gmt8 = utc_to_local(now_utc)

    current_minute = now_gmt8.minute
    if current_minute < 30:
        default_time_gmt8 = now_gmt8.replace(minute=30, second=0, microsecond=0)
    else:
        default_time_gmt8 = now_gmt8.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    default_time_str = default_time_gmt8.strftime('%Y-%m-%dT%H:%M')

    return render_template('recruits/schedule_broadcast.html', recruit=recruit, default_time=default_time_str)


@recruit_bp.route('/<recruit_id>/schedule-broadcast', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def schedule_broadcast(recruit_id):
    """执行预约开播"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_BROADCAST_SCHEDULE:
        flash('只能对待预约开播状态的征召执行预约开播', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    try:
        scheduled_broadcast_time_str = request.form.get('scheduled_broadcast_time')
        introduction_fee = request.form.get('introduction_fee', '0')
        remarks = request.form.get('remarks', '')

        if not scheduled_broadcast_time_str:
            flash('请选择预约开播时间', 'error')
            return redirect(url_for('recruit.schedule_broadcast_page', recruit_id=recruit_id))

        try:
            scheduled_broadcast_time_local = datetime.fromisoformat(scheduled_broadcast_time_str.replace('T', ' '))
            scheduled_broadcast_time_utc = local_to_utc(scheduled_broadcast_time_local)
        except ValueError:
            flash('预约开播时间格式不正确', 'error')
            return redirect(url_for('recruit.schedule_broadcast_page', recruit_id=recruit_id))

        try:
            introduction_fee_decimal = Decimal(introduction_fee).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                flash('介绍费不能为负数', 'error')
                return redirect(url_for('recruit.schedule_broadcast_page', recruit_id=recruit_id))
        except (ValueError, InvalidOperation):
            flash('介绍费格式不正确', 'error')
            return redirect(url_for('recruit.schedule_broadcast_page', recruit_id=recruit_id))

        old_recruit_data = {
            'pilot': str(recruit.pilot.id) if recruit.pilot else None,
            'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
            'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
            'channel': recruit.channel.value if recruit.channel else None,
            'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
            'remarks': recruit.remarks,
            'status': recruit.status.value if recruit.status else None,
        }

        from utils.timezone_helper import get_current_utc_time

        recruit.scheduled_broadcast_time = scheduled_broadcast_time_utc
        recruit.scheduled_broadcast_decision_maker = current_user
        recruit.scheduled_broadcast_decision_time = get_current_utc_time()
        recruit.introduction_fee = introduction_fee_decimal
        recruit.remarks = remarks

        recruit.status = RecruitStatus.PENDING_BROADCAST

        recruit.save()

        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        logger.info('预约开播成功：ID=%s，机师=%s，开播时间=%s', recruit_id, recruit.pilot.nickname, scheduled_broadcast_time_utc)
        flash('预约开播成功，机师已进入待开播阶段', 'success')

        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    except ValidationError as e:
        logger.error('预约开播验证失败：%s', str(e))
        flash('数据验证失败，请检查输入', 'error')
        return redirect(url_for('recruit.schedule_broadcast_page', recruit_id=recruit_id))
    except Exception as e:
        logger.error('预约开播失败：%s', str(e))
        flash('预约开播失败，请重试', 'error')
        return redirect(url_for('recruit.schedule_broadcast_page', recruit_id=recruit_id))


@recruit_bp.route('/<recruit_id>/broadcast-decision')
@roles_accepted('gicho', 'kancho')
def broadcast_decision_page(recruit_id):
    """开播决策页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_BROADCAST:
        flash('只能对待开播状态的招募执行开播决策', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    active_decisions = {d for d in BroadcastDecision if not d.name.endswith('_OLD')}

    broadcast_decision_choices = sorted(
        [(d.value, d.value) for d in active_decisions],
        key=lambda x: [BroadcastDecision.OFFICIAL.value, BroadcastDecision.INTERN.value, BroadcastDecision.NOT_RECRUIT.value].index(x[0]))

    owner_choices = _get_recruiter_choices()

    from models.pilot import Platform
    platform_choices = [(p.value, p.value) for p in Platform]

    return render_template('recruits/broadcast_decision.html',
                           recruit=recruit,
                           broadcast_decision_choices=broadcast_decision_choices,
                           owner_choices=owner_choices,
                           platform_choices=platform_choices)


@recruit_bp.route('/<recruit_id>/broadcast-decision', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def broadcast_decision(recruit_id):
    """执行开播决策"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    effective_status = recruit.get_effective_status()
    if effective_status != RecruitStatus.PENDING_BROADCAST:
        flash('只能对待开播状态的招募执行开播决策', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    try:
        broadcast_decision_value = request.form.get('broadcast_decision')
        introduction_fee = request.form.get('introduction_fee', '0')
        remarks = request.form.get('remarks', '')

        owner = request.form.get('owner', '')
        platform = request.form.get('platform', '')

        if not broadcast_decision_value:
            flash('请选择开播决策', 'error')
            return redirect(url_for('recruit.broadcast_decision_page', recruit_id=recruit_id))

        try:
            broadcast_decision_enum = BroadcastDecision(broadcast_decision_value)
        except ValueError:
            flash('无效的开播决策', 'error')
            return redirect(url_for('recruit.broadcast_decision_page', recruit_id=recruit_id))

        if broadcast_decision_enum in [BroadcastDecision.OFFICIAL, BroadcastDecision.INTERN]:
            if not owner:
                flash('招募成功时必须选择所属', 'error')
                return redirect(url_for('recruit.broadcast_decision_page', recruit_id=recruit_id))

            if not platform:
                flash('招募成功时必须选择开播平台', 'error')
                return redirect(url_for('recruit.broadcast_decision_page', recruit_id=recruit_id))

            try:
                from models.pilot import Platform
                Platform(platform)  # 验证开播平台值是否有效
            except ValueError:
                flash('无效的开播平台选择', 'error')
                return redirect(url_for('recruit.broadcast_decision_page', recruit_id=recruit_id))

            try:
                owner_user = User.objects.get(id=owner)
                if not (owner_user.has_role('kancho') or owner_user.has_role('gicho')):
                    flash('直属运营必须是运营或管理员', 'error')
                    return redirect(url_for('recruit.broadcast_decision_page', recruit_id=recruit_id))
            except DoesNotExist:
                flash('无效的所属选择', 'error')
                return redirect(url_for('recruit.broadcast_decision_page', recruit_id=recruit_id))

        try:
            introduction_fee_decimal = Decimal(introduction_fee).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                flash('介绍费不能为负数', 'error')
                return redirect(url_for('recruit.broadcast_decision_page', recruit_id=recruit_id))
        except (ValueError, InvalidOperation):
            flash('介绍费格式不正确', 'error')
            return redirect(url_for('recruit.broadcast_decision_page', recruit_id=recruit_id))

        old_recruit_data = {
            'pilot': str(recruit.pilot.id) if recruit.pilot else None,
            'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
            'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
            'channel': recruit.channel.value if recruit.channel else None,
            'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
            'remarks': recruit.remarks,
            'status': recruit.status.value if recruit.status else None,
        }

        old_pilot_data = {
            'nickname': recruit.pilot.nickname,
            'real_name': recruit.pilot.real_name,
            'gender': recruit.pilot.gender.value if recruit.pilot.gender else None,
            'birth_year': recruit.pilot.birth_year,
            'owner': str(recruit.pilot.owner.id) if recruit.pilot.owner else None,
            'platform': recruit.pilot.platform.value if recruit.pilot.platform else None,
            'work_mode': recruit.pilot.work_mode.value if recruit.pilot.work_mode else None,
            'rank': recruit.pilot.rank.value if recruit.pilot.rank else None,
            'status': recruit.pilot.status.value if recruit.pilot.status else None,
        }

        from utils.timezone_helper import get_current_utc_time

        recruit.broadcast_decision = broadcast_decision_enum
        recruit.broadcast_decision_maker = current_user
        recruit.broadcast_decision_time = get_current_utc_time()
        recruit.introduction_fee = introduction_fee_decimal
        recruit.remarks = remarks

        recruit.status = RecruitStatus.ENDED

        if broadcast_decision_enum in [BroadcastDecision.OFFICIAL, BroadcastDecision.INTERN]:
            from models.pilot import Platform
            recruit.pilot.owner = User.objects.get(id=owner)
            recruit.pilot.platform = Platform(platform)
            recruit.pilot.status = Status.RECRUITED

            if broadcast_decision_enum == BroadcastDecision.OFFICIAL:
                recruit.pilot.rank = Rank.OFFICIAL
            else:
                recruit.pilot.rank = Rank.INTERN

            recruit.pilot.save()
        else:
            recruit.pilot.status = Status.NOT_RECRUITING
            recruit.pilot.save()

        recruit.save()

        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        from routes.pilot import _record_changes as record_pilot_changes
        record_pilot_changes(recruit.pilot, old_pilot_data, current_user, _get_client_ip())

        if broadcast_decision_enum in [BroadcastDecision.OFFICIAL, BroadcastDecision.INTERN]:
            logger.info('开播决策成功：ID=%s，主播=%s，招募为%s', recruit_id, recruit.pilot.nickname, broadcast_decision_enum.value)
            flash(f'开播决策成功，主播已被招募为{broadcast_decision_enum.value}', 'success')
        else:
            logger.info('开播决策完成：ID=%s，主播=%s，不招募', recruit_id, recruit.pilot.nickname)
            flash('开播决策完成，已决定不招募该主播', 'success')

        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    except ValidationError as e:
        logger.error('开播决策验证失败：%s', str(e))
        flash('数据验证失败，请检查输入', 'error')
        return redirect(url_for('recruit.broadcast_decision_page', recruit_id=recruit_id))
    except Exception as e:
        logger.error('开播决策失败：%s', str(e))
        flash('开播决策失败，请重试', 'error')
        return redirect(url_for('recruit.broadcast_decision_page', recruit_id=recruit_id))


@recruit_bp.route('/<recruit_id>/confirm', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def confirm_recruit(recruit_id):
    """确认招募"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    if recruit.status != RecruitStatus.STARTED:
        flash('只能确认已启动状态的招募', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    if not recruit.pilot.real_name or not recruit.pilot.real_name.strip():
        flash('该主播未填写真实姓名，请先在主播管理补全基本资料后再确认招募', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    try:
        introduction_fee = request.form.get('introduction_fee', '0')
        remarks = request.form.get('remarks', '')

        try:
            introduction_fee_decimal = Decimal(introduction_fee).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                flash('介绍费不能为负数', 'error')
                return redirect(url_for('recruit.confirm_recruit_page', recruit_id=recruit_id))
        except (ValueError, InvalidOperation):
            flash('介绍费格式不正确', 'error')
            return redirect(url_for('recruit.confirm_recruit_page', recruit_id=recruit_id))

        old_recruit_data = {
            'pilot': str(recruit.pilot.id) if recruit.pilot else None,
            'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
            'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
            'channel': recruit.channel.value if recruit.channel else None,
            'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
            'remarks': recruit.remarks,
            'status': recruit.status.value if recruit.status else None,
        }

        old_pilot_data = {
            'nickname': recruit.pilot.nickname,
            'real_name': recruit.pilot.real_name,
            'gender': recruit.pilot.gender.value if recruit.pilot.gender else None,
            'birth_year': recruit.pilot.birth_year,
            'owner': str(recruit.pilot.owner.id) if recruit.pilot.owner else None,
            'platform': recruit.pilot.platform.value if recruit.pilot.platform else None,
            'work_mode': recruit.pilot.work_mode.value if recruit.pilot.work_mode else None,
            'rank': recruit.pilot.rank.value if recruit.pilot.rank else None,
            'status': recruit.pilot.status.value if recruit.pilot.status else None,
        }

        try:
            from utils.recruit_service import confirm_recruit_atomic
            confirm_recruit_atomic(recruit, introduction_fee_decimal, remarks, current_user, _get_client_ip())
        except Exception as service_error:
            logger.error('招募确认服务失败：%s', str(service_error))
            flash(f'招募确认失败：{str(service_error)}', 'error')
            return redirect(url_for('recruit.confirm_recruit_page', recruit_id=recruit_id))

        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        from routes.pilot import _record_changes as record_pilot_changes
        record_pilot_changes(recruit.pilot, old_pilot_data, current_user, _get_client_ip())

        logger.info('确认招募：ID=%s，主播=%s，主播分类设为试播主播，状态设为已招募', recruit_id, recruit.pilot.nickname)

        flash('招募已确认，主播分类已设为试播主播，状态已设为已招募', 'success')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    except Exception as e:
        logger.error('确认招募失败：%s', str(e))
        flash('确认招募失败，请重试', 'error')
        return redirect(url_for('recruit.confirm_recruit_page', recruit_id=recruit_id))


@recruit_bp.route('/<recruit_id>/abandon', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def abandon_recruit(recruit_id):
    """放弃招募"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    if recruit.status != RecruitStatus.STARTED:
        flash('只能放弃已启动状态的招募', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    try:
        old_recruit_data = {
            'pilot': str(recruit.pilot.id) if recruit.pilot else None,
            'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
            'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
            'channel': recruit.channel.value if recruit.channel else None,
            'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
            'remarks': recruit.remarks,
            'status': recruit.status.value if recruit.status else None,
        }

        old_pilot_data = {
            'nickname': recruit.pilot.nickname,
            'real_name': recruit.pilot.real_name,
            'gender': recruit.pilot.gender.value if recruit.pilot.gender else None,
            'birth_year': recruit.pilot.birth_year,
            'owner': str(recruit.pilot.owner.id) if recruit.pilot.owner else None,
            'platform': recruit.pilot.platform.value if recruit.pilot.platform else None,
            'work_mode': recruit.pilot.work_mode.value if recruit.pilot.work_mode else None,
            'rank': recruit.pilot.rank.value if recruit.pilot.rank else None,
            'status': recruit.pilot.status.value if recruit.pilot.status else None,
        }

        try:
            from utils.recruit_service import abandon_recruit_atomic
            abandon_recruit_atomic(recruit, current_user, _get_client_ip())
        except Exception as service_error:
            logger.error('招募放弃服务失败：%s', str(service_error))
            flash(f'招募放弃失败：{str(service_error)}', 'error')
            return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        from routes.pilot import _record_changes as record_pilot_changes
        record_pilot_changes(recruit.pilot, old_pilot_data, current_user, _get_client_ip())

        logger.info('放弃招募：ID=%s，主播=%s，状态设为不招募', recruit_id, recruit.pilot.nickname)

        flash('招募已放弃，主播状态已设为不招募', 'success')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    except Exception as e:
        logger.error('放弃招募失败：%s', str(e))
        flash('放弃招募失败，请重试', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))


@recruit_bp.route('/<recruit_id>/changes')
@roles_accepted('gicho', 'kancho')
def recruit_changes(recruit_id):
    """招募变更记录"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    changes = RecruitChangeLog.objects.filter(recruit_id=recruit).order_by('-change_time').limit(100)

    logger.debug('查看招募变更记录：ID=%s，记录数量=%d', recruit_id, changes.count())

    return jsonify([{
        'change_time': change.change_time.strftime('%Y-%m-%d %H:%M:%S'),
        'user': change.user_id.nickname or change.user_id.username,
        'field': change.field_display_name,
        'old_value': change.old_value,
        'new_value': change.new_value,
        'ip_address': change.ip_address
    } for change in changes])


@recruit_bp.route('/<recruit_id>/training')
@roles_accepted('gicho', 'kancho')
def training_recruit_page(recruit_id):
    """试播招募页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    if recruit.status != RecruitStatus.STARTED:
        flash('只能对已启动状态的招募执行试播招募', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    active_decisions = [d for d in TrainingDecisionOld if not d.name.endswith('_OLD')]
    training_decision_choices = [(d.value, d.value) for d in active_decisions]

    from models.pilot import WorkMode
    work_mode_choices = [(w.value, w.value) for w in WorkMode if w != WorkMode.UNKNOWN]

    logger.debug('打开试播招募页面：ID=%s，主播=%s', recruit_id, recruit.pilot.nickname)

    return render_template('recruits/training.html',
                           recruit=recruit,
                           training_decision_choices=training_decision_choices,
                           work_mode_choices=work_mode_choices,
                           default_training_time=recruit.appointment_time)


@recruit_bp.route('/<recruit_id>/training', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def training_recruit(recruit_id):
    """执行试播招募决策"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    if recruit.status != RecruitStatus.STARTED:
        flash('只能对已启动状态的招募执行试播招募', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    try:
        training_decision_value = request.form.get('training_decision')
        training_time_str = request.form.get('training_time', '')
        introduction_fee = request.form.get('introduction_fee', '0')
        remarks = request.form.get('remarks', '')

        real_name = request.form.get('real_name', '').strip()
        birth_year_str = request.form.get('birth_year', '')
        work_mode = request.form.get('work_mode', '')

        if not training_decision_value:
            flash('请选择试播招募决策', 'error')
            return redirect(url_for('recruit.training_recruit_page', recruit_id=recruit_id))

        try:
            training_decision_enum = TrainingDecisionOld(training_decision_value)
        except ValueError:
            flash('无效的试播招募决策', 'error')
            return redirect(url_for('recruit.training_recruit_page', recruit_id=recruit_id))

        training_time_utc = None
        if training_decision_enum == TrainingDecisionOld.RECRUIT_AS_TRAINEE:
            if not training_time_str:
                flash('招募为试播主播时必须填写试播时间', 'error')
                return redirect(url_for('recruit.training_recruit_page', recruit_id=recruit_id))

            try:
                training_time_local = datetime.fromisoformat(training_time_str.replace('T', ' '))
                training_time_utc = local_to_utc(training_time_local)

            except ValueError:
                flash('试播时间格式不正确', 'error')
                return redirect(url_for('recruit.training_recruit_page', recruit_id=recruit_id))

            if not real_name:
                flash('招募为试播主播时必须填写真实姓名', 'error')
                return redirect(url_for('recruit.training_recruit_page', recruit_id=recruit_id))

            if not birth_year_str:
                flash('招募为试播主播时必须填写出生年', 'error')
                return redirect(url_for('recruit.training_recruit_page', recruit_id=recruit_id))

            if not work_mode:
                flash('招募为试播主播时必须选择开播方式', 'error')
                return redirect(url_for('recruit.training_recruit_page', recruit_id=recruit_id))

            try:
                birth_year = int(birth_year_str)
                current_year = datetime.now().year
                if birth_year < current_year - 60 or birth_year > current_year - 10:
                    flash('出生年必须在距今60年前到距今10年前之间', 'error')
                    return redirect(url_for('recruit.training_recruit_page', recruit_id=recruit_id))
            except ValueError:
                flash('出生年格式不正确', 'error')
                return redirect(url_for('recruit.training_recruit_page', recruit_id=recruit_id))

        try:
            introduction_fee_decimal = Decimal(introduction_fee).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                flash('介绍费不能为负数', 'error')
                return redirect(url_for('recruit.training_recruit_page', recruit_id=recruit_id))
        except (ValueError, InvalidOperation):
            flash('介绍费格式不正确', 'error')
            return redirect(url_for('recruit.training_recruit_page', recruit_id=recruit_id))

        old_recruit_data = {
            'pilot': str(recruit.pilot.id) if recruit.pilot else None,
            'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
            'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
            'channel': recruit.channel.value if recruit.channel else None,
            'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
            'remarks': recruit.remarks,
            'status': recruit.status.value if recruit.status else None,
            'training_decision': recruit.training_decision.value if recruit.training_decision else None,
            'training_decision_maker': str(recruit.training_decision_maker.id) if recruit.training_decision_maker else None,
            'training_decision_time': recruit.training_decision_time.isoformat() if recruit.training_decision_time else None,
            'training_time': recruit.training_time.isoformat() if recruit.training_time else None,
        }

        old_pilot_data = {
            'nickname': recruit.pilot.nickname,
            'real_name': recruit.pilot.real_name,
            'gender': recruit.pilot.gender.value if recruit.pilot.gender else None,
            'birth_year': recruit.pilot.birth_year,
            'owner': str(recruit.pilot.owner.id) if recruit.pilot.owner else None,
            'platform': recruit.pilot.platform.value if recruit.pilot.platform else None,
            'work_mode': recruit.pilot.work_mode.value if recruit.pilot.work_mode else None,
            'rank': recruit.pilot.rank.value if recruit.pilot.rank else None,
            'status': recruit.pilot.status.value if recruit.pilot.status else None,
        }

        pilot_basic_info = {}
        if training_decision_enum == TrainingDecisionOld.RECRUIT_AS_TRAINEE:
            pilot_basic_info = {
                'real_name': real_name,
                'birth_year': birth_year,
                'work_mode': work_mode,
            }

        try:
            from utils.recruit_service import training_recruit_atomic
            training_recruit_atomic(recruit, training_decision_enum, training_time_utc, pilot_basic_info, introduction_fee_decimal, remarks, current_user,
                                    _get_client_ip())
        except Exception as service_error:
            logger.error('试播招募服务失败：%s', str(service_error))
            flash(f'试播招募失败：{str(service_error)}', 'error')
            return redirect(url_for('recruit.training_recruit_page', recruit_id=recruit_id))

        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        if training_decision_enum == TrainingDecisionOld.RECRUIT_AS_TRAINEE:
            from routes.pilot import _record_changes as record_pilot_changes
            record_pilot_changes(recruit.pilot, old_pilot_data, current_user, _get_client_ip())

        if training_decision_enum == TrainingDecisionOld.RECRUIT_AS_TRAINEE:
            logger.info('试播招募成功：ID=%s，主播=%s，招募为试播主播', recruit_id, recruit.pilot.nickname)
            flash('试播招募成功，主播已被招募为试播主播', 'success')
        else:
            logger.info('试播招募结束：ID=%s，主播=%s，不招募', recruit_id, recruit.pilot.nickname)
            flash('试播招募完成，已决定不招募该主播', 'success')

        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit.id))

    except ValidationError as e:
        logger.error('试播招募验证失败：%s', str(e))
        flash('数据验证失败，请检查输入', 'error')
        return redirect(url_for('recruit.training_recruit_page', recruit_id=recruit_id))
    except Exception as e:
        logger.error('试播招募失败：%s', str(e))
        flash('试播招募失败，请重试', 'error')
        return redirect(url_for('recruit.training_recruit_page', recruit_id=recruit_id))



