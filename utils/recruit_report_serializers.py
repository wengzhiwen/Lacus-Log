# -*- coding: utf-8 -*-
"""招募日报 REST 响应序列化工具。"""
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from models.recruit import Recruit
from utils.timezone_helper import utc_to_local

RANGE_LABELS: Dict[str, str] = {
    'report_day': '报表日',
    'last_7_days': '近7日',
    'last_14_days': '近14日',
}

METRIC_LABELS: Dict[str, str] = {
    'appointments': '约面',
    'interviews': '到面',
    'trials': '试播',
    'new_recruits': '新开播',
}


def _enum_to_value(value: Any) -> Any:
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


def serialize_summary_block(stats: Dict[str, int]) -> Dict[str, int]:
    """序列化统计计数信息。"""
    return {
        'appointments': stats.get('appointments', 0),
        'interviews': stats.get('interviews', 0),
        'trials': stats.get('trials', 0),
        'new_recruits': stats.get('new_recruits', 0),
    }


def serialize_average_block(averages: Dict[str, float]) -> Dict[str, float]:
    """序列化日均数据信息。"""
    return {
        'appointments': float(averages.get('appointments', 0.0)),
        'interviews': float(averages.get('interviews', 0.0)),
        'trials': float(averages.get('trials', 0.0)),
        'new_recruits': float(averages.get('new_recruits', 0.0)),
    }


def build_daily_summary_payload(report_date: datetime, raw_stats: Dict[str, Any]) -> Dict[str, Any]:
    """构建日报汇总响应数据。"""
    summary = {
        'report_day': serialize_summary_block(raw_stats.get('report_day', {})),
        'last_7_days': serialize_summary_block(raw_stats.get('last_7_days', {})),
        'last_14_days': serialize_summary_block(raw_stats.get('last_14_days', {})),
    }

    averages_raw = raw_stats.get('averages', {})
    averages = {
        'last_7_days': serialize_average_block(averages_raw.get('last_7_days', {})),
        'last_14_days': serialize_average_block(averages_raw.get('last_14_days', {})),
    }

    return {
        'date': report_date.strftime('%Y-%m-%d'),
        'summary': summary,
        'averages': averages,
    }


def _resolve_metric_time(recruit: Recruit, metric: str) -> Tuple[str, Optional[datetime]]:
    """根据指标确定突出展示的时间与标签。"""
    if metric == 'appointments':
        return '创建', recruit.created_at
    if metric == 'interviews':
        return '面试决策', recruit.get_effective_interview_decision_time()
    if metric == 'trials':
        return '试播决策', recruit.get_effective_training_decision_time()
    if metric == 'new_recruits':
        return '开播决策', recruit.get_effective_broadcast_decision_time()
    return '', None


def serialize_detail_record(recruit: Recruit, metric: str) -> Dict[str, Any]:
    """序列化日报详情记录。"""
    highlight_label, highlight_dt = _resolve_metric_time(recruit, metric)

    return {
        'id': str(recruit.id),
        'pilot': {
            'id': str(recruit.pilot.id) if recruit.pilot else None,
            'nickname': recruit.pilot.nickname if recruit.pilot else None,
            'real_name': recruit.pilot.real_name if recruit.pilot else None,
        },
        'recruiter': {
            'id': str(recruit.recruiter.id),
            'nickname': getattr(recruit.recruiter, 'nickname', None),
            'username': getattr(recruit.recruiter, 'username', None),
        } if recruit.recruiter else None,
        'channel': _enum_to_value(recruit.channel),
        'effective_status': _enum_to_value(recruit.get_effective_status()),
        'highlight': {
            'label': highlight_label,
            'time': _format_local_iso(highlight_dt),
            'display': _format_local_display(highlight_dt),
        },
        'created_at': _format_local_iso(recruit.created_at),
        'remarks': recruit.remarks or '',
    }


def serialize_detail_records(recruits: List[Recruit], metric: str) -> List[Dict[str, Any]]:
    """批量序列化日报详情记录。"""
    return [serialize_detail_record(recruit, metric) for recruit in recruits]


def build_daily_detail_payload(report_date: datetime, range_param: str, metric: str, recruits: List[Recruit]) -> Dict[str, Any]:
    """构建日报详情响应数据。"""
    return {
        'date': report_date.strftime('%Y-%m-%d'),
        'range': range_param,
        'metric': metric,
        'range_label': RANGE_LABELS.get(range_param, range_param),
        'metric_label': METRIC_LABELS.get(metric, metric),
        'count': len(recruits),
        'recruits': serialize_detail_records(recruits, metric),
    }
