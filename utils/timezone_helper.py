# 时间戳处理工具模块
# 根据基础技术设计.md中的时间戳处理规则实现

from datetime import datetime, timezone, timedelta
from typing import Optional

# GMT+8 时区对象
GMT_PLUS_8 = timezone(timedelta(hours=8))


def get_current_utc_time() -> datetime:
    """获取当前UTC时间
    
    Returns:
        datetime: 当前UTC时间
    """
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_current_local_time() -> datetime:
    """获取当前GMT+8时间
    
    Returns:
        datetime: 当前GMT+8时间
    """
    return datetime.now(GMT_PLUS_8).replace(tzinfo=None)


def utc_to_local(utc_dt: Optional[datetime]) -> Optional[datetime]:
    """将UTC时间转换为GMT+8时间
    
    Args:
        utc_dt: UTC时间（naive datetime对象）
        
    Returns:
        datetime: GMT+8时间（naive datetime对象），如果输入为None则返回None
    """
    if utc_dt is None:
        return None

    # 确保输入是naive datetime，如果有时区信息则移除
    if utc_dt.tzinfo is not None:
        utc_dt = utc_dt.replace(tzinfo=None)

    # 将UTC时间转换为GMT+8时间
    utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    local_dt = utc_dt.astimezone(GMT_PLUS_8)

    # 返回naive datetime
    return local_dt.replace(tzinfo=None)


def local_to_utc(local_dt: Optional[datetime]) -> Optional[datetime]:
    """将GMT+8时间转换为UTC时间
    
    Args:
        local_dt: GMT+8时间（naive datetime对象）
        
    Returns:
        datetime: UTC时间（naive datetime对象），如果输入为None则返回None
    """
    if local_dt is None:
        return None

    # 确保输入是naive datetime，如果有时区信息则移除
    if local_dt.tzinfo is not None:
        local_dt = local_dt.replace(tzinfo=None)

    # 将GMT+8时间转换为UTC时间
    local_dt = local_dt.replace(tzinfo=GMT_PLUS_8)
    utc_dt = local_dt.astimezone(timezone.utc)

    # 返回naive datetime
    return utc_dt.replace(tzinfo=None)


def format_local_datetime(utc_dt: Optional[datetime], format_str: str = '%Y年%m月%d日 %H:%M') -> str:
    """将UTC时间转换为GMT+8并格式化显示
    
    Args:
        utc_dt: UTC时间
        format_str: 格式化字符串，默认为中文格式
        
    Returns:
        str: 格式化后的GMT+8时间字符串，如果输入为None则返回'未知'
    """
    if utc_dt is None:
        return '未知'

    local_dt = utc_to_local(utc_dt)
    if local_dt is None:
        return '未知'

    return local_dt.strftime(format_str)


def format_local_date(utc_dt: Optional[datetime], format_str: str = '%Y-%m-%d') -> str:
    """将UTC时间转换为GMT+8并格式化为日期
    
    Args:
        utc_dt: UTC时间
        format_str: 格式化字符串，默认为ISO日期格式
        
    Returns:
        str: 格式化后的GMT+8日期字符串，如果输入为None则返回'未知'
    """
    if utc_dt is None:
        return '未知'

    local_dt = utc_to_local(utc_dt)
    if local_dt is None:
        return '未知'

    return local_dt.strftime(format_str)


def format_local_time(utc_dt: Optional[datetime], format_str: str = '%H:%M') -> str:
    """将UTC时间转换为GMT+8并格式化为时间
    
    Args:
        utc_dt: UTC时间
        format_str: 格式化字符串，默认为时:分格式
        
    Returns:
        str: 格式化后的GMT+8时间字符串，如果输入为None则返回'未知'
    """
    if utc_dt is None:
        return '未知'

    local_dt = utc_to_local(utc_dt)
    if local_dt is None:
        return '未知'

    return local_dt.strftime(format_str)


def parse_local_datetime(datetime_str: str) -> Optional[datetime]:
    """解析GMT+8时间字符串并转换为UTC时间
    
    Args:
        datetime_str: 时间字符串，支持ISO格式（如：2024-01-15T14:30）
        
    Returns:
        datetime: UTC时间（naive datetime对象），解析失败则返回None
    """
    if not datetime_str:
        return None

    try:
        # 解析ISO格式的时间字符串
        local_dt = datetime.fromisoformat(datetime_str)
        # 转换为UTC时间
        return local_to_utc(local_dt)
    except (ValueError, TypeError):
        return None


def compare_time_in_local(utc_dt1: Optional[datetime], utc_dt2: Optional[datetime]) -> int:
    """在GMT+8时区下比较两个UTC时间
    
    Args:
        utc_dt1: 第一个UTC时间
        utc_dt2: 第二个UTC时间
        
    Returns:
        int: -1表示dt1<dt2，0表示相等，1表示dt1>dt2，如果任一时间为None则返回0
    """
    if utc_dt1 is None or utc_dt2 is None:
        return 0

    local_dt1 = utc_to_local(utc_dt1)
    local_dt2 = utc_to_local(utc_dt2)

    if local_dt1 is None or local_dt2 is None:
        return 0

    if local_dt1 < local_dt2:
        return -1
    elif local_dt1 > local_dt2:
        return 1
    else:
        return 0


def get_local_datetime_for_input(utc_dt: Optional[datetime]) -> str:
    """将UTC时间转换为适合HTML datetime-local输入框的格式
    
    Args:
        utc_dt: UTC时间
        
    Returns:
        str: 适合datetime-local输入框的GMT+8时间字符串，格式为YYYY-MM-DDTHH:MM
    """
    if utc_dt is None:
        return ''

    local_dt = utc_to_local(utc_dt)
    if local_dt is None:
        return ''

    return local_dt.strftime('%Y-%m-%dT%H:%M')


def get_current_local_datetime_for_input() -> str:
    """获取当前GMT+8时间并格式化为适合HTML datetime-local输入框的格式
    默认时间设置为13:00（下午1点）便于用户输入
    
    Returns:
        str: 当前GMT+8时间字符串，格式为YYYY-MM-DDTHH:MM，时间固定为13:00
    """
    local_dt = get_current_local_time()
    # 设置时间为下午13:00
    local_dt = local_dt.replace(hour=13, minute=0, second=0, microsecond=0)
    return local_dt.strftime('%Y-%m-%dT%H:%M')


def get_current_month_last_day_for_input() -> str:
    """获取当前月最后一天的日期，格式化为适合HTML date输入框的格式
    
    Returns:
        str: 当前月最后一天的日期字符串，格式为YYYY-MM-DD
    """
    local_dt = get_current_local_time()

    # 获取下个月的第一天，然后减去一天得到当前月的最后一天
    if local_dt.month == 12:
        next_month = local_dt.replace(year=local_dt.year + 1, month=1, day=1)
    else:
        next_month = local_dt.replace(month=local_dt.month + 1, day=1)

    last_day = next_month - timedelta(days=1)
    return last_day.strftime('%Y-%m-%d')


def parse_local_date_to_end_datetime(date_str: str) -> Optional[datetime]:
    """解析GMT+8日期字符串并转换为当天23:59的UTC时间
    
    Args:
        date_str: 日期字符串，格式为YYYY-MM-DD
        
    Returns:
        datetime: UTC时间（23:59），解析失败则返回None
    """
    if not date_str:
        return None

    try:
        # 解析日期字符串
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        # 设置时间为23:59
        local_dt = date_obj.replace(hour=23, minute=59, second=59, microsecond=0)
        # 转换为UTC时间
        return local_to_utc(local_dt)
    except (ValueError, TypeError):
        return None
