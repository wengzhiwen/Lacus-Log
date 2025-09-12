# pylint: disable=no-member
from datetime import datetime, timedelta
from calendar import monthrange

from flask import Blueprint, jsonify, render_template, request
from flask_login import login_required
from flask_security import current_user, roles_accepted

from models.announcement import Announcement
from models.battle_area import BattleArea
from utils.logging_setup import get_logger
from utils.timezone_helper import utc_to_local, local_to_utc

logger = get_logger('calendar')

calendar_bp = Blueprint('calendar', __name__)


@calendar_bp.route('/')
@login_required
@roles_accepted('gicho', 'kancho')
def index():
    """日历主页，默认进入周视图"""
    logger.debug('用户进入作战计划日历：%s', getattr(current_user, 'username', 'anonymous'))
    return render_template('calendar/week.html')


@calendar_bp.route('/month')
@login_required
@roles_accepted('gicho', 'kancho')
def month_view():
    """月视图"""
    return render_template('calendar/month.html')


@calendar_bp.route('/week')
@login_required
@roles_accepted('gicho', 'kancho')
def week_view():
    """周视图"""
    return render_template('calendar/week.html')


@calendar_bp.route('/day')
@login_required
@roles_accepted('gicho', 'kancho')
def day_view():
    """日视图"""
    return render_template('calendar/day.html')


@calendar_bp.route('/api/month-data')
@login_required
@roles_accepted('gicho', 'kancho')
def month_data():
    """获取月视图数据"""
    try:
        # 获取参数
        year = int(request.args.get('year', datetime.now().year))
        month = int(request.args.get('month', datetime.now().month))

        # 使用公共聚合方法
        from utils.calendar_aggregator import aggregate_monthly_data
        result = aggregate_monthly_data(year, month)
        
        return jsonify(result)

    except Exception as e:
        logger.error('获取月视图数据失败：%s', str(e))
        return jsonify({'error': '获取数据失败'}), 500


@calendar_bp.route('/api/week-data')
@login_required
@roles_accepted('gicho', 'kancho')
def week_data():
    """获取周视图数据"""
    try:
        # 获取参数
        date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        date = datetime.strptime(date_str, '%Y-%m-%d')

        # 使用公共聚合方法
        from utils.calendar_aggregator import aggregate_weekly_data
        result = aggregate_weekly_data(date)
        
        return jsonify(result)

    except Exception as e:
        logger.error('获取周视图数据失败：%s', str(e))
        return jsonify({'error': '获取数据失败'}), 500


@calendar_bp.route('/api/day-data')
@login_required
@roles_accepted('gicho', 'kancho')
def day_data():
    """获取日视图数据"""
    try:
        # 获取参数
        date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        date = datetime.strptime(date_str, '%Y-%m-%d')

        # 使用公共聚合方法
        from utils.calendar_aggregator import aggregate_daily_data
        result = aggregate_daily_data(date)
        
        return jsonify(result)

    except Exception as e:
        logger.error('获取日视图数据失败：%s', str(e))
        return jsonify({'error': '获取数据失败'}), 500
