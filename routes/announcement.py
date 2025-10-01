# pylint: disable=no-member
import calendar
import json
from datetime import datetime, timedelta

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for)
from flask_security import current_user, roles_accepted
from mongoengine import DoesNotExist, ValidationError

from models.announcement import (Announcement, AnnouncementChangeLog, RecurrenceType)
from models.battle_area import BattleArea
from models.pilot import Pilot, Rank, Status
from models.user import User
from utils.filter_state import persist_and_restore_filters
from utils.logging_setup import get_logger
from utils.timezone_helper import (format_local_datetime, get_current_local_datetime_for_input, get_current_local_time, get_current_month_last_day_for_input,
                                   local_to_utc, parse_local_date_to_end_datetime, parse_local_datetime, utc_to_local)

logger = get_logger('announcement')

announcement_bp = Blueprint('announcement', __name__)


def _get_client_ip():
    """获取客户端IP地址"""
    return request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR')


def _record_changes(announcement, old_data, user, ip_address):
    """记录通告字段变更（主播字段不再记录变更）"""
    changes = []
    field_mapping = {
        'battle_area': str(announcement.battle_area.id) if announcement.battle_area else None,
        'x_coord': announcement.x_coord,
        'y_coord': announcement.y_coord,
        'z_coord': announcement.z_coord,
        'start_time': announcement.start_time.isoformat() if announcement.start_time else None,
        'duration_hours': announcement.duration_hours,
        'recurrence_type': announcement.recurrence_type.value if announcement.recurrence_type else None,
        'recurrence_pattern': announcement.recurrence_pattern,
        'recurrence_end': announcement.recurrence_end.isoformat() if announcement.recurrence_end else None,
    }

    for field_name, new_value in field_mapping.items():
        old_value = old_data.get(field_name)
        if str(old_value) != str(new_value):
            change_log = AnnouncementChangeLog(announcement_id=announcement,
                                               user_id=user,
                                               field_name=field_name,
                                               old_value=str(old_value) if old_value is not None else '',
                                               new_value=str(new_value) if new_value is not None else '',
                                               ip_address=ip_address)
            changes.append(change_log)

    if changes:
        AnnouncementChangeLog.objects.insert(changes)
        logger.info('记录通告变更：%s，共%d个字段', announcement.id, len(changes))


def _get_pilot_choices():
    """获取机师选择列表，按所属、阶级、昵称排序"""
    pilots = Pilot.objects.all()

    owner_groups = {}
    no_owner_pilots = []

    for pilot in pilots:
        if pilot.owner:
            owner_key = pilot.owner.nickname or pilot.owner.username
            if owner_key not in owner_groups:
                owner_groups[owner_key] = []
            owner_groups[owner_key].append(pilot)
        else:
            no_owner_pilots.append(pilot)

    choices = [('', '请选择机师')]

    for owner_name in sorted(owner_groups.keys()):
        pilots_in_group = owner_groups[owner_name]
        pilots_in_group.sort(key=lambda p: (p.rank.value, p.nickname))
        for pilot in pilots_in_group:
            display_name = f"{pilot.nickname}[{pilot.real_name or ''}] - {owner_name}"
            choices.append((str(pilot.id), display_name))

    if no_owner_pilots:
        no_owner_pilots.sort(key=lambda p: (p.rank.value, p.nickname))
        for pilot in no_owner_pilots:
            display_name = f"{pilot.nickname}[{pilot.real_name or ''}] - 无所属"
            choices.append((str(pilot.id), display_name))

    return choices


def _get_battle_area_choices():
    """获取战斗区域选择列表"""
    areas = BattleArea.objects(availability='可用').order_by('x_coord', 'y_coord', 'z_coord')

    x_groups = {}
    for area in areas:
        if area.x_coord not in x_groups:
            x_groups[area.x_coord] = {}
        if area.y_coord not in x_groups[area.x_coord]:
            x_groups[area.x_coord][area.y_coord] = []
        x_groups[area.x_coord][area.y_coord].append(area)

    return x_groups


def _render_new_template(form=None, conflicts=None):
    """渲染新建通告模板的辅助函数"""
    context = {
        'battle_area_choices': _get_battle_area_choices(),
        'default_start_time': get_current_local_datetime_for_input(),
        'default_recurrence_end_date': get_current_month_last_day_for_input()
    }
    if form:
        context['form'] = form
    if conflicts:
        context['conflicts'] = conflicts
    return render_template('announcements/new.html', **context)


def _get_filter_choices():
    """获取筛选选项"""
    pilots = Pilot.objects.all()
    areas = BattleArea.objects.all()

    owners = set()
    for pilot in pilots:
        if pilot.owner:
            owners.add((str(pilot.owner.id), pilot.owner.nickname or pilot.owner.username))
    owner_choices = [('', '全部所属')] + sorted(list(owners), key=lambda x: x[1])

    x_coords = set()
    for area in areas:
        x_coords.add(area.x_coord)
    x_choices = [('', '全部基地')] + [(x, x) for x in sorted(x_coords)]

    time_choices = [('two_days', '这两天'), ('seven_days', '近7天'), ('today', '今天')]

    return {'owner_choices': owner_choices, 'x_choices': x_choices, 'time_choices': time_choices}


@announcement_bp.route('/')
@roles_accepted('gicho', 'kancho')
def list_announcements():
    """通告列表页面"""
    filters = persist_and_restore_filters(
        'announcements_list',
        allowed_keys=['owner', 'x', 'time'],
        default_filters={
            'owner': '',
            'x': '',
            'time': 'two_days'
        },
    )
    owner_filter = filters.get('owner') or None
    x_filter = filters.get('x') or None
    time_scope = filters.get('time') or 'two_days'


    query = Announcement.objects


    if owner_filter:
        try:
            owner_user = User.objects.get(id=owner_filter)
            owner_pilots = Pilot.objects(owner=owner_user)
            pilot_ids = [pilot.id for pilot in owner_pilots]
            query = query.filter(pilot__in=pilot_ids)
        except DoesNotExist:
            pass

    if x_filter:
        query = query.filter(x_coord=x_filter)

    if time_scope == 'two_days':
        current_local = get_current_local_time()
        today_local_start = current_local.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_local_start = today_local_start - timedelta(days=1)
        day_after_tomorrow_local_start = today_local_start + timedelta(days=2)
        range_start_utc = local_to_utc(yesterday_local_start)
        range_end_utc = local_to_utc(day_after_tomorrow_local_start)
        query = query.filter(start_time__gte=range_start_utc, start_time__lt=range_end_utc)
    elif time_scope == 'today':
        current_local = get_current_local_time()
        today_local_start = current_local.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_local_start = today_local_start + timedelta(days=1)
        range_start_utc = local_to_utc(today_local_start)
        range_end_utc = local_to_utc(tomorrow_local_start)
        query = query.filter(start_time__gte=range_start_utc, start_time__lt=range_end_utc)
    elif time_scope == 'seven_days':
        current_local = get_current_local_time()
        today_local_start = current_local.replace(hour=0, minute=0, second=0, microsecond=0)
        seven_days_later_local_start = today_local_start + timedelta(days=7)
        range_start_utc = local_to_utc(today_local_start)
        range_end_utc = local_to_utc(seven_days_later_local_start)
        query = query.filter(start_time__gte=range_start_utc, start_time__lt=range_end_utc)

    announcements = list(query.limit(100))
    announcements.sort(key=lambda a: ((utc_to_local(a.start_time).date() if a.start_time else None), (a.pilot.nickname or '') if a.pilot else ''))

    filter_choices = _get_filter_choices()

    return render_template('announcements/list.html',
                           announcements=announcements,
                           owner_filter=owner_filter,
                           x_filter=x_filter,
                           time_scope=time_scope,
                           **filter_choices)


@announcement_bp.route('/<announcement_id>')
@roles_accepted('gicho', 'kancho')
def announcement_detail(announcement_id):
    """通告详情页面"""
    try:
        announcement = Announcement.objects.get(id=announcement_id)


        related_announcements = []
        if announcement.parent_announcement:
            related_announcements = Announcement.objects(parent_announcement=announcement.parent_announcement).order_by('start_time')
        elif announcement.recurrence_type != RecurrenceType.NONE:
            related_announcements = Announcement.objects(parent_announcement=announcement).order_by('start_time')

        from_param = request.args.get('from')
        date_param = request.args.get('date')

        return render_template('announcements/detail.html',
                               announcement=announcement,
                               related_announcements=related_announcements,
                               from_param=from_param,
                               date_param=date_param)
    except DoesNotExist:
        abort(404)


@announcement_bp.route('/new', methods=['GET', 'POST'])
@roles_accepted('gicho', 'kancho')
def new_announcement():
    """新建通告"""
    if request.method == 'POST':
        try:
            pilot_id = request.form.get('pilot')
            battle_area_id = request.form.get('battle_area')
            start_time_str = request.form.get('start_time')
            duration_hours = request.form.get('duration_hours', type=float)
            recurrence_type = request.form.get('recurrence_type')

            if not pilot_id:
                flash('请选择机师', 'error')
                return _render_new_template(form=request.form)

            if not battle_area_id:
                flash('请选择开播地点', 'error')
                return _render_new_template(form=request.form)

            if not start_time_str:
                flash('请选择开始时间', 'error')
                return _render_new_template(form=request.form)

            if not duration_hours:
                flash('请输入时长', 'error')
                return _render_new_template(form=request.form)

            try:
                pilot = Pilot.objects.get(id=pilot_id)
                battle_area = BattleArea.objects.get(id=battle_area_id)
            except DoesNotExist:
                flash('主播或开播地点不存在', 'error')
                return _render_new_template(form=request.form)


            start_time = parse_local_datetime(start_time_str)
            if start_time is None:
                flash('时间格式错误', 'error')
                return _render_new_template(form=request.form)

            announcement = Announcement(pilot=pilot,
                                        battle_area=battle_area,
                                        x_coord=battle_area.x_coord,
                                        y_coord=battle_area.y_coord,
                                        z_coord=battle_area.z_coord,
                                        start_time=start_time,
                                        duration_hours=duration_hours,
                                        created_by=current_user)

            if recurrence_type and recurrence_type != 'NONE':
                announcement.recurrence_type = getattr(RecurrenceType, recurrence_type)

                pattern_type = getattr(RecurrenceType, recurrence_type).value.lower()
                pattern = {'type': pattern_type}

                if recurrence_type == 'DAILY':
                    interval = request.form.get('daily_interval', 1, type=int)
                    pattern['interval'] = interval
                elif recurrence_type == 'WEEKLY':
                    interval = request.form.get('weekly_interval', 1, type=int)
                    days_of_week = request.form.getlist('days_of_week')
                    pattern['interval'] = interval
                    pattern['days_of_week'] = [int(day) for day in days_of_week if str(day).isdigit()]
                elif recurrence_type == 'CUSTOM':
                    custom_dates = request.form.get('custom_dates', '').strip()
                    if custom_dates:
                        try:
                            dates = [date.strip() for date in custom_dates.split('\n') if date.strip()]
                            pattern['specific_dates'] = dates
                        except Exception:
                            flash('自定义日期格式错误', 'error')
                            return _render_new_template(form=request.form)

                recurrence_end_date_str = request.form.get('recurrence_end_date')
                if recurrence_end_date_str:
                    recurrence_end = parse_local_date_to_end_datetime(recurrence_end_date_str)
                    if recurrence_end:
                        announcement.recurrence_end = recurrence_end

                announcement.recurrence_pattern = json.dumps(pattern)

            announcement.save()

            instances = Announcement.generate_recurrence_instances(announcement)

            all_conflicts = []
            for instance in instances:
                conflicts = instance.check_conflicts(exclude_self=True)
                if conflicts['area_conflicts'] or conflicts['pilot_conflicts']:
                    all_conflicts.extend(conflicts['area_conflicts'])
                    all_conflicts.extend(conflicts['pilot_conflicts'])

            if all_conflicts:
                announcement.delete()
                flash('存在时间冲突，无法创建通告', 'error')
                return _render_new_template(form=request.form, conflicts=all_conflicts)

            for instance in instances[1:]:  # 跳过第一个（基础通告）
                instance.save()

            flash('创建通告成功', 'success')
            logger.info('用户%s创建通告：机师%s，时间%s', current_user.username, pilot.nickname, start_time)
            return redirect(url_for('announcement.list_announcements'))

        except (ValueError, ValidationError) as e:
            flash(f'数据验证失败：{str(e)}', 'error')
            return _render_new_template(form=request.form)
        except Exception as e:
            flash(f'创建失败：{str(e)}', 'error')
            logger.error('创建通告失败：%s', str(e))
            return _render_new_template(form=request.form)

    return _render_new_template()


@announcement_bp.route('/<announcement_id>/edit', methods=['GET', 'POST'])
@roles_accepted('gicho', 'kancho')
def edit_announcement(announcement_id):
    """编辑通告"""
    try:
        announcement = Announcement.objects.get(id=announcement_id)


        if request.method == 'POST':
            edit_scope = request.form.get('edit_scope', 'this_only')

            old_data = {
                'battle_area': str(announcement.battle_area.id) if announcement.battle_area else None,
                'x_coord': announcement.x_coord,
                'y_coord': announcement.y_coord,
                'z_coord': announcement.z_coord,
                'start_time': announcement.start_time.isoformat() if announcement.start_time else None,
                'duration_hours': announcement.duration_hours,
                'recurrence_type': announcement.recurrence_type.value if announcement.recurrence_type else None,
                'recurrence_pattern': announcement.recurrence_pattern,
                'recurrence_end': announcement.recurrence_end.isoformat() if announcement.recurrence_end else None,
            }

            try:
                pilot_id = request.form.get('pilot')
                battle_area_id = request.form.get('battle_area')
                duration_hours = request.form.get('duration_hours', type=float)

                if edit_scope == 'future_all':
                    start_date_str = request.form.get('start_date')
                    start_hour = request.form.get('start_hour')
                    start_minute = request.form.get('start_minute')
                    if not start_date_str or not start_hour or not start_minute:
                        flash('请填写所有必填项', 'error')
                        return render_template('announcements/edit.html', announcement=announcement, battle_area_choices=_get_battle_area_choices())
                    start_time_str = f"{start_date_str}T{start_hour}:{start_minute}"
                else:
                    start_time_str = request.form.get('start_time')

                logger.debug('编辑通告表单数据 - pilot_id: %s, battle_area_id: %s, start_time: %s, duration_hours: %s', pilot_id, battle_area_id, start_time_str,
                             duration_hours)

                if not battle_area_id or not start_time_str or not duration_hours:
                    logger.debug('必填项验证失败 - battle_area_id: %s, start_time: %s, duration_hours: %s', battle_area_id, start_time_str,
                                 duration_hours)
                    flash('请填写所有必填项', 'error')
                    return render_template('announcements/edit.html', announcement=announcement, battle_area_choices=_get_battle_area_choices())

                try:
                    battle_area = BattleArea.objects.get(id=battle_area_id)
                except DoesNotExist:
                    flash('战斗区域不存在', 'error')
                    return render_template('announcements/edit.html', announcement=announcement, battle_area_choices=_get_battle_area_choices())


                start_time = parse_local_datetime(start_time_str)
                if start_time is None:
                    flash('时间格式错误', 'error')
                    return render_template('announcements/edit.html', announcement=announcement, battle_area_choices=_get_battle_area_choices())

                if edit_scope == 'future_all' and announcement.is_in_recurrence_group:
                    future_announcements = announcement.split_recurrence_group_from_current()

                    parsed_start_time = parse_local_datetime(start_time_str)
                    if parsed_start_time is None:
                        flash('时间格式错误', 'error')
                        return render_template('announcements/edit.html', announcement=announcement, battle_area_choices=_get_battle_area_choices())

                    for ann in future_announcements:
                        ann.battle_area = battle_area
                        ann.x_coord = battle_area.x_coord
                        ann.y_coord = battle_area.y_coord
                        ann.z_coord = battle_area.z_coord
                        ann.duration_hours = duration_hours

                        if ann.id != announcement.id:
                            new_time = parsed_start_time.time()
                            ann.start_time = ann.start_time.replace(hour=new_time.hour, minute=new_time.minute, second=new_time.second)
                        else:
                            ann.start_time = parsed_start_time

                    all_conflicts = []
                    for ann in future_announcements:
                        conflicts = ann.check_conflicts(exclude_self=True)
                        all_conflicts.extend(conflicts['area_conflicts'])
                        all_conflicts.extend(conflicts['pilot_conflicts'])

                    if all_conflicts:
                        flash('存在时间冲突，无法保存修改', 'error')
                        return render_template('announcements/edit.html',
                                               announcement=announcement,
                                               battle_area_choices=_get_battle_area_choices(),
                                               conflicts=all_conflicts)

                    for ann in future_announcements:
                        ann.save()
                        _record_changes(ann, old_data, current_user, _get_client_ip())

                    flash('更新未来循环通告成功', 'success')
                    logger.info('用户%s更新未来循环通告：%s（共%d个）', current_user.username, announcement.id, len(future_announcements))

                else:
                    announcement.battle_area = battle_area
                    announcement.x_coord = battle_area.x_coord
                    announcement.y_coord = battle_area.y_coord
                    announcement.z_coord = battle_area.z_coord
                    announcement.start_time = start_time
                    announcement.duration_hours = duration_hours

                    conflicts = announcement.check_conflicts(exclude_self=True)
                    if conflicts['area_conflicts'] or conflicts['pilot_conflicts']:
                        flash('存在时间冲突，无法保存修改', 'error')
                        all_conflicts = conflicts['area_conflicts'] + conflicts['pilot_conflicts']
                        return render_template('announcements/edit.html',
                                               announcement=announcement,
                                               battle_area_choices=_get_battle_area_choices(),
                                               conflicts=all_conflicts)

                    announcement.save()

                    _record_changes(announcement, old_data, current_user, _get_client_ip())

                    flash('更新通告成功', 'success')
                    logger.info('用户%s更新通告：%s', current_user.username, announcement.id)

                from_param = request.args.get('from')
                date_param = request.args.get('date')

                if from_param == 'calendar' and date_param:
                    return redirect(url_for('announcement.announcement_detail', announcement_id=announcement_id, **{'from': 'calendar', 'date': date_param}))
                else:
                    return redirect(url_for('announcement.announcement_detail', announcement_id=announcement_id))

            except (ValueError, ValidationError) as e:
                flash(f'数据验证失败：{str(e)}', 'error')
                return render_template('announcements/edit.html', announcement=announcement, battle_area_choices=_get_battle_area_choices())
            except Exception as e:
                flash(f'更新失败：{str(e)}', 'error')
                logger.error('更新通告失败：%s', str(e))
                return render_template('announcements/edit.html', announcement=announcement, battle_area_choices=_get_battle_area_choices())

        return render_template('announcements/edit.html', announcement=announcement, battle_area_choices=_get_battle_area_choices())
    except DoesNotExist:
        abort(404)


@announcement_bp.route('/<announcement_id>/delete', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def delete_announcement(announcement_id):
    """删除通告"""
    try:
        announcement = Announcement.objects.get(id=announcement_id)


        delete_scope = request.form.get('delete_scope', 'this_only')

        if delete_scope == 'future_all' and announcement.is_in_recurrence_group:
            future_announcements = announcement.get_future_announcements_in_group(include_self=True)

            count = len(future_announcements)
            for ann in future_announcements:
                ann.delete()

            flash(f'删除未来循环通告成功（共{count}个）', 'success')
            logger.info('用户%s删除未来循环通告：%s（共%d个）', current_user.username, announcement.id, count)
        else:
            announcement.delete()
            flash('删除通告成功', 'success')
            logger.info('用户%s删除通告：%s', current_user.username, announcement.id)

        from_param = request.form.get('from')
        date_param = request.form.get('date')

        if from_param == 'calendar' and date_param:
            return redirect(url_for('calendar.day_view', date=date_param))
        else:
            return redirect(url_for('announcement.list_announcements'))

    except DoesNotExist:
        abort(404)
    except Exception as e:
        flash(f'删除失败：{str(e)}', 'error')
        logger.error('删除通告失败：%s', str(e))
        return redirect(url_for('announcement.list_announcements'))


@announcement_bp.route('/check-conflicts', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def check_conflicts():
    """冲突检查API"""
    try:
        data = request.get_json()

        pilot_id = data.get('pilot_id')
        battle_area_id = data.get('battle_area_id')
        start_time_str = data.get('start_time')
        duration_hours = data.get('duration_hours')
        exclude_id = data.get('exclude_id')  # 编辑时排除自身
        edit_scope = data.get('edit_scope', 'this_only')  # 编辑范围：this_only 或 future_all

        recurrence_type = data.get('recurrence_type', 'NONE')
        recurrence_pattern = data.get('recurrence_pattern', {})
        recurrence_end_date = data.get('recurrence_end_date')

        if not all([pilot_id, battle_area_id, start_time_str, duration_hours]):
            return jsonify({'success': False, 'error': '缺少必要参数'}), 400

        try:
            pilot = Pilot.objects.get(id=pilot_id)
            battle_area = BattleArea.objects.get(id=battle_area_id)
            start_time = parse_local_datetime(start_time_str)
            if start_time is None:
                return jsonify({'success': False, 'error': '时间格式错误'}), 400
            end_time = None
            if recurrence_end_date:
                end_time = parse_local_date_to_end_datetime(recurrence_end_date)
                if end_time is None:
                    return jsonify({'success': False, 'error': '重复结束日期格式错误'}), 400
        except DoesNotExist as e:
            return jsonify({'success': False, 'error': f'参数错误：{str(e)}'}), 400

        temp_announcement = Announcement(
            pilot=pilot,
            battle_area=battle_area,
            start_time=start_time,
            duration_hours=duration_hours,
            recurrence_end=end_time,
            x_coord=battle_area.x_coord,
            y_coord=battle_area.y_coord,
            z_coord=battle_area.z_coord)

        if recurrence_type and recurrence_type != 'NONE':
            temp_announcement.recurrence_type = getattr(RecurrenceType, recurrence_type)
            temp_announcement.recurrence_pattern = json.dumps(recurrence_pattern)
        else:
            temp_announcement.recurrence_type = RecurrenceType.NONE

        if exclude_id:
            temp_announcement.id = exclude_id

        instances = []
        planned_instances = []

        if edit_scope == 'future_all' and exclude_id:
            try:
                original_announcement = Announcement.objects.get(id=exclude_id)
                if original_announcement.is_in_recurrence_group:
                    future_announcements = original_announcement.get_future_announcements_in_group(include_self=True)

                    for ann in future_announcements:
                        updated_instance = Announcement(
                            pilot=pilot,
                            battle_area=battle_area,
                            start_time=ann.start_time,  # 保持原时间
                            duration_hours=duration_hours,
                            x_coord=battle_area.x_coord,
                            y_coord=battle_area.y_coord,
                            z_coord=battle_area.z_coord)

                        parsed_start_time = parse_local_datetime(start_time_str)
                        if parsed_start_time:
                            if ann.id != original_announcement.id:
                                new_time = parsed_start_time.time()
                                updated_instance.start_time = ann.start_time.replace(hour=new_time.hour, minute=new_time.minute, second=new_time.second)
                            else:
                                updated_instance.start_time = parsed_start_time

                        instances.append(updated_instance)

                        planned_instances.append({
                            'pilot_name': updated_instance.pilot.nickname,
                            'start_time': format_local_datetime(updated_instance.start_time, '%Y-%m-%d %H:%M'),
                            'duration': f"{updated_instance.duration_hours}小时",
                            'coords': f"{updated_instance.x_coord} - {updated_instance.y_coord} - {updated_instance.z_coord}"
                        })
                else:
                    instances = [temp_announcement]
                    planned_instances.append({
                        'pilot_name': temp_announcement.pilot.nickname,
                        'start_time': format_local_datetime(temp_announcement.start_time, '%Y-%m-%d %H:%M'),
                        'duration': f"{temp_announcement.duration_hours}小时",
                        'coords': f"{temp_announcement.x_coord} - {temp_announcement.y_coord} - {temp_announcement.z_coord}"
                    })
            except DoesNotExist:
                instances = [temp_announcement]
                planned_instances.append({
                    'pilot_name': temp_announcement.pilot.nickname,
                    'start_time': format_local_datetime(temp_announcement.start_time, '%Y-%m-%d %H:%M'),
                    'duration': f"{temp_announcement.duration_hours}小时",
                    'coords': f"{temp_announcement.x_coord} - {temp_announcement.y_coord} - {temp_announcement.z_coord}"
                })
        else:
            if recurrence_type != 'NONE':
                instances = Announcement.generate_recurrence_instances(temp_announcement)
            else:
                instances = [temp_announcement]

            for instance in instances:
                planned_instances.append({
                    'pilot_name': instance.pilot.nickname,
                    'start_time': format_local_datetime(instance.start_time, '%Y-%m-%d %H:%M'),
                    'duration': f"{instance.duration_hours}小时",
                    'coords': f"{instance.x_coord} - {instance.y_coord} - {instance.z_coord}"
                })

        all_conflicts = []

        exclude_ids = []
        if edit_scope == 'future_all' and exclude_id:
            try:
                original_announcement = Announcement.objects.get(id=exclude_id)
                if original_announcement.is_in_recurrence_group:
                    future_announcements = original_announcement.get_future_announcements_in_group(include_self=True)
                    exclude_ids = [str(ann.id) for ann in future_announcements]
            except DoesNotExist:
                pass

        for instance in instances:
            conflicts = instance.check_conflicts(exclude_self=bool(exclude_id), exclude_ids=exclude_ids)

            for conflict in conflicts['area_conflicts']:
                all_conflicts.append({
                    'type': '区域冲突',
                    'instance_time': format_local_datetime(instance.start_time, '%Y-%m-%d %H:%M'),
                    'announcement_id': str(conflict['announcement'].id),
                    'pilot_name': conflict['announcement'].pilot.nickname,
                    'start_time': format_local_datetime(conflict['announcement'].start_time, '%Y-%m-%d %H:%M'),
                    'duration': conflict['announcement'].duration_display,
                    'coords': f"{conflict['announcement'].x_coord} - {conflict['announcement'].y_coord} - {conflict['announcement'].z_coord}"
                })

            for conflict in conflicts['pilot_conflicts']:
                all_conflicts.append({
                    'type': '机师冲突',
                    'instance_time': format_local_datetime(instance.start_time, '%Y-%m-%d %H:%M'),
                    'announcement_id': str(conflict['announcement'].id),
                    'pilot_name': conflict['announcement'].pilot.nickname,
                    'start_time': format_local_datetime(conflict['announcement'].start_time, '%Y-%m-%d %H:%M'),
                    'duration': conflict['announcement'].duration_display,
                    'coords': f"{conflict['announcement'].x_coord} - {conflict['announcement'].y_coord} - {conflict['announcement'].z_coord}"
                })

        return jsonify({'success': True, 'has_conflicts': len(all_conflicts) > 0, 'conflicts': all_conflicts, 'planned_instances': planned_instances})

    except Exception as e:
        logger.error('冲突检查失败：%s', str(e))
        return jsonify({'success': False, 'error': '冲突检查失败'}), 500


@announcement_bp.route('/<announcement_id>/changes')
@roles_accepted('gicho', 'kancho')
def announcement_changes(announcement_id):
    """通告变更记录"""
    try:
        announcement = Announcement.objects.get(id=announcement_id)


        changes = AnnouncementChangeLog.objects(announcement_id=announcement).order_by('-change_time').limit(100)

        return jsonify({
            'success':
            True,
            'changes': [{
                'field_name': change.field_display_name,
                'old_value': change.old_value,
                'new_value': change.new_value,
                'change_time': change.change_time.strftime('%Y-%m-%d %H:%M:%S'),
                'user_name': change.user_id.nickname or change.user_id.username if change.user_id else '未知用户',
                'ip_address': change.ip_address or '未知'
            } for change in changes]
        })
    except DoesNotExist:
        return jsonify({'success': False, 'error': '通告不存在'}), 404
    except Exception as e:
        logger.error('获取变更记录失败：%s', str(e))
        return jsonify({'success': False, 'error': '获取变更记录失败'}), 500


@announcement_bp.route('/api/areas/<x_coord>')
@roles_accepted('gicho', 'kancho')
def get_y_coords(x_coord):
    """根据X坐标获取Y坐标选项"""
    try:
        areas = BattleArea.objects(x_coord=x_coord, availability='可用').only('y_coord')
        y_coords = sorted(list(set([area.y_coord for area in areas])))
        return jsonify({'success': True, 'y_coords': y_coords})
    except Exception as e:
        logger.error('获取Y坐标失败：%s', str(e))
        return jsonify({'success': False, 'error': '获取Y坐标失败'}), 500


@announcement_bp.route('/api/areas/<x_coord>/<y_coord>')
@roles_accepted('gicho', 'kancho')
def get_z_coords(x_coord, y_coord):
    """根据X、Y坐标获取Z坐标选项"""
    try:
        areas = BattleArea.objects(x_coord=x_coord, y_coord=y_coord, availability='可用').only('z_coord')

        z_coords = [area.z_coord for area in areas]
        try:
            z_coords.sort(key=int)
        except ValueError:
            z_coords.sort()

        result = []
        for area in areas:
            if area.z_coord in z_coords:  # 保持排序
                result.append({'id': str(area.id), 'z_coord': area.z_coord})

        return jsonify({'success': True, 'areas': result})
    except Exception as e:
        logger.error('获取Z坐标失败：%s', str(e))
        return jsonify({'success': False, 'error': '获取Z坐标失败'}), 500


@announcement_bp.route('/api/pilots/by-owner/<owner_id>')
@roles_accepted('gicho', 'kancho')
def get_pilots_by_owner(owner_id):
    """根据所属获取机师选项"""
    try:
        if owner_id == 'none':
            pilots = Pilot.objects(owner=None).order_by('rank', 'nickname')
        else:
            owner = User.objects.get(id=owner_id)
            pilots = Pilot.objects(owner=owner).order_by('rank', 'nickname')

        result = []
        for pilot in pilots:
            result.append({'id': str(pilot.id), 'nickname': pilot.nickname, 'real_name': pilot.real_name or '', 'rank': pilot.rank.value})

        return jsonify({'success': True, 'pilots': result})
    except DoesNotExist:
        return jsonify({'success': False, 'error': '用户不存在'}), 404
    except Exception as e:
        logger.error('获取机师失败：%s', str(e))
        return jsonify({'success': False, 'error': '获取机师失败'}), 500


@announcement_bp.route('/api/pilot-filters')
@roles_accepted('gicho', 'kancho')
def get_pilot_filters():
    """获取机师筛选器选项"""
    try:
        pilots = Pilot.objects(status__in=['已征召', '已签约'])

        owners = set()
        for pilot in pilots:
            if pilot.owner:
                owners.add((str(pilot.owner.id), pilot.owner.nickname or pilot.owner.username))

        owner_choices = sorted(list(owners), key=lambda x: x[1])
        owner_options = [{'id': owner_id, 'name': owner_name} for owner_id, owner_name in owner_choices]

        rank_options = [
            Rank.CANDIDATE.value,
            Rank.TRAINEE.value,
            Rank.INTERN.value,
            Rank.OFFICIAL.value,
        ]

        return jsonify({'success': True, 'owners': owner_options, 'ranks': rank_options})
    except Exception as e:
        logger.error('获取筛选器选项失败：%s', str(e))
        return jsonify({'success': False, 'error': '获取筛选器选项失败'}), 500


@announcement_bp.route('/api/pilots-filtered')
@roles_accepted('gicho', 'kancho')
def get_pilots_filtered():
    """根据筛选条件获取机师列表"""
    try:
        owner_id = request.args.get('owner')
        rank = request.args.get('rank')

        query = Pilot.objects(status__in=['已招募', '已签约', '已征召'])

        if owner_id:
            try:
                owner = User.objects.get(id=owner_id)
                query = query.filter(owner=owner)
            except DoesNotExist:
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

        pilots = query.order_by('owner', 'rank', 'nickname')

        result = []
        for pilot in pilots:
            owner_name = pilot.owner.nickname or pilot.owner.username if pilot.owner else '无所属'
            age_str = f"({pilot.age})" if getattr(pilot, 'age', None) else ""
            try:
                gender_value = pilot.gender.value
            except Exception:
                gender_value = None
            gender_icon = '♂' if gender_value == 0 else ('♀' if gender_value == 1 else '?')
            display_name = f"{pilot.nickname}{age_str}[{pilot.status.value}]{gender_icon}"

            result.append({
                'id': str(pilot.id),
                'name': display_name,
                'nickname': pilot.nickname,
                'real_name': pilot.real_name or '',
                'age': pilot.age or '',
                'gender': gender_value,
                'rank': pilot.rank.value,
                'owner': owner_name
            })

        return jsonify({'success': True, 'pilots': result})
    except Exception as e:
        logger.error('获取筛选机师失败：%s', str(e))
        return jsonify({'success': False, 'error': '获取筛选机师失败'}), 500


@announcement_bp.route('/export', methods=['GET', 'POST'])
@roles_accepted('gicho', 'kancho')
def export_page():
    """通告导出页面"""
    if request.method == 'POST':
        try:
            pilot_id = request.form.get('pilot_id')
            year = request.form.get('year', type=int)
            month = request.form.get('month', type=int)

            if not pilot_id:
                flash('请选择机师', 'error')
                return render_template('announcements/export.html')

            if not year or not month:
                flash('请选择年月', 'error')
                return render_template('announcements/export.html')

            try:
                pilot = Pilot.objects.get(id=pilot_id)
            except DoesNotExist:
                flash('机师不存在', 'error')
                return render_template('announcements/export.html')

            table_data, venue_info = generate_export_table(pilot, year, month)

            return render_template('announcements/export_table.html', pilot=pilot, year=year, month=month, table_data=table_data, venue_info=venue_info)

        except Exception as e:
            logger.error('生成导出表格失败：%s', str(e))
            flash(f'生成失败：{str(e)}', 'error')
            return render_template('announcements/export.html')

    return render_template('announcements/export.html')


def get_pilot_choices():
    """获取机师选择列表（用于导出页面）"""
    pilots = Pilot.objects(status__in=['已征召', '已签约']).order_by('owner', 'rank', 'nickname')

    owner_groups = {}
    no_owner_pilots = []

    for pilot in pilots:
        if pilot.owner:
            owner_key = pilot.owner.nickname or pilot.owner.username
            if owner_key not in owner_groups:
                owner_groups[owner_key] = []
            owner_groups[owner_key].append(pilot)
        else:
            no_owner_pilots.append(pilot)

    choices = []

    for owner_name in sorted(owner_groups.keys()):
        pilots_in_group = owner_groups[owner_name]
        pilots_in_group.sort(key=lambda p: (p.rank.value, p.nickname))
        for pilot in pilots_in_group:
            choices.append({'id': str(pilot.id), 'nickname': pilot.nickname, 'real_name': pilot.real_name or '', 'owner': owner_name, 'rank': pilot.rank.value})

    if no_owner_pilots:
        no_owner_pilots.sort(key=lambda p: (p.rank.value, p.nickname))
        for pilot in no_owner_pilots:
            choices.append({'id': str(pilot.id), 'nickname': pilot.nickname, 'real_name': pilot.real_name or '', 'owner': '无所属', 'rank': pilot.rank.value})

    return choices


def get_monthly_announcements(pilot_id, year, month):
    """获取指定机师在指定月份的通告数据"""
    start_date = datetime(year, month, 1)
    if month == 12:
        end_date = datetime(year + 1, 1, 1)
    else:
        end_date = datetime(year, month + 1, 1)

    start_utc = local_to_utc(start_date)
    end_utc = local_to_utc(end_date)

    announcements = Announcement.objects(pilot=pilot_id, start_time__gte=start_utc, start_time__lt=end_utc).order_by('start_time')

    return list(announcements)


def generate_export_table(pilot, year, month):
    """生成导出表格数据"""
    announcements = get_monthly_announcements(pilot.id, year, month)

    venue_coords = set()

    announcements_by_date = {}
    for announcement in announcements:
        if announcement.x_coord:
            venue_coords.add(announcement.x_coord)

        local_time = utc_to_local(announcement.start_time)
        date_key = local_time.date()
        if date_key not in announcements_by_date:
            announcements_by_date[date_key] = []
        announcements_by_date[date_key].append(announcement)

    venue_info = ', '.join(sorted(venue_coords)) if venue_coords else None

    table_data = []
    days_in_month = calendar.monthrange(year, month)[1]

    for day in range(1, days_in_month + 1):
        date_obj = datetime(year, month, day).date()
        weekday_names = ['一', '二', '三', '四', '五', '六', '日']
        weekday = weekday_names[date_obj.weekday()]

        date_str = f"{month:02d}/{day:02d} 星期{weekday}"

        day_announcements = announcements_by_date.get(date_obj, [])

        if day_announcements:
            start_times = []
            durations = []
            equipments = []

            for ann in day_announcements:
                local_start = utc_to_local(ann.start_time)
                start_times.append(local_start.strftime('%H:%M'))
                durations.append(f"{ann.duration_hours}小时")

                equipment = f"{ann.y_coord}-{ann.z_coord}"
                if equipment not in equipments:
                    equipments.append(equipment)

            row_data = {
                'date': date_str,
                'time': ', '.join(start_times),  # 通告时间
                'equipment': ', '.join(equipments),  # 设备（Y-Z坐标）
                'duration': ', '.join(durations),  # 通告时长
                'work_content': '弹幕游戏直播'  # 固定工作内容
            }
        else:
            row_data = {'date': date_str, 'time': '', 'equipment': '', 'duration': '', 'work_content': ''}

        table_data.append(row_data)

    return table_data, venue_info


@announcement_bp.route('/cleanup')
@roles_accepted('gicho', 'kancho')
def cleanup_page():
    """通告清理页面：列出状态为流失且从明天开始仍有通告的主播"""
    current_local = get_current_local_time()
    tomorrow_local_start = current_local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
    tomorrow_utc_start = local_to_utc(tomorrow_local_start)

    future_announcements = Announcement.objects(start_time__gte=tomorrow_utc_start).only('pilot')
    pilot_id_to_count = {}
    for ann in future_announcements:
        if ann.pilot:
            pid = str(ann.pilot.id)
            pilot_id_to_count[pid] = pilot_id_to_count.get(pid, 0) + 1

    pilots = Pilot.objects(id__in=list(pilot_id_to_count.keys()), status__in=[Status.FALLEN, Status.FALLEN_OLD])

    items = []
    for p in pilots:
        owner_name = p.owner.nickname or p.owner.username if p.owner else '无所属'
        items.append({
            'id': str(p.id),
            'nickname': p.nickname,
            'real_name': p.real_name or '',
            'owner_name': owner_name,
            'future_count': pilot_id_to_count.get(str(p.id), 0)
        })

    items.sort(key=lambda x: x['nickname'])

    return render_template('announcements/cleanup.html', items=items)


@announcement_bp.route('/cleanup/delete-future', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def cleanup_delete_future():
    """删除指定主播从明天开始的所有通告（不可恢复）"""
    try:
        pilot_id = request.form.get('pilot_id')
        if not pilot_id:
            flash('缺少参数：pilot_id', 'error')
            return redirect(url_for('announcement.cleanup_page'))

        current_local = get_current_local_time()
        tomorrow_local_start = current_local.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
        tomorrow_utc_start = local_to_utc(tomorrow_local_start)

        anns = Announcement.objects(pilot=pilot_id, start_time__gte=tomorrow_utc_start)
        count = anns.count()
        for ann in anns:
            ann.delete()

        flash(f'已删除该主播明天开始的所有通告，共{count}条', 'success')
        logger.info('用户%s清理通告：pilot=%s，从明天开始删除共%d条', current_user.username, pilot_id, count)
        return redirect(url_for('announcement.cleanup_page'))
    except Exception as e:
        logger.error('清理通告失败：%s', str(e))
        flash(f'清理失败：{str(e)}', 'error')
        return redirect(url_for('announcement.cleanup_page'))
