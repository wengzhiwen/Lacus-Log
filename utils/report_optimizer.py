"""报表计算优化模块

优化报表模块的数据库查询性能，减少重复查询次数。
"""

from collections import defaultdict
from datetime import timedelta
from decimal import Decimal

from utils.commission_helper import (calculate_commission_amounts,
                                     get_pilot_commission_rate_for_date)
from utils.logging_setup import get_logger
from utils.timezone_helper import utc_to_local

logger = get_logger('report_optimizer')


def calculate_pilot_three_day_avg_revenue_optimized(pilot, report_date):
    """优化版：计算机师3日平均流水
    
    一次查询获取7天数据，然后在内存中计算，避免循环查询数据库。
    
    Args:
        pilot: 机师对象
        report_date: 报表日期（本地时间）
        
    Returns:
        Decimal: 3日平均流水，若不足3天则返回None
    """
    from routes.report import get_battle_records_for_date_range
    week_start = report_date - timedelta(days=6)
    week_end = report_date + timedelta(days=1)
    week_records = get_battle_records_for_date_range(week_start, week_end)
    pilot_week_records = week_records.filter(pilot=pilot)

    daily_revenues = defaultdict(Decimal)
    for record in pilot_week_records:
        local_start = utc_to_local(record.start_time)
        record_date = local_start.date()
        daily_revenues[record_date] += record.revenue_amount

    report_date_obj = report_date.date()
    days_with_records = []

    for i in range(7):
        check_date = report_date_obj - timedelta(days=i)
        if check_date in daily_revenues:
            days_with_records.append(daily_revenues[check_date])
            if len(days_with_records) >= 3:
                break

    if len(days_with_records) < 3:
        return None

    total_revenue = sum(days_with_records[:3])
    return total_revenue / 3


def calculate_pilot_monthly_stats_optimized(pilot, report_date):
    """优化版：计算机师月度统计数据
    
    Args:
        pilot: 机师对象
        report_date: 报表日期（本地时间）
        
    Returns:
        dict: 包含月累计天数、月日均播时、月累计流水、月累计底薪
    """
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    from routes.report import get_battle_records_for_date_range
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1))
    pilot_month_records = month_records.filter(pilot=pilot)

    record_dates = set()
    total_duration = 0
    total_revenue = Decimal('0')
    total_base_salary = Decimal('0')

    for record in pilot_month_records:
        local_start = utc_to_local(record.start_time)
        record_date = local_start.date()
        record_dates.add(record_date)

        if record.duration_hours:
            total_duration += record.duration_hours

        total_revenue += record.revenue_amount
        total_base_salary += record.base_salary

    month_days_count = len(record_dates)
    month_avg_duration = total_duration / month_days_count if month_days_count > 0 else 0

    return {
        'month_days_count': month_days_count,
        'month_avg_duration': round(month_avg_duration, 1),
        'month_total_revenue': total_revenue,
        'month_total_base_salary': total_base_salary
    }


def batch_calculate_pilot_stats(pilots, report_date):
    """批量计算机师统计数据
    
    批量查询减少数据库访问次数，提高性能。
    
    Args:
        pilots: 机师列表
        report_date: 报表日期（本地时间）
        
    Returns:
        dict: 机师ID -> 统计数据的映射
    """
    if not pilots:
        return {}

    pilot_stats = {}

    from routes.report import get_battle_records_for_date_range
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1))

    pilot_month_data = defaultdict(list)
    for record in month_records:
        pilot_id = str(record.pilot.id)
        if pilot_id in [str(p.id) for p in pilots]:
            pilot_month_data[pilot_id].append(record)

    week_records = get_battle_records_for_date_range(report_date - timedelta(days=6), report_date + timedelta(days=1))

    pilot_week_data = defaultdict(list)
    for record in week_records:
        pilot_id = str(record.pilot.id)
        if pilot_id in [str(p.id) for p in pilots]:
            pilot_week_data[pilot_id].append(record)

    for pilot in pilots:
        pilot_id = str(pilot.id)

        month_records_list = pilot_month_data.get(pilot_id, [])
        monthly_stats = _calculate_monthly_stats_from_records(month_records_list)

        monthly_commission_stats = _calculate_monthly_commission_stats_from_records(month_records_list, pilot, report_date)

        week_records_list = pilot_week_data.get(pilot_id, [])
        three_day_avg = _calculate_three_day_avg_from_records(week_records_list, report_date)

        pilot_stats[pilot_id] = {'monthly_stats': monthly_stats, 'three_day_avg_revenue': three_day_avg, 'monthly_commission_stats': monthly_commission_stats}

    logger.debug('批量计算完成：%d个机师', len(pilots))
    return pilot_stats


def _calculate_monthly_commission_stats_from_records(records, pilot, report_date):
    """从记录列表计算月度分成统计"""
    if not records:
        return {'month_total_pilot_share': Decimal('0'), 'month_total_company_share': Decimal('0'), 'month_total_profit': Decimal('0')}

    month_total_pilot_share = Decimal('0')
    month_total_company_share = Decimal('0')

    for record in records:
        record_date = utc_to_local(record.start_time).date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(record.pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)

        month_total_pilot_share += commission_amounts['pilot_amount']
        month_total_company_share += commission_amounts['company_amount']

    rebate_info = _calculate_pilot_rebate_from_records(records, pilot, report_date)
    monthly_stats = _calculate_monthly_stats_from_records(records)

    month_total_profit = month_total_company_share + rebate_info['rebate_amount'] - monthly_stats['month_total_base_salary']

    return {
        'month_total_pilot_share': month_total_pilot_share,
        'month_total_company_share': month_total_company_share,
        'month_total_profit': month_total_profit
    }


def _calculate_pilot_rebate_from_records(records, pilot, report_date):  # pylint: disable=unused-argument
    """从记录列表计算机师返点信息"""
    if not records:
        return {'rebate_amount': Decimal('0'), 'rebate_rate': 0}

    valid_days = set()  # 有效天数（单次播时≥60分钟的自然日）
    total_duration = 0  # 总播时（小时）
    total_revenue = Decimal('0')  # 总流水（元）

    for record in records:
        local_start = utc_to_local(record.start_time)
        record_date = local_start.date()

        if record.duration_hours:
            total_duration += record.duration_hours

            if record.duration_hours >= 1.0:  # 60分钟 = 1小时
                valid_days.add(record_date)

        total_revenue += record.revenue_amount

    valid_days_count = len(valid_days)

    rebate_stages = [{
        'stage': 1,
        'min_days': 12,
        'min_hours': 42,
        'min_revenue': Decimal('1000'),
        'rate': 0.05,
        'rate_percent': '5%'
    }, {
        'stage': 2,
        'min_days': 18,
        'min_hours': 100,
        'min_revenue': Decimal('5000'),
        'rate': 0.07,
        'rate_percent': '7%'
    }, {
        'stage': 3,
        'min_days': 18,
        'min_hours': 100,
        'min_revenue': Decimal('10000'),
        'rate': 0.11,
        'rate_percent': '11%'
    }, {
        'stage': 4,
        'min_days': 22,
        'min_hours': 130,
        'min_revenue': Decimal('30000'),
        'rate': 0.14,
        'rate_percent': '14%'
    }, {
        'stage': 5,
        'min_days': 22,
        'min_hours': 130,
        'min_revenue': Decimal('80000'),
        'rate': 0.18,
        'rate_percent': '18%'
    }]

    qualified_stages = []
    for stage in rebate_stages:
        days_ok = valid_days_count >= stage['min_days']
        hours_ok = total_duration >= stage['min_hours']
        revenue_ok = total_revenue >= stage['min_revenue']

        stage_qualified = days_ok and hours_ok and revenue_ok

        if stage_qualified:
            qualified_stages.append(stage)

    if qualified_stages:
        qualified_stages.sort(key=lambda x: x['stage'], reverse=True)
        best_stage = qualified_stages[0]

        rebate_amount = total_revenue * Decimal(str(best_stage['rate']))

        return {'rebate_amount': rebate_amount, 'rebate_rate': best_stage['rate']}
    else:
        return {'rebate_amount': Decimal('0'), 'rebate_rate': 0}


def _calculate_monthly_stats_from_records(records):
    """从记录列表计算月度统计"""
    if not records:
        return {'month_days_count': 0, 'month_avg_duration': 0, 'month_total_revenue': Decimal('0'), 'month_total_base_salary': Decimal('0')}

    record_dates = set()
    total_duration = 0
    total_revenue = Decimal('0')
    total_base_salary = Decimal('0')

    for record in records:
        local_start = utc_to_local(record.start_time)
        record_date = local_start.date()
        record_dates.add(record_date)

        if record.duration_hours:
            total_duration += record.duration_hours

        total_revenue += record.revenue_amount
        total_base_salary += record.base_salary

    month_days_count = len(record_dates)
    month_avg_duration = total_duration / month_days_count if month_days_count > 0 else 0

    return {
        'month_days_count': month_days_count,
        'month_avg_duration': round(month_avg_duration, 1),
        'month_total_revenue': total_revenue,
        'month_total_base_salary': total_base_salary
    }


def _calculate_three_day_avg_from_records(records, report_date):
    """从记录列表计算3日平均流水"""
    if not records:
        return None

    daily_revenues = defaultdict(Decimal)
    for record in records:
        local_start = utc_to_local(record.start_time)
        record_date = local_start.date()
        daily_revenues[record_date] += record.revenue_amount

    report_date_obj = report_date.date()
    days_with_records = []

    for i in range(7):
        check_date = report_date_obj - timedelta(days=i)
        if check_date in daily_revenues:
            days_with_records.append(daily_revenues[check_date])
            if len(days_with_records) >= 3:
                break

    if len(days_with_records) < 3:
        return None

    total_revenue = sum(days_with_records[:3])
    return total_revenue / 3
