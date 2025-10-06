"""
招募统计工具模块

提供统一的招募统计数据计算功能，避免在多个地方重复实现相同的逻辑。
"""
# pylint: disable=no-member
from datetime import datetime, timedelta
from typing import Any, Dict

from mongoengine import Q

from models.recruit import BroadcastDecision, FinalDecision, Recruit
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)


def calculate_recruit_period_stats(start_utc: datetime, end_utc: datetime, recruiter_id: str = None) -> Dict[str, int]:
    """计算指定时间范围内的招募统计数据
    
    Args:
        start_utc: 开始时间（UTC）
        end_utc: 结束时间（UTC）
        recruiter_id: 招募负责人ID，为None时统计全部
        
    Returns:
        dict: 包含约面、到面、试播、新开播的统计数据
    """
    base_query = {}
    if recruiter_id and recruiter_id != 'all':
        base_query['recruiter'] = recruiter_id

    appointments_query = {**base_query, 'created_at__gte': start_utc, 'created_at__lt': end_utc}
    appointments = Recruit.objects.filter(**appointments_query).count()

    interviews_query = Q(**base_query) & (Q(interview_decision_time__gte=start_utc, interview_decision_time__lt=end_utc)
                                          | Q(training_decision_time_old__gte=start_utc, training_decision_time_old__lt=end_utc))
    interviews = Recruit.objects.filter(interviews_query).count()

    trials_query = Q(**base_query) & (Q(training_decision_time__gte=start_utc, training_decision_time__lt=end_utc)
                                      | Q(training_decision_time_old__gte=start_utc, training_decision_time_old__lt=end_utc))
    trials = Recruit.objects.filter(trials_query).count()

    new_recruits_query = Q(**base_query) & (
        Q(broadcast_decision_time__gte=start_utc,
          broadcast_decision_time__lt=end_utc,
          broadcast_decision__in=[BroadcastDecision.OFFICIAL, BroadcastDecision.INTERN, BroadcastDecision.OFFICIAL_OLD, BroadcastDecision.INTERN_OLD])
        | Q(final_decision_time__gte=start_utc, final_decision_time__lt=end_utc, final_decision__in=[FinalDecision.OFFICIAL, FinalDecision.INTERN]))
    new_recruits = Recruit.objects.filter(new_recruits_query).count()

    return {'appointments': appointments, 'interviews': interviews, 'trials': trials, 'new_recruits': new_recruits}


def calculate_recruit_stats_for_date(target_date: datetime, recruiter_id: str = None) -> Dict[str, int]:
    """计算指定日期的招募统计数据
    
    Args:
        target_date: 目标日期（本地时间）
        recruiter_id: 招募负责人ID，为None时统计全部
        
    Returns:
        dict: 包含约面、到面、试播、新开播的统计数据
    """
    date_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    date_end = date_start + timedelta(days=1)

    date_start_utc = local_to_utc(date_start)
    date_end_utc = local_to_utc(date_end)

    return calculate_recruit_period_stats(date_start_utc, date_end_utc, recruiter_id)


def calculate_recruit_daily_stats(report_date: datetime, recruiter_id: str = None) -> Dict[str, Any]:
    """计算指定日期的招募日报统计数据（包含多时间维度和日均数据）
    
    Args:
        report_date: 报表日期（本地时间）
        recruiter_id: 招募负责人ID，为None时统计全部
        
    Returns:
        dict: 包含报表日、近7日、近14日的统计数据，以及日均数据
    """
    report_day_start = report_date
    report_day_end = report_day_start + timedelta(days=1)

    last_7_days_start = report_date - timedelta(days=6)
    last_14_days_start = report_date - timedelta(days=13)

    report_day_start_utc = local_to_utc(report_day_start)
    report_day_end_utc = local_to_utc(report_day_end)
    last_7_days_start_utc = local_to_utc(last_7_days_start)
    last_14_days_start_utc = local_to_utc(last_14_days_start)

    report_day_stats = calculate_recruit_period_stats(report_day_start_utc, report_day_end_utc, recruiter_id)
    last_7_days_stats = calculate_recruit_period_stats(last_7_days_start_utc, report_day_end_utc, recruiter_id)
    last_14_days_stats = calculate_recruit_period_stats(last_14_days_start_utc, report_day_end_utc, recruiter_id)

    statistics = {'report_day': report_day_stats, 'last_7_days': last_7_days_stats, 'last_14_days': last_14_days_stats}

    averages = {'last_7_days': {}, 'last_14_days': {}}

    for key in ['appointments', 'interviews', 'trials', 'new_recruits']:
        last_7_value = statistics['last_7_days'][key]
        averages['last_7_days'][key] = round(last_7_value / 7, 1)

    for key in ['appointments', 'interviews', 'trials', 'new_recruits']:
        last_14_value = statistics['last_14_days'][key]
        averages['last_14_days'][key] = round(last_14_value / 14, 1)

    statistics['averages'] = averages
    return statistics


def get_recruit_records_for_detail(report_date: datetime, range_param: str, metric: str, recruiter_id: str = None) -> list:
    """获取招募详情页面的记录列表
    
    Args:
        report_date: 报表日期（本地时间）
        range_param: 统计范围（report_day / last_7_days / last_14_days）
        metric: 指标类型（appointments / interviews / trials / new_recruits）
        recruiter_id: 招募负责人ID，为None时统计全部
        
    Returns:
        list: 招募记录列表
    """
    base_query = {}
    if recruiter_id and recruiter_id != 'all':
        base_query['recruiter'] = recruiter_id

    if range_param == 'report_day':
        start_date = report_date
        end_date = start_date + timedelta(days=1)
    elif range_param == 'last_7_days':
        start_date = report_date - timedelta(days=6)
        end_date = report_date + timedelta(days=1)
    elif range_param == 'last_14_days':
        start_date = report_date - timedelta(days=13)
        end_date = report_date + timedelta(days=1)
    else:
        return []

    start_utc = local_to_utc(start_date)
    end_utc = local_to_utc(end_date)

    if metric == 'appointments':
        query = {**base_query, 'created_at__gte': start_utc, 'created_at__lt': end_utc}
        recruits = Recruit.objects.filter(**query).order_by('-created_at')
    elif metric == 'interviews':
        interviews_query = Q(**base_query) & (Q(interview_decision_time__gte=start_utc, interview_decision_time__lt=end_utc)
                                              | Q(training_decision_time_old__gte=start_utc, training_decision_time_old__lt=end_utc))
        recruits = Recruit.objects.filter(interviews_query).order_by('-interview_decision_time', '-training_decision_time_old')
    elif metric == 'trials':
        trials_query = Q(**base_query) & (Q(training_decision_time__gte=start_utc, training_decision_time__lt=end_utc)
                                          | Q(training_decision_time_old__gte=start_utc, training_decision_time_old__lt=end_utc))
        recruits = Recruit.objects.filter(trials_query).order_by('-training_decision_time', '-training_decision_time_old')
    elif metric == 'new_recruits':
        new_recruits_query = Q(**base_query) & (
            Q(broadcast_decision_time__gte=start_utc,
              broadcast_decision_time__lt=end_utc,
              broadcast_decision__in=[BroadcastDecision.OFFICIAL, BroadcastDecision.INTERN, BroadcastDecision.OFFICIAL_OLD, BroadcastDecision.INTERN_OLD])
            | Q(final_decision_time__gte=start_utc, final_decision_time__lt=end_utc, final_decision__in=[FinalDecision.OFFICIAL, FinalDecision.INTERN]))
        recruits = Recruit.objects.filter(new_recruits_query).order_by('-broadcast_decision_time', '-final_decision_time')
    else:
        return []

    return list(recruits)


def calculate_recruit_today_stats() -> Dict[str, int]:
    """计算今日的招募统计数据（用于仪表盘）
    
    Returns:
        dict: 包含今日约面、到面、新开播的统计数据
    """
    now = get_current_utc_time()
    current_local = utc_to_local(now)
    today_local = current_local.replace(hour=0, minute=0, second=0, microsecond=0)

    today_stats = calculate_recruit_stats_for_date(today_local)

    return {'appointments': today_stats['appointments'], 'interviews': today_stats['interviews'], 'new_recruits': today_stats['new_recruits']}
