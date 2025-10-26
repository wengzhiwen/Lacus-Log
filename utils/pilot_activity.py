# -*- coding: utf-8 -*-
# pylint: disable=no-member
"""
活跃主播辅助方法

提供活跃主播缓存与排序工具，便于多个模块共用。
"""

from datetime import datetime, timedelta
from typing import Callable, Iterable, List, Optional, Sequence, Set

from models.announcement import Announcement
from models.battle_record import BattleRecord
from models.pilot import Pilot
from utils.cache_helper import get_cached_active_pilots
from utils.logging_setup import get_logger
from utils.timezone_helper import get_current_utc_time

ACTIVE_PILOT_CACHE_KEY = 'active_pilots_set'
ACTIVE_WINDOW_HOURS = 48

logger = get_logger('pilot_activity')


def _normalize_pilot_id(raw_value) -> Optional[str]:
    if raw_value is None:
        return None
    try:
        return str(raw_value.id)
    except AttributeError:
        return str(raw_value)


def _build_active_pilot_id_set() -> Set[str]:
    """计算最近48小时内活跃主播ID集合"""
    cutoff = get_current_utc_time() - timedelta(hours=ACTIVE_WINDOW_HOURS)
    active_ids: Set[str] = set()

    try:
        announcement_ids: Sequence = Announcement.objects(pilot__ne=None, start_time__gte=cutoff).distinct(field='pilot')
        battle_record_ids: Sequence = BattleRecord.objects(pilot__ne=None, start_time__gte=cutoff).distinct(field='pilot')

        for raw_id in list(announcement_ids) + list(battle_record_ids):
            normalized = _normalize_pilot_id(raw_id)
            if normalized:
                active_ids.add(normalized)
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('计算活跃主播列表失败：%s', exc, exc_info=True)

    return active_ids


def _get_latest_activity_marker() -> str:
    """获取最近活跃时间戳，用于缓存键"""
    cutoff = get_current_utc_time() - timedelta(hours=ACTIVE_WINDOW_HOURS)
    candidates: List[datetime] = []

    try:
        latest_announcement = Announcement.objects(pilot__ne=None, start_time__gte=cutoff).order_by('-start_time').only('start_time').first()
        if latest_announcement and latest_announcement.start_time:
            candidates.append(latest_announcement.start_time)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning('获取活跃通告时间失败：%s', exc, exc_info=True)

    try:
        latest_battle_record = BattleRecord.objects(pilot__ne=None, start_time__gte=cutoff).order_by('-start_time').only('start_time').first()
        if latest_battle_record and latest_battle_record.start_time:
            candidates.append(latest_battle_record.start_time)
    except Exception as exc:  # pylint: disable=broad-except
        logger.warning('获取活跃开播记录时间失败：%s', exc, exc_info=True)

    if not candidates:
        return 'none'
    latest = max(candidates)
    return latest.isoformat()


def get_active_pilot_ids() -> Set[str]:
    """获取缓存的活跃主播ID集合"""
    marker = _get_latest_activity_marker()
    cache_key = f'{ACTIVE_PILOT_CACHE_KEY}:{marker}'
    return get_cached_active_pilots(cache_key, _build_active_pilot_id_set)


def sort_pilots_with_active_priority(pilots: Iterable[Pilot], key_func: Optional[Callable[[Pilot], str]] = None) -> List[Pilot]:
    """将活跃主播置顶并按昵称字典序排序。

    Args:
        pilots: 主播模型列表
        key_func: 可选的排序关键字函数，默认为主播昵称

    Returns:
        List[Pilot]: 排序后的主播列表
    """
    pilot_list = list(pilots)
    active_ids = get_active_pilot_ids()
    if not pilot_list:
        return pilot_list

    def default_key(pilot: Pilot) -> str:
        return (pilot.nickname or '').strip()

    key_func = key_func or default_key

    def sort_key(pilot: Pilot):
        nickname_key = key_func(pilot) or ''
        return (0 if str(pilot.id) in active_ids else 1, nickname_key.casefold(), str(pilot.id))

    return sorted(pilot_list, key=sort_key)
