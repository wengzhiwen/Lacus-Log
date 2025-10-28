# -*- coding: utf-8 -*-
"""
主播业绩计算工具
"""
# pylint: disable=no-member,too-many-locals

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Tuple

from models.battle_record import (BaseSalaryApplication, BaseSalaryApplicationStatus, BattleRecord)
from models.pilot import Pilot
from utils.commission_helper import calculate_commission_amounts, get_pilot_commission_rate_for_date
from utils.logging_setup import get_logger
from utils.rebate_calculator import calculate_pilot_rebate
from utils.timezone_helper import get_current_local_time, local_to_utc, utc_to_local

logger = get_logger('pilot_performance')


def _create_daily_bucket() -> Dict[str, Decimal]:
    return {'revenue': Decimal('0'), 'basepay': Decimal('0'), 'company_share': Decimal('0'), 'hours': Decimal('0')}


def calculate_pilot_performance_stats(pilot: Pilot, report_date: datetime = None) -> Dict[str, Any]:
    """计算主播业绩统计数据
    
    Args:
        pilot: 主播对象
        report_date: 报表日期（本地时间），默认为当前日期
        
    Returns:
        dict: 包含本月统计、近7日统计、近3日统计和最近开播记录
    """
    if report_date is None:
        report_date = get_current_local_time()

    # 计算本月统计
    month_stats, month_daily_series = _calculate_month_stats(pilot, report_date)

    # 计算近7日统计
    week_stats = _calculate_week_stats(pilot)

    # 计算近3日统计
    three_day_stats = _calculate_three_day_stats(pilot)

    # 获取最近开播记录并附带底薪申请信息
    recent_records = _get_recent_records_with_applications(pilot, limit=30)

    return {
        'month_stats': month_stats,
        'month_daily_series': month_daily_series,
        'week_stats': week_stats,
        'three_day_stats': three_day_stats,
        'recent_records': recent_records
    }


def _calculate_month_stats(pilot: Pilot, report_date: datetime) -> Tuple[Dict[str, Any], List[Dict[str, Any]]]:
    """计算本月统计并返回日级序列"""
    # 本月开始时间（本地时间）
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # 本月结束时间（本地时间）
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    month_start_utc = local_to_utc(month_start)
    month_end_utc = local_to_utc(month_end)

    # 获取本月开播记录
    records = list(BattleRecord.objects(pilot=pilot, start_time__gte=month_start_utc, start_time__lte=month_end_utc).order_by('start_time'))

    approved_map, _ = _build_base_salary_maps(records)
    daily_totals: Dict[date, Dict[str, Decimal]] = defaultdict(_create_daily_bucket)

    # 计算统计数据
    record_count = len(records)
    total_hours = round(sum(record.duration_hours for record in records if record.duration_hours), 1)
    avg_hours = round(total_hours / record_count, 1) if record_count > 0 else 0

    total_revenue = Decimal('0')
    total_basepay = Decimal('0')
    total_company_share = Decimal('0')

    for record in records:
        revenue_amount = Decimal(record.revenue_amount or Decimal('0'))
        basepay_amount = approved_map.get(str(record.id), Decimal('0'))

        # 使用正确的分成计算
        record_date = utc_to_local(record.start_time).date() if record.start_time else None
        commission_rate = get_pilot_commission_rate_for_date(str(pilot.id), record_date)[0] if record_date else 20.0
        commission_amounts = calculate_commission_amounts(revenue_amount, commission_rate)
        company_share_amount = commission_amounts['company_amount']

        duration_hours = Decimal(str(record.duration_hours or 0))

        total_revenue += revenue_amount
        total_basepay += basepay_amount
        total_company_share += company_share_amount

        if record.start_time:
            local_day = utc_to_local(record.start_time).date()
            bucket = daily_totals[local_day]
            bucket['revenue'] += revenue_amount
            bucket['basepay'] += basepay_amount
            bucket['company_share'] += company_share_amount
            bucket['hours'] += duration_hours

    # 计算日均数据（分母为开播记录数）
    daily_avg_revenue = total_revenue / record_count if record_count > 0 else Decimal('0')
    daily_avg_basepay = total_basepay / record_count if record_count > 0 else Decimal('0')

    # 计算返点
    total_rebate = Decimal('0')
    if records:
        # 计算有效开播天数（播时≥1小时的天数）
        daily_duration_map = defaultdict(float)
        for record in records:
            if record.start_time:
                local_day = utc_to_local(record.start_time).date()
                daily_duration_map[local_day] += float(record.duration_hours or 0)

        valid_days = sum(1 for duration in daily_duration_map.values() if duration >= 1.0)
        total_duration_float = float(total_hours)

        # 使用统一返点计算器
        rebate_rate, total_rebate = calculate_pilot_rebate(valid_days, total_duration_float, total_revenue)
        logger.debug('主播 %s 月度返点计算 - 有效天数: %d, 总播时: %.1f, 总流水: %s, 返点比例: %.2f%%, 返点金额: %s', pilot.id, valid_days, total_duration_float, total_revenue,
                     rebate_rate * 100, total_rebate)

    # 运营利润估算
    operating_profit = total_company_share + total_rebate - total_basepay
    daily_avg_operating_profit = operating_profit / record_count if record_count > 0 else Decimal('0')

    stats = {
        'record_count': record_count,
        'total_hours': total_hours,
        'avg_hours': avg_hours,
        'total_revenue': total_revenue,
        'daily_avg_revenue': daily_avg_revenue,
        'total_basepay': total_basepay,
        'daily_avg_basepay': daily_avg_basepay,
        'total_rebate': total_rebate,
        'total_company_share': total_company_share,
        'operating_profit': operating_profit,
        'daily_avg_operating_profit': daily_avg_operating_profit
    }

    month_daily_series = _build_month_daily_series(daily_totals, month_start.date(), month_end.date())

    return stats, month_daily_series


def _calculate_week_stats(pilot: Pilot) -> Dict[str, Any]:
    """计算近7日统计（最近的7条开播记录）"""
    # 获取最近7条开播记录
    records = list(BattleRecord.objects(pilot=pilot).order_by('-start_time').limit(7))
    approved_map, _ = _build_base_salary_maps(records)

    return _calculate_stats_from_records(records, approved_map)


def _calculate_three_day_stats(pilot: Pilot) -> Dict[str, Any]:
    """计算近3日统计（最近的3条开播记录）"""
    # 获取最近3条开播记录
    records = list(BattleRecord.objects(pilot=pilot).order_by('-start_time').limit(3))
    approved_map, _ = _build_base_salary_maps(records)

    return _calculate_stats_from_records(records, approved_map)


def _calculate_stats_from_records(records, approved_map=None) -> Dict[str, Any]:
    """从开播记录计算统计数据"""
    # 如果是QuerySet，转换为列表
    if not isinstance(records, list):
        records = list(records)

    record_count = len(records)
    total_hours = round(sum(record.duration_hours for record in records if record.duration_hours), 1)
    avg_hours = round(total_hours / record_count, 1) if record_count > 0 else 0

    total_revenue = sum((record.revenue_amount or Decimal('0')) for record in records)
    total_basepay = sum((approved_map.get(str(record.id), Decimal('0')) if approved_map else Decimal('0') for record in records), Decimal('0'))

    # 计算日均数据（分母为开播记录数）
    daily_avg_revenue = total_revenue / record_count if record_count > 0 else Decimal('0')
    daily_avg_basepay = total_basepay / record_count if record_count > 0 else Decimal('0')

    # 使用正确的公司分成计算
    total_company_share = Decimal('0')
    if records:
        pilot_id = str(records[0].pilot.id) if records[0].pilot else None
        for record in records:
            revenue_amount = Decimal(record.revenue_amount or Decimal('0'))
            record_date = utc_to_local(record.start_time).date() if record.start_time else None
            commission_rate = get_pilot_commission_rate_for_date(pilot_id, record_date)[0] if record_date and pilot_id else 20.0
            commission_amounts = calculate_commission_amounts(revenue_amount, commission_rate)
            total_company_share += commission_amounts['company_amount']

    # 计算返点
    total_rebate = Decimal('0')
    if records:
        # 计算有效开播天数（播时≥1小时的天数）
        daily_duration_map = defaultdict(float)
        for record in records:
            if record.start_time:
                local_day = utc_to_local(record.start_time).date()
                daily_duration_map[local_day] += float(record.duration_hours or 0)

        valid_days = sum(1 for duration in daily_duration_map.values() if duration >= 1.0)
        total_duration_float = float(total_hours)

        # 使用统一返点计算器
        rebate_rate, total_rebate = calculate_pilot_rebate(valid_days, total_duration_float, total_revenue)
        pilot_id = records[0].pilot.id if records and records[0].pilot else 'unknown'
        logger.debug('主播 %s 近期返点计算 - 有效天数: %d, 总播时: %.1f, 总流水: %s, 返点比例: %.2f%%, 返点金额: %s', pilot_id, valid_days, total_duration_float, total_revenue,
                     rebate_rate * 100, total_rebate)

    # 运营利润估算
    operating_profit = total_company_share + total_rebate - total_basepay
    daily_avg_operating_profit = operating_profit / record_count if record_count > 0 else Decimal('0')

    return {
        'record_count': record_count,
        'total_hours': total_hours,
        'avg_hours': avg_hours,
        'total_revenue': total_revenue,
        'daily_avg_revenue': daily_avg_revenue,
        'total_basepay': total_basepay,
        'daily_avg_basepay': daily_avg_basepay,
        'total_rebate': total_rebate,
        'total_company_share': total_company_share,
        'operating_profit': operating_profit,
        'daily_avg_operating_profit': daily_avg_operating_profit
    }


def _build_month_daily_series(daily_totals: Dict[date, Dict[str, Decimal]], month_start_date: date, month_end_date: date) -> List[Dict[str, Any]]:
    if month_start_date > month_end_date:
        return []

    cumulative = {'revenue': Decimal('0'), 'basepay': Decimal('0'), 'company_share': Decimal('0'), 'hours': Decimal('0')}
    series: List[Dict[str, Any]] = []
    current_day = month_start_date
    while current_day <= month_end_date:
        metrics = daily_totals.get(current_day) or _create_daily_bucket()
        cumulative['revenue'] += metrics['revenue']
        cumulative['basepay'] += metrics['basepay']
        cumulative['company_share'] += metrics['company_share']
        cumulative['hours'] += metrics['hours']

        operating_profit = cumulative['company_share'] - cumulative['basepay']

        series.append({
            'date': current_day.strftime('%Y-%m-%d'),
            'revenue_cumulative': cumulative['revenue'],
            'basepay_cumulative': cumulative['basepay'],
            'company_share_cumulative': cumulative['company_share'],
            'operating_profit_cumulative': operating_profit,
            'hours_cumulative': cumulative['hours'],
        })
        current_day += timedelta(days=1)
    return series


def _get_recent_records(pilot: Pilot, limit: int = 30) -> List[BattleRecord]:
    """获取最近的开播记录"""
    return list(BattleRecord.objects(pilot=pilot).order_by('-start_time').limit(limit))


def _get_recent_records_with_applications(pilot: Pilot, limit: int = 30) -> List[BattleRecord]:
    """获取最近开播记录并附带底薪申请数据"""
    records = _get_recent_records(pilot, limit)
    approved_map, application_map = _build_base_salary_maps(records)

    for record in records:
        setattr(record, '_approved_base_salary', approved_map.get(str(record.id), Decimal('0')))
        setattr(record, '_latest_base_salary_application', application_map.get(str(record.id)))
    return records


def _build_base_salary_maps(records: List[BattleRecord]) -> Tuple[Dict[str, Decimal], Dict[str, BaseSalaryApplication]]:
    """根据开播记录批量构建底薪金额与关联申请映射"""
    record_ids = [record.id for record in records if record.id]
    if not record_ids:
        return {}, {}

    applications = list(BaseSalaryApplication.objects.filter(battle_record_id__in=record_ids))

    approved_map: defaultdict[str, Decimal] = defaultdict(lambda: Decimal('0'))
    latest_map: Dict[str, BaseSalaryApplication] = {}

    for application in applications:
        battle_record = application.battle_record_id
        if not battle_record:
            continue
        record_key = str(battle_record.id)
        amount = Decimal(application.base_salary_amount or Decimal('0'))
        if application.status == BaseSalaryApplicationStatus.APPROVED:
            approved_map[record_key] += amount

        current_latest = latest_map.get(record_key)
        current_updated_at = current_latest.updated_at if current_latest and current_latest.updated_at else None
        application_updated_at = application.updated_at or application.created_at
        if not current_latest or (application_updated_at and application_updated_at >= (current_updated_at or application_updated_at)):
            latest_map[record_key] = application

    return dict(approved_map), latest_map
