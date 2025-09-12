# pylint: disable=no-member
from decimal import Decimal, InvalidOperation

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)
from flask_security import current_user, roles_accepted
from mongoengine import DoesNotExist, ValidationError

from models.pilot import Pilot, Rank, Status
from models.recruit import (Recruit, RecruitChangeLog, RecruitChannel,
                            RecruitStatus)
from models.user import Role, User
from utils.logging_setup import get_logger
from utils.timezone_helper import local_to_utc

logger = get_logger('recruit')

recruit_bp = Blueprint('recruit', __name__)


def _get_client_ip():
    """获取客户端IP地址"""
    return request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR')


def _record_changes(recruit, old_data, user, ip_address):
    """记录征召字段变更"""
    changes = []
    field_mapping = {
        'pilot': str(recruit.pilot.id) if recruit.pilot else None,
        'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
        'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
        'channel': recruit.channel.value if recruit.channel else None,
        'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
        'remarks': recruit.remarks,
        'status': recruit.status.value if recruit.status else None,
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
        logger.info('记录征召变更：机师%s，共%d个字段', recruit.pilot.nickname if recruit.pilot else 'N/A', len(changes))


def _get_recruiter_choices():
    """获取征召负责人选择列表"""
    # 通过角色文档查询，避免对引用字段子字段查询导致的空结果
    role_docs = list(Role.objects.filter(name__in=['gicho', 'kancho']).only('id'))
    users = User.objects.filter(roles__in=role_docs).all()
    choices = []

    # 当前用户优先
    if current_user.has_role('kancho') or current_user.has_role('gicho'):
        label = current_user.nickname or current_user.username
        if current_user.has_role('gicho'):
            label = f"{label} [议长]"
        elif current_user.has_role('kancho'):
            label = f"{label} [舰长]"
        choices.append((str(current_user.id), label))

    # 其他活跃舰长/议长（昵称字典顺序）
    active_users = [u for u in users if u.active and u.id != current_user.id]
    active_users.sort(key=lambda x: x.nickname or x.username)
    for user in active_users:
        label = user.nickname or user.username
        if user.has_role('gicho'):
            label = f"{label} [议长]"
        elif user.has_role('kancho'):
            label = f"{label} [舰长]"
        choices.append((str(user.id), label))

    return choices


@recruit_bp.route('/')
@roles_accepted('gicho', 'kancho')
def list_recruits():
    """征召列表页面"""
    # 获取筛选参数
    status_filter = request.args.get('status', RecruitStatus.STARTED.value)

    # 构建查询
    query = Recruit.objects
    if status_filter:
        try:
            status_enum = RecruitStatus(status_filter)
            query = query.filter(status=status_enum)
        except ValueError:
            pass

    # 按预约时间升序排序
    recruits = query.order_by('appointment_time')

    logger.debug('征召列表查询：状态=%s，结果数量=%d', status_filter, recruits.count())

    return render_template('recruits/list.html', recruits=recruits, current_status=status_filter)


@recruit_bp.route('/<recruit_id>')
@roles_accepted('gicho', 'kancho')
def detail_recruit(recruit_id):
    """征召详情页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    # 检查用户权限：议长与舰长权限一致
    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    logger.debug('查看征召详情：ID=%s，机师=%s', recruit_id, recruit.pilot.nickname)

    return render_template('recruits/detail.html', recruit=recruit)


@recruit_bp.route('/start/<pilot_id>')
@roles_accepted('gicho', 'kancho')
def start_recruit(pilot_id):
    """启动征召页面"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)
    except DoesNotExist:
        abort(404)

    # 检查机师状态
    if pilot.status != Status.NOT_RECRUITED:
        flash('只有未征召状态的机师才能启动征召', 'error')
        return redirect(url_for('pilot.pilot_detail', pilot_id=pilot_id))

    # 检查是否已有进行中的征召
    existing_recruit = Recruit.objects.filter(pilot=pilot, status=RecruitStatus.STARTED).first()
    if existing_recruit:
        flash('该机师已有正在进行的征召', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=existing_recruit.id))

    # 检查用户权限：议长与舰长权限一致
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
    """创建征召"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)
    except DoesNotExist:
        abort(404)

    # 检查机师状态
    if pilot.status != Status.NOT_RECRUITED:
        flash('只有未征召状态的机师才能启动征召', 'error')
        return redirect(url_for('pilot.pilot_detail', pilot_id=pilot_id))

    # 检查是否已有进行中的征召
    existing_recruit = Recruit.objects.filter(pilot=pilot, status=RecruitStatus.STARTED).first()
    if existing_recruit:
        flash('该机师已有正在进行的征召', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=existing_recruit.id))

    # 检查用户权限：议长与舰长权限一致
    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    try:
        # 获取表单数据
        recruiter_id = request.form.get('recruiter')
        appointment_time_str = request.form.get('appointment_time')
        channel = request.form.get('channel')
        introduction_fee = request.form.get('introduction_fee', '0')
        remarks = request.form.get('remarks', '')

        # 验证必填项
        if not recruiter_id:
            flash('请选择征召负责人', 'error')
            return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))

        if not appointment_time_str:
            flash('请选择预约时间', 'error')
            return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))

        if not channel:
            flash('请选择征召渠道', 'error')
            return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))

        # 验证征召负责人
        try:
            recruiter = User.objects.get(id=recruiter_id)
            if not (recruiter.has_role('kancho') or recruiter.has_role('gicho')):
                flash('征召负责人必须是舰长或议长', 'error')
                return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))
        except DoesNotExist:
            flash('无效的征召负责人', 'error')
            return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))

        # 解析时间（前端传来的是GMT+8本地时间）
        from datetime import datetime
        appointment_time_local = datetime.fromisoformat(appointment_time_str.replace('T', ' '))
        appointment_time_utc = local_to_utc(appointment_time_local)

        # 验证渠道
        try:
            channel_enum = RecruitChannel(channel)
        except ValueError:
            flash('无效的征召渠道', 'error')
            return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))

        # 验证介绍费
        try:
            introduction_fee_decimal = Decimal(introduction_fee).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                flash('介绍费不能为负数', 'error')
                return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))
        except (ValueError, InvalidOperation):
            flash('介绍费格式不正确', 'error')
            return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))

        # 创建征召记录
        recruit = Recruit(pilot=pilot,
                          recruiter=recruiter,
                          appointment_time=appointment_time_utc,
                          channel=channel_enum,
                          introduction_fee=introduction_fee_decimal,
                          remarks=remarks,
                          status=RecruitStatus.STARTED)

        recruit.save()

        # 记录操作日志
        logger.info('启动征召：机师=%s，负责人=%s，预约时间=%s', pilot.nickname, recruiter.nickname or recruiter.username, appointment_time_utc)

        flash('征召已成功启动', 'success')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit.id))

    except ValidationError as e:
        logger.error('创建征召验证失败：%s', str(e))
        flash('数据验证失败，请检查输入', 'error')
        return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))
    except Exception as e:
        logger.error('创建征召失败：%s', str(e))
        flash('创建征召失败，请重试', 'error')
        return redirect(url_for('recruit.start_recruit', pilot_id=pilot_id))


@recruit_bp.route('/<recruit_id>/edit')
@roles_accepted('gicho', 'kancho')
def edit_recruit(recruit_id):
    """编辑征召页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    # 检查用户权限：议长与舰长权限一致
    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    recruiter_choices = _get_recruiter_choices()
    channel_choices = [(c.value, c.value) for c in RecruitChannel]
    status_choices = [(s.value, s.value) for s in RecruitStatus]

    return render_template('recruits/edit.html',
                           recruit=recruit,
                           recruiter_choices=recruiter_choices,
                           channel_choices=channel_choices,
                           status_choices=status_choices)


@recruit_bp.route('/<recruit_id>/edit', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def update_recruit(recruit_id):
    """更新征召"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    # 检查用户权限：议长与舰长权限一致
    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    # 保存修改前的数据用于变更记录
    old_data = {
        'pilot': str(recruit.pilot.id) if recruit.pilot else None,
        'recruiter': str(recruit.recruiter.id) if recruit.recruiter else None,
        'appointment_time': recruit.appointment_time.isoformat() if recruit.appointment_time else None,
        'channel': recruit.channel.value if recruit.channel else None,
        'introduction_fee': str(recruit.introduction_fee) if recruit.introduction_fee else None,
        'remarks': recruit.remarks,
        'status': recruit.status.value if recruit.status else None,
    }

    try:
        # 获取表单数据
        recruiter_id = request.form.get('recruiter')
        appointment_time_str = request.form.get('appointment_time')
        channel = request.form.get('channel')
        introduction_fee = request.form.get('introduction_fee', '0')
        remarks = request.form.get('remarks', '')
        status = request.form.get('status')

        # 验证必填项
        if not recruiter_id:
            flash('请选择征召负责人', 'error')
            return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))

        if not appointment_time_str:
            flash('请选择预约时间', 'error')
            return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))

        if not channel:
            flash('请选择征召渠道', 'error')
            return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))

        if not status:
            flash('请选择征召状态', 'error')
            return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))

        # 验证征召负责人
        try:
            recruiter = User.objects.get(id=recruiter_id)
            if not (recruiter.has_role('kancho') or recruiter.has_role('gicho')):
                flash('征召负责人必须是舰长或议长', 'error')
                return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))
        except DoesNotExist:
            flash('无效的征召负责人', 'error')
            return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))

        # 解析时间（前端传来的是GMT+8本地时间）
        from datetime import datetime
        appointment_time_local = datetime.fromisoformat(appointment_time_str.replace('T', ' '))
        appointment_time_utc = local_to_utc(appointment_time_local)

        # 验证渠道
        try:
            channel_enum = RecruitChannel(channel)
        except ValueError:
            flash('无效的征召渠道', 'error')
            return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))

        # 验证状态
        try:
            status_enum = RecruitStatus(status)
        except ValueError:
            flash('无效的征召状态', 'error')
            return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))

        # 验证介绍费
        try:
            introduction_fee_decimal = Decimal(introduction_fee).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                flash('介绍费不能为负数', 'error')
                return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))
        except (ValueError, InvalidOperation):
            flash('介绍费格式不正确', 'error')
            return redirect(url_for('recruit.edit_recruit', recruit_id=recruit_id))

        # 更新征召记录
        recruit.recruiter = recruiter
        recruit.appointment_time = appointment_time_utc
        recruit.channel = channel_enum
        recruit.introduction_fee = introduction_fee_decimal
        recruit.remarks = remarks
        recruit.status = status_enum

        recruit.save()

        # 记录变更日志
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


@recruit_bp.route('/<recruit_id>/confirm')
@roles_accepted('gicho', 'kancho')
def confirm_recruit_page(recruit_id):
    """确认征召页面"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    # 检查征召状态
    if recruit.status != RecruitStatus.STARTED:
        flash('只能确认已启动状态的征召', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    # 检查用户权限：议长与舰长权限一致
    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    return render_template('recruits/confirm.html', recruit=recruit)


@recruit_bp.route('/<recruit_id>/confirm', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def confirm_recruit(recruit_id):
    """确认征召"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    # 检查征召状态
    if recruit.status != RecruitStatus.STARTED:
        flash('只能确认已启动状态的征召', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    # 检查用户权限：议长与舰长权限一致
    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    # 检查机师真实姓名是否为空
    if not recruit.pilot.real_name or not recruit.pilot.real_name.strip():
        flash('该机师未填写真实姓名，请先在机师管理补全基本资料后再确认征召', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    try:
        # 获取表单数据
        introduction_fee = request.form.get('introduction_fee', '0')
        remarks = request.form.get('remarks', '')

        # 验证介绍费
        try:
            introduction_fee_decimal = Decimal(introduction_fee).quantize(Decimal('0.00'))
            if introduction_fee_decimal < 0:
                flash('介绍费不能为负数', 'error')
                return redirect(url_for('recruit.confirm_recruit_page', recruit_id=recruit_id))
        except (ValueError, InvalidOperation):
            flash('介绍费格式不正确', 'error')
            return redirect(url_for('recruit.confirm_recruit_page', recruit_id=recruit_id))

        # 保存修改前的数据用于变更记录
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

        # 使用服务层方法确保原子性
        try:
            from utils.recruit_service import confirm_recruit_atomic
            confirm_recruit_atomic(recruit, introduction_fee_decimal, remarks, current_user, _get_client_ip())
        except Exception as service_error:
            logger.error('征召确认服务失败：%s', str(service_error))
            flash(f'征召确认失败：{str(service_error)}', 'error')
            return redirect(url_for('recruit.confirm_recruit_page', recruit_id=recruit_id))

        # 记录征召变更日志
        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        # 记录机师变更日志
        from routes.pilot import _record_changes as record_pilot_changes
        record_pilot_changes(recruit.pilot, old_pilot_data, current_user, _get_client_ip())

        logger.info('确认征召：ID=%s，机师=%s，阶级设为训练机师，状态设为已征召', recruit_id, recruit.pilot.nickname)

        flash('征召已确认，机师阶级已设为训练机师，状态已设为已征召', 'success')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    except Exception as e:
        logger.error('确认征召失败：%s', str(e))
        flash('确认征召失败，请重试', 'error')
        return redirect(url_for('recruit.confirm_recruit_page', recruit_id=recruit_id))


@recruit_bp.route('/<recruit_id>/abandon', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def abandon_recruit(recruit_id):
    """放弃征召"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    # 检查征召状态
    if recruit.status != RecruitStatus.STARTED:
        flash('只能放弃已启动状态的征召', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    # 检查用户权限：议长与舰长权限一致
    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    try:
        # 保存修改前的数据用于变更记录
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

        # 使用服务层方法确保原子性
        try:
            from utils.recruit_service import abandon_recruit_atomic
            abandon_recruit_atomic(recruit, current_user, _get_client_ip())
        except Exception as service_error:
            logger.error('征召放弃服务失败：%s', str(service_error))
            flash(f'征召放弃失败：{str(service_error)}', 'error')
            return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

        # 记录征召变更日志
        _record_changes(recruit, old_recruit_data, current_user, _get_client_ip())

        # 记录机师变更日志
        from routes.pilot import _record_changes as record_pilot_changes
        record_pilot_changes(recruit.pilot, old_pilot_data, current_user, _get_client_ip())

        logger.info('放弃征召：ID=%s，机师=%s，状态设为不征召', recruit_id, recruit.pilot.nickname)

        flash('征召已放弃，机师状态已设为不征召', 'success')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))

    except Exception as e:
        logger.error('放弃征召失败：%s', str(e))
        flash('放弃征召失败，请重试', 'error')
        return redirect(url_for('recruit.detail_recruit', recruit_id=recruit_id))


@recruit_bp.route('/<recruit_id>/changes')
@roles_accepted('gicho', 'kancho')
def recruit_changes(recruit_id):
    """征召变更记录"""
    try:
        recruit = Recruit.objects.get(id=recruit_id)
    except DoesNotExist:
        abort(404)

    # 检查用户权限：议长与舰长权限一致
    if not (current_user.has_role('gicho') or current_user.has_role('kancho')):
        abort(403)

    # 获取变更记录（最近100条）
    changes = RecruitChangeLog.objects.filter(recruit_id=recruit).order_by('-change_time').limit(100)

    logger.debug('查看征召变更记录：ID=%s，记录数量=%d', recruit_id, changes.count())

    return jsonify([{
        'change_time': change.change_time.strftime('%Y-%m-%d %H:%M:%S'),
        'user': change.user_id.nickname or change.user_id.username,
        'field': change.field_display_name,
        'old_value': change.old_value,
        'new_value': change.new_value,
        'ip_address': change.ip_address
    } for change in changes])
