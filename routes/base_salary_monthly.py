# pylint: disable=duplicate-code
"""底薪月报页面路由"""

from datetime import timedelta

from flask import Blueprint, render_template, request
from flask_security import roles_accepted

from utils.logging_setup import get_logger
from utils.base_salary_monthly_calculations import get_local_month_from_string
from utils.timezone_helper import get_current_utc_time, utc_to_local

logger = get_logger('base_salary_monthly')

base_salary_monthly_bp = Blueprint('base_salary_monthly', __name__)


def _parse_mode_param() -> str:
    """解析开播方式参数"""
    mode = request.args.get('mode', 'offline') or 'offline'
    if mode not in ('all', 'online', 'offline'):
        logger.warning('非法开播方式参数：%s，已回退到 offline', mode)
        return 'offline'
    return mode


def _parse_settlement_param() -> str:
    """解析结算方式参数"""
    settlement = request.args.get('settlement', 'monthly_base') or 'monthly_base'
    if settlement not in ('all', 'daily_base', 'monthly_base', 'none'):
        logger.warning('非法结算方式参数：%s，已回退到 monthly_base', settlement)
        return 'monthly_base'
    return settlement


@base_salary_monthly_bp.route('/base-salary-monthly')
@roles_accepted('gicho', 'kancho')
def base_salary_monthly_report():
    """底薪月报页面"""
    month_str = request.args.get('month')
    if not month_str:
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_month = today_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        report_month = get_local_month_from_string(month_str)
        if not report_month:
            logger.error('无效的底薪月报月份参数：%s', month_str)
            return '无效的月份格式', 400
        report_month = report_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    mode = _parse_mode_param()
    settlement = _parse_settlement_param()

    logger.info('访问底薪月报页面，月份：%s，开播方式：%s，结算方式：%s', report_month.strftime('%Y-%m'), mode, settlement)

    # 构建分页导航信息
    pagination = {
        'month': report_month.strftime('%Y-%m'),
        'prev_month': (report_month - timedelta(days=1)).replace(day=1).strftime('%Y-%m'),
        'next_month': (report_month + timedelta(days=31)).replace(day=1).strftime('%Y-%m')
    }

    return render_template('base_salary_monthly/monthly.html', pagination=pagination, selected_mode=mode, selected_settlement=settlement)
