# pylint: disable=no-member
from datetime import timedelta

from flask import Blueprint, flash, redirect, render_template, request, url_for
from flask_login import login_required
from flask_security import current_user
from flask_security.utils import hash_password

from models.announcement import Announcement
from models.battle_record import BattleRecord
from models.pilot import Pilot, Rank, Status
from utils.logging_setup import get_logger
from utils.timezone_helper import (
    get_current_local_time,
    get_current_utc_time,
    local_to_utc,
    utc_to_local,
)

logger = get_logger('main')

main_bp = Blueprint('main', __name__)


def _calculate_dashboard_data():
    """计算仪表板数据"""
    now = get_current_utc_time()

    current_local = utc_to_local(now)
    today_local_start = current_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_local_end = today_local_start + timedelta(days=1)
    yesterday_local_start = today_local_start - timedelta(days=1)
    yesterday_local_end = today_local_start
    week_local_start = today_local_start - timedelta(days=7)

    today_start_utc = local_to_utc(today_local_start)
    today_end_utc = local_to_utc(today_local_end)
    yesterday_start_utc = local_to_utc(yesterday_local_start)
    yesterday_end_utc = local_to_utc(yesterday_local_end)
    week_start_utc = local_to_utc(week_local_start)

    today_count = Announcement.objects(start_time__gte=today_start_utc, start_time__lt=today_end_utc).count()

    yesterday_count = Announcement.objects(start_time__gte=yesterday_start_utc, start_time__lt=yesterday_end_utc).count()

    if yesterday_count > 0:
        change_rate = round(((today_count - yesterday_count) / yesterday_count) * 100, 1)
    else:
        change_rate = 100.0 if today_count > 0 else 0.0

    week_count = Announcement.objects(start_time__gte=week_start_utc, start_time__lt=today_end_utc).count()
    week_avg = round(week_count / 7, 1)

    br_today_records = BattleRecord.objects(start_time__gte=today_start_utc, start_time__lt=today_end_utc)
    br_today_revenue = sum(record.revenue_amount for record in br_today_records)

    br_yesterday_records = BattleRecord.objects(start_time__gte=yesterday_start_utc, start_time__lt=yesterday_end_utc)
    br_yesterday_revenue = sum(record.revenue_amount for record in br_yesterday_records)

    br_week_records = BattleRecord.objects(start_time__gte=week_start_utc, start_time__lt=today_end_utc)
    br_week_revenue = sum(record.revenue_amount for record in br_week_records)
    br_week_avg_revenue = br_week_revenue / 7

    serving_status = [Status.RECRUITED, Status.CONTRACTED]
    pilot_serving = Pilot.objects(status__in=serving_status).count()
    pilot_intern_serving = Pilot.objects(rank=Rank.INTERN, status__in=serving_status).count()
    pilot_official_serving = Pilot.objects(rank=Rank.OFFICIAL, status__in=serving_status).count()

    candidate_not_recruited = Pilot.objects(rank=Rank.CANDIDATE, status=Status.NOT_RECRUITED).count()
    trainee_serving = Pilot.objects(rank=Rank.TRAINEE, status__in=serving_status).count()

    from utils.recruit_stats import calculate_recruit_today_stats
    today_recruit_stats = calculate_recruit_today_stats()
    recruit_today_appointments = today_recruit_stats['appointments']
    recruit_today_interviews = today_recruit_stats['interviews']
    recruit_today_new_recruits = today_recruit_stats['new_recruits']

    return {
        'today_count': today_count,
        'change_rate': change_rate,
        'week_avg': week_avg,
        'battle_today_revenue': br_today_revenue,
        'battle_yesterday_revenue': br_yesterday_revenue,
        'battle_week_avg_revenue': br_week_avg_revenue,
        'pilot_serving_count': pilot_serving,
        'pilot_intern_serving_count': pilot_intern_serving,
        'pilot_official_serving_count': pilot_official_serving,
        'candidate_not_recruited_count': candidate_not_recruited,
        'trainee_serving_count': trainee_serving,
        'recruit_today_appointments': recruit_today_appointments,
        'recruit_today_interviews': recruit_today_interviews,
        'recruit_today_new_recruits': recruit_today_new_recruits,
    }


@main_bp.route('/')
@login_required
def home():
    """用户首页（移动端优先）。"""
    logger.debug('用户进入首页：%s', getattr(current_user, 'username', 'anonymous'))

    dashboard_data = _calculate_dashboard_data()

    now_local = get_current_local_time()
    start_local = now_local.replace(year=2025, month=10, day=1, hour=0, minute=0, second=0, microsecond=0)
    end_local = now_local.replace(year=2025, month=10, day=5, hour=23, minute=59, second=59, microsecond=0)
    show_featured_image = start_local <= now_local <= end_local

    return render_template('index.html', dashboard_data=dashboard_data, show_featured_image=show_featured_image)


@main_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """修改密码页面（自定义实现）。"""
    if request.method == 'POST':
        current_password = request.form.get('password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('new_password_confirm', '').strip()

        if not current_password or not new_password or not confirm_password:
            flash('所有字段都是必填的', 'error')
            return render_template('security/change_password.html')

        if new_password != confirm_password:
            flash('新密码和确认密码不匹配', 'error')
            return render_template('security/change_password.html')

        if len(new_password) < 6:
            flash('新密码长度至少6个字符', 'error')
            return render_template('security/change_password.html')

        if not current_user.verify_and_update_password(current_password):
            flash('当前密码错误', 'error')
            return render_template('security/change_password.html')

        current_user.password = hash_password(new_password)
        current_user.save()

        flash('密码修改成功', 'success')
        logger.info('用户修改密码：%s', current_user.username)
        return redirect(url_for('main.home'))

    return render_template('security/change_password.html')
