
from datetime import datetime, timezone, timedelta
from typing import Optional

GMT_PLUS_8 = timezone(timedelta(hours=8))


def get_current_utc_time() -> datetime:
    """获取当前 UTC 时间。"""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def get_current_local_time() -> datetime:
    """获取当前 GMT+8 时间。"""
    return datetime.now(GMT_PLUS_8).replace(tzinfo=None)


def utc_to_local(utc_dt: Optional[datetime]) -> Optional[datetime]:
    """UTC → GMT+8。

    Args:
        utc_dt: UTC 时间（naive datetime）

    Returns:
        datetime: GMT+8 时间（naive datetime），None 透传
    """
    if utc_dt is None:
        return None

    if utc_dt.tzinfo is not None:
        utc_dt = utc_dt.replace(tzinfo=None)

    utc_dt = utc_dt.replace(tzinfo=timezone.utc)
    local_dt = utc_dt.astimezone(GMT_PLUS_8)

    return local_dt.replace(tzinfo=None)


def local_to_utc(local_dt: Optional[datetime]) -> Optional[datetime]:
    """GMT+8 → UTC。

    Args:
        local_dt: 本地时间（naive datetime）

    Returns:
        datetime: UTC 时间（naive datetime），None 透传
    """
    if local_dt is None:
        return None

    if local_dt.tzinfo is not None:
        local_dt = local_dt.replace(tzinfo=None)

    local_dt = local_dt.replace(tzinfo=GMT_PLUS_8)
    utc_dt = local_dt.astimezone(timezone.utc)

    return utc_dt.replace(tzinfo=None)


def format_local_datetime(utc_dt: Optional[datetime], format_str: str = '%Y年%m月%d日 %H:%M') -> str:
    """UTC → GMT+8 并格式化显示。None 返回 '未知'。"""
    if utc_dt is None:
        return '未知'

    local_dt = utc_to_local(utc_dt)
    if local_dt is None:
        return '未知'

    return local_dt.strftime(format_str)


def format_local_date(utc_dt: Optional[datetime], format_str: str = '%Y-%m-%d') -> str:
    """UTC → GMT+8 并格式化为日期。None 返回 '未知'。"""
    if utc_dt is None:
        return '未知'

    local_dt = utc_to_local(utc_dt)
    if local_dt is None:
        return '未知'

    return local_dt.strftime(format_str)


def format_local_time(utc_dt: Optional[datetime], format_str: str = '%H:%M') -> str:
    """UTC → GMT+8 并格式化为时间。None 返回 '未知'。"""
    if utc_dt is None:
        return '未知'

    local_dt = utc_to_local(utc_dt)
    if local_dt is None:
        return '未知'

    return local_dt.strftime(format_str)


def parse_local_datetime(datetime_str: str) -> Optional[datetime]:
    """解析 GMT+8 字符串并转换为 UTC。失败返回 None。"""
    if not datetime_str:
        return None

    try:
        local_dt = datetime.fromisoformat(datetime_str)
        return local_to_utc(local_dt)
    except (ValueError, TypeError):
        return None


def compare_time_in_local(utc_dt1: Optional[datetime], utc_dt2: Optional[datetime]) -> int:
    """在 GMT+8 下比较两个 UTC 时间；任一为 None 返回 0。"""
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


def get_local_date_for_input(utc_dt: Optional[datetime]) -> str:
    """UTC → HTML date（GMT+8，YYYY-MM-DD）。"""
    if utc_dt is None:
        return ''

    local_dt = utc_to_local(utc_dt)
    if local_dt is None:
        return ''

    return local_dt.strftime('%Y-%m-%d')


def get_local_time_for_input(utc_dt: Optional[datetime]) -> str:
    """UTC → HTML time（GMT+8，HH:MM）。"""
    if utc_dt is None:
        return ''

    local_dt = utc_to_local(utc_dt)
    if local_dt is None:
        return ''

    return local_dt.strftime('%H:%M')


def get_local_datetime_for_input(utc_dt: Optional[datetime]) -> str:
    """UTC → HTML datetime-local（GMT+8，YYYY-MM-DDTHH:MM）。"""
    if utc_dt is None:
        return ''

    local_dt = utc_to_local(utc_dt)
    if local_dt is None:
        return ''

    return local_dt.strftime('%Y-%m-%dT%H:%M')


def get_current_local_datetime_for_input() -> str:
    """当前 GMT+8 时间的 HTML datetime-local，时间固定 13:00。"""
    local_dt = get_current_local_time()
    local_dt = local_dt.replace(hour=13, minute=0, second=0, microsecond=0)
    return local_dt.strftime('%Y-%m-%dT%H:%M')


def get_current_month_last_day_for_input() -> str:
    """当前月最后一天（HTML date，YYYY-MM-DD）。"""
    local_dt = get_current_local_time()

    if local_dt.month == 12:
        next_month = local_dt.replace(year=local_dt.year + 1, month=1, day=1)
    else:
        next_month = local_dt.replace(month=local_dt.month + 1, day=1)

    last_day = next_month - timedelta(days=1)
    return last_day.strftime('%Y-%m-%d')


def parse_local_date_to_end_datetime(date_str: str) -> Optional[datetime]:
    """解析本地日期并转换为当日 23:59 的 UTC；失败返回 None。"""
    if not date_str:
        return None

    try:
        date_obj = datetime.strptime(date_str, '%Y-%m-%d')
        local_dt = date_obj.replace(hour=23, minute=59, second=59, microsecond=0)
        return local_to_utc(local_dt)
    except (ValueError, TypeError):
        return None
