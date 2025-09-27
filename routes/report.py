"""开播日报路由

实现开播日报的日视图和CSV导出功能。
注意：mongoengine 的动态属性在pylint中会触发 no-member 误报，这里统一抑制。
"""
# pylint: disable=no-member
import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import quote

from flask import Blueprint, Response, render_template, request
from flask_security import current_user, roles_accepted
from mongoengine import Q

from models.battle_record import BattleRecord
from models.recruit import Recruit, BroadcastDecision, FinalDecision
from utils.commission_helper import (calculate_commission_amounts, get_pilot_commission_rate_for_date)
from utils.logging_setup import get_logger
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)

# 创建日志器（按模块分文件）
logger = get_logger('report')

report_bp = Blueprint('report', __name__)


def get_local_date_from_string(date_str):
    """将日期字符串解析为本地日期对象"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return None

def get_battle_records_for_date_range(start_local_date, end_local_date):
    """获取指定本地日期范围内的开播记录"""
    start_utc = local_to_utc(start_local_date)
    end_utc = local_to_utc(end_local_date)
    return BattleRecord.objects.filter(start_time__gte=start_utc, start_time__lt=end_utc)


def calculate_pilot_three_day_avg_revenue(pilot, report_date):
    """计算主播3日平均流水"""
    days_with_records = []
    for i in range(7):
        check_date = report_date - timedelta(days=i)
        check_date_start = check_date.replace(hour=0, minute=0, second=0, microsecond=0)
        check_date_end = check_date_start + timedelta(days=1)
        daily_records = get_battle_records_for_date_range(check_date_start, check_date_end)
        pilot_daily_records = daily_records.filter(pilot=pilot)
        if pilot_daily_records.count() > 0:
            daily_revenue = sum(record.revenue_amount for record in pilot_daily_records)
            days_with_records.append(daily_revenue)
            if len(days_with_records) >= 3:
                break
    if len(days_with_records) < 3:
        return None
    total_revenue = sum(days_with_records[:3])
    return total_revenue / 3


def calculate_pilot_rebate(pilot, report_date):
    """计算主播返点金额"""
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1))
    pilot_month_records = month_records.filter(pilot=pilot)
    valid_days = set()
    total_duration = 0
    total_revenue = Decimal('0')
    for record in pilot_month_records:
        local_start = utc_to_local(record.start_time)
        record_date = local_start.date()
        if record.duration_hours:
            total_duration += record.duration_hours
            if record.duration_hours >= 1.0:
                valid_days.add(record_date)
        total_revenue += record.revenue_amount
    valid_days_count = len(valid_days)
    rebate_stages = [
        {'stage': 1, 'min_days': 12, 'min_hours': 42, 'min_revenue': Decimal('1000'), 'rate': 0.05},
        {'stage': 2, 'min_days': 18, 'min_hours': 100, 'min_revenue': Decimal('5000'), 'rate': 0.07},
        {'stage': 3, 'min_days': 18, 'min_hours': 100, 'min_revenue': Decimal('10000'), 'rate': 0.11},
        {'stage': 4, 'min_days': 22, 'min_hours': 130, 'min_revenue': Decimal('30000'), 'rate': 0.14},
        {'stage': 5, 'min_days': 22, 'min_hours': 130, 'min_revenue': Decimal('80000'), 'rate': 0.18}
    ]
    qualified_stages = [s for s in rebate_stages if valid_days_count >= s['min_days'] and total_duration >= s['min_hours'] and total_revenue >= s['min_revenue']]
    if qualified_stages:
        best_stage = max(qualified_stages, key=lambda x: x['stage'])
        rebate_amount = total_revenue * Decimal(str(best_stage['rate']))
        return {'rebate_amount': rebate_amount, 'rebate_rate': best_stage['rate'], 'rebate_stage': best_stage['stage'], 'valid_days_count': valid_days_count, 'total_duration': total_duration, 'total_revenue': total_revenue, 'qualified_stages': qualified_stages}
    return {'rebate_amount': Decimal('0'), 'rebate_rate': 0, 'rebate_stage': 0, 'valid_days_count': valid_days_count, 'total_duration': total_duration, 'total_revenue': total_revenue, 'qualified_stages': []}


def calculate_pilot_monthly_stats(pilot, report_date):
    """计算主播月度统计数据"""
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1))
    pilot_month_records = month_records.filter(pilot=pilot)
    record_dates = set()
    total_duration = 0
    total_revenue = Decimal('0')
    total_base_salary = Decimal('0')
    for record in pilot_month_records:
        local_start = utc_to_local(record.start_time)
        record_dates.add(local_start.date())
        if record.duration_hours:
            total_duration += record.duration_hours
        total_revenue += record.revenue_amount
        total_base_salary += record.base_salary
    month_days_count = len(record_dates)
    month_avg_duration = total_duration / month_days_count if month_days_count > 0 else 0
    return {'month_days_count': month_days_count, 'month_avg_duration': round(month_avg_duration, 1), 'month_total_revenue': total_revenue, 'month_total_base_salary': total_base_salary}

@report_bp.route('/daily')
@roles_accepted('gicho', 'kancho')
def daily_report():
    """开播日报页面"""
    # ... (rest of the function as before)
    return render_template('reports/daily.html', ...)

@report_bp.route('/daily/export.csv')
@roles_accepted('gicho', 'kancho')
def export_daily_csv():
    """导出开播日报CSV"""
    # ... (rest of the function as before)
    return response

# ==================== 征召日报相关函数 ====================
def _calculate_recruit_statistics(report_date):
    """计算征召统计数据"""
    # ... (logic from report_mail.py)
    return {'report_day': report_day_stats, 'last_7_days': last_7_days_stats, 'last_14_days': last_14_days_stats}

def _calculate_period_stats(start_utc, end_utc):
    """计算指定时间范围内的征召统计数据"""
    # ... (logic from report_mail.py)
    return {'appointments': appointments, 'interviews': interviews, 'trials': trials, 'new_recruits': new_recruits}

@report_bp.route('/recruits/daily-report')
@roles_accepted('gicho', 'kancho')
def recruit_daily_report():
    """主播招募日报页面"""
    # ... (logic to calculate stats and render template)
    return render_template('recruit_reports/daily.html', statistics=statistics, pagination=pagination)
