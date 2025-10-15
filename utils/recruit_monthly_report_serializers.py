# -*- coding: utf-8 -*-
"""主播招募月报 REST 响应序列化工具。"""
from datetime import datetime
from typing import Any, Dict, List, Optional

from models.recruit import Recruit
from models.pilot import Pilot
from utils.timezone_helper import utc_to_local

MONTHLY_METRIC_LABELS: Dict[str, str] = {
    'appointments': '约面数',
    'interviews': '到面数',
    'trials': '试播数',
    'new_recruits': '新开播数',
    'full_7_days': '满7天数',
}

CONVERSION_RATE_LABELS: Dict[str, str] = {
    'interview_conversion': '到面转化率',
    'trial_conversion': '试播转化率',
    'broadcast_conversion': '新开播转化率',
    'full_7_days_conversion': '满7天转化率',
}

TREND_LABELS: Dict[str, str] = {
    'up': '↑',
    'down': '↓',
    'stable': '—',
}


def _enum_to_value(value: Any) -> Any:
    """将枚举转换为值。"""
    if value is None:
        return None
    return getattr(value, 'value', value)


def _format_local_iso(dt: Optional[datetime]) -> Optional[str]:
    """将UTC时间转换为本地ISO字符串。"""
    if dt is None:
        return None
    local_dt = utc_to_local(dt)
    if not local_dt:
        return None
    return local_dt.strftime('%Y-%m-%dT%H:%M:%S')


def _format_local_display(dt: Optional[datetime]) -> str:
    """生成本地时间的展示用字符串。"""
    if dt is None:
        return '未知'
    local_dt = utc_to_local(dt)
    if not local_dt:
        return '未知'
    return local_dt.strftime('%m月%d日 %H:%M')


def serialize_monthly_stats(stats: Dict[str, int]) -> Dict[str, int]:
    """序列化月报统计数据。"""
    return {
        'appointments': stats.get('appointments', 0),
        'interviews': stats.get('interviews', 0),
        'trials': stats.get('trials', 0),
        'new_recruits': stats.get('new_recruits', 0),
        'full_7_days': stats.get('full_7_days', 0),
    }


def serialize_conversion_rates(rates: Dict[str, float]) -> Dict[str, Any]:
    """序列化转化率数据。"""
    return {
        'interview_conversion': {
            'value': rates.get('interview_conversion', 0.0),
            'display': f"{rates.get('interview_conversion', 0.0):.1f}%",
        },
        'trial_conversion': {
            'value': rates.get('trial_conversion', 0.0),
            'display': f"{rates.get('trial_conversion', 0.0):.1f}%",
        },
        'broadcast_conversion': {
            'value': rates.get('broadcast_conversion', 0.0),
            'display': f"{rates.get('broadcast_conversion', 0.0):.1f}%",
        },
        'full_7_days_conversion': {
            'value': rates.get('full_7_days_conversion', 0.0),
            'display': f"{rates.get('full_7_days_conversion', 0.0):.1f}%",
        },
    }


def serialize_trends(trends: Dict[str, str]) -> Dict[str, str]:
    """序列化趋势数据。"""
    return {
        'appointments': trends.get('appointments', 'stable'),
        'interviews': trends.get('interviews', 'stable'),
        'trials': trends.get('trials', 'stable'),
        'new_recruits': trends.get('new_recruits', 'stable'),
        'full_7_days': trends.get('full_7_days', 'stable'),
    }


def serialize_metric_card(metric: str, value: int, trend: str, conversion_rate: Optional[float] = None) -> Dict[str, Any]:
    """序列化单个指标卡片。"""
    card = {
        'metric': metric,
        'label': MONTHLY_METRIC_LABELS.get(metric, metric),
        'value': value,
        'trend': {
            'symbol': TREND_LABELS.get(trend, '—'),
            'direction': trend,
        },
    }

    # 为到面数及之后的指标添加转化率
    if metric in ['interviews', 'trials', 'new_recruits', 'full_7_days'] and conversion_rate is not None:
        card['conversion_rate'] = {
            'value': round(conversion_rate, 1),
            'display': f"{conversion_rate:.1f}%",
        }
    else:
        card['conversion_rate'] = None

    return card


def build_monthly_summary_payload(monthly_stats: Dict[str, Any]) -> Dict[str, Any]:
    """构建月报汇总响应数据。"""
    current_window = monthly_stats.get('current_window', {})
    previous_window = monthly_stats.get('previous_window', {})
    trends = monthly_stats.get('trends', {})

    current_stats = serialize_monthly_stats(current_window.get('stats', {}))
    current_rates = serialize_conversion_rates(current_window.get('rates', {}))
    serialized_trends = serialize_trends(trends)

    # 构建指标卡片
    cards = []

    # 约面数卡片
    cards.append(serialize_metric_card('appointments', current_stats['appointments'], serialized_trends['appointments']))

    # 到面数卡片（含到面转化率）
    cards.append(
        serialize_metric_card('interviews', current_stats['interviews'], serialized_trends['interviews'], current_rates['interview_conversion']['value']))

    # 试播数卡片（含试播转化率）
    cards.append(serialize_metric_card('trials', current_stats['trials'], serialized_trends['trials'], current_rates['trial_conversion']['value']))

    # 新开播数卡片（含新开播转化率）
    cards.append(
        serialize_metric_card('new_recruits', current_stats['new_recruits'], serialized_trends['new_recruits'], current_rates['broadcast_conversion']['value']))

    # 满7天数卡片（含满7天转化率）
    cards.append(
        serialize_metric_card('full_7_days', current_stats['full_7_days'], serialized_trends['full_7_days'], current_rates['full_7_days_conversion']['value']))

    return {
        'window_info': {
            'current_start': current_window.get('start_date'),
            'current_end': current_window.get('end_date'),
            'previous_start': previous_window.get('start_date'),
            'previous_end': previous_window.get('end_date'),
        },
        'stats': current_stats,
        'rates': current_rates,
        'trends': serialized_trends,
        'cards': cards,
    }


def serialize_monthly_detail_record(recruit_data: Dict[str, Any]) -> Dict[str, Any]:
    """序列化月报明细记录。"""
    recruit = recruit_data.get('recruit')
    if not recruit:
        return {}

    pilot = recruit.pilot

    return {
        'id': str(recruit.id),
        'pilot': {
            'id': str(pilot.id) if pilot else None,
            'nickname': pilot.nickname if pilot else None,
            'real_name': pilot.real_name if pilot else None,
            'gender': pilot.gender.value if pilot and hasattr(pilot, 'gender') else None,
        },
        'recruiter': {
            'id': str(recruit.recruiter.id),
            'nickname': getattr(recruit.recruiter, 'nickname', None),
            'username': getattr(recruit.recruiter, 'username', None),
        } if recruit.recruiter else None,
        'owner': {
            'id': str(pilot.owner.id),
            'nickname': getattr(pilot.owner, 'nickname', None),
            'username': getattr(pilot.owner, 'username', None),
        } if pilot and pilot.owner else None,
        'status': _enum_to_value(recruit.get_effective_status()),
        'channel': _enum_to_value(recruit.channel),
        'introduction_fee': float(recruit.introduction_fee) if recruit.introduction_fee else 0,
        'broadcast_days': recruit_data.get('broadcast_days', 0),
        'long_sessions_count': recruit_data.get('long_sessions_count', 0),
        'last_broadcast_time': _format_local_iso(recruit_data.get('last_broadcast_time')),
        'created_at': _format_local_iso(recruit.created_at),
        'interview_decision_time': _format_local_iso(recruit.get_effective_interview_decision_time()),
        'training_decision_time': _format_local_iso(recruit.get_effective_training_decision_time()),
        'broadcast_decision_time': _format_local_iso(recruit.get_effective_broadcast_decision_time()),
        'remarks': recruit.remarks or '',
    }


def serialize_monthly_detail_records(recruit_data_list: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """批量序列化月报明细记录。"""
    return [serialize_monthly_detail_record(recruit_data) for recruit_data in recruit_data_list]


def build_monthly_detail_payload(recruit_data_list: List[Dict[str, Any]]) -> Dict[str, Any]:
    """构建月报明细响应数据。"""
    return {
        'count': len(recruit_data_list),
        'records': serialize_monthly_detail_records(recruit_data_list),
    }
