"""
招募统计工具模块

提供统一的招募统计数据计算功能，避免在多个地方重复实现相同的逻辑。
"""
# pylint: disable=no-member
from datetime import datetime, timedelta
from typing import Dict, Any

from mongoengine import Q
from models.recruit import Recruit, BroadcastDecision, FinalDecision
from utils.timezone_helper import local_to_utc, get_current_utc_time, utc_to_local


def calculate_recruit_period_stats(start_utc: datetime, end_utc: datetime, recruiter_id: str = None) -> Dict[str, int]:
    """计算指定时间范围内的招募统计数据
    
    Args:
        start_utc: 开始时间（UTC）
        end_utc: 结束时间（UTC）
        recruiter_id: 招募负责人ID，为None时统计全部
        
    Returns:
        dict: 包含约面、到面、试播、新开播的统计数据
    """
    # 构建基础查询条件
    base_query = {}
    if recruiter_id and recruiter_id != 'all':
        base_query['recruiter'] = recruiter_id

    # 约面：当天创建的招募数量
    appointments_query = {**base_query, 'created_at__gte': start_utc, 'created_at__lt': end_utc}
    appointments = Recruit.objects.filter(**appointments_query).count()

    # 到面：当天发生的面试决策数量（新六步制 + 历史兼容）
    # 新六步制：使用 interview_decision_time
    # 历史兼容：使用 training_decision_time_old
    interviews_query = Q(**base_query) & (
        Q(interview_decision_time__gte=start_utc, interview_decision_time__lt=end_utc)
        | Q(training_decision_time_old__gte=start_utc, training_decision_time_old__lt=end_utc)
    )
    interviews = Recruit.objects.filter(interviews_query).count()

    # 试播：当天发生的试播决策数量（新六步制 + 历史兼容）
    # 新六步制：使用 training_decision_time
    # 历史兼容：使用 training_decision_time_old
    trials_query = Q(**base_query) & (
        Q(training_decision_time__gte=start_utc, training_decision_time__lt=end_utc)
        | Q(training_decision_time_old__gte=start_utc, training_decision_time_old__lt=end_utc)
    )
    trials = Recruit.objects.filter(trials_query).count()

    # 新开播：当天在开播决策中决定招募的数量（不招募不算）
    # 新六步制：使用 broadcast_decision_time 和 broadcast_decision
    # 历史兼容：使用 final_decision_time 和 final_decision
    # 兼容历史旧枚举值（正式机师/实习机师）
    new_recruits_query = Q(**base_query) & (
        Q(broadcast_decision_time__gte=start_utc,
          broadcast_decision_time__lt=end_utc,
          broadcast_decision__in=[
              BroadcastDecision.OFFICIAL, BroadcastDecision.INTERN, BroadcastDecision.OFFICIAL_OLD, BroadcastDecision.INTERN_OLD
          ])
        | Q(final_decision_time__gte=start_utc,
            final_decision_time__lt=end_utc,
            final_decision__in=[FinalDecision.OFFICIAL, FinalDecision.INTERN])
    )
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
    # 计算目标日期的UTC时间范围
    date_start = target_date.replace(hour=0, minute=0, second=0, microsecond=0)
    date_end = date_start + timedelta(days=1)

    date_start_utc = local_to_utc(date_start)
    date_end_utc = local_to_utc(date_end)

    return calculate_recruit_period_stats(date_start_utc, date_end_utc, recruiter_id)


def calculate_recruit_daily_stats(report_date: datetime, recruiter_id: str = None) -> Dict[str, Any]:
    """计算指定日期的招募日报统计数据（包含多时间维度和百分比）
    
    Args:
        report_date: 报表日期（本地时间）
        recruiter_id: 招募负责人ID，为None时统计全部
        
    Returns:
        dict: 包含报表日、近7日、近14日的统计数据，以及百分比数据
    """
    # 计算时间范围
    report_day_start = report_date
    report_day_end = report_day_start + timedelta(days=1)

    last_7_days_start = report_date - timedelta(days=6)  # 包含报表日，共7天
    last_14_days_start = report_date - timedelta(days=13)  # 包含报表日，共14天

    # 转换为UTC时间范围
    report_day_start_utc = local_to_utc(report_day_start)
    report_day_end_utc = local_to_utc(report_day_end)
    last_7_days_start_utc = local_to_utc(last_7_days_start)
    last_14_days_start_utc = local_to_utc(last_14_days_start)

    # 计算各时间维度的数据
    report_day_stats = calculate_recruit_period_stats(report_day_start_utc, report_day_end_utc, recruiter_id)
    last_7_days_stats = calculate_recruit_period_stats(last_7_days_start_utc, report_day_end_utc, recruiter_id)
    last_14_days_stats = calculate_recruit_period_stats(last_14_days_start_utc, report_day_end_utc, recruiter_id)

    # 构建基础统计数据
    statistics = {'report_day': report_day_stats, 'last_7_days': last_7_days_stats, 'last_14_days': last_14_days_stats}

    # 计算百分比（基于report_day和last_7_days的对比）
    percentages = {'report_day': {}, 'last_7_days': {}}

    # 计算report_day相对于last_7_days的百分比
    for key in ['appointments', 'interviews', 'trials', 'new_recruits']:
        report_value = statistics['report_day'][key]
        last_7_value = statistics['last_7_days'][key]

        if last_7_value > 0:
            percentages['report_day'][key] = round((report_value / last_7_value) * 100, 1)
        else:
            percentages['report_day'][key] = 0.0

    # 计算last_7_days相对于last_14_days的百分比
    for key in ['appointments', 'interviews', 'trials', 'new_recruits']:
        last_7_value = statistics['last_7_days'][key]
        last_14_value = statistics['last_14_days'][key]

        if last_14_value > 0:
            percentages['last_7_days'][key] = round((last_7_value / last_14_value) * 100, 1)
        else:
            percentages['last_7_days'][key] = 0.0

    statistics['percentages'] = percentages
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
    # 构建基础查询条件
    base_query = {}
    if recruiter_id and recruiter_id != 'all':
        base_query['recruiter'] = recruiter_id

    # 计算时间范围
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

    # 转换为UTC时间
    start_utc = local_to_utc(start_date)
    end_utc = local_to_utc(end_date)

    # 根据指标类型构建查询
    if metric == 'appointments':
        # 约面：按创建时间筛选
        query = {**base_query, 'created_at__gte': start_utc, 'created_at__lt': end_utc}
        recruits = Recruit.objects.filter(**query).order_by('-created_at')
    elif metric == 'interviews':
        # 到面：按面试决策时间筛选
        interviews_query = Q(**base_query) & (
            Q(interview_decision_time__gte=start_utc, interview_decision_time__lt=end_utc)
            | Q(training_decision_time_old__gte=start_utc, training_decision_time_old__lt=end_utc)
        )
        recruits = Recruit.objects.filter(interviews_query).order_by('-interview_decision_time', '-training_decision_time_old')
    elif metric == 'trials':
        # 试播：按试播决策时间筛选
        trials_query = Q(**base_query) & (
            Q(training_decision_time__gte=start_utc, training_decision_time__lt=end_utc)
            | Q(training_decision_time_old__gte=start_utc, training_decision_time_old__lt=end_utc)
        )
        recruits = Recruit.objects.filter(trials_query).order_by('-training_decision_time', '-training_decision_time_old')
    elif metric == 'new_recruits':
        # 新开播：按开播决策时间筛选，且决策为招募（兼容历史旧枚举值）
        new_recruits_query = Q(**base_query) & (
            Q(broadcast_decision_time__gte=start_utc,
              broadcast_decision_time__lt=end_utc,
              broadcast_decision__in=[
                  BroadcastDecision.OFFICIAL, BroadcastDecision.INTERN, BroadcastDecision.OFFICIAL_OLD, BroadcastDecision.INTERN_OLD
              ])
            | Q(final_decision_time__gte=start_utc,
                final_decision_time__lt=end_utc,
                final_decision__in=[FinalDecision.OFFICIAL, FinalDecision.INTERN])
        )
        recruits = Recruit.objects.filter(new_recruits_query).order_by('-broadcast_decision_time', '-final_decision_time')
    else:
        return []

    return list(recruits)


def calculate_recruit_today_stats() -> Dict[str, int]:
    """计算今日的招募统计数据（用于仪表盘）
    
    Returns:
        dict: 包含今日约面、到面、新开播的统计数据
    """
    # 获取今日的本地时间
    now = get_current_utc_time()
    current_local = utc_to_local(now)
    today_local = current_local.replace(hour=0, minute=0, second=0, microsecond=0)

    # 使用统一的日期统计函数
    today_stats = calculate_recruit_stats_for_date(today_local)

    return {'appointments': today_stats['appointments'], 'interviews': today_stats['interviews'], 'new_recruits': today_stats['new_recruits']}
