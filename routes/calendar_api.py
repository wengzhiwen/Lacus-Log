# pylint: disable=no-member
"""通告日历 REST 接口蓝图。"""

from datetime import datetime

from flask import Blueprint, jsonify, request
from flask_login import login_required
from flask_security import roles_accepted

from utils.calendar_aggregator import (aggregate_daily_data, aggregate_monthly_data, aggregate_weekly_data)
from utils.logging_setup import get_logger

logger = get_logger('calendar_api')

calendar_api_bp = Blueprint('calendar_api', __name__)


@calendar_api_bp.route('/month-data')
@login_required
@roles_accepted('gicho', 'kancho')
def month_data():
    """获取月视图数据。"""
    try:
        year = int(request.args.get('year', datetime.now().year))
        month = int(request.args.get('month', datetime.now().month))
        result = aggregate_monthly_data(year, month)
        return jsonify(result)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取月视图数据失败：%s', exc)
        return jsonify({'error': '获取数据失败'}), 500


@calendar_api_bp.route('/week-data')
@login_required
@roles_accepted('gicho', 'kancho')
def week_data():
    """获取周视图数据。"""
    try:
        date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        target_date = datetime.strptime(date_str, '%Y-%m-%d')
        result = aggregate_weekly_data(target_date)
        return jsonify(result)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取周视图数据失败：%s', exc)
        return jsonify({'error': '获取数据失败'}), 500


@calendar_api_bp.route('/day-data')
@login_required
@roles_accepted('gicho', 'kancho')
def day_data():
    """获取日视图数据。"""
    try:
        date_str = request.args.get('date', datetime.now().strftime('%Y-%m-%d'))
        target_date = datetime.strptime(date_str, '%Y-%m-%d')
        result = aggregate_daily_data(target_date)
        return jsonify(result)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取日视图数据失败：%s', exc)
        return jsonify({'error': '获取数据失败'}), 500
