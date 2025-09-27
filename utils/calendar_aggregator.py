"""日历数据聚合模块

提取日历数据聚合的公共方法，统一处理不同时间粒度的数据。
"""
# pylint: disable=no-member

from calendar import monthrange
from datetime import datetime, timedelta

from models.announcement import Announcement
from models.battle_area import BattleArea
from utils.logging_setup import get_logger
from utils.timezone_helper import local_to_utc, utc_to_local

logger = get_logger('calendar_aggregator')


def aggregate_monthly_data(year, month):
    """聚合月视图数据
    
    Args:
        year: 年份
        month: 月份
        
    Returns:
        dict: 月视图数据
    """
    # 计算月份的第一天和最后一天
    first_day = datetime(year, month, 1)
    last_day = datetime(year, month, monthrange(year, month)[1], 23, 59, 59)

    # 转换为UTC时间进行查询
    first_day_utc = local_to_utc(first_day)
    last_day_utc = local_to_utc(last_day)

    # 查询当月的所有通告
    announcements = Announcement.objects(start_time__gte=first_day_utc, start_time__lte=last_day_utc).only('start_time', 'pilot', 'x_coord', 'y_coord',
                                                                                                           'z_coord')

    # 按日期统计通告数量
    daily_counts = {}
    for announcement in announcements:
        # 转换为本地时间
        local_start = utc_to_local(announcement.start_time)
        date_key = local_start.strftime('%Y-%m-%d')
        daily_counts[date_key] = daily_counts.get(date_key, 0) + 1

    logger.debug('月视图数据聚合完成：%d-%d，通告数=%d', year, month, len(announcements))
    return {'year': year, 'month': month, 'daily_counts': daily_counts}


def aggregate_weekly_data(date):
    """聚合周视图数据
    
    Args:
        date: 参考日期（datetime对象）
        
    Returns:
        dict: 周视图数据
    """
    # 计算周的第一天（周一）和最后一天（周日）
    days_since_monday = date.weekday()
    week_start = date - timedelta(days=days_since_monday)
    week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)

    # 转换为UTC时间进行查询
    week_start_utc = local_to_utc(week_start)
    week_end_utc = local_to_utc(week_end)

    # 查询当周的所有通告
    announcements = Announcement.objects(start_time__gte=week_start_utc, start_time__lte=week_end_utc).only('start_time', 'pilot', 'battle_area', 'x_coord',
                                                                                                            'y_coord', 'z_coord')

    # 获取所有可用的开播地点
    available_areas = BattleArea.objects(availability='可用').only('x_coord', 'y_coord', 'z_coord')

    # 按日期统计通告数量和可用区域
    weekly_data = _initialize_weekly_data(week_start)

    # 统计每日的通告和使用的区域
    for announcement in announcements:
        local_start = utc_to_local(announcement.start_time)
        date_key = local_start.strftime('%Y-%m-%d')
        if date_key in weekly_data:
            weekly_data[date_key]['announcement_count'] += 1
            area_key = f"{announcement.x_coord}-{announcement.y_coord}-{announcement.z_coord}"
            weekly_data[date_key]['used_areas'].add(area_key)

    # 计算每日可用区域数量
    total_areas = len(available_areas)
    for daily_data in weekly_data.values():
        used_count = len(daily_data['used_areas'])
        daily_data['available_areas_count'] = total_areas - used_count
        daily_data['used_areas'] = list(daily_data['used_areas'])  # 转换为列表用于JSON序列化

    logger.debug('周视图数据聚合完成：%s，通告数=%d', date.strftime('%Y-%m-%d'), len(announcements))
    return {'week_start': week_start.strftime('%Y-%m-%d'), 'week_end': (week_start + timedelta(days=6)).strftime('%Y-%m-%d'), 'week_data': weekly_data}


def aggregate_daily_data(date):
    """聚合日视图数据
    
    Args:
        date: 日期（datetime对象）
        
    Returns:
        dict: 日视图数据
    """
    # 计算当日的开始和结束时间
    day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = date.replace(hour=23, minute=59, second=59, microsecond=999999)

    # 转换为UTC时间进行查询
    day_start_utc = local_to_utc(day_start)
    day_end_utc = local_to_utc(day_end)

    # 查询与该日相关的作战计划
    announcements = Announcement.objects(start_time__lte=day_end_utc)

    # 过滤出真正与当日相关的计划
    relevant_announcements = _filter_relevant_announcements(announcements, day_start_utc, day_end_utc)

    # 按战斗区域坐标排序
    relevant_announcements.sort(key=_get_area_sort_key)

    # 构建时间轴数据
    area_timelines, used_areas_count = _build_daily_timelines(relevant_announcements, date)

    logger.debug('日视图数据聚合完成：%s，通告数=%d', date.strftime('%Y-%m-%d'), len(relevant_announcements))
    return {'date': date.strftime('%Y-%m-%d'), 'area_timelines': area_timelines, 'used_areas_count': used_areas_count}


def _initialize_weekly_data(week_start):
    """初始化周视图数据结构"""
    weekly_data = {}
    for i in range(7):
        current_day = week_start + timedelta(days=i)
        date_key = current_day.strftime('%Y-%m-%d')
        weekly_data[date_key] = {
            'date': date_key,
            'day_name': ['周一', '周二', '周三', '周四', '周五', '周六', '周日'][i],
            'announcement_count': 0,
            'used_areas': set(),
            'is_today': date_key == datetime.now().strftime('%Y-%m-%d')
        }
    return weekly_data


def _filter_relevant_announcements(announcements, day_start_utc, day_end_utc):
    """过滤出与指定日期相关的通告"""
    relevant_announcements = []
    for announcement in announcements:
        # 计算结束时间
        end_time = announcement.start_time + timedelta(hours=announcement.duration_hours)
        if end_time > day_start_utc and announcement.start_time <= day_end_utc:
            relevant_announcements.append(announcement)
    return relevant_announcements


def _get_area_sort_key(announcement):
    """获取区域排序键"""
    x = announcement.x_coord
    y = announcement.y_coord
    z = announcement.z_coord

    # Z坐标数值排序处理
    try:
        z_num = float(z)
        z_sort = (0, z_num)  # 数值类型排在前面
    except ValueError:
        z_sort = (1, z)  # 非数值类型按字符串排序

    return (x, y, z_sort)


def _build_daily_timelines(relevant_announcements, date):
    """构建日视图时间轴数据"""
    from flask_security import current_user

    time_slots = []
    used_areas = set()

    for announcement in relevant_announcements:
        local_start = utc_to_local(announcement.start_time)
        local_end = utc_to_local(announcement.start_time + timedelta(hours=announcement.duration_hours))

        # 计算在当日的开始和结束小时
        day_start_hour, day_end_hour = _calculate_day_hours(local_start, local_end, date)

        area_key = f"{announcement.x_coord}-{announcement.y_coord}-{announcement.z_coord}"
        used_areas.add(area_key)

        time_slots.append({
            'id': str(announcement.id),
            'area_display': f"{announcement.x_coord}-{announcement.y_coord}-{announcement.z_coord}",
            'pilot_display':
            f"{announcement.pilot.nickname}[{announcement.pilot.owner.nickname if announcement.pilot.owner else '无'}]-{announcement.pilot.rank.value}",
            'start_hour': day_start_hour,
            'end_hour': day_end_hour,
            'duration': day_end_hour - day_start_hour + 1,
            'is_own': str(announcement.pilot.owner.id) == str(current_user.id) if announcement.pilot.owner and current_user.is_authenticated else False,
            'start_time': local_start.strftime('%H:%M'),
            'end_time': local_end.strftime('%H:%M'),
            'area_key': area_key
        })

    # 按区域分组时间轴
    area_timelines = {}
    for slot in time_slots:
        area_key = slot['area_key']
        if area_key not in area_timelines:
            area_timelines[area_key] = {'area_display': slot['area_display'], 'slots': []}
        area_timelines[area_key]['slots'].append(slot)

    return area_timelines, len(used_areas)


def _calculate_day_hours(local_start, local_end, date):
    """计算在指定日期的开始和结束小时"""
    # 计算在当日的开始和结束小时
    day_start_hour = max(0, local_start.hour if local_start.date() == date.date() else 0)
    day_end_hour = min(23, local_end.hour if local_end.date() == date.date() else 23)

    # 如果跨天，需要特殊处理
    if local_start.date() < date.date():
        day_start_hour = 0
    if local_end.date() > date.date():
        day_end_hour = 23

    return day_start_hour, day_end_hour
