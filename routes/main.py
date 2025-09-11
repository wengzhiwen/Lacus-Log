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
from utils.timezone_helper import get_current_utc_time

logger = get_logger('main')

main_bp = Blueprint('main', __name__)


def _calculate_dashboard_data():
    """计算仪表板数据"""
    now = get_current_utc_time()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    today_end = today_start + timedelta(days=1)
    yesterday_start = today_start - timedelta(days=1)
    yesterday_end = today_start
    week_start = today_start - timedelta(days=7)

    # 今日作战计划数量（开播起始日为当前日期的作战计划）
    today_count = Announcement.objects(start_time__gte=today_start, start_time__lt=today_end).count()

    # 昨日作战计划数量
    yesterday_count = Announcement.objects(start_time__gte=yesterday_start, start_time__lt=yesterday_end).count()

    # 计算环比（百分比，保留一位小数）
    if yesterday_count > 0:
        change_rate = round(((today_count - yesterday_count) / yesterday_count) * 100, 1)
    else:
        change_rate = 100.0 if today_count > 0 else 0.0

    # 最近7天的日均作战计划数量
    week_count = Announcement.objects(start_time__gte=week_start, start_time__lt=today_end).count()
    week_avg = round(week_count / 7, 1)

    # 作战记录统计（开始时间为今天的作战记录）
    br_today = BattleRecord.objects(start_time__gte=today_start, start_time__lt=today_end).count()
    br_yesterday = BattleRecord.objects(start_time__gte=yesterday_start, start_time__lt=yesterday_end).count()
    if br_yesterday > 0:
        br_change_rate = round(((br_today - br_yesterday) / br_yesterday) * 100, 1)
    else:
        br_change_rate = 100.0 if br_today > 0 else 0.0
    br_week_count = BattleRecord.objects(start_time__gte=week_start, start_time__lt=today_end).count()
    br_week_avg = round(br_week_count / 7, 1)

    # 机师统计
    serving_status = [Status.RECRUITED, Status.CONTRACTED]
    pilot_serving = Pilot.objects(status__in=serving_status).count()
    pilot_intern_serving = Pilot.objects(rank=Rank.INTERN, status__in=serving_status).count()
    pilot_official_serving = Pilot.objects(rank=Rank.OFFICIAL, status__in=serving_status).count()

    # 候补机师统计
    candidate_not_recruited = Pilot.objects(rank=Rank.CANDIDATE, status=Status.NOT_RECRUITED).count()
    trainee_serving = Pilot.objects(rank=Rank.TRAINEE, status__in=serving_status).count()

    return {
        # 作战计划统计（保留现有键名以兼容模板）
        'today_count': today_count,
        'change_rate': change_rate,
        'week_avg': week_avg,
        # 作战记录统计
        'battle_today_count': br_today,
        'battle_change_rate': br_change_rate,
        'battle_week_avg': br_week_avg,
        # 机师统计
        'pilot_serving_count': pilot_serving,
        'pilot_intern_serving_count': pilot_intern_serving,
        'pilot_official_serving_count': pilot_official_serving,
        # 候补机师统计
        'candidate_not_recruited_count': candidate_not_recruited,
        'trainee_serving_count': trainee_serving,
    }


@main_bp.route('/')
@login_required
def home():
    """用户首页（移动端优先）。"""
    logger.debug('用户进入首页：%s', getattr(current_user, 'username', 'anonymous'))

    # 计算仪表板数据
    dashboard_data = _calculate_dashboard_data()

    return render_template('index.html', dashboard_data=dashboard_data)


@main_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """修改密码页面（自定义实现）。"""
    if request.method == 'POST':
        current_password = request.form.get('password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('new_password_confirm', '').strip()

        # 验证输入
        if not current_password or not new_password or not confirm_password:
            flash('所有字段都是必填的', 'error')
            return render_template('security/change_password.html')

        if new_password != confirm_password:
            flash('新密码和确认密码不匹配', 'error')
            return render_template('security/change_password.html')

        if len(new_password) < 6:
            flash('新密码长度至少6个字符', 'error')
            return render_template('security/change_password.html')

        # 验证当前密码
        if not current_user.verify_and_update_password(current_password):
            flash('当前密码错误', 'error')
            return render_template('security/change_password.html')

        # 更新密码
        current_user.password = hash_password(new_password)
        current_user.save()

        flash('密码修改成功', 'success')
        logger.info('用户修改密码：%s', current_user.username)
        return redirect(url_for('main.home'))

    return render_template('security/change_password.html')
