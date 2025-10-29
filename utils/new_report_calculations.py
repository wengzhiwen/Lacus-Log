"""开播新报表计算与查询工具。"""
# pylint: disable=too-many-locals,no-member

from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Dict, List, Optional, Sequence, Tuple

from mongoengine import QuerySet

from models.battle_record import (BaseSalaryApplication, BaseSalaryApplicationStatus, BattleRecord)
from models.pilot import Pilot, WorkMode
from utils.cache_helper import cached_monthly_report
from utils.commission_helper import (calculate_commission_amounts, get_pilot_commission_rate_for_date)
from utils.logging_setup import get_logger
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)

logger = get_logger('new_report_calculations')

# —— 时间与参数解析工具 ——


def get_local_date_from_string(date_str: Optional[str]) -> Optional[datetime]:
    """解析 YYYY-MM-DD 字符串为本地时间（当天 00:00:00）。"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return None


def get_local_date_from_string_safe(date_str: Optional[str]) -> Optional[datetime]:
    """安全解析 YYYY-MM-DD 字符串，失败返回 None。"""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d') if date_str else None
    except ValueError:
        return None


def get_local_month_from_string(month_str: Optional[str]) -> Optional[datetime]:
    """解析 YYYY-MM 字符串为本地时间（当月 1 日 00:00:00）。"""
    if not month_str:
        return None
    try:
        return datetime.strptime(month_str, '%Y-%m')
    except ValueError:
        return None


def get_week_start_tuesday(local_date: datetime) -> datetime:
    """获取包含给定日期的“周二 00:00”作为周起始。"""
    target_weekday = 1  # Tuesday
    delta_days = (local_date.weekday() - target_weekday) % 7
    week_start = local_date - timedelta(days=delta_days)
    return week_start.replace(hour=0, minute=0, second=0, microsecond=0)


def get_default_week_start_for_now_prev_week() -> datetime:
    """默认选择当前日期前一周的周二起始。"""
    now_utc = get_current_utc_time()
    today_local = utc_to_local(now_utc).replace(hour=0, minute=0, second=0, microsecond=0)
    prev_week_date = today_local - timedelta(days=7)
    return get_week_start_tuesday(prev_week_date)


# —— 数据查询与预处理 ——


def _normalize_owner_and_mode(owner_id: Optional[str], mode: Optional[str]) -> Tuple[Optional[str], Optional[str]]:
    """统一 owner 与 mode 参数取值。"""
    owner_normalized = None if owner_id in (None, '', 'all') else owner_id
    mode_normalized = None if mode in (None, '', 'all') else mode
    return owner_normalized, mode_normalized


def get_battle_records_for_date_range(start_local: datetime, end_local: datetime, owner_id: Optional[str] = None, mode: str = 'all') -> List[BattleRecord]:
    """获取本地时间范围内的开播记录，可按直属运营与开播方式筛选。"""
    owner_normalized, mode_normalized = _normalize_owner_and_mode(owner_id, mode)

    start_utc = local_to_utc(start_local)
    end_utc = local_to_utc(end_local)

    records: QuerySet[BattleRecord] = BattleRecord.objects.filter(start_time__gte=start_utc, start_time__lt=end_utc)

    if owner_normalized is None and mode_normalized is None:
        return list(records)

    from models.user import User  # 避免循环导入

    owner_user = None
    if owner_normalized is not None:
        try:
            owner_user = User.objects.get(id=owner_normalized)
        except User.DoesNotExist:
            logger.warning('直属运营不存在：%s，返回空结果集', owner_normalized)
            return []

    pilot_to_records: Dict[str, List[BattleRecord]] = {}
    for record in records:
        pilot_to_records.setdefault(str(record.pilot.id), []).append(record)

    filtered_records: List[BattleRecord] = []
    for rec_list in pilot_to_records.values():
        rec_list.sort(key=lambda item: item.start_time)
        last_record = rec_list[-1]

        owner_ok = True
        if owner_user is not None:
            last_owner = last_record.owner_snapshot or last_record.pilot.owner
            owner_ok = bool(last_owner and str(last_owner.id) == str(owner_user.id))

        mode_ok = True
        if mode_normalized is not None:
            expected_mode = WorkMode.ONLINE if mode_normalized == 'online' else WorkMode.OFFLINE
            mode_ok = last_record.work_mode == expected_mode

        if owner_ok and mode_ok:
            filtered_records.extend(rec_list)

    return filtered_records


def get_battle_records_for_month(year: int, month: int, owner_id: Optional[str] = None, mode: str = 'all') -> List[BattleRecord]:
    """获取指定年月内的开播记录，当前月仅统计至昨天。"""
    month_start = datetime(year, month, 1, 0, 0, 0, 0)
    if month == 12:
        next_month_start = datetime(year + 1, 1, 1, 0, 0, 0, 0)
    else:
        next_month_start = datetime(year, month + 1, 1, 0, 0, 0, 0)
    month_end = next_month_start - timedelta(microseconds=1)

    now_utc = get_current_utc_time()
    now_local = utc_to_local(now_utc)
    current_month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if month_start == current_month_start:
        yesterday_local = now_local - timedelta(days=1)
        month_end = yesterday_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        logger.info('新月报当前月特殊处理：%s - %s', month_start.strftime('%Y-%m-%d'), month_end.strftime('%Y-%m-%d %H:%M:%S'))

    return get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1), owner_id, mode)


def _fetch_approved_base_salary_map(records: Sequence[BattleRecord]) -> Dict[str, Decimal]:
    """批量构建 battle_record_id -> 已确认底薪金额 映射。"""
    record_ids = [record.id for record in records if record.id]
    if not record_ids:
        return {}

    applications: QuerySet[BaseSalaryApplication] = BaseSalaryApplication.objects.filter(battle_record_id__in=record_ids,
                                                                                         status=BaseSalaryApplicationStatus.APPROVED)

    base_salary_map: defaultdict[str, Decimal] = defaultdict(lambda: Decimal('0'))
    for application in applications:
        battle_record = application.battle_record_id
        if not battle_record:
            continue
        amount = application.base_salary_amount or Decimal('0')
        base_salary_map[str(battle_record.id)] += Decimal(amount)

    return dict(base_salary_map)


def _get_record_base_salary(record: BattleRecord, base_salary_map: Dict[str, Decimal]) -> Decimal:
    """从映射中读取单条开播记录的底薪金额。"""
    return base_salary_map.get(str(record.id), Decimal('0'))


# —— 指标计算辅助函数 ——


def calculate_pilot_three_day_avg_revenue(pilot: Pilot, report_date: datetime, owner_id: Optional[str] = None, mode: str = 'all') -> Optional[Decimal]:
    """计算主播近三个有记录自然日的平均流水。"""
    days_with_revenue: List[Decimal] = []

    for offset in range(7):
        check_date = report_date - timedelta(days=offset)
        check_start = check_date.replace(hour=0, minute=0, second=0, microsecond=0)
        check_end = check_start + timedelta(days=1)
        daily_records = get_battle_records_for_date_range(check_start, check_end, owner_id, mode)
        pilot_records = [item for item in daily_records if item.pilot.id == pilot.id]
        if pilot_records:
            daily_revenue = sum(record.revenue_amount for record in pilot_records)
            days_with_revenue.append(daily_revenue)
            if len(days_with_revenue) >= 3:
                break

    if len(days_with_revenue) < 3:
        return None

    total = sum(days_with_revenue[:3])
    return total / 3


def calculate_pilot_rebate(pilot: Pilot, report_date: datetime, owner_id: Optional[str] = None, mode: str = 'all') -> Dict[str, Any]:
    """计算主播月度返点信息。"""
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1), owner_id, mode)
    pilot_month_records = [record for record in month_records if record.pilot.id == pilot.id]

    valid_days = set()
    total_duration = 0.0
    total_revenue = Decimal('0')

    for record in pilot_month_records:
        local_start = utc_to_local(record.start_time)
        record_date_local = local_start.date()
        if record.duration_hours:
            total_duration += record.duration_hours
            if record.duration_hours >= 1.0:
                valid_days.add(record_date_local)
        total_revenue += record.revenue_amount

    valid_days_count = len(valid_days)
    rebate_stages = [{
        'stage': 1,
        'min_days': 12,
        'min_hours': 42,
        'min_revenue': Decimal('1000'),
        'rate': 0.05
    }, {
        'stage': 2,
        'min_days': 18,
        'min_hours': 100,
        'min_revenue': Decimal('5000'),
        'rate': 0.07
    }, {
        'stage': 3,
        'min_days': 18,
        'min_hours': 100,
        'min_revenue': Decimal('10000'),
        'rate': 0.11
    }, {
        'stage': 4,
        'min_days': 22,
        'min_hours': 130,
        'min_revenue': Decimal('30000'),
        'rate': 0.14
    }, {
        'stage': 5,
        'min_days': 22,
        'min_hours': 130,
        'min_revenue': Decimal('80000'),
        'rate': 0.18
    }]

    qualified = [
        stage for stage in rebate_stages
        if valid_days_count >= stage['min_days'] and total_duration >= stage['min_hours'] and total_revenue >= stage['min_revenue']
    ]

    if qualified:
        best_stage = max(qualified, key=lambda item: item['stage'])
        rebate_amount = total_revenue * Decimal(str(best_stage['rate']))
        return {
            'rebate_amount': rebate_amount,
            'rebate_rate': best_stage['rate'],
            'rebate_stage': best_stage['stage'],
            'valid_days_count': valid_days_count,
            'total_duration': total_duration,
            'total_revenue': total_revenue,
            'qualified_stages': qualified
        }

    return {
        'rebate_amount': Decimal('0'),
        'rebate_rate': 0,
        'rebate_stage': 0,
        'valid_days_count': valid_days_count,
        'total_duration': total_duration,
        'total_revenue': total_revenue,
        'qualified_stages': []
    }


def calculate_pilot_monthly_stats(pilot: Pilot, report_date: datetime, owner_id: Optional[str] = None, mode: str = 'all') -> Dict[str, Decimal]:
    """计算主播月度统计。"""
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1), owner_id, mode)
    base_salary_map = _fetch_approved_base_salary_map(month_records)
    pilot_records = [record for record in month_records if record.pilot.id == pilot.id]

    record_dates = set()
    total_duration = 0.0
    total_revenue = Decimal('0')
    total_base_salary = Decimal('0')

    for record in pilot_records:
        local_start = utc_to_local(record.start_time)
        record_dates.add(local_start.date())
        if record.duration_hours:
            total_duration += record.duration_hours
        total_revenue += record.revenue_amount
        total_base_salary += _get_record_base_salary(record, base_salary_map)

    month_days_count = len(record_dates)
    month_avg_duration = (total_duration / month_days_count) if month_days_count > 0 else 0.0

    return {
        'month_days_count': month_days_count,
        'month_avg_duration': round(month_avg_duration, 1),
        'month_total_revenue': total_revenue,
        'month_total_base_salary': total_base_salary
    }


def calculate_pilot_monthly_commission_stats(pilot: Pilot, year: int, month: int, owner_id: Optional[str] = None, mode: str = 'all') -> Dict[str, Decimal]:
    """计算主播月度分成统计。"""
    month_records = get_battle_records_for_month(year, month, owner_id, mode)
    base_salary_map = _fetch_approved_base_salary_map(month_records)
    pilot_records = [record for record in month_records if record.pilot.id == pilot.id]

    total_pilot_share = Decimal('0')
    total_company_share = Decimal('0')
    total_base_salary = Decimal('0')

    for record in pilot_records:
        record_date = utc_to_local(record.start_time).date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)
        total_pilot_share += commission_amounts['pilot_amount']
        total_company_share += commission_amounts['company_amount']
        total_base_salary += _get_record_base_salary(record, base_salary_map)

    return {'total_pilot_share': total_pilot_share, 'total_company_share': total_company_share, 'total_base_salary': total_base_salary}


def calculate_pilot_monthly_rebate_stats(pilot: Pilot, year: int, month: int, owner_id: Optional[str] = None, mode: str = 'all') -> Dict[str, Any]:
    """计算主播月度返点统计。"""
    month_start = datetime(year, month, 1, 0, 0, 0, 0)
    if month == 12:
        next_month_start = datetime(year + 1, 1, 1, 0, 0, 0, 0)
    else:
        next_month_start = datetime(year, month + 1, 1, 0, 0, 0, 0)
    month_end = next_month_start - timedelta(microseconds=1)

    now_utc = get_current_utc_time()
    now_local = utc_to_local(now_utc)
    current_month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if month_start == current_month_start:
        yesterday_local = now_local - timedelta(days=1)
        report_date = yesterday_local.replace(hour=23, minute=59, second=59, microsecond=999999)
    else:
        report_date = month_end

    rebate_info = calculate_pilot_rebate(pilot, report_date, owner_id, mode)
    return {'rebate_amount': rebate_info['rebate_amount'], 'rebate_rate': rebate_info['rebate_rate']}


# —— 报表主逻辑 ——


def calculate_daily_summary(report_date: datetime, owner_id: Optional[str] = None, mode: str = 'all') -> Dict[str, Any]:
    """计算新日报汇总信息。"""
    day_start = report_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    day_records = get_battle_records_for_date_range(day_start, day_end + timedelta(microseconds=1), owner_id, mode)
    base_salary_map = _fetch_approved_base_salary_map(day_records)

    pilot_ids = set()
    effective_pilot_ids = set()
    pilot_duration: defaultdict[str, float] = defaultdict(float)

    total_revenue = Decimal('0')
    total_base_salary = Decimal('0')
    total_pilot_share = Decimal('0')
    total_company_share = Decimal('0')

    for record in day_records:
        pilot_id = str(record.pilot.id)
        pilot_ids.add(pilot_id)

        if record.duration_hours:
            pilot_duration[pilot_id] += record.duration_hours

        base_salary = _get_record_base_salary(record, base_salary_map)
        total_revenue += record.revenue_amount
        total_base_salary += base_salary

        record_date = utc_to_local(record.start_time).date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(record.pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)
        total_pilot_share += commission_amounts['pilot_amount']
        total_company_share += commission_amounts['company_amount']

    for pilot_id, duration in pilot_duration.items():
        if duration >= 6.0:
            effective_pilot_ids.add(pilot_id)

    conversion_rate = None
    if total_base_salary > 0:
        conversion_rate = int((total_revenue / total_base_salary) * 100)

    return {
        'pilot_count': len(pilot_ids),
        'effective_pilot_count': len(effective_pilot_ids),
        'revenue_sum': total_revenue,
        'basepay_sum': total_base_salary,
        'pilot_share_sum': total_pilot_share,
        'company_share_sum': total_company_share,
        'conversion_rate': conversion_rate,
    }


# pylint: disable=too-many-statements
def calculate_daily_details(report_date: datetime, owner_id: Optional[str] = None, mode: str = 'all') -> List[Dict[str, Any]]:
    """计算新日报明细列表。"""
    day_start = report_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    day_records = get_battle_records_for_date_range(day_start, day_end + timedelta(microseconds=1), owner_id, mode)
    base_salary_map = _fetch_approved_base_salary_map(day_records)

    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1), owner_id, mode)
    month_base_salary_map = _fetch_approved_base_salary_map(month_records)

    monthly_stats_cache: Dict[str, Dict[str, Any]] = {}
    pilot_month_records_cache: Dict[str, List[BattleRecord]] = {}
    monthly_commission_cache: Dict[str, Dict[str, Decimal]] = {}
    three_day_avg_cache: Dict[str, Optional[Decimal]] = {}

    details: List[Dict[str, Any]] = []

    for record in day_records:
        pilot = record.pilot
        pilot_id = str(pilot.id)
        local_start = utc_to_local(record.start_time)

        pilot_display = pilot.nickname or ''
        if pilot.real_name:
            pilot_display += f"（{pilot.real_name}）"

        gender_icon = "♂" if pilot.gender.value == 0 else "♀" if pilot.gender.value == 1 else "?"
        current_year = datetime.now().year
        age = current_year - pilot.birth_year if pilot.birth_year else "未知"
        gender_age = f"{age}-{gender_icon}"

        owner_name = record.owner_snapshot.nickname if record.owner_snapshot else (pilot.owner.nickname if pilot.owner else "未知")
        rank = pilot.rank.value
        battle_area = f"{record.work_mode.value}@{record.x_coord}-{record.y_coord}-{record.z_coord}"
        duration = record.duration_hours or 0.0

        record_date = local_start.date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)

        record_base_salary = _get_record_base_salary(record, base_salary_map)
        daily_profit = commission_amounts['company_amount'] - record_base_salary

        if pilot_id not in monthly_commission_cache or pilot_id not in monthly_stats_cache:
            pilot_month_records = pilot_month_records_cache.setdefault(pilot_id, [item for item in month_records if item.pilot.id == pilot.id])

            month_total_pilot_share = Decimal('0')
            month_total_company_share = Decimal('0')
            month_total_base_salary = Decimal('0')
            month_total_revenue = Decimal('0')
            month_total_duration = 0.0
            month_dates: set[datetime.date] = set()

            for month_record in pilot_month_records:
                local_month_start = utc_to_local(month_record.start_time)
                month_dates.add(local_month_start.date())
                if month_record.duration_hours:
                    month_total_duration += month_record.duration_hours
                month_total_revenue += month_record.revenue_amount

                month_record_date = local_month_start.date()
                commission_rate_month, _, _ = get_pilot_commission_rate_for_date(pilot.id, month_record_date)
                commission_amounts_month = calculate_commission_amounts(month_record.revenue_amount, commission_rate_month)
                month_total_pilot_share += commission_amounts_month['pilot_amount']
                month_total_company_share += commission_amounts_month['company_amount']
                month_total_base_salary += _get_record_base_salary(month_record, month_base_salary_map)

            monthly_commission_cache[pilot_id] = {
                'total_pilot_share': month_total_pilot_share,
                'total_company_share': month_total_company_share,
                'total_base_salary': month_total_base_salary,
            }

            month_days_count = len(month_dates)
            month_avg_duration = round((month_total_duration / month_days_count) if month_days_count > 0 else 0.0, 1)
            monthly_stats_cache[pilot_id] = {
                'month_days_count': month_days_count,
                'month_avg_duration': month_avg_duration,
                'month_total_revenue': month_total_revenue,
                'month_total_base_salary': month_total_base_salary
            }

        monthly_commission_raw = monthly_commission_cache[pilot_id]
        monthly_stats = monthly_stats_cache[pilot_id]
        month_total_pilot_share = monthly_commission_raw['total_pilot_share']
        month_total_company_share = monthly_commission_raw['total_company_share']
        month_total_base_salary = monthly_commission_raw['total_base_salary']
        month_total_profit = month_total_company_share - month_total_base_salary

        monthly_commission_stats = {
            'month_total_pilot_share': month_total_pilot_share,
            'month_total_company_share': month_total_company_share,
            'month_total_profit': month_total_profit
        }

        if pilot_id not in three_day_avg_cache:
            three_day_avg_cache[pilot_id] = calculate_pilot_three_day_avg_revenue(pilot, report_date, owner_id, mode)
        three_day_avg = three_day_avg_cache[pilot_id]

        detail = {
            'pilot_id': pilot_id,
            'pilot_display': pilot_display,
            'gender_age': gender_age,
            'owner': owner_name,
            'rank': rank,
            'battle_area': battle_area,
            'duration': duration,
            'revenue': record.revenue_amount,
            'commission_rate': commission_rate,
            'pilot_share': commission_amounts['pilot_amount'],
            'company_share': commission_amounts['company_amount'],
            'base_salary': record_base_salary,
            'daily_profit': daily_profit,
            'three_day_avg_revenue': three_day_avg,
            'monthly_stats': monthly_stats,
            'monthly_commission_stats': monthly_commission_stats,
            'status': record.current_status.value,
            'status_display': record.get_status_display() or '',
            'pilot_status': pilot.status.value,
            'pilot_status_display': pilot.status_display
        }

        details.append(detail)

    details.sort(key=lambda item: item['daily_profit'])
    return details


def calculate_weekly_summary(week_start_local: datetime, owner_id: Optional[str] = None, mode: str = 'all') -> Dict[str, Any]:
    """计算新周报汇总信息（周二至次周一）。"""
    week_end_local = week_start_local + timedelta(days=7) - timedelta(microseconds=1)
    week_records = get_battle_records_for_date_range(week_start_local, week_end_local + timedelta(microseconds=1), owner_id, mode)
    base_salary_map = _fetch_approved_base_salary_map(week_records)

    pilot_ids = set()
    total_revenue = Decimal('0')
    total_base_salary = Decimal('0')
    total_pilot_share = Decimal('0')
    total_company_share = Decimal('0')

    for record in week_records:
        pilot_ids.add(str(record.pilot.id))
        base_salary = _get_record_base_salary(record, base_salary_map)
        total_base_salary += base_salary
        total_revenue += record.revenue_amount

        record_date = utc_to_local(record.start_time).date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(record.pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)
        total_pilot_share += commission_amounts['pilot_amount']
        total_company_share += commission_amounts['company_amount']

    profit_7d = total_company_share - total_base_salary
    conversion_rate = None
    if total_base_salary > 0:
        conversion_rate = int((total_revenue / total_base_salary) * 100)

    return {
        'pilot_count': len(pilot_ids),
        'revenue_sum': total_revenue,
        'basepay_sum': total_base_salary,
        'pilot_share_sum': total_pilot_share,
        'company_share_sum': total_company_share,
        'profit_7d': profit_7d,
        'conversion_rate': conversion_rate,
    }


def calculate_weekly_details(week_start_local: datetime, owner_id: Optional[str] = None, mode: str = 'all') -> List[Dict[str, Any]]:
    """计算新周报明细。"""
    week_end_local = week_start_local + timedelta(days=7) - timedelta(microseconds=1)
    week_records = get_battle_records_for_date_range(week_start_local, week_end_local + timedelta(microseconds=1), owner_id, mode)
    base_salary_map = _fetch_approved_base_salary_map(week_records)

    pilot_stats: Dict[str, Dict[str, Any]] = {}

    for record in week_records:
        pilot_id = str(record.pilot.id)
        stats = pilot_stats.setdefault(
            pilot_id, {
                'pilot': record.pilot,
                'records_count': 0,
                'total_duration': 0.0,
                'total_revenue': Decimal('0'),
                'total_base_salary': Decimal('0'),
                'total_pilot_share': Decimal('0'),
                'total_company_share': Decimal('0'),
            })

        stats['records_count'] += 1
        if record.duration_hours:
            stats['total_duration'] += record.duration_hours
        stats['total_revenue'] += record.revenue_amount
        base_salary = _get_record_base_salary(record, base_salary_map)
        stats['total_base_salary'] += base_salary

        record_date = utc_to_local(record.start_time).date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(record.pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)
        stats['total_pilot_share'] += commission_amounts['pilot_amount']
        stats['total_company_share'] += commission_amounts['company_amount']

    details: List[Dict[str, Any]] = []

    for pilot_id, stats in pilot_stats.items():
        pilot = stats['pilot']
        pilot_display = pilot.nickname or ''
        if pilot.real_name:
            pilot_display += f"（{pilot.real_name}）"

        gender_icon = "♂" if pilot.gender.value == 0 else "♀" if pilot.gender.value == 1 else "?"
        current_year = datetime.now().year
        age = current_year - pilot.birth_year if pilot.birth_year else "未知"
        gender_age = f"{age}-{gender_icon}"
        owner_name = pilot.owner.nickname if pilot.owner else "未知"
        rank = pilot.rank.value

        records_count = stats['records_count']
        avg_duration = stats['total_duration'] / records_count if records_count > 0 else 0.0
        total_profit = stats['total_company_share'] - stats['total_base_salary']

        detail = {
            'pilot_id': pilot_id,
            'pilot_display': pilot_display,
            'gender_age': gender_age,
            'owner': owner_name,
            'rank': rank,
            'records_count': records_count,
            'avg_duration': round(avg_duration, 1),
            'total_revenue': stats['total_revenue'],
            'total_pilot_share': stats['total_pilot_share'],
            'total_company_share': stats['total_company_share'],
            'total_base_salary': stats['total_base_salary'],
            'total_profit': total_profit,
            'status': pilot.status.value,
            'status_display': pilot.status.value
        }
        details.append(detail)

    details.sort(key=lambda item: item['total_profit'])
    return details
