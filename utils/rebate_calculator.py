# -*- coding: utf-8 -*-
"""
主播月度返点计算工具模块

提供统一的返点阶梯设置和计算逻辑，供快速月报、传统报告和主播业绩页共同使用。
"""

from __future__ import annotations

from decimal import Decimal
from typing import Dict, List, Tuple

from utils.logging_setup import get_logger

logger = get_logger('rebate_calculator')


def get_rebate_stages() -> Tuple[Dict[str, object], ...]:
    """获取返点阶梯设置。

    Returns:
        返点阶梯配置元组
    """
    return (
        {
            'stage': 1,
            'min_days': 10,
            'min_hours': 30,
            'min_revenue': Decimal('1000'),
            'rate': 0.05
        },
        {
            'stage': 2,
            'min_days': 15,
            'min_hours': 70,
            'min_revenue': Decimal('5000'),
            'rate': 0.07
        },
        {
            'stage': 3,
            'min_days': 15,
            'min_hours': 70,
            'min_revenue': Decimal('10000'),
            'rate': 0.12
        },
        {
            'stage': 4,
            'min_days': 20,
            'min_hours': 100,
            'min_revenue': Decimal('20000'),
            'rate': 0.14
        },
        {
            'stage': 5,
            'min_days': 20,
            'min_hours': 100,
            'min_revenue': Decimal('60000'),
            'rate': 0.16
        },
    )


def calculate_pilot_rebate(valid_days: int, total_duration: float, total_revenue: Decimal) -> Tuple[float, Decimal]:
    """根据有效天数、总播时和总流水计算返点比例与金额。

    Args:
        valid_days: 有效开播天数（播时≥1小时的天数）
        total_duration: 总播时长（小时）
        total_revenue: 总流水（元）

    Returns:
        返点比例和金额的元组 (rate, amount)
    """
    rebate_stages = get_rebate_stages()

    qualified_stages = [
        stage for stage in rebate_stages
        if (valid_days >= stage['min_days'] and
            total_duration >= stage['min_hours'] and
            total_revenue >= stage['min_revenue'])
    ]

    if not qualified_stages:
        return 0.0, Decimal('0')

    best_stage = max(qualified_stages, key=lambda item: item['stage'])
    rate = float(best_stage['rate'])
    rebate_amount = total_revenue * Decimal(str(rate))

    logger.debug('返点计算结果 - 有效天数: %d, 总播时: %.1f, 总流水: %s, 返点比例: %.2f%%, 返点金额: %s',
                   valid_days, total_duration, total_revenue, rate * 100, rebate_amount)

    return rate, rebate_amount


def get_rebate_stage_info(valid_days: int, total_duration: float, total_revenue: Decimal) -> Dict[str, object]:
    """获取返点阶段详细信息。

    Args:
        valid_days: 有效开播天数（播时≥1小时的天数）
        total_duration: 总播时长（小时）
        total_revenue: 总流水（元）

    Returns:
        包含返点详情的字典
    """
    rebate_stages = get_rebate_stages()

    qualified_stages = [
        stage for stage in rebate_stages
        if (valid_days >= stage['min_days'] and
            total_duration >= stage['min_hours'] and
            total_revenue >= stage['min_revenue'])
    ]

    if qualified_stages:
        best_stage = max(qualified_stages, key=lambda x: x['stage'])
        rebate_amount = total_revenue * Decimal(str(best_stage['rate']))
        return {
            'rebate_amount': rebate_amount,
            'rebate_rate': best_stage['rate'],
            'rebate_stage': best_stage['stage'],
            'valid_days_count': valid_days,
            'total_duration': total_duration,
            'total_revenue': total_revenue,
            'qualified_stages': qualified_stages
        }

    return {
        'rebate_amount': Decimal('0'),
        'rebate_rate': 0,
        'rebate_stage': 0,
        'valid_days_count': valid_days,
        'total_duration': total_duration,
        'total_revenue': total_revenue,
        'qualified_stages': []
    }