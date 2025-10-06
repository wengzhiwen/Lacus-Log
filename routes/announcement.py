# pylint: disable=no-member
from flask import (Blueprint, abort, flash, redirect, render_template, request,
                   url_for)
from flask_security import current_user, roles_accepted
from mongoengine import DoesNotExist

from models.announcement import (Announcement, AnnouncementChangeLog,
                                 RecurrenceType)
from models.pilot import Pilot
from utils.filter_state import persist_and_restore_filters
from utils.logging_setup import get_logger
from utils.timezone_helper import (get_current_local_datetime_for_input,
                                   get_current_month_last_day_for_input)

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


@announcement_bp.route('/cleanup')
@roles_accepted('gicho', 'kancho')
def cleanup_page():
    """渲染通告清理页面。"""
    return render_template('announcements/cleanup.html')


@announcement_bp.route('/export')
@roles_accepted('gicho', 'kancho')
def export_page():
    """渲染通告导出页面。"""
    return render_template('announcements/export.html')


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


def _cleanup_orphaned_references(announcement_id):
    """清理指向已删除通告的孤立引用"""
    child_announcements = Announcement.objects(parent_announcement=announcement_id)
    for child in child_announcements:
        child.parent_announcement = None
        child.save()


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
                _cleanup_orphaned_references(ann.id)
                ann.delete()

            flash(f'删除未来循环通告成功（共{count}个）', 'success')
            logger.info('用户%s删除未来循环通告：%s（共%d个）', current_user.username, announcement.id, count)
        else:
            _cleanup_orphaned_references(announcement.id)
            announcement.delete()
            flash('删除通告成功', 'success')
            logger.info('用户%s删除通告：%s', current_user.username, announcement.id)

        from_param = request.form.get('from')
        date_param = request.form.get('date')

        if from_param == 'calendar' and date_param:
            return redirect(url_for('calendar.day_view', date=date_param))
        return redirect(url_for('announcement.list_announcements'))

    except DoesNotExist:
        abort(404)
    except Exception as e:
        flash(f'删除失败：{str(e)}', 'error')
        logger.error('删除通告失败：%s', str(e))
        return redirect(url_for('announcement.list_announcements'))


@announcement_bp.route('/export/view')
@roles_accepted('gicho', 'kancho')
def export_view_page():
    """渲染通告导出的打印视图页面。"""
    return render_template('announcements/export_view.html')
