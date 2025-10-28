"""开播新报表 REST 接口序列化工具。"""
from decimal import Decimal
from typing import Any, Dict, List, Optional


def create_success_response(data: Any = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """生成统一成功响应结构。"""
    return {'success': True, 'data': data, 'error': None, 'meta': meta or {}}


def create_error_response(code: str, message: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """生成统一错误响应结构。"""
    return {'success': False, 'data': None, 'error': {'code': code, 'message': message}, 'meta': meta or {}}


def _decimal_to_float(value: Any) -> Optional[float]:
    """将 Decimal 转换为浮点数，保留 None。"""
    if value is None:
        return None
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (int, float)):
        return float(value)
    return value


def _enum_to_str(value: Any) -> Optional[str]:
    """将枚举转换为字符串值，保留 None。"""
    if value is None:
        return None
    if hasattr(value, 'value'):
        return str(value.value)
    return str(value) if value else None


def serialize_daily_summary(raw: Dict[str, Any]) -> Dict[str, Any]:
    """序列化日报汇总数据。"""
    return {
        'pilot_count': raw.get('pilot_count', 0),
        'effective_pilot_count': raw.get('effective_pilot_count', 0),
        'revenue_sum': _decimal_to_float(raw.get('revenue_sum')),
        'basepay_sum': _decimal_to_float(raw.get('basepay_sum')),
        'pilot_share_sum': _decimal_to_float(raw.get('pilot_share_sum')),
        'company_share_sum': _decimal_to_float(raw.get('company_share_sum')),
        'conversion_rate': raw.get('conversion_rate'),
    }


def serialize_month_snapshot(raw: Dict[str, Any]) -> Dict[str, Any]:
    """序列化日报明细中的月度统计。"""
    return {
        'month_days_count': raw.get('month_days_count', 0),
        'month_avg_duration': _decimal_to_float(raw.get('month_avg_duration')),
        'month_total_revenue': _decimal_to_float(raw.get('month_total_revenue')),
        'month_total_base_salary': _decimal_to_float(raw.get('month_total_base_salary')),
    }


def serialize_month_commission_snapshot(raw: Dict[str, Any]) -> Dict[str, Any]:
    """序列化日报明细中的月度分成统计。"""
    return {
        'month_total_pilot_share': _decimal_to_float(raw.get('month_total_pilot_share')),
        'month_total_company_share': _decimal_to_float(raw.get('month_total_company_share')),
        'month_total_profit': _decimal_to_float(raw.get('month_total_profit')),
    }


def serialize_daily_detail(raw: Dict[str, Any]) -> Dict[str, Any]:
    """序列化日报单条明细。"""
    return {
        'pilot_id': raw.get('pilot_id'),
        'pilot_display': raw.get('pilot_display', ''),
        'gender_age': raw.get('gender_age', ''),
        'owner': raw.get('owner', ''),
        'rank': _enum_to_str(raw.get('rank')),
        'battle_area': raw.get('battle_area', ''),
        'duration': _decimal_to_float(raw.get('duration')),
        'revenue': _decimal_to_float(raw.get('revenue')),
        'commission_rate': _decimal_to_float(raw.get('commission_rate')),
        'pilot_share': _decimal_to_float(raw.get('pilot_share')),
        'company_share': _decimal_to_float(raw.get('company_share')),
        'base_salary': _decimal_to_float(raw.get('base_salary')),
        'daily_profit': _decimal_to_float(raw.get('daily_profit')),
        'three_day_avg_revenue': _decimal_to_float(raw.get('three_day_avg_revenue')),
        'monthly_stats': serialize_month_snapshot(raw.get('monthly_stats', {})),
        'monthly_commission_stats': serialize_month_commission_snapshot(raw.get('monthly_commission_stats', {})),
        'status': _enum_to_str(raw.get('status')),
        'status_display': _enum_to_str(raw.get('status_display'))
    }


def serialize_weekly_summary(raw: Dict[str, Any]) -> Dict[str, Any]:
    """序列化周报汇总数据。"""
    return {
        'pilot_count': raw.get('pilot_count', 0),
        'revenue_sum': _decimal_to_float(raw.get('revenue_sum')),
        'basepay_sum': _decimal_to_float(raw.get('basepay_sum')),
        'pilot_share_sum': _decimal_to_float(raw.get('pilot_share_sum')),
        'company_share_sum': _decimal_to_float(raw.get('company_share_sum')),
        'profit_7d': _decimal_to_float(raw.get('profit_7d')),
        'conversion_rate': raw.get('conversion_rate'),
    }


def serialize_weekly_detail(raw: Dict[str, Any]) -> Dict[str, Any]:
    """序列化周报单条明细。"""
    return {
        'pilot_id': raw.get('pilot_id'),
        'pilot_display': raw.get('pilot_display', ''),
        'gender_age': raw.get('gender_age', ''),
        'owner': raw.get('owner', ''),
        'rank': raw.get('rank', ''),
        'records_count': raw.get('records_count', 0),
        'avg_duration': _decimal_to_float(raw.get('avg_duration')),
        'total_revenue': _decimal_to_float(raw.get('total_revenue')),
        'total_pilot_share': _decimal_to_float(raw.get('total_pilot_share')),
        'total_company_share': _decimal_to_float(raw.get('total_company_share')),
        'total_base_salary': _decimal_to_float(raw.get('total_base_salary')),
        'total_profit': _decimal_to_float(raw.get('total_profit')),
    }


def serialize_daily_details(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [serialize_daily_detail(item) for item in items]


def serialize_weekly_details(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [serialize_weekly_detail(item) for item in items]


def serialize_monthly_summary(raw: Dict[str, Any]) -> Dict[str, Any]:
    """序列化月报汇总数据（快速月报使用）。"""
    return {
        'pilot_count': raw.get('pilot_count', 0),
        'revenue_sum': _decimal_to_float(raw.get('revenue_sum')),
        'basepay_sum': _decimal_to_float(raw.get('basepay_sum')),
        'rebate_sum': _decimal_to_float(raw.get('rebate_sum')),
        'pilot_share_sum': _decimal_to_float(raw.get('pilot_share_sum')),
        'company_share_sum': _decimal_to_float(raw.get('company_share_sum')),
        'operating_profit': _decimal_to_float(raw.get('operating_profit')),
        'conversion_rate': raw.get('conversion_rate'),
    }


def serialize_monthly_detail(raw: Dict[str, Any]) -> Dict[str, Any]:
    """序列化月报单条明细（快速月报使用）。"""
    return {
        'pilot_id': raw.get('pilot_id'),
        'pilot_display': raw.get('pilot_display', ''),
        'gender_age': raw.get('gender_age', ''),
        'owner': raw.get('owner', ''),
        'rank': raw.get('rank', ''),
        'records_count': raw.get('records_count', 0),
        'avg_duration': _decimal_to_float(raw.get('avg_duration')),
        'total_revenue': _decimal_to_float(raw.get('total_revenue')),
        'daily_avg_profit': _decimal_to_float(raw.get('daily_avg_profit')),
        'total_profit': _decimal_to_float(raw.get('total_profit')),
        'total_pilot_share': _decimal_to_float(raw.get('total_pilot_share')),
        'total_company_share': _decimal_to_float(raw.get('total_company_share')),
        'rebate_rate': _decimal_to_float(raw.get('rebate_rate')),
        'rebate_amount': _decimal_to_float(raw.get('rebate_amount')),
        'total_base_salary': _decimal_to_float(raw.get('total_base_salary')),
    }


def serialize_monthly_details(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [serialize_monthly_detail(item) for item in items]


def serialize_monthly_daily_series(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """序列化月报日级序列，用于前端折线图（快速月报使用）。"""
    serialized: List[Dict[str, Any]] = []
    for item in items:
        serialized.append({
            'date': item.get('date'),
            'revenue_cumulative': _decimal_to_float(item.get('revenue_cumulative')),
            'basepay_cumulative': _decimal_to_float(item.get('basepay_cumulative')),
            'pilot_share_cumulative': _decimal_to_float(item.get('pilot_share_cumulative')),
            'company_share_cumulative': _decimal_to_float(item.get('company_share_cumulative')),
            'operating_profit_cumulative': _decimal_to_float(item.get('operating_profit_cumulative')),
        })
    return serialized
