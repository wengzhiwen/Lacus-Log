"""作战记录路由。"""
# pylint: disable=no-member
from datetime import datetime, timedelta
from decimal import Decimal

from flask import (Blueprint, flash, jsonify, redirect, render_template, request, url_for)
from flask_security import current_user, roles_accepted

from models.announcement import Announcement
from models.battle_record import BattleRecord, BattleRecordChangeLog
from models.pilot import Pilot, Rank, WorkMode
from models.user import Role, User
from utils.filter_state import persist_and_restore_filters
from utils.james_alert import trigger_james_alert_if_needed
from utils.logging_setup import get_logger
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)

logger = get_logger('battle_record')

battle_record_bp = Blueprint('battle_record', __name__)


def validate_notes_required(start_time, end_time, revenue_amount, base_salary, related_announcement, notes):
    """验证备注是否必填；无错误返回 None。"""
    if notes and notes.strip():
        return None

    reasons = []

    if start_time and end_time:
        duration = (end_time - start_time).total_seconds() / 3600
        if duration < 6.0:
            reasons.append("开播时长小于6.0小时")
        elif duration >= 9.0:
            reasons.append("开播时长大于等于9.0小时")

    if base_salary and base_salary != Decimal('0') and base_salary != Decimal('150'):
        reasons.append("底薪不等于0也不等于150")

    if revenue_amount and revenue_amount != Decimal('0') and revenue_amount < Decimal('100'):
        reasons.append("流水不等于0且小于100")

    if revenue_amount and revenue_amount >= Decimal('5000'):
        reasons.append("流水大于等于5000")

    if related_announcement and hasattr(related_announcement, 'start_time') and related_announcement.start_time:
        announcement_start_local = utc_to_local(related_announcement.start_time)
        record_start_local = utc_to_local(start_time)

        time_diff = abs((record_start_local - announcement_start_local).total_seconds() / 3600)
        if time_diff > 6:
            reasons.append("开播时间与关联通告时间相差超过6个小时")

    if reasons:
        return "因为" + "或".join(reasons) + "原因，必须填写备注"

    return None


def log_battle_record_change(battle_record, field_name, old_value, new_value, user_id, ip_address):
    """记录开播记录变更日志"""
    try:
        change_log = BattleRecordChangeLog(battle_record_id=battle_record,
                                           user_id=user_id,
                                           field_name=field_name,
                                           old_value=str(old_value) if old_value is not None else '',
                                           new_value=str(new_value) if new_value is not None else '',
                                           ip_address=ip_address)
        change_log.save()
        logger.debug(f"记录开播记录变更: {field_name} {old_value} -> {new_value}")
    except Exception as e:
        logger.error(f"记录开播记录变更失败: {e}")


def get_time_rounded_to_half_hour(dt, backward=True):  # pylint: disable=unused-argument
    """取最近整点/半点（分钟<=30取整点，>30取半点）。"""
    if dt.minute == 0 or dt.minute == 30:
        return dt.replace(second=0, microsecond=0)
    elif dt.minute <= 30:
        return dt.replace(minute=0, second=0, microsecond=0)
    else:
        return dt.replace(minute=30, second=0, microsecond=0)


@battle_record_bp.route('/')
@roles_accepted('gicho', 'kancho')
def list_battle_records():
    """开播记录列表页"""
    logger.info(f"用户 {current_user.username} 访问开播记录列表")

    filters = persist_and_restore_filters(
        'battle_records_list',
        allowed_keys=['owner', 'x', 'time'],
        default_filters={
            'owner': 'all',
            'x': '',
            'time': 'two_days'
        },
    )

    owner_filter = filters.get('owner') or 'all'
    x_filter = filters.get('x') or ''
    time_filter = filters.get('time') or 'two_days'

    query = BattleRecord.objects

    if owner_filter == 'self':
        query = query.filter(owner_snapshot=current_user.id)
    elif owner_filter and owner_filter != 'all':
        try:
            owner_user = User.objects.get(id=owner_filter)
            query = query.filter(owner_snapshot=owner_user.id)
        except Exception:
            pass

    if x_filter:
        query = query.filter(x_coord=x_filter)

    now_utc = get_current_utc_time()
    if time_filter == 'today':
        local_today_start = utc_to_local(now_utc).replace(hour=0, minute=0, second=0, microsecond=0)
        local_today_end = local_today_start + timedelta(days=1)
        utc_today_start = local_to_utc(local_today_start)
        utc_today_end = local_to_utc(local_today_end)
        query = query.filter(start_time__gte=utc_today_start, start_time__lt=utc_today_end)
    elif time_filter == 'two_days':
        now_local = utc_to_local(now_utc)
        today_local_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_local_start = today_local_start - timedelta(days=1)
        day_after_tomorrow_local_start = today_local_start + timedelta(days=2)
        range_start_utc = local_to_utc(yesterday_local_start)
        range_end_utc = local_to_utc(day_after_tomorrow_local_start)
        query = query.filter(start_time__gte=range_start_utc, start_time__lt=range_end_utc)
    elif time_filter == 'seven_days':
        now_local = utc_to_local(now_utc)
        today_local_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days_later_local_start = today_local_start + timedelta(days=7)
        range_start_utc = local_to_utc(today_local_start)
        range_end_utc = local_to_utc(seven_days_later_local_start)
        query = query.filter(start_time__gte=range_start_utc, start_time__lt=range_end_utc)

    query = query.order_by('-start_time', '-revenue_amount')

    page = int(request.args.get('page', 1))
    per_page = 100
    skip = (page - 1) * per_page

    battle_records = query.skip(skip).limit(per_page)
    total_count = query.count()

    gicho = Role.objects(name='gicho').first()
    kancho = Role.objects(name='kancho').first()
    role_list = [r for r in [gicho, kancho] if r]
    owners = User.objects(roles__in=role_list).order_by('username') if role_list else []

    x_coords = sorted(list({br.x_coord for br in BattleRecord.objects.only('x_coord') if br.x_coord}))

    return render_template('battle_records/list.html',
                           battle_records=battle_records,
                           owners=owners,
                           x_choices=[('', '全部基地')] + [(x, x) for x in x_coords],
                           current_filters={
                               'owner': owner_filter,
                               'x': x_filter,
                               'time': time_filter
                           },
                           current_page=page,
                           total_count=total_count,
                           has_more=total_count > page * per_page)


@battle_record_bp.route('/new')
@roles_accepted('gicho', 'kancho')
def new_battle_record():
    """新建作战记录页"""
    logger.info(f"用户 {current_user.username} 访问新建作战记录页")

    announcement_id = request.args.get('announcement_id')

    current_local = utc_to_local(get_current_utc_time())

    default_start_local = current_local - timedelta(hours=6)
    default_start_local = get_time_rounded_to_half_hour(default_start_local)

    default_end_local = get_time_rounded_to_half_hour(current_local)

    default_data = {
        'start_time': default_start_local,
        'end_time': default_end_local,
        'revenue_amount': Decimal('0'),
        'base_salary': Decimal('0'),
    }

    related_announcement = None
    if announcement_id:
        try:
            related_announcement = Announcement.objects.get(id=announcement_id)
            default_data.update({
                'pilot': related_announcement.pilot,
                'related_announcement': related_announcement,
                'start_time': utc_to_local(related_announcement.start_time),
                'end_time': utc_to_local(related_announcement.end_time),
                'x_coord': related_announcement.x_coord,
                'y_coord': related_announcement.y_coord,
                'z_coord': related_announcement.z_coord,
                'work_mode': WorkMode.OFFLINE,
                'owner_snapshot': related_announcement.pilot.owner,
                'base_salary': Decimal('150'),  # 从通告新建时底薪默认150元
            })
            logger.debug(f"从通告 {announcement_id} 预填作战记录数据")
        except Announcement.DoesNotExist:
            logger.warning(f"指定的通告 {announcement_id} 不存在")

    return render_template('battle_records/new.html', default_data=default_data, related_announcement=related_announcement)


@battle_record_bp.route('/create', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def create_battle_record():
    """创建作战记录"""
    logger.info(f"用户 {current_user.username} 创建作战记录")

    try:
        pilot_id = request.form.get('pilot')
        related_announcement_id = request.form.get('related_announcement')
        start_time_str = request.form.get('start_time')
        end_time_str = request.form.get('end_time')
        revenue_amount_str = request.form.get('revenue_amount', '0')
        base_salary_str = request.form.get('base_salary', '0')
        x_coord = request.form.get('x_coord') or ''
        y_coord = request.form.get('y_coord') or ''
        z_coord = request.form.get('z_coord') or ''
        work_mode = request.form.get('work_mode')
        notes = request.form.get('notes', '')

        if not all([pilot_id, start_time_str, end_time_str, work_mode]):
            flash('请填写所有必填项', 'error')
            return redirect(url_for('battle_record.new_battle_record'))

        try:
            wm_enum = WorkMode(work_mode)
        except Exception:
            flash('参战形式不正确', 'error')
            return redirect(url_for('battle_record.new_battle_record'))

        try:
            pilot = Pilot.objects.get(id=pilot_id)
        except Pilot.DoesNotExist:
            flash('选择的主播不存在', 'error')
            return redirect(url_for('battle_record.new_battle_record'))

        related_announcement = None
        if related_announcement_id:
            try:
                related_announcement = Announcement.objects.get(id=related_announcement_id)
            except Announcement.DoesNotExist:
                pass

        try:
            start_time_local = datetime.fromisoformat(start_time_str)
            end_time_local = datetime.fromisoformat(end_time_str)
            start_time_utc = local_to_utc(start_time_local)
            end_time_utc = local_to_utc(end_time_local)
        except ValueError:
            flash('时间格式错误', 'error')
            return redirect(url_for('battle_record.new_battle_record'))

        try:
            revenue_amount = Decimal(revenue_amount_str)
            base_salary = Decimal(base_salary_str)
        except (ValueError, TypeError):
            flash('金额格式错误', 'error')
            return redirect(url_for('battle_record.new_battle_record'))

        if wm_enum == WorkMode.OFFLINE:
            if not (x_coord and y_coord and z_coord):
                flash('线下开播时必须选择X/Y/Z坐标', 'error')
                return redirect(url_for('battle_record.new_battle_record'))

        validation_error = validate_notes_required(start_time_utc, end_time_utc, revenue_amount, base_salary, related_announcement,
                                                   notes.strip() if notes else '')
        if validation_error:
            flash(validation_error, 'error')
            return redirect(url_for('battle_record.new_battle_record'))

        battle_record = BattleRecord(
            pilot=pilot,
            related_announcement=related_announcement,
            start_time=start_time_utc,
            end_time=end_time_utc,
            revenue_amount=revenue_amount,
            base_salary=base_salary,
            x_coord=x_coord,
            y_coord=y_coord,
            z_coord=z_coord,
            work_mode=wm_enum,
            owner_snapshot=pilot.owner,  # 无所属机师不使用当前用户作为快照
            registered_by=current_user,
            notes=notes.strip() if notes else '')

        battle_record.save()

        logger.info(f"开播记录创建成功，ID: {battle_record.id}")
        flash('开播记录创建成功', 'success')

        trigger_james_alert_if_needed(battle_record)

        return redirect(url_for('battle_record.detail_battle_record', record_id=battle_record.id))

    except Exception as e:
        logger.error(f"创建开播记录失败: {e}")
        flash('创建开播记录失败，请重试', 'error')
        return redirect(url_for('battle_record.new_battle_record'))


@battle_record_bp.route('/<record_id>')
@roles_accepted('gicho', 'kancho')
def detail_battle_record(record_id):
    """开播记录详情页"""
    try:
        battle_record = BattleRecord.objects.get(id=record_id)
        logger.info(f"用户 {current_user.username} 查看开播记录详情 {record_id}")

        related_announcement = None
        related_announcement_deleted = False
        try:
            related_announcement = battle_record.related_announcement
            _ = related_announcement.id if related_announcement else None
        except Exception as e:  # mongoengine.errors.DoesNotExist 等
            related_announcement_deleted = True
            logger.warning(f"开播记录 {record_id} 的关联通告不存在，显示已删除占位。原因: {e}", exc_info=True)

        return render_template('battle_records/detail.html',
                               battle_record=battle_record,
                               related_announcement=related_announcement,
                               related_announcement_deleted=related_announcement_deleted)
    except BattleRecord.DoesNotExist:
        flash('开播记录不存在', 'error')
        return redirect(url_for('battle_record.list_battle_records'))


@battle_record_bp.route('/<record_id>/edit')
@roles_accepted('gicho', 'kancho')
def edit_battle_record(record_id):
    """编辑开播记录页"""
    try:
        battle_record = BattleRecord.objects.get(id=record_id)
        logger.info(f"用户 {current_user.username} 编辑开播记录 {record_id}")

        related_announcement = None
        related_announcement_deleted = False
        try:
            related_announcement = battle_record.related_announcement
            _ = related_announcement.id if related_announcement else None
        except Exception as e:
            related_announcement_deleted = True
            logger.warning(f"开播记录 {record_id} 的关联通告不存在（编辑页），显示已删除占位。原因: {e}", exc_info=True)

        return render_template('battle_records/edit.html',
                               battle_record=battle_record,
                               related_announcement=related_announcement,
                               related_announcement_deleted=related_announcement_deleted)
    except BattleRecord.DoesNotExist:
        flash('开播记录不存在', 'error')
        return redirect(url_for('battle_record.list_battle_records'))


@battle_record_bp.route('/<record_id>/update', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def update_battle_record(record_id):
    """更新开播记录"""
    try:
        battle_record = BattleRecord.objects.get(id=record_id)
        logger.info(f"用户 {current_user.username} 更新开播记录 {record_id}")

        old_record_data = {
            'revenue_amount': battle_record.revenue_amount,
            'base_salary': battle_record.base_salary,
            'start_time': battle_record.start_time,
            'end_time': battle_record.end_time,
            'work_mode': battle_record.work_mode
        }

        try:
            old_related_announcement = battle_record.related_announcement
            _ = old_related_announcement.id if old_related_announcement else None
        except Exception:
            old_related_announcement = None

        old_values = {
            'pilot': battle_record.pilot,
            'related_announcement': old_related_announcement,
            'start_time': battle_record.start_time,
            'end_time': battle_record.end_time,
            'revenue_amount': battle_record.revenue_amount,
            'base_salary': battle_record.base_salary,
            'x_coord': battle_record.x_coord,
            'y_coord': battle_record.y_coord,
            'z_coord': battle_record.z_coord,
            'work_mode': battle_record.work_mode,
            'notes': battle_record.notes,
        }

        pilot_id = request.form.get('pilot')
        if pilot_id:
            pilot = Pilot.objects.get(id=pilot_id)
            battle_record.pilot = pilot
            battle_record.owner_snapshot = pilot.owner

        try:
            _tmp_ann = battle_record.related_announcement
            _ = _tmp_ann.id if _tmp_ann else None
        except Exception as e:
            logger.warning(f"开播记录 {record_id} 的关联通告在保存时检测为不存在，自动清空该引用。原因: {e}", exc_info=True)
            battle_record.related_announcement = None

        start_time_str = request.form.get('start_time')
        end_time_str = request.form.get('end_time')
        if start_time_str and end_time_str:
            start_time_local = datetime.fromisoformat(start_time_str)
            end_time_local = datetime.fromisoformat(end_time_str)
            battle_record.start_time = local_to_utc(start_time_local)
            battle_record.end_time = local_to_utc(end_time_local)

        revenue_amount_str = request.form.get('revenue_amount')
        base_salary_str = request.form.get('base_salary')
        if revenue_amount_str:
            battle_record.revenue_amount = Decimal(revenue_amount_str)
        if base_salary_str:
            battle_record.base_salary = Decimal(base_salary_str)

        work_mode = request.form.get('work_mode')
        if work_mode:
            battle_record.work_mode = WorkMode(work_mode)

        if battle_record.work_mode == WorkMode.OFFLINE:
            x_coord = request.form.get('x_coord')
            y_coord = request.form.get('y_coord')
            z_coord = request.form.get('z_coord')
            if not all([x_coord, y_coord, z_coord]):
                flash('线下开播时必须选择X/Y/Z坐标', 'error')
                return redirect(url_for('battle_record.edit_battle_record', record_id=record_id))
            battle_record.x_coord = x_coord
            battle_record.y_coord = y_coord
            battle_record.z_coord = z_coord
        else:
            battle_record.x_coord = ''
            battle_record.y_coord = ''
            battle_record.z_coord = ''

        notes = request.form.get('notes', '')
        battle_record.notes = notes.strip()

        validation_error = validate_notes_required(battle_record.start_time, battle_record.end_time, battle_record.revenue_amount, battle_record.base_salary,
                                                   battle_record.related_announcement, battle_record.notes)
        if validation_error:
            flash(validation_error, 'error')
            return redirect(url_for('battle_record.edit_battle_record', record_id=record_id))

        battle_record.save()

        client_ip = request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR')

        for field_name, old_value in old_values.items():
            new_value = getattr(battle_record, field_name)
            if old_value != new_value:
                log_battle_record_change(battle_record, field_name, old_value, new_value, current_user, client_ip)

        class OldRecord:

            def __init__(self, data):
                for key, value in data.items():
                    setattr(self, key, value)
                if hasattr(self, 'start_time') and hasattr(self, 'end_time') and self.start_time and self.end_time:
                    duration = (self.end_time - self.start_time).total_seconds() / 3600
                    self.duration_hours = round(duration, 1) if duration > 0 else 0
                else:
                    self.duration_hours = 0

        old_record = OldRecord(old_record_data)
        trigger_james_alert_if_needed(battle_record, old_record)

        flash('开播记录更新成功', 'success')
        return redirect(url_for('battle_record.detail_battle_record', record_id=record_id))

    except BattleRecord.DoesNotExist:
        flash('开播记录不存在', 'error')
        return redirect(url_for('battle_record.list_battle_records'))
    except Exception as e:
        logger.error(f"更新开播记录失败: {e}")
        flash('更新开播记录失败，请重试', 'error')
        return redirect(url_for('battle_record.edit_battle_record', record_id=record_id))


@battle_record_bp.route('/<record_id>/delete', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def delete_battle_record(record_id):
    """删除开播记录"""
    try:
        battle_record = BattleRecord.objects.get(id=record_id)
        logger.info(f"用户 {current_user.username} 删除开播记录 {record_id}")

        BattleRecordChangeLog.objects.filter(battle_record_id=battle_record).delete()

        battle_record.delete()

        flash('开播记录删除成功', 'success')
        return redirect(url_for('battle_record.list_battle_records'))

    except BattleRecord.DoesNotExist:
        flash('开播记录不存在', 'error')
        return redirect(url_for('battle_record.list_battle_records'))
    except Exception as e:
        logger.error(f"删除开播记录失败: {e}")
        flash('删除开播记录失败，请重试', 'error')
        return redirect(url_for('battle_record.detail_battle_record', record_id=record_id))


@battle_record_bp.route('/<record_id>/changes')
@roles_accepted('gicho', 'kancho')
def view_battle_record_changes(record_id):
    """查看开播记录变更记录"""
    try:
        battle_record = BattleRecord.objects.get(id=record_id)
        changes = BattleRecordChangeLog.objects.filter(battle_record_id=battle_record).order_by('-change_time').limit(100)

        logger.info(f"用户 {current_user.username} 查看开播记录变更记录 {record_id}")

        return jsonify({
            'success':
            True,
            'changes': [{
                'change_time': change.change_time.isoformat(),
                'user_name': change.user_id.username if change.user_id else '未知',
                'field_name': change.field_display_name,
                'old_value': change.old_value,
                'new_value': change.new_value,
                'ip_address': change.ip_address
            } for change in changes]
        })

    except BattleRecord.DoesNotExist:
        return jsonify({'success': False, 'error': '开播记录不存在'}), 404
    except Exception as e:
        logger.error(f"获取开播记录变更记录失败: {e}")
        return jsonify({'success': False, 'error': '获取变更记录失败'}), 500




@battle_record_bp.route('/api/pilot-filters')
@roles_accepted('gicho', 'kancho')
def api_pilot_filters():
    """获取主播筛选器数据"""
    try:
        gicho = Role.objects(name='gicho').first()
        kancho = Role.objects(name='kancho').first()
        role_list = [r for r in [gicho, kancho] if r]
        owners = User.objects(roles__in=role_list).order_by('username') if role_list else []
        owners_data = [{'id': str(owner.id), 'name': owner.nickname or owner.username} for owner in owners]

        ranks_data = [
            {
                'value': Rank.CANDIDATE.value,
                'name': Rank.CANDIDATE.value
            },
            {
                'value': Rank.TRAINEE.value,
                'name': Rank.TRAINEE.value
            },
            {
                'value': Rank.INTERN.value,
                'name': Rank.INTERN.value
            },
            {
                'value': Rank.OFFICIAL.value,
                'name': Rank.OFFICIAL.value
            },
        ]

        return jsonify({'success': True, 'owners': owners_data, 'ranks': ranks_data})

    except Exception as e:
        logger.error(f"获取主播筛选器数据失败: {e}")
        return jsonify({'success': False, 'error': '获取筛选器数据失败'}), 500


@battle_record_bp.route('/api/pilots-filtered')
@roles_accepted('gicho', 'kancho')
def api_pilots_filtered():
    """根据筛选条件获取主播列表"""
    try:
        owner_id = request.args.get('owner')
        rank = request.args.get('rank')

        query = Pilot.objects.filter(status__in=['已招募', '已签约', '已征召'])

        if owner_id and owner_id != 'all':
            try:
                owner = User.objects.get(id=owner_id)
                query = query.filter(owner=owner)
            except User.DoesNotExist:
                pass

        if rank:
            try:
                rank_enum = Rank(rank)
                if rank_enum == Rank.CANDIDATE:
                    query = query.filter(rank__in=[Rank.CANDIDATE, Rank.CANDIDATE_OLD])
                elif rank_enum == Rank.TRAINEE:
                    query = query.filter(rank__in=[Rank.TRAINEE, Rank.TRAINEE_OLD])
                elif rank_enum == Rank.INTERN:
                    query = query.filter(rank__in=[Rank.INTERN, Rank.INTERN_OLD])
                elif rank_enum == Rank.OFFICIAL:
                    query = query.filter(rank__in=[Rank.OFFICIAL, Rank.OFFICIAL_OLD])
                else:
                    query = query.filter(rank=rank_enum)
            except ValueError:
                pass

        pilots = query.order_by('nickname')

        pilots_data = []
        for pilot in pilots:
            age_str = f"({pilot.age})" if pilot.age else ""
            gender_icon = "♂" if pilot.gender.value == 0 else "♀" if pilot.gender.value == 1 else "?"
            display_name = f"{pilot.nickname}{age_str}[{pilot.status.value}]{gender_icon}"

            owner_name = ''
            if pilot.owner:
                owner_name = (pilot.owner.nickname or pilot.owner.username) or ''

            pilots_data.append({
                'id': str(pilot.id),
                'name': display_name,
                'nickname': pilot.nickname,
                'real_name': pilot.real_name or '',
                'age': pilot.age or '',
                'gender': pilot.gender.value if hasattr(pilot, 'gender') and pilot.gender is not None else None,
                'status': pilot.status.value,
                'rank': pilot.rank.value,
                'owner': owner_name
            })

        return jsonify({'success': True, 'pilots': pilots_data})

    except Exception as e:
        logger.error(f"获取主播列表失败: {e}")
        return jsonify({'success': False, 'error': '获取主播列表失败'}), 500


@battle_record_bp.route('/api/battle-areas')
@roles_accepted('gicho', 'kancho')
def api_battle_areas():
    """获取开播地点数据（三联选择）"""
    try:
        from models.battle_area import Availability, BattleArea

        areas = BattleArea.objects.filter(availability=Availability.ENABLED).order_by('x_coord', 'y_coord', 'z_coord')

        x_coords = {}

        for area in areas:
            x_coord = area.x_coord
            y_coord = area.y_coord
            z_coord = area.z_coord

            if x_coord not in x_coords:
                x_coords[x_coord] = {}

            if y_coord not in x_coords[x_coord]:
                x_coords[x_coord][y_coord] = []

            x_coords[x_coord][y_coord].append(z_coord)

        result = {}
        for x_coord in sorted(x_coords.keys()):
            result[x_coord] = {}
            for y_coord in sorted(x_coords[x_coord].keys()):
                z_coords = x_coords[x_coord][y_coord]
                try:
                    z_coords.sort(key=lambda z: int(z))  # pylint: disable=unnecessary-lambda
                except ValueError:
                    z_coords.sort()  # 如果不是数字，按字典顺序排序
                result[x_coord][y_coord] = z_coords

        return jsonify({'success': True, 'areas': result})

    except Exception as e:
        logger.error(f"获取开播地点数据失败: {e}")
        return jsonify({'success': False, 'error': '获取开播地点数据失败'}), 500


@battle_record_bp.route('/api/announcements/<announcement_id>')
@roles_accepted('gicho', 'kancho')
def api_announcement_detail(announcement_id):
    """获取通告详情用于预填"""
    try:
        announcement = Announcement.objects.get(id=announcement_id)

        return jsonify({
            'success': True,
            'announcement': {
                'id': str(announcement.id),
                'pilot_id': str(announcement.pilot.id),
                'pilot_name': announcement.pilot.nickname,
                'start_time': utc_to_local(announcement.start_time).isoformat(),
                'end_time': utc_to_local(announcement.end_time).isoformat(),
                'x_coord': announcement.x_coord,
                'y_coord': announcement.y_coord,
                'z_coord': announcement.z_coord,
                'work_mode': WorkMode.OFFLINE.value,
                'owner_id': str(announcement.pilot.owner.id) if announcement.pilot.owner else '',
                'owner_name': announcement.pilot.owner.nickname or announcement.pilot.owner.username if announcement.pilot.owner else ''
            }
        })

    except Announcement.DoesNotExist:
        return jsonify({'success': False, 'error': '通告不存在'}), 404
    except Exception as e:
        logger.error(f"获取通告详情失败: {e}")
        return jsonify({'success': False, 'error': '获取通告详情失败'}), 500


@battle_record_bp.route('/api/related-announcements')
@roles_accepted('gicho', 'kancho')
def api_related_announcements():
    """根据机师返回昨天/今天/明天的通告列表（本地时区计算）。

    返回：[{id, label}]，label格式：yyyy-mm-dd 星期M N小时 @X-Y-Z
    排序：今天在前，随后昨天、明天。
    """
    try:
        pilot_id = request.args.get('pilot_id')
        if not pilot_id:
            return jsonify({'success': True, 'announcements': []})

        try:
            pilot = Pilot.objects.get(id=pilot_id)
        except Pilot.DoesNotExist:
            return jsonify({'success': True, 'announcements': []})

        now_utc = get_current_utc_time()
        now_local = utc_to_local(now_utc)

        today_local_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_local_start = today_local_start + timedelta(days=1)
        day_after_tomorrow_local_start = today_local_start + timedelta(days=2)
        yesterday_local_start = today_local_start - timedelta(days=1)

        range_start_utc = local_to_utc(yesterday_local_start)
        range_end_utc = local_to_utc(day_after_tomorrow_local_start)

        candidates = Announcement.objects(pilot=pilot, start_time__gte=range_start_utc, start_time__lt=range_end_utc)

        weekday_names = ['一', '二', '三', '四', '五', '六', '日']

        result_today = []
        result_yesterday = []
        result_tomorrow = []

        for ann in candidates:
            local_dt = utc_to_local(ann.start_time)
            if today_local_start <= local_dt < tomorrow_local_start:
                bucket = result_today
            elif yesterday_local_start <= local_dt < today_local_start:
                bucket = result_yesterday
            elif tomorrow_local_start <= local_dt < day_after_tomorrow_local_start:
                bucket = result_tomorrow
            else:
                continue

            date_str = local_dt.strftime('%Y-%m-%d')
            weekday_str = f"星期{weekday_names[local_dt.weekday()]}"
            duration_str = f"{ann.duration_hours}小时" if ann.duration_hours == int(ann.duration_hours) else f"{ann.duration_hours}小时"
            label = f"{date_str} {weekday_str} {duration_str} @{ann.x_coord}-{ann.y_coord}-{ann.z_coord}"
            bucket.append({'id': str(ann.id), 'label': label, 'local_ts': local_dt.timestamp()})

        result_today.sort(key=lambda x: x['local_ts'])
        result_yesterday.sort(key=lambda x: x['local_ts'])
        result_tomorrow.sort(key=lambda x: x['local_ts'])

        merged = result_today + result_yesterday + result_tomorrow
        for item in merged:
            item.pop('local_ts', None)

        return jsonify({'success': True, 'announcements': merged})

    except Exception as e:
        logger.error(f"获取关联开播记录失败: {e}")
        return jsonify({'success': False, 'error': '获取关联通告失败'}), 500
