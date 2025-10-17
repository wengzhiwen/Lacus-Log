# -*- coding: utf-8 -*-
"""
主播业绩计算工具
"""

from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List

from models.battle_record import BattleRecord
from models.pilot import Pilot
from utils.logging_setup import get_logger
from utils.timezone_helper import get_current_local_time

logger = get_logger('pilot_performance')


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
    month_stats = _calculate_month_stats(pilot, report_date)

    # 计算近7日统计
    week_stats = _calculate_week_stats(pilot)

    # 计算近3日统计
    three_day_stats = _calculate_three_day_stats(pilot)

    # 获取最近开播记录
    recent_records = _get_recent_records(pilot, limit=30)

    return {'month_stats': month_stats, 'week_stats': week_stats, 'three_day_stats': three_day_stats, 'recent_records': recent_records}


def _calculate_month_stats(pilot: Pilot, report_date: datetime) -> Dict[str, Any]:
    """计算本月统计"""
    # 本月开始时间（本地时间）
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    # 本月结束时间（本地时间）
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    # 转换为UTC时间
    from utils.timezone_helper import local_to_utc
    month_start_utc = local_to_utc(month_start)
    month_end_utc = local_to_utc(month_end)

    # 获取本月开播记录
    records = BattleRecord.objects(pilot=pilot, start_time__gte=month_start_utc, start_time__lte=month_end_utc).order_by('start_time')

    # 计算统计数据
    record_count = records.count()
    total_hours = round(sum(record.duration_hours for record in records if record.duration_hours), 1)
    avg_hours = round(total_hours / record_count, 1) if record_count > 0 else 0

    total_revenue = sum(record.revenue_amount for record in records)
    total_basepay = sum(record.base_salary for record in records)

    # 计算日均数据（分母为开播记录数）
    daily_avg_revenue = total_revenue / record_count if record_count > 0 else Decimal('0')
    daily_avg_basepay = total_basepay / record_count if record_count > 0 else Decimal('0')

    # 计算公司分成和返点（简化计算，实际应该根据分成比例计算）
    total_company_share = total_revenue * Decimal('0.3')  # 假设公司分成30%
    total_rebate = Decimal('0')  # 返点计算较复杂，暂时设为0

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


def _calculate_week_stats(pilot: Pilot) -> Dict[str, Any]:
    """计算近7日统计（最近的7条开播记录）"""
    # 获取最近7条开播记录
    records = list(BattleRecord.objects(pilot=pilot).order_by('-start_time').limit(7))

    return _calculate_stats_from_records(records)


def _calculate_three_day_stats(pilot: Pilot) -> Dict[str, Any]:
    """计算近3日统计（最近的3条开播记录）"""
    # 获取最近3条开播记录
    records = list(BattleRecord.objects(pilot=pilot).order_by('-start_time').limit(3))

    return _calculate_stats_from_records(records)


def _calculate_stats_from_records(records) -> Dict[str, Any]:
    """从开播记录计算统计数据"""
    # 如果是QuerySet，转换为列表
    if not isinstance(records, list):
        records = list(records)
    
    record_count = len(records)
    total_hours = round(sum(record.duration_hours for record in records if record.duration_hours), 1)
    avg_hours = round(total_hours / record_count, 1) if record_count > 0 else 0

    total_revenue = sum(record.revenue_amount for record in records)
    total_basepay = sum(record.base_salary for record in records)

    # 计算日均数据（分母为开播记录数）
    daily_avg_revenue = total_revenue / record_count if record_count > 0 else Decimal('0')
    daily_avg_basepay = total_basepay / record_count if record_count > 0 else Decimal('0')

    # 计算公司分成（简化计算）
    total_company_share = total_revenue * Decimal('0.3')  # 假设公司分成30%
    total_rebate = Decimal('0')  # 返点计算较复杂，暂时设为0

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


def _get_recent_records(pilot: Pilot, limit: int = 30) -> List[BattleRecord]:
    """获取最近的开播记录"""
    return list(BattleRecord.objects(pilot=pilot).order_by('-start_time').limit(limit))
