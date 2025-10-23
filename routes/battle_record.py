"""开播记录页面路由。"""
# pylint: disable=no-member
from datetime import timedelta
from decimal import Decimal

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_security import current_user, roles_accepted

from models.announcement import Announcement
from models.battle_record import BattleRecord, BattleRecordChangeLog
from models.pilot import WorkMode
from utils.csrf_helper import ensure_csrf_token
from utils.filter_state import persist_and_restore_filters
from utils.logging_setup import get_logger
from utils.timezone_helper import get_current_utc_time, utc_to_local

logger = get_logger('battle_record')

battle_record_bp = Blueprint('battle_record', __name__)


def validate_notes_required(start_time, end_time, revenue_amount, base_salary, related_announcement, notes):  # pylint: disable=too-many-arguments,too-many-positional-arguments
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


def log_battle_record_change(battle_record, field_name, old_value, new_value, user_id, ip_address):  # pylint: disable=too-many-arguments,too-many-positional-arguments
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
    if dt.minute in (0, 30):
        return dt.replace(second=0, microsecond=0)
    if dt.minute <= 30:
        return dt.replace(minute=0, second=0, microsecond=0)
    return dt.replace(minute=30, second=0, microsecond=0)


@battle_record_bp.route('/')
@roles_accepted('gicho', 'kancho')
def list_battle_records():
    """开播记录列表页"""
    logger.info('用户 %s 访问开播记录列表', current_user.username)

    def get_today_date_string():
        """获取GMT+8时区的今天日期字符串 YYYY-MM-DD"""
        now_local = utc_to_local(get_current_utc_time())
        return now_local.strftime('%Y-%m-%d')

    filters = persist_and_restore_filters(
        'battle_records_list',
        allowed_keys=['owner', 'x', 'status', 'date'],
        default_filters={
            'owner': 'all',
            'x': '',
            'status': 'all',
            'date': get_today_date_string()
        },
    )

    return render_template('battle_records/list.html', filters=filters)


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

        # 获取来源参数
        from_param = request.args.get('from')
        application_id = request.args.get('application_id')
        csrf_token = ensure_csrf_token()

        return render_template('battle_records/detail.html',
                               battle_record=battle_record,
                               related_announcement=related_announcement,
                               related_announcement_deleted=related_announcement_deleted,
                               from_param=from_param,
                               application_id=application_id,
                               csrf_token=csrf_token)
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
        except Exception as err:
            related_announcement_deleted = True
            logger.warning('开播记录 %s 的关联通告不存在（编辑页），显示已删除占位。原因: %s', record_id, err, exc_info=True)

        return render_template('battle_records/edit.html',
                               battle_record=battle_record,
                               related_announcement=related_announcement,
                               related_announcement_deleted=related_announcement_deleted)
    except BattleRecord.DoesNotExist:
        flash('开播记录不存在', 'error')
        return redirect(url_for('battle_record.list_battle_records'))


@battle_record_bp.route('/<record_id>/base_salary_application')
@roles_accepted('gicho', 'kancho')
def base_salary_application(record_id):
    """申请底薪页面"""
    try:
        battle_record = BattleRecord.objects.get(id=record_id)
        logger.info(f"用户 {current_user.username} 访问申请底薪页面 {record_id}")

        # 检查是否已存在底薪申请
        from models.battle_record import BaseSalaryApplication
        existing_application = BaseSalaryApplication.objects(battle_record_id=battle_record).first()

        return render_template('battle_records/base_salary_application.html', battle_record=battle_record, existing_application=existing_application)
    except BattleRecord.DoesNotExist:
        flash('开播记录不存在', 'error')
        return redirect(url_for('battle_record.list_battle_records'))
