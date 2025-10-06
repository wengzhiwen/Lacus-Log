# pylint: disable=no-member

from flask import (Blueprint, flash, jsonify, redirect, render_template,
                   request, url_for)
from flask_login import login_required
from flask_security import current_user
from flask_security.utils import hash_password

from routes.report import (build_dashboard_feature_banner,
                           calculate_dashboard_announcement_metrics,
                           calculate_dashboard_battle_metrics,
                           calculate_dashboard_candidate_metrics,
                           calculate_dashboard_conversion_rate_metrics,
                           calculate_dashboard_pilot_metrics,
                           calculate_dashboard_pilot_ranking_metrics,
                           calculate_dashboard_recruit_metrics)
from utils.dashboard_serializers import create_success_response
from utils.logging_setup import get_logger

logger = get_logger('main')

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
@login_required
def home():
    """用户首页（移动端优先）。"""
    logger.debug('用户进入首页：%s', getattr(current_user, 'username', 'anonymous'))

    return render_template('dashboard/index.html')


@main_bp.route('/api/dashboard/recruit', methods=['GET'])
@login_required
def dashboard_recruit_data():
    """仪表盘招募统计接口。"""
    data = calculate_dashboard_recruit_metrics()
    meta = {'segment': 'recruit', 'link': url_for('report.recruit_daily_report')}
    return jsonify(create_success_response(data, meta))


@main_bp.route('/api/dashboard/announcements', methods=['GET'])
@login_required
def dashboard_announcement_data():
    """仪表盘通告统计接口。"""
    data = calculate_dashboard_announcement_metrics()
    meta = {'segment': 'announcement', 'link': url_for('calendar.day_view')}
    return jsonify(create_success_response(data, meta))


@main_bp.route('/api/dashboard/battle-records', methods=['GET'])
@login_required
def dashboard_battle_data():
    """仪表盘开播记录统计接口。"""
    data = calculate_dashboard_battle_metrics()
    meta = {'segment': 'battle', 'link': url_for('report.daily_report')}
    return jsonify(create_success_response(data, meta))


@main_bp.route('/api/dashboard/pilots', methods=['GET'])
@login_required
def dashboard_pilot_data():
    """仪表盘主播统计接口。"""
    data = calculate_dashboard_pilot_metrics()
    meta = {'segment': 'pilot'}
    return jsonify(create_success_response(data, meta))


@main_bp.route('/api/dashboard/candidates', methods=['GET'])
@login_required
def dashboard_candidate_data():
    """仪表盘候选人统计接口。"""
    data = calculate_dashboard_candidate_metrics()
    meta = {'segment': 'candidate'}
    return jsonify(create_success_response(data, meta))


@main_bp.route('/api/dashboard/feature', methods=['GET'])
@login_required
def dashboard_feature_data():
    """仪表盘横幅展示接口。"""
    data = build_dashboard_feature_banner()
    meta = {'segment': 'feature'}
    return jsonify(create_success_response(data, meta))


@main_bp.route('/api/dashboard/conversion-rate', methods=['GET'])
@login_required
def dashboard_conversion_rate_data():
    """仪表盘底薪流水转化率统计接口。"""
    data = calculate_dashboard_conversion_rate_metrics()
    meta = {'segment': 'conversion_rate', 'link': url_for('report.monthly_report')}
    return jsonify(create_success_response(data, meta))


@main_bp.route('/api/dashboard/pilot-ranking', methods=['GET'])
@login_required
def dashboard_pilot_ranking_data():
    """仪表盘昨日主播排名统计接口。"""
    data = calculate_dashboard_pilot_ranking_metrics()
    meta = {'segment': 'pilot_ranking'}
    return jsonify(create_success_response(data, meta))


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
