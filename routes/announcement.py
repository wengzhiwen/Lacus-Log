# pylint: disable=no-member
import calendar
from datetime import datetime, timedelta

from flask import (Blueprint, abort, flash, redirect, render_template, request, url_for)
from flask_security import current_user, roles_accepted
from mongoengine import DoesNotExist

from models.announcement import (Announcement, AnnouncementChangeLog, RecurrenceType)
from models.pilot import Pilot, Status
from utils.filter_state import persist_and_restore_filters
from utils.logging_setup import get_logger
from utils.timezone_helper import (get_current_local_datetime_for_input, get_current_local_time, get_current_month_last_day_for_input, local_to_utc,
                                   utc_to_local)

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

    return render_template('announcements/list.html', filters=filters)


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


@announcement_bp.route('/new', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def new_announcement():
    """新建通告"""
    context = {
        'default_start_time': get_current_local_datetime_for_input(),
        'default_recurrence_end_date': get_current_month_last_day_for_input(),
    }
    return render_template('announcements/new.html', **context)


@announcement_bp.route('/<announcement_id>/edit', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def edit_announcement(announcement_id):
    """编辑通告"""
    try:
        announcement = Announcement.objects.get(id=announcement_id)
        edit_scope = request.args.get('edit_scope', 'this_only') or 'this_only'
        context = {
            'announcement': announcement,
            'edit_scope': edit_scope,
            'default_recurrence_end_date': get_current_month_last_day_for_input(),
        }
        return render_template('announcements/edit.html', **context)
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
