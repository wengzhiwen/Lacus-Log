# pylint: disable=too-many-locals,too-many-statements,no-member
"""开播新周报（加速版）计算工具。

实现要点：
- 单次扫描完成汇总与明细统计；
- 预取分成比例，避免每条记录重复查询；
- 在数据库层面尽量精准过滤直属运营与开播方式；
- 完全复现原周报计算逻辑，确保结果一致性。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from bson import ObjectId
from mongoengine import DoesNotExist, QuerySet

from models.battle_record import BattleRecord
from models.pilot import Pilot, WorkMode
from models.user import User
from utils.cache_helper import cached_weekly_report
from utils.commission_helper import calculate_commission_amounts
from utils.logging_setup import get_logger
from utils.new_report_calculations import (_fetch_approved_base_salary_map, get_battle_records_for_date_range, get_pilot_commission_rate_for_date)
from utils.timezone_helper import get_current_utc_time, local_to_utc, utc_to_local

logger = get_logger('new_report_fast_weekly_calculations')


def _normalize_owner(owner_id: Optional[str]) -> Optional[str]:
    """标准化直属运营ID。"""
    if owner_id in (None, '', 'all'):
        return None
    return owner_id


def _normalize_mode(mode: Optional[str]) -> Optional[WorkMode]:
    """标准化开播方式。"""
    if mode in (None, '', 'all'):
        return None
    if mode == 'online':
        return WorkMode.ONLINE
    if mode == 'offline':
        return WorkMode.OFFLINE
    logger.warning('非法开播方式参数：%s，已回退为 all', mode)
    return None


def _calc_week_range(week_start_local: datetime) -> Tuple[datetime, datetime]:
    """计算周范围（周二至次周一）。"""
    week_end_local = week_start_local + timedelta(days=7) - timedelta(microseconds=1)
    return week_start_local, week_end_local


def _load_owner_pilots(owner_user: User) -> List[ObjectId]:
    """获取指定直属运营所管理的主播ID列表。"""
    pilots = Pilot.objects(owner=owner_user).only('id')  # type: ignore[attr-defined]
    ids = [pilot.id for pilot in pilots]
    logger.debug('直属运营 %s 管理主播数量：%d', owner_user.username, len(ids))
    return ids


def _fetch_commission_cache(pilot_ids: List[str]) -> Dict[str, List[Tuple[datetime, float]]]:
    """预取所有相关主播的分成调整记录。"""
    if not pilot_ids:
        return {}
    object_ids = [ObjectId(pid) for pid in pilot_ids]
    from models.pilot import PilotCommission
    commissions: QuerySet[PilotCommission] = PilotCommission.objects(pilot_id__in=object_ids,
                                                                     is_active=True).order_by('pilot_id', 'adjustment_date')  # type: ignore[attr-defined]
    cache: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
    for commission in commissions:
        pilot_id = str(commission.pilot_id.id)
        cache[pilot_id].append((commission.adjustment_date, float(commission.commission_rate)))
    return cache


def _resolve_commission_rate(cache: Dict[str, List[Tuple[datetime, float]]], pilot_id: str, record_date_local: datetime.date) -> float:
    """从缓存中查找指定日期的分成比例，默认为20%。"""
    entries = cache.get(pilot_id)
    if not entries:
        return 20.0
    target_local = datetime.combine(record_date_local, datetime.min.time())
    target_utc = local_to_utc(target_local)
    for adjustment_date, rate in reversed(entries):
        if adjustment_date <= target_utc:
            return rate
    return 20.0


def _fetch_two_weeks_records(week_start_local: datetime, owner_id: Optional[str], mode: Optional[WorkMode]) -> List[BattleRecord]:
    """获取两周记录（前一周+当前周），使用优化查询。"""
    # 计算前一周的开始和结束时间
    prev_week_start_local = week_start_local - timedelta(days=7)
    week_end_local = week_start_local + timedelta(days=7) - timedelta(microseconds=1)

    # 查询两周的数据范围
    prev_week_start_utc = local_to_utc(prev_week_start_local)
    week_end_exclusive_local = week_end_local + timedelta(microseconds=1)
    week_end_exclusive_utc = local_to_utc(week_end_exclusive_local)

    query: QuerySet[BattleRecord] = BattleRecord.objects(start_time__gte=prev_week_start_utc, start_time__lt=week_end_exclusive_utc)  # type: ignore[attr-defined]

    owner_user = None
    owner_pilot_ids: List[ObjectId] = []
    if owner_id:
        try:
            owner_user = User.objects.get(id=owner_id)  # type: ignore[attr-defined]
        except DoesNotExist:
            logger.warning('指定直属运营不存在：%s', owner_id)
            return []
        owner_pilot_ids = _load_owner_pilots(owner_user)
        if not owner_pilot_ids:
            logger.info('直属运营 %s 无关联主播，直接返回空结果', owner_user.username)
            return []
        query = query.filter(pilot__in=owner_pilot_ids)

    if mode:
        query = query.filter(work_mode=mode)

    records = list(query.select_related())  # 预取关联，减少后续访问
    logger.debug('加速版周报加载两周记录数量：%d', len(records))
    return records


def _create_week_stats() -> Dict[str, object]:
    """创建周统计数据结构。"""
    return {
        'pilot': None,
        'records_count': 0,
        'total_duration': 0.0,
        'total_revenue': Decimal('0'),
        'total_base_salary': Decimal('0'),
        'total_pilot_share': Decimal('0'),
        'total_company_share': Decimal('0'),
    }


@cached_weekly_report()
def _calculate_weekly_data(week_start_local: datetime, owner_id: Optional[str] = None, mode: str = 'all') -> Tuple[Dict[str, object], List[Dict[str, object]]]:
    """核心计算：返回（汇总，明细），包含当前周和前一周数据。"""
    owner_normalized = _normalize_owner(owner_id)
    mode_normalized = _normalize_mode(mode)

    two_weeks_records = _fetch_two_weeks_records(week_start_local, owner_normalized, mode_normalized)
    if not two_weeks_records:
        summary = {
            'pilot_count': 0,
            'revenue_sum': Decimal('0'),
            'basepay_sum': Decimal('0'),
            'pilot_share_sum': Decimal('0'),
            'company_share_sum': Decimal('0'),
            'profit_7d': Decimal('0'),
            'conversion_rate': None,
        }
        return summary, []

    base_salary_map = _fetch_approved_base_salary_map(two_weeks_records)

    # 分别存储当前周和前一周的统计数据
    current_week_stats: Dict[str, Dict[str, object]] = {}
    prev_week_stats: Dict[str, Dict[str, object]] = {}

    total_revenue_sum = Decimal('0')
    total_base_salary_sum = Decimal('0')
    total_pilot_share_sum = Decimal('0')
    total_company_share_sum = Decimal('0')

    # 预取分成比例
    pilot_ids = list({str(record.pilot.id) for record in two_weeks_records if record.pilot})
    commission_cache = _fetch_commission_cache(pilot_ids)

    # 计算时间范围
    week_end_local = week_start_local + timedelta(days=7) - timedelta(microseconds=1)
    prev_week_start_local = week_start_local - timedelta(days=7)

    for record in two_weeks_records:
        pilot = record.pilot
        if not pilot:
            continue
        pilot_id = str(pilot.id)

        # 判断记录属于哪一周
        record_date = utc_to_local(record.start_time).date()
        if prev_week_start_local.date() <= record_date <= (prev_week_start_local + timedelta(days=6)).date():
            # 前一周
            stats = prev_week_stats.setdefault(pilot_id, _create_week_stats())
            stats['pilot'] = pilot
        elif week_start_local.date() <= record_date <= week_end_local.date():
            # 当前周
            stats = current_week_stats.setdefault(pilot_id, _create_week_stats())
            stats['pilot'] = pilot
        else:
            # 超出两周范围，跳过
            continue

        commission_rate = _resolve_commission_rate(commission_cache, pilot_id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)

        record_base_salary = base_salary_map.get(str(record.id), Decimal('0'))

        stats['records_count'] += 1
        if record.duration_hours:
            stats['total_duration'] += record.duration_hours
        stats['total_revenue'] += record.revenue_amount
        stats['total_base_salary'] += record_base_salary
        stats['total_pilot_share'] += commission_amounts['pilot_amount']
        stats['total_company_share'] += commission_amounts['company_amount']

        # 只将当前周的数据计入汇总
        if stats in current_week_stats.values():
            total_revenue_sum += record.revenue_amount
            total_base_salary_sum += record_base_salary
            total_pilot_share_sum += commission_amounts['pilot_amount']
            total_company_share_sum += commission_amounts['company_amount']

    if not current_week_stats:
        summary = {
            'pilot_count': 0,
            'revenue_sum': Decimal('0'),
            'basepay_sum': Decimal('0'),
            'pilot_share_sum': Decimal('0'),
            'company_share_sum': Decimal('0'),
            'profit_7d': Decimal('0'),
            'conversion_rate': None,
        }
        return summary, []

    details: List[Dict[str, object]] = []
    current_year = datetime.now().year

    for pilot_id, current_stats in current_week_stats.items():
        pilot: Pilot = current_stats['pilot']  # type: ignore[assignment]
        total_duration = float(current_stats['total_duration'])
        records_count = current_stats['records_count']
        avg_duration = total_duration / records_count if records_count > 0 else 0.0
        total_base_salary = Decimal(current_stats['total_base_salary'])
        total_company_share = Decimal(current_stats['total_company_share'])
        total_profit = total_company_share - total_base_salary

        # 获取前一周数据
        prev_stats = prev_week_stats.get(pilot_id, _create_week_stats())
        prev_records_count = prev_stats['records_count']
        prev_avg_duration = float(prev_stats['total_duration']) / prev_records_count if prev_records_count > 0 else 0.0
        prev_total_revenue = prev_stats['total_revenue']
        prev_total_base_salary = prev_stats['total_base_salary']
        prev_total_company_share = prev_stats['total_company_share']
        prev_total_profit = prev_total_company_share - prev_total_base_salary

        pilot_display = pilot.nickname or ''
        if pilot.real_name:
            pilot_display += f"（{pilot.real_name}）"
        gender_icon = "♂" if pilot.gender and pilot.gender.value == 0 else "♀" if pilot.gender and pilot.gender.value == 1 else "?"
        age = current_year - pilot.birth_year if getattr(pilot, 'birth_year', None) else "未知"
        gender_age = f"{age}-{gender_icon}"
        owner_name = pilot.owner.nickname if pilot.owner and pilot.owner.nickname else pilot.owner.username if pilot.owner else '未知'
        rank_value = pilot.rank.value if pilot.rank else ''

        details.append({
            'pilot_id': pilot_id,
            'pilot_display': pilot_display,
            'gender_age': gender_age,
            'owner': owner_name,
            'rank': rank_value,
            'records_count': records_count,
            'prev_week_records_count': prev_records_count,
            'avg_duration': round(avg_duration, 1),
            'prev_week_avg_duration': round(prev_avg_duration, 1),
            'total_revenue': current_stats['total_revenue'],
            'prev_week_total_revenue': prev_total_revenue,
            'total_pilot_share': Decimal(current_stats['total_pilot_share']),
            'total_company_share': total_company_share,
            'total_base_salary': total_base_salary,
            'total_profit': total_profit,
            'prev_week_total_profit': prev_total_profit,
        })

    details.sort(key=lambda item: item['total_profit'])

    profit_7d = total_company_share_sum - total_base_salary_sum
    conversion_rate = None
    if total_base_salary_sum > 0:
        conversion_rate = int((total_revenue_sum / total_base_salary_sum) * 100)

    summary = {
        'pilot_count': len(current_week_stats),
        'revenue_sum': total_revenue_sum,
        'basepay_sum': total_base_salary_sum,
        'pilot_share_sum': total_pilot_share_sum,
        'company_share_sum': total_company_share_sum,
        'profit_7d': profit_7d,
        'conversion_rate': conversion_rate,
    }

    return summary, details


def calculate_weekly_summary_fast(week_start_local: datetime, owner_id: Optional[str] = None, mode: str = 'all') -> Dict[str, object]:
    """加速版周报汇总。"""
    summary, _ = _calculate_weekly_data(week_start_local, owner_id, mode)
    return summary


def calculate_weekly_details_fast(week_start_local: datetime, owner_id: Optional[str] = None, mode: str = 'all') -> List[Dict[str, object]]:
    """加速版周报明细。"""
    _, details = _calculate_weekly_data(week_start_local, owner_id, mode)
    return details


def calculate_weekly_report_fast(week_start_local: datetime,
                                 owner_id: Optional[str] = None,
                                 mode: str = 'all') -> Tuple[Dict[str, object], List[Dict[str, object]]]:
    """返回加速版周报的汇总与明细。"""
    return _calculate_weekly_data(week_start_local, owner_id, mode)