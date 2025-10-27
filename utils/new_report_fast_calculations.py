# pylint: disable=too-many-locals,too-many-statements,no-member
"""开播新月报（加速版）计算工具。

实现要点：
- 单次扫描完成汇总与明细统计；
- 预取分成比例，避免每条记录重复查询；
- 在数据库层面尽量精准过滤直属运营与开播方式。
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

from bson import ObjectId
from mongoengine import DoesNotExist, QuerySet

from models.battle_record import BattleRecord
from models.pilot import Pilot, PilotCommission, WorkMode, Status
from models.user import User
from utils.cache_helper import cached_monthly_report
from utils.commission_helper import calculate_commission_amounts
from utils.logging_setup import get_logger
from utils.new_report_calculations import _fetch_approved_base_salary_map  # pylint: disable=protected-access
from utils.timezone_helper import get_current_utc_time, local_to_utc, utc_to_local

logger = get_logger('new_report_fast_calculations')

REBATE_STAGES: Tuple[Dict[str, object], ...] = (
    {
        'stage': 1,
        'min_days': 12,
        'min_hours': 42,
        'min_revenue': Decimal('1000'),
        'rate': 0.05
    },
    {
        'stage': 2,
        'min_days': 18,
        'min_hours': 100,
        'min_revenue': Decimal('5000'),
        'rate': 0.07
    },
    {
        'stage': 3,
        'min_days': 18,
        'min_hours': 100,
        'min_revenue': Decimal('10000'),
        'rate': 0.11
    },
    {
        'stage': 4,
        'min_days': 22,
        'min_hours': 130,
        'min_revenue': Decimal('30000'),
        'rate': 0.14
    },
    {
        'stage': 5,
        'min_days': 22,
        'min_hours': 130,
        'min_revenue': Decimal('80000'),
        'rate': 0.18
    },
)


def _create_daily_metric_bucket() -> Dict[str, Decimal]:
    return {
        'revenue': Decimal('0'),
        'basepay': Decimal('0'),
        'pilot_share': Decimal('0'),
        'company_share': Decimal('0'),
        'rebate': Decimal('0'),
    }


def _distribute_rebate_to_daily_totals(daily_totals: Dict[date, Dict[str, Decimal]], revenue_by_day: Dict[date, Decimal], rebate_amount: Decimal,
                                       fallback_day: date) -> None:
    if rebate_amount <= 0:
        return
    total_revenue = sum(revenue_by_day.values(), Decimal('0'))
    if total_revenue > 0:
        for day, day_revenue in revenue_by_day.items():
            if day_revenue <= 0:
                continue
            share = (day_revenue / total_revenue) * rebate_amount
            if share <= 0:
                continue
            daily_totals[day]['rebate'] += share
        return
    daily_totals[fallback_day]['rebate'] += rebate_amount


def _build_daily_series(daily_totals: Dict[date, Dict[str, Decimal]], month_start_date: date, month_end_date: date) -> List[Dict[str, object]]:
    if not daily_totals:
        return []
    cumulative = {
        'revenue': Decimal('0'),
        'basepay': Decimal('0'),
        'pilot_share': Decimal('0'),
        'company_share': Decimal('0'),
        'rebate': Decimal('0'),
    }
    series: List[Dict[str, object]] = []
    current_day = month_start_date
    while current_day <= month_end_date:
        metrics = daily_totals.get(current_day) or _create_daily_metric_bucket()
        cumulative['revenue'] += metrics['revenue']
        cumulative['basepay'] += metrics['basepay']
        cumulative['pilot_share'] += metrics['pilot_share']
        cumulative['company_share'] += metrics['company_share']
        cumulative['rebate'] += metrics['rebate']

        operating_profit = cumulative['company_share'] + cumulative['rebate'] - cumulative['basepay']

        series.append({
            'date': current_day.strftime('%Y-%m-%d'),
            'revenue_cumulative': cumulative['revenue'],
            'basepay_cumulative': cumulative['basepay'],
            'pilot_share_cumulative': cumulative['pilot_share'],
            'company_share_cumulative': cumulative['company_share'],
            'operating_profit_cumulative': operating_profit,
        })
        current_day += timedelta(days=1)
    return series


def _normalize_owner(owner_id: Optional[str]) -> Optional[str]:
    if owner_id in (None, '', 'all'):
        return None
    return owner_id


def _normalize_mode(mode: Optional[str]) -> Optional[WorkMode]:
    if mode in (None, '', 'all'):
        return None
    if mode == 'online':
        return WorkMode.ONLINE
    if mode == 'offline':
        return WorkMode.OFFLINE
    logger.warning('非法开播方式参数：%s，已回退为 all', mode)
    return None


def _normalize_status(status: Optional[str]) -> Optional[Status]:
    if status in (None, '', 'all'):
        return None
    status_mapping = {
        'not_recruited': Status.NOT_RECRUITED,
        'not_recruiting': Status.NOT_RECRUITING,
        'recruited': Status.RECRUITED,
        'contracted': Status.CONTRACTED,
        'fallen': Status.FALLEN
    }
    normalized = status_mapping.get(status)
    if not normalized:
        logger.warning('非法状态参数：%s，已回退为 all', status)
        return None
    return normalized


def _calc_month_range(year: int, month: int) -> Tuple[datetime, datetime, datetime]:
    """返回（月起始，本月统计用结束，本月报表参考日）。"""
    month_start = datetime(year, month, 1, 0, 0, 0, 0)
    if month == 12:
        next_month_start = datetime(year + 1, 1, 1, 0, 0, 0, 0)
    else:
        next_month_start = datetime(year, month + 1, 1, 0, 0, 0, 0)
    month_end = next_month_start - timedelta(microseconds=1)

    now_local = utc_to_local(get_current_utc_time())
    current_month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if month_start == current_month_start:
        yesterday_local = now_local - timedelta(days=1)
        month_end = yesterday_local.replace(hour=23, minute=59, second=59, microsecond=999999)

    report_date = month_end
    return month_start, month_end, report_date


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
    commissions: QuerySet[PilotCommission] = PilotCommission.objects(pilot_id__in=object_ids,
                                                                     is_active=True).order_by('pilot_id', 'adjustment_date')  # type: ignore[attr-defined]
    cache: Dict[str, List[Tuple[datetime, float]]] = defaultdict(list)
    for commission in commissions:
        pilot_id = str(commission.pilot_id.id)
        cache[pilot_id].append((commission.adjustment_date, float(commission.commission_rate)))
    return cache


def _resolve_commission_rate(cache: Dict[str, List[Tuple[datetime, float]]], pilot_id: str, record_date_local: date) -> float:
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


def _evaluate_rebate(valid_days: int, total_duration: float, total_revenue: Decimal) -> Tuple[float, Decimal]:
    """根据返点阶梯计算返点比例与金额。"""
    qualified = [
        stage for stage in REBATE_STAGES if valid_days >= stage['min_days'] and total_duration >= stage['min_hours'] and total_revenue >= stage['min_revenue']
    ]
    if not qualified:
        return 0.0, Decimal('0')
    best_stage = max(qualified, key=lambda item: item['stage'])  # type: ignore[arg-type]
    rate = float(best_stage['rate'])
    rebate_amount = total_revenue * Decimal(str(rate))
    return rate, rebate_amount


def _fetch_month_records(year: int,
                         month: int,
                         owner_id: Optional[str],
                         mode: Optional[WorkMode],
                         status: Optional[Status] = None) -> Tuple[List[BattleRecord], List[BattleRecord], datetime]:
    """获取扩展时间窗内的开播记录，返回（全部记录列表、当月记录列表、报表参考日期）。"""
    month_start_local, month_end_local, report_date = _calc_month_range(year, month)
    window_start_utc = local_to_utc(month_start_local)
    month_end_exclusive_local = month_end_local + timedelta(microseconds=1)
    month_end_exclusive_utc = local_to_utc(month_end_exclusive_local)

    query: QuerySet[BattleRecord] = BattleRecord.objects(start_time__gte=window_start_utc, start_time__lt=month_end_exclusive_utc)  # type: ignore[attr-defined]

    owner_user = None
    owner_pilot_ids: List[ObjectId] = []
    if owner_id:
        try:
            owner_user = User.objects.get(id=owner_id)  # type: ignore[attr-defined]
        except DoesNotExist:
            logger.warning('指定直属运营不存在：%s', owner_id)
            return [], [], report_date
        owner_pilot_ids = _load_owner_pilots(owner_user)
        if not owner_pilot_ids:
            logger.info('直属运营 %s 无关联主播，直接返回空结果', owner_user.username)
            return [], [], report_date
        query = query.filter(pilot__in=owner_pilot_ids)

    if mode:
        query = query.filter(work_mode=mode)

    records = list(query.select_related())  # 预取关联，减少后续访问
    logger.debug('加速版月报加载记录数量（状态筛选前）：%d', len(records))

    # 按主播当前状态筛选
    if status:
        filtered_records = []
        for record in records:
            pilot = record.pilot
            if pilot and pilot.status == status:
                filtered_records.append(record)
        records = filtered_records
        logger.debug('状态筛选后记录数量：%d', len(records))

    return records, records, report_date


@cached_monthly_report()
def _calculate_monthly_data(year: int,
                            month: int,
                            owner_id: Optional[str] = None,
                            mode: str = 'all',
                            status: str = 'all') -> Tuple[Dict[str, object], List[Dict[str, object]], List[Dict[str, object]]]:
    """核心计算：返回（汇总，明细，日级序列）。"""
    owner_normalized = _normalize_owner(owner_id)
    mode_normalized = _normalize_mode(mode)
    status_normalized = _normalize_status(status)

    window_records, monthly_records, _ = _fetch_month_records(year, month, owner_normalized, mode_normalized, status_normalized)
    if not monthly_records:
        summary = {
            'pilot_count': 0,
            'revenue_sum': Decimal('0'),
            'basepay_sum': Decimal('0'),
            'rebate_sum': Decimal('0'),
            'pilot_share_sum': Decimal('0'),
            'company_share_sum': Decimal('0'),
            'operating_profit': Decimal('0'),
            'conversion_rate': None,
        }
        return summary, [], []

    month_start_local, month_end_local, _ = _calc_month_range(year, month)
    month_start_date = month_start_local.date()
    month_end_date = month_end_local.date()

    base_salary_map = _fetch_approved_base_salary_map(monthly_records)

    pilot_stats: Dict[str, Dict[str, object]] = {}
    daily_duration: Dict[str, Dict[date, float]] = defaultdict(lambda: defaultdict(float))
    daily_totals: Dict[date, Dict[str, Decimal]] = defaultdict(_create_daily_metric_bucket)
    pilot_daily_revenue: Dict[str, Dict[date, Decimal]] = defaultdict(lambda: defaultdict(lambda: Decimal('0')))

    total_revenue_sum = Decimal('0')
    total_base_salary_sum = Decimal('0')
    total_pilot_share_sum = Decimal('0')
    total_company_share_sum = Decimal('0')

    # 预取分成比例
    pilot_ids = list({str(record.pilot.id) for record in monthly_records if record.pilot})
    commission_cache = _fetch_commission_cache(pilot_ids)

    month_start_utc = local_to_utc(month_start_local)
    month_end_exclusive_local = month_end_local + timedelta(microseconds=1)
    month_end_exclusive_utc = local_to_utc(month_end_exclusive_local)

    for record in window_records:
        pilot = record.pilot
        if not pilot:
            continue
        pilot_id = str(pilot.id)

        local_start = utc_to_local(record.start_time)
        record_date = local_start.date()
        revenue_amount = Decimal(record.revenue_amount or Decimal('0'))
        duration = float(record.duration_hours or 0.0)

        daily_duration[pilot_id][record_date] += duration

        if record.start_time < month_start_utc or record.start_time >= month_end_exclusive_utc:
            continue

        stats = pilot_stats.setdefault(
            pilot_id, {
                'pilot': pilot,
                'records_count': 0,
                'total_duration': 0.0,
                'total_revenue': Decimal('0'),
                'total_base_salary': Decimal('0'),
                'total_pilot_share': Decimal('0'),
                'total_company_share': Decimal('0'),
            })

        commission_rate = _resolve_commission_rate(commission_cache, pilot_id, record_date)
        commission_amounts = calculate_commission_amounts(revenue_amount, commission_rate)

        record_base_salary = base_salary_map.get(str(record.id), Decimal('0'))

        stats['records_count'] += 1
        stats['total_duration'] += duration
        stats['total_revenue'] += revenue_amount
        stats['total_base_salary'] += record_base_salary
        stats['total_pilot_share'] += commission_amounts['pilot_amount']
        stats['total_company_share'] += commission_amounts['company_amount']

        total_revenue_sum += revenue_amount
        total_base_salary_sum += record_base_salary
        total_pilot_share_sum += commission_amounts['pilot_amount']
        total_company_share_sum += commission_amounts['company_amount']

        daily_bucket = daily_totals[record_date]
        daily_bucket['revenue'] += revenue_amount
        daily_bucket['basepay'] += record_base_salary
        daily_bucket['pilot_share'] += commission_amounts['pilot_amount']
        daily_bucket['company_share'] += commission_amounts['company_amount']
        pilot_daily_revenue[pilot_id][record_date] += revenue_amount

    if not pilot_stats:
        summary = {
            'pilot_count': 0,
            'revenue_sum': Decimal('0'),
            'basepay_sum': Decimal('0'),
            'rebate_sum': Decimal('0'),
            'pilot_share_sum': Decimal('0'),
            'company_share_sum': Decimal('0'),
            'operating_profit': Decimal('0'),
            'conversion_rate': None,
        }
        return summary, [], []

    total_rebate_sum = Decimal('0')
    details: List[Dict[str, object]] = []
    current_year = datetime.now().year

    for pilot_id, stats in pilot_stats.items():
        pilot: Pilot = stats['pilot']  # type: ignore[assignment]
        duration_by_day = daily_duration.get(pilot_id, {})
        duration_current_month = [value for day, value in duration_by_day.items() if month_start_date <= day <= month_end_date]
        valid_days = sum(1 for value in duration_current_month if value >= 1.0)
        total_duration = float(stats['total_duration'])
        total_revenue = Decimal(stats['total_revenue'])

        rebate_rate, rebate_amount = _evaluate_rebate(valid_days, total_duration, total_revenue)
        stats['rebate_rate'] = rebate_rate
        stats['rebate_amount'] = rebate_amount
        total_rebate_sum += rebate_amount
        _distribute_rebate_to_daily_totals(daily_totals, pilot_daily_revenue.get(pilot_id, {}), rebate_amount, month_end_date)

        avg_duration = total_duration / stats['records_count'] if stats['records_count'] else 0.0
        total_base_salary = Decimal(stats['total_base_salary'])
        total_company_share = Decimal(stats['total_company_share'])
        total_profit = total_company_share + rebate_amount - total_base_salary

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
            'records_count': stats['records_count'],
            'avg_duration': round(avg_duration, 1),
            'total_revenue': total_revenue,
            'total_pilot_share': Decimal(stats['total_pilot_share']),
            'total_company_share': total_company_share,
            'rebate_rate': rebate_rate,
            'rebate_amount': rebate_amount,
            'total_base_salary': total_base_salary,
            'total_profit': total_profit,
        })

    details.sort(key=lambda item: item['total_profit'])

    operating_profit = total_company_share_sum + total_rebate_sum - total_base_salary_sum
    conversion_rate = None
    if total_base_salary_sum > 0:
        conversion_rate = int((total_revenue_sum / total_base_salary_sum) * 100)

    summary = {
        'pilot_count': len(pilot_stats),
        'revenue_sum': total_revenue_sum,
        'basepay_sum': total_base_salary_sum,
        'rebate_sum': total_rebate_sum,
        'pilot_share_sum': total_pilot_share_sum,
        'company_share_sum': total_company_share_sum,
        'operating_profit': operating_profit,
        'conversion_rate': conversion_rate,
    }

    daily_series = _build_daily_series(daily_totals, month_start_date, month_end_date)

    return summary, details, daily_series


def calculate_monthly_summary_fast(year: int, month: int, owner_id: Optional[str] = None, mode: str = 'all', status: str = 'all') -> Dict[str, object]:
    """加速版月报汇总。"""
    summary, _, _ = _calculate_monthly_data(year, month, owner_id, mode, status)
    return summary


def calculate_monthly_details_fast(year: int, month: int, owner_id: Optional[str] = None, mode: str = 'all', status: str = 'all') -> List[Dict[str, object]]:
    """加速版月报明细。"""
    _, details, _ = _calculate_monthly_data(year, month, owner_id, mode, status)
    return details


def calculate_monthly_report_fast(year: int,
                                  month: int,
                                  owner_id: Optional[str] = None,
                                  mode: str = 'all',
                                  status: str = 'all') -> Tuple[Dict[str, object], List[Dict[str, object]], List[Dict[str, object]]]:
    """返回加速版月报的汇总、明细与日级序列。"""
    return _calculate_monthly_data(year, month, owner_id, mode, status)
