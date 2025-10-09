"""
招募统计工具模块

提供统一的招募统计数据计算功能，避免在多个地方重复实现相同的逻辑。
"""
# pylint: disable=no-member
from datetime import datetime, timedelta
from typing import Any, Dict

from mongoengine import Q

from models.battle_record import BattleRecord
from models.recruit import BroadcastDecision, FinalDecision, Recruit
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)
from utils.logging_setup import get_logger

# 设置日志器
logger = get_logger('recruit_stats')


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

    # 查询窗口内所有招募记录中，其招募决策为正式主播或实习主播的
    # 这样不论招募经历了什么中间状态，只要最终被决定招募就计入新开播数
    new_recruits_query = Q(**base_query) & (
        Q(broadcast_decision_time__gte=start_utc,
          broadcast_decision_time__lt=end_utc,
          broadcast_decision__in=[BroadcastDecision.OFFICIAL, BroadcastDecision.INTERN, BroadcastDecision.OFFICIAL_OLD, BroadcastDecision.INTERN_OLD])
        | Q(final_decision_time__gte=start_utc, final_decision_time__lt=end_utc, final_decision__in=[FinalDecision.OFFICIAL, FinalDecision.INTERN]))
    recruits = Recruit.objects.filter(new_recruits_query)

    new_recruits_count = 0
    processed_pilots = set()  # 避免重复统计同一主播

    logger.info(f"新开播数计算：查询到 {recruits.count()} 条招募记录")

    for recruit in recruits:
        if recruit.pilot and recruit.pilot.id not in processed_pilots:
            processed_pilots.add(recruit.pilot.id)

            # 调试日志：记录每个主播的信息
            logger.info(f"✓ {recruit.pilot.nickname} (ID: {recruit.pilot.id}) 被计入新开播数")
            new_recruits_count += 1

    logger.info(f"新开播数计算完成，总计: {new_recruits_count}")
    return {'appointments': appointments, 'interviews': interviews, 'trials': trials, 'new_recruits': new_recruits_count}


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


def calculate_recruit_monthly_stats(recruiter_id: str = None) -> Dict[str, Any]:
    """计算招募月报统计数据（滚动60天）

    Args:
        recruiter_id: 招募负责人ID，为None时统计全部

    Returns:
        dict: 包含当期和上期的统计数据及趋势比较
    """
    now = get_current_utc_time()
    today_local = utc_to_local(now)

    # 当期窗口：今天向前滚动60天（包含今天）
    current_window_end = today_local.replace(hour=23, minute=59, second=59, microsecond=999999)
    current_window_start = today_local - timedelta(days=59)
    current_window_start = current_window_start.replace(hour=0, minute=0, second=0, microsecond=0)

    # 上期窗口：第61-120天
    previous_window_end = current_window_start - timedelta(days=1)
    previous_window_end = previous_window_end.replace(hour=23, minute=59, second=59, microsecond=999999)
    previous_window_start = current_window_start - timedelta(days=60)

    # 转换为UTC进行查询
    current_start_utc = local_to_utc(current_window_start)
    current_end_utc = local_to_utc(current_window_end)
    previous_start_utc = local_to_utc(previous_window_start)
    previous_end_utc = local_to_utc(previous_window_end)

    # 计算当期统计数据
    current_stats = calculate_recruit_period_stats(current_start_utc, current_end_utc, recruiter_id)

    # 计算上期统计数据
    previous_stats = calculate_recruit_period_stats(previous_start_utc, previous_end_utc, recruiter_id)

    # 计算满7天数（需要特殊处理）
    current_full_7_days = calculate_full_7_days_recruits(current_start_utc, current_end_utc, recruiter_id)
    previous_full_7_days = calculate_full_7_days_recruits(previous_start_utc, previous_end_utc, recruiter_id)

    current_stats['full_7_days'] = current_full_7_days
    previous_stats['full_7_days'] = previous_full_7_days

    # 计算转化率
    current_rates = calculate_conversion_rates(current_stats)
    previous_rates = calculate_conversion_rates(previous_stats)

    return {
        'current_window': {
            'start_date': current_window_start.strftime('%Y-%m-%d'),
            'end_date': current_window_end.strftime('%Y-%m-%d'),
            'stats': current_stats,
            'rates': current_rates
        },
        'previous_window': {
            'start_date': previous_window_start.strftime('%Y-%m-%d'),
            'end_date': previous_window_end.strftime('%Y-%m-%d'),
            'stats': previous_stats,
            'rates': previous_rates
        },
        'trends': calculate_trends(current_stats, previous_stats)
    }


def calculate_full_7_days_recruits(start_utc: datetime, end_utc: datetime, recruiter_id: str = None) -> int:
    """计算满7天的主播数量

    Args:
        start_utc: 开始时间（UTC）
        end_utc: 结束时间（UTC）
        recruiter_id: 招募负责人ID，为None时统计全部

    Returns:
        int: 满7天的主播数量
    """
    # 查找窗口内被决定招募的主播（与新开播数相同的逻辑）
    base_query = {}
    if recruiter_id and recruiter_id != 'all':
        base_query['recruiter'] = recruiter_id

    # 查询窗口内被决定招募的主播
    new_recruits_query = Q(**base_query) & (
        Q(broadcast_decision_time__gte=start_utc,
          broadcast_decision_time__lt=end_utc,
          broadcast_decision__in=[BroadcastDecision.OFFICIAL, BroadcastDecision.INTERN, BroadcastDecision.OFFICIAL_OLD, BroadcastDecision.INTERN_OLD])
        | Q(final_decision_time__gte=start_utc, final_decision_time__lt=end_utc, final_decision__in=[FinalDecision.OFFICIAL, FinalDecision.INTERN]))
    recruits = Recruit.objects.filter(new_recruits_query)

    full_7_days_count = 0
    processed_pilots = set()  # 避免重复统计同一主播

    for recruit in recruits:
        if recruit.pilot and recruit.pilot.id not in processed_pilots:
            processed_pilots.add(recruit.pilot.id)

            # 检查该主播在滚动窗口内的开播记录
            battle_records = BattleRecord.objects.filter(pilot=recruit.pilot, start_time__gte=start_utc, start_time__lte=end_utc)

            # 计算超过6小时的开播记录数
            long_sessions_count = 0
            for record in battle_records:
                if record.duration_hours and record.duration_hours > 6:
                    long_sessions_count += 1

            # 如果有7条或以上超过6小时的开播记录，计入满7天数
            if long_sessions_count >= 7:
                full_7_days_count += 1

    return full_7_days_count


def calculate_conversion_rates(stats: Dict[str, int]) -> Dict[str, float]:
    """计算转化率

    Args:
        stats: 统计数据

    Returns:
        dict: 各项转化率
    """
    rates = {}

    # 到面转化率 = 到面数 / 约面数
    if stats.get('appointments', 0) > 0:
        rates['interview_conversion'] = round(stats.get('interviews', 0) / stats['appointments'] * 100, 1)
    else:
        rates['interview_conversion'] = 0.0

    # 试播转化率 = 试播数 / 到面数
    if stats.get('interviews', 0) > 0:
        rates['trial_conversion'] = round(stats.get('trials', 0) / stats['interviews'] * 100, 1)
    else:
        rates['trial_conversion'] = 0.0

    # 新开播转化率 = 新开播数 / 到面数
    if stats.get('interviews', 0) > 0:
        rates['broadcast_conversion'] = round(stats.get('new_recruits', 0) / stats['interviews'] * 100, 1)
    else:
        rates['broadcast_conversion'] = 0.0

    # 满7天转化率 = 满7天数 / 到面数
    if stats.get('interviews', 0) > 0:
        rates['full_7_days_conversion'] = round(stats.get('full_7_days', 0) / stats['interviews'] * 100, 1)
    else:
        rates['full_7_days_conversion'] = 0.0

    return rates


def calculate_trends(current_stats: Dict[str, int], previous_stats: Dict[str, int]) -> Dict[str, str]:
    """计算趋势比较

    Args:
        current_stats: 当期统计数据
        previous_stats: 上期统计数据

    Returns:
        dict: 趋势指示器
    """
    trends = {}

    for key in ['appointments', 'interviews', 'trials', 'new_recruits', 'full_7_days']:
        current_value = current_stats.get(key, 0)
        previous_value = previous_stats.get(key, 0)

        if current_value > previous_value:
            trends[key] = 'up'
        elif current_value < previous_value:
            trends[key] = 'down'
        else:
            trends[key] = 'stable'

    return trends


def get_recruit_monthly_detail_records(recruiter_id: str = None) -> list:
    """获取招募月报明细记录

    Args:
        recruiter_id: 招募负责人ID，为None时统计全部

    Returns:
        list: 招募记录列表（按开播天数排序）
    """
    now = get_current_utc_time()
    today_local = utc_to_local(now)

    # 滚动60天窗口
    window_end = today_local.replace(hour=23, minute=59, second=59, microsecond=999999)
    window_start = today_local - timedelta(days=59)
    window_start = window_start.replace(hour=0, minute=0, second=0, microsecond=0)

    # 转换为UTC进行查询
    start_utc = local_to_utc(window_start)
    end_utc = local_to_utc(window_end)

    # 基础查询条件
    base_query = {}
    if recruiter_id and recruiter_id != 'all':
        base_query['recruiter'] = recruiter_id

    # 查询窗口内创建的所有招募记录（包含所有状态的招募）
    # 这样可以确保展示完整的招募流程，即使某些历史数据缺少中间决策时间
    base_query.update({'created_at__gte': start_utc, 'created_at__lte': end_utc})

    recruits = Recruit.objects.filter(**base_query).order_by('-created_at')

    # 为每个招募记录计算开播天数
    recruit_list = []
    processed_ids = set()  # 避免重复处理同一个招募记录

    for recruit in recruits:
        if recruit.id in processed_ids or not recruit.pilot:
            processed_ids.add(recruit.id)
            continue

        processed_ids.add(recruit.id)

        # 计算该主播在滚动窗口内的开播天数
        battle_records = BattleRecord.objects.filter(pilot=recruit.pilot, start_time__gte=start_utc, start_time__lte=end_utc)

        # 计算不重复的开播日期数
        unique_dates = set()
        long_sessions_count = 0

        for record in battle_records:
            if record.duration_hours and record.duration_hours > 6:
                long_sessions_count += 1

            # 获取本地日期
            local_start = utc_to_local(record.start_time)
            if local_start:
                unique_dates.add(local_start.date())

        recruit_dict = {'recruit': recruit, 'broadcast_days': len(unique_dates), 'long_sessions_count': long_sessions_count, 'last_broadcast_time': None}

        # 获取最近一次开播时间
        if battle_records:
            latest_record = battle_records.order_by('-start_time').first()
            if latest_record:
                recruit_dict['last_broadcast_time'] = latest_record.start_time

        recruit_list.append(recruit_dict)

    # 按开播天数降序排序
    recruit_list.sort(key=lambda x: x['broadcast_days'], reverse=True)

    return recruit_list
