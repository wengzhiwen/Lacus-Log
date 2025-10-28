"""开播日报与月报路由。"""
# pylint: disable=no-member
import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import quote

from flask import Blueprint, Response, render_template, request, url_for
from flask_security import roles_accepted

from models.announcement import Announcement
from models.battle_record import BattleRecord
from models.pilot import Pilot, Rank, Status, WorkMode
from utils.cache_helper import cached_monthly_report
from utils.commission_helper import (calculate_commission_amounts, get_pilot_commission_rate_for_date)
from utils.logging_setup import get_logger
from utils.new_report_calculations import (calculate_daily_summary, calculate_weekly_summary)
from utils.new_report_fast_calculations import calculate_monthly_summary_fast
from utils.recruit_stats import calculate_recruit_today_stats
from utils.rebate_calculator import get_rebate_stage_info
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)

logger = get_logger('report')

report_bp = Blueprint('report', __name__)


def _get_dashboard_time_frames():
    """生成仪表盘相关的本地/UTC时间窗口。"""
    now_utc = get_current_utc_time()
    now_local = utc_to_local(now_utc)
    today_local_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
    today_local_end = today_local_start + timedelta(days=1)
    yesterday_local_start = today_local_start - timedelta(days=1)
    yesterday_local_end = today_local_start
    week_local_start = today_local_start - timedelta(days=7)

    frames = {
        'now_local': now_local,
        'today_start_local': today_local_start,
        'today_end_local': today_local_end,
        'today_start_utc': local_to_utc(today_local_start),
        'today_end_utc': local_to_utc(today_local_end),
        'yesterday_start_utc': local_to_utc(yesterday_local_start),
        'yesterday_end_utc': local_to_utc(yesterday_local_end),
        'week_start_utc': local_to_utc(week_local_start),
    }

    return frames


def build_dashboard_feature_banner():
    """构建仪表盘顶部横幅配置。"""
    frames = _get_dashboard_time_frames()
    now_local = frames['now_local']
    start_local = now_local.replace(year=2025, month=10, day=1, hour=0, minute=0, second=0, microsecond=0)
    end_local = now_local.replace(year=2025, month=10, day=5, hour=23, minute=59, second=59, microsecond=0)

    is_active = start_local <= now_local <= end_local
    banner = {
        'generated_at': now_local.strftime('%Y-%m-%d %H:%M:%S'),
        'show': bool(is_active),
        'title': '',
        'image': '',
        'icon': '🌕',
    }

    if is_active:
        banner.update({
            'title': '请所有运营同学尽量欢度国庆，中秋佳节陪伴主播',
            'image': url_for('static', filename='1001.jpeg'),
        })

    return banner


def calculate_dashboard_recruit_metrics():
    """计算仪表盘招募统计。"""
    frames = _get_dashboard_time_frames()
    today_stats = calculate_recruit_today_stats()

    return {
        'generated_at': frames['now_local'].strftime('%Y-%m-%d %H:%M:%S'),
        'recruit_today_appointments': int(today_stats.get('appointments', 0) or 0),
        'recruit_today_interviews': int(today_stats.get('interviews', 0) or 0),
        'recruit_today_new_recruits': int(today_stats.get('new_recruits', 0) or 0),
    }


def calculate_dashboard_announcement_metrics():
    """计算仪表盘通告统计。"""
    frames = _get_dashboard_time_frames()
    today_start = frames['today_start_utc']
    today_end = frames['today_end_utc']
    yesterday_start = frames['yesterday_start_utc']
    yesterday_end = frames['yesterday_end_utc']
    week_start = frames['week_start_utc']

    today_count = Announcement.objects(start_time__gte=today_start, start_time__lt=today_end).count()
    yesterday_count = Announcement.objects(start_time__gte=yesterday_start, start_time__lt=yesterday_end).count()

    if yesterday_count > 0:
        change_rate = round(((today_count - yesterday_count) / yesterday_count) * 100, 1)
    else:
        change_rate = 100.0 if today_count > 0 else 0.0

    week_count = Announcement.objects(start_time__gte=week_start, start_time__lt=today_end).count()
    week_avg = round(week_count / 7, 1)

    return {
        'generated_at': frames['now_local'].strftime('%Y-%m-%d %H:%M:%S'),
        'today_count': int(today_count),
        'change_rate': float(change_rate),
        'week_avg': float(week_avg),
    }


def calculate_dashboard_battle_metrics():
    """计算仪表盘开播记录统计。"""
    frames = _get_dashboard_time_frames()
    today_start = frames['today_start_utc']
    today_end = frames['today_end_utc']
    yesterday_start = frames['yesterday_start_utc']
    yesterday_end = frames['yesterday_end_utc']
    week_start = frames['week_start_utc']

    today_records = BattleRecord.objects(start_time__gte=today_start, start_time__lt=today_end)
    yesterday_records = BattleRecord.objects(start_time__gte=yesterday_start, start_time__lt=yesterday_end)
    week_records = BattleRecord.objects(start_time__gte=week_start, start_time__lt=today_end)

    today_revenue = sum(record.revenue_amount or Decimal('0') for record in today_records)
    yesterday_revenue = sum(record.revenue_amount or Decimal('0') for record in yesterday_records)
    week_revenue = sum(record.revenue_amount or Decimal('0') for record in week_records)

    battle_today = float(today_revenue)
    battle_yesterday = float(yesterday_revenue)
    battle_week_avg = float(week_revenue) / 7 if week_revenue else 0.0

    return {
        'generated_at': frames['now_local'].strftime('%Y-%m-%d %H:%M:%S'),
        'battle_today_revenue': battle_today,
        'battle_yesterday_revenue': battle_yesterday,
        'battle_week_avg_revenue': battle_week_avg,
    }


def calculate_dashboard_pilot_metrics():
    """计算仪表盘主播统计。"""
    frames = _get_dashboard_time_frames()
    serving_status = [Status.RECRUITED, Status.CONTRACTED]

    pilot_serving = Pilot.objects(status__in=serving_status).count()
    pilot_intern = Pilot.objects(rank=Rank.INTERN, status__in=serving_status).count()
    pilot_official = Pilot.objects(rank=Rank.OFFICIAL, status__in=serving_status).count()

    return {
        'generated_at': frames['now_local'].strftime('%Y-%m-%d %H:%M:%S'),
        'pilot_serving_count': int(pilot_serving),
        'pilot_intern_serving_count': int(pilot_intern),
        'pilot_official_serving_count': int(pilot_official),
    }


def calculate_dashboard_candidate_metrics():
    """计算仪表盘候选人统计。"""
    frames = _get_dashboard_time_frames()
    serving_status = [Status.RECRUITED, Status.CONTRACTED]

    candidate_not_recruited = Pilot.objects(rank=Rank.CANDIDATE, status=Status.NOT_RECRUITED).count()
    trainee_serving = Pilot.objects(rank=Rank.TRAINEE, status__in=serving_status).count()

    return {
        'generated_at': frames['now_local'].strftime('%Y-%m-%d %H:%M:%S'),
        'candidate_not_recruited_count': int(candidate_not_recruited),
        'trainee_serving_count': int(trainee_serving),
    }


def calculate_dashboard_conversion_rate_metrics():
    """计算仪表盘底薪流水转化率统计。"""
    frames = _get_dashboard_time_frames()
    now_local = frames['now_local']

    yesterday_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)

    month_conversion = _calculate_month_conversion_rate(yesterday_local)
    day_conversion = _calculate_day_conversion_rate(yesterday_local)
    week_conversion = _calculate_week_conversion_rate(yesterday_local)

    return {
        'generated_at': frames['now_local'].strftime('%Y-%m-%d %H:%M:%S'),
        'month_conversion_rate': month_conversion,
        'yesterday_conversion_rate': day_conversion,
        'last_week_conversion_rate': week_conversion,
    }


def _calculate_month_conversion_rate(report_date):
    """计算月度底薪流水转化率（截至报表日所在月）。"""
    summary = calculate_monthly_summary_fast(report_date.year, report_date.month, owner_id=None, mode='offline')
    return _calculate_conversion_rate(summary.get('revenue_sum'), summary.get('basepay_sum'))


def _calculate_day_conversion_rate(report_date):
    """计算日度底薪流水转化率（报表日当天）。"""
    summary = calculate_daily_summary(report_date, owner_id=None, mode='offline')
    return _calculate_conversion_rate(summary.get('revenue_sum'), summary.get('basepay_sum'))


def _calculate_week_conversion_rate(report_date):
    """计算周度底薪流水转化率（报表日所在周的上一周，周二至次周一）。"""
    this_week_start = get_week_start_tuesday(report_date)
    last_week_start = this_week_start - timedelta(days=7)
    summary = calculate_weekly_summary(last_week_start, owner_id=None, mode='offline')
    return _calculate_conversion_rate(summary.get('revenue_sum'), summary.get('basepay_sum'))


def _calculate_conversion_rate(total_revenue, total_base_salary):
    """统一按照新报表口径计算底薪流水转化率。"""
    if total_revenue is None and total_base_salary is None:
        return None

    revenue = Decimal(total_revenue or 0)
    base_salary = Decimal(total_base_salary or 0)
    if base_salary == 0:
        return None
    return int((revenue / base_salary) * 100)


def calculate_dashboard_pilot_ranking_metrics():
    """计算仪表盘昨日主播排名统计。"""
    frames = _get_dashboard_time_frames()
    now_local = frames['now_local']

    yesterday_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    day_start = yesterday_local.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = yesterday_local.replace(hour=23, minute=59, second=59, microsecond=999999)

    day_records = get_battle_records_for_date_range(day_start, day_end + timedelta(microseconds=1), owner_id=None, mode='all')

    pilot_revenue = {}

    for record in day_records:
        pilot_id = str(record.pilot.id)
        if pilot_id not in pilot_revenue:
            pilot_revenue[pilot_id] = {'pilot': record.pilot, 'total_revenue': Decimal('0')}
        pilot_revenue[pilot_id]['total_revenue'] += record.revenue_amount or Decimal('0')

    sorted_pilots = sorted(pilot_revenue.values(), key=lambda x: x['total_revenue'], reverse=True)

    def format_pilot_info(pilot_data):
        if not pilot_data:
            return '--'
        pilot = pilot_data['pilot']
        nickname = pilot.nickname or ''
        real_name = pilot.real_name or ''
        owner_name = pilot.owner.nickname if pilot.owner and pilot.owner.nickname else (pilot.owner.username if pilot.owner else '无')

        if real_name:
            return f"{nickname}（{real_name}）[{owner_name}]"
        return f"{nickname}[{owner_name}]"

    champion = format_pilot_info(sorted_pilots[0]) if len(sorted_pilots) > 0 else '--'
    second = format_pilot_info(sorted_pilots[1]) if len(sorted_pilots) > 1 else '--'
    third = format_pilot_info(sorted_pilots[2]) if len(sorted_pilots) > 2 else '--'

    return {
        'generated_at': frames['now_local'].strftime('%Y-%m-%d %H:%M:%S'),
        'champion': champion,
        'second_place': second,
        'third_place': third,
    }


def get_local_date_from_string(date_str):
    """解析 YYYY-MM-DD 为本地日期对象。"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return None


def get_battle_records_for_date_range(start_local_date, end_local_date, owner_id=None, mode: str = 'all'):
    """获取本地日期范围内的开播记录；可按直属运营与开播方式筛选。

    Args:
        start_local_date: 本地开始时间（含）
        end_local_date: 本地结束时间（不含）
        owner_id: 直属运营ID，'all' 或 None 表示不过滤
        mode: 开播方式筛选（'all' | 'online' | 'offline'），默认'all'
    """
    # 标准化参数：将 'all' 统一转换为 None
    if owner_id == 'all':
        owner_id = None
    if mode == 'all':
        mode = None

    start_utc = local_to_utc(start_local_date)
    end_utc = local_to_utc(end_local_date)

    records = BattleRecord.objects.filter(start_time__gte=start_utc, start_time__lt=end_utc)

    if owner_id is not None or mode is not None:
        from models.user import User
        try:
            owner_user = None
            if owner_id is not None:
                owner_user = User.objects.get(id=owner_id)

            # 规则：以筛选范围内“每位主播最后一次开播记录”的运营与开播方式为准，
            # 若最后一次记录同时满足所选的 owner 与 mode（若提供），则计入该主播在本范围内的所有记录；否则剔除该主播的所有记录。
            pilot_to_records = {}
            for rec in records:
                pid = str(rec.pilot.id)
                pilot_to_records.setdefault(pid, []).append(rec)

            filtered_records = []
            for rec_list in pilot_to_records.values():
                rec_list.sort(key=lambda r: r.start_time)
                last_rec = rec_list[-1]
                # 校验 owner 条件
                owner_ok = True
                if owner_user is not None:
                    last_owner = last_rec.owner_snapshot if last_rec.owner_snapshot else last_rec.pilot.owner
                    owner_ok = bool(last_owner and str(last_owner.id) == str(owner_user.id))

                # 校验 mode 条件
                mode_ok = True
                if mode is not None:
                    target_mode = WorkMode.ONLINE if mode == 'online' else WorkMode.OFFLINE
                    mode_ok = last_rec.work_mode == target_mode

                if owner_ok and mode_ok:
                    filtered_records.extend(rec_list)

            return filtered_records
        except User.DoesNotExist:
            logger.warning('指定的直属运营用户不存在：%s', owner_id)
            return []

    return list(records)


def calculate_pilot_three_day_avg_revenue(pilot, report_date, owner_id=None, mode: str = 'all'):
    """计算主播近3个有记录自然日的平均流水。"""
    days_with_records = []
    for i in range(7):
        check_date = report_date - timedelta(days=i)
        check_date_start = check_date.replace(hour=0, minute=0, second=0, microsecond=0)
        check_date_end = check_date_start + timedelta(days=1)
        daily_records = get_battle_records_for_date_range(check_date_start, check_date_end, owner_id, mode)
        pilot_daily_records = [record for record in daily_records if record.pilot.id == pilot.id]
        if len(pilot_daily_records) > 0:
            daily_revenue = sum(record.revenue_amount for record in pilot_daily_records)
            days_with_records.append(daily_revenue)
            if len(days_with_records) >= 3:
                break
    if len(days_with_records) < 3:
        return None
    total_revenue = sum(days_with_records[:3])
    return total_revenue / 3


def calculate_pilot_rebate(pilot, report_date, owner_id=None, mode: str = 'all'):
    """计算主播返点金额。"""
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1), owner_id, mode)
    pilot_month_records = [record for record in month_records if record.pilot.id == pilot.id]
    valid_days = set()
    total_duration = 0
    total_revenue = Decimal('0')
    for record in pilot_month_records:
        local_start = utc_to_local(record.start_time)
        record_date = local_start.date()
        if record.duration_hours:
            total_duration += record.duration_hours
            if record.duration_hours >= 1.0:
                valid_days.add(record_date)
        total_revenue += record.revenue_amount
    valid_days_count = len(valid_days)
    # 使用统一的返点计算工具
    return get_rebate_stage_info(valid_days_count, total_duration, total_revenue)


def calculate_pilot_monthly_stats(pilot, report_date, owner_id=None, mode: str = 'all'):
    """计算主播月度统计。"""
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1), owner_id, mode)
    pilot_month_records = [record for record in month_records if record.pilot.id == pilot.id]
    record_dates = set()
    total_duration = 0
    total_revenue = Decimal('0')
    total_base_salary = Decimal('0')
    for record in pilot_month_records:
        local_start = utc_to_local(record.start_time)
        record_dates.add(local_start.date())
        if record.duration_hours:
            total_duration += record.duration_hours
        total_revenue += record.revenue_amount
        total_base_salary += record.base_salary
    month_days_count = len(record_dates)
    month_avg_duration = total_duration / month_days_count if month_days_count > 0 else 0
    return {
        'month_days_count': month_days_count,
        'month_avg_duration': round(month_avg_duration, 1),
        'month_total_revenue': total_revenue,
        'month_total_base_salary': total_base_salary
    }


@cached_monthly_report()
def _calculate_month_summary(report_date, owner_id=None, mode: str = 'all'):
    """计算月度汇总（截至报表日）。"""
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1), owner_id, mode)

    pilot_ids = set()
    effective_pilot_ids = set()  # 播时≥6小时的主播
    pilot_duration = {}  # 主播ID -> 累计播时

    total_revenue = Decimal('0')
    total_base_salary = Decimal('0')
    total_pilot_share = Decimal('0')
    total_company_share = Decimal('0')
    total_rebate = Decimal('0')

    for record in month_records:
        pilot_id = str(record.pilot.id)
        pilot_ids.add(pilot_id)

        if record.duration_hours:
            if pilot_id not in pilot_duration:
                pilot_duration[pilot_id] = 0
            pilot_duration[pilot_id] += record.duration_hours

        total_revenue += record.revenue_amount
        total_base_salary += record.base_salary

        record_date = utc_to_local(record.start_time).date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(record.pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)

        total_pilot_share += commission_amounts['pilot_amount']
        total_company_share += commission_amounts['company_amount']

    for pilot_id, duration in pilot_duration.items():
        if duration >= 6.0:
            effective_pilot_ids.add(pilot_id)

    # 计算所有主播的返点总额
    total_rebate = Decimal('0')
    for pilot_id in pilot_ids:
        pilot = Pilot.objects.get(id=pilot_id)
        rebate_info = calculate_pilot_rebate(pilot, report_date, owner_id, mode)
        total_rebate += rebate_info['rebate_amount']

    operating_profit = total_company_share + total_rebate - total_base_salary

    conversion_rate = None
    if total_base_salary > 0:
        conversion_rate = int((total_revenue / total_base_salary) * 100)

    return {
        'pilot_count': len(pilot_ids),
        'effective_pilot_count': len(effective_pilot_ids),
        'revenue_sum': total_revenue,
        'basepay_sum': total_base_salary,
        'rebate_sum': total_rebate,
        'pilot_share_sum': total_pilot_share,
        'company_share_sum': total_company_share,
        'operating_profit': operating_profit,
        'conversion_rate': conversion_rate
    }


def _calculate_recruit_statistics(report_date, recruiter_id=None):
    """计算招募统计数据。"""
    from utils.recruit_stats import calculate_recruit_daily_stats
    return calculate_recruit_daily_stats(report_date, recruiter_id)


def _get_recruit_records_for_detail(report_date, range_param, metric, recruiter_id=None):
    """获取招募详情记录列表。"""
    from utils.recruit_stats import get_recruit_records_for_detail
    return get_recruit_records_for_detail(report_date, range_param, metric, recruiter_id)


def get_local_month_from_string(month_str):
    """解析 YYYY-MM 为本地日期对象。"""
    if not month_str:
        return None
    try:
        return datetime.strptime(month_str, '%Y-%m')
    except ValueError:
        return None


def get_week_start_tuesday(local_date: datetime) -> datetime:
    """获取包含给定本地日期的“周二开始”的周起始（周二 00:00:00）。

    规则：周定义为周二至次周一，共7天。
    """
    # Python weekday(): Monday=0 ... Sunday=6
    # 我们要找最近的周二（weekday=1），不晚于当前local_date的那一天
    target_weekday = 1  # Tuesday
    delta_days = (local_date.weekday() - target_weekday) % 7
    week_start = local_date - timedelta(days=delta_days)
    return week_start.replace(hour=0, minute=0, second=0, microsecond=0)


def get_default_week_start_for_now_prev_week() -> datetime:
    """默认选择：当前日期的前一周的周二起始（本地时间）。"""
    now_utc = get_current_utc_time()
    today_local = utc_to_local(now_utc).replace(hour=0, minute=0, second=0, microsecond=0)
    prev_week_date = today_local - timedelta(days=7)
    return get_week_start_tuesday(prev_week_date)


def get_local_date_from_string_safe(date_str):
    """解析 YYYY-MM-DD 为本地日期对象（安全封装）。"""
    try:
        return datetime.strptime(date_str, '%Y-%m-%d') if date_str else None
    except ValueError:
        return None


def get_battle_records_for_month(year, month, owner_id=None, mode: str = 'all'):
    """获取指定月份开播记录。
    
    特殊规则：当报告月是当前月时，筛选范围调整为"当月1日到昨天为止"。
    """
    month_start = datetime(year, month, 1, 0, 0, 0, 0)
    if month == 12:
        next_month_start = datetime(year + 1, 1, 1, 0, 0, 0, 0)
    else:
        next_month_start = datetime(year, month + 1, 1, 0, 0, 0, 0)
    month_end = next_month_start - timedelta(microseconds=1)

    # 检查是否为当前月
    now_utc = get_current_utc_time()
    now_local = utc_to_local(now_utc)
    current_month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    # 如果报告月是当前月，调整结束时间为昨天
    if month_start == current_month_start:
        yesterday_local = now_local - timedelta(days=1)
        month_end = yesterday_local.replace(hour=23, minute=59, second=59, microsecond=999999)
        logger.info('当前月特殊处理：筛选范围调整为 %s 到 %s', month_start.strftime('%Y-%m-%d'), month_end.strftime('%Y-%m-%d %H:%M:%S'))

    return get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1), owner_id, mode)


def calculate_pilot_monthly_commission_stats(pilot, year, month, owner_id=None):
    """计算主播月度分成统计（按日累加）。"""
    month_records = get_battle_records_for_month(year, month, owner_id)
    pilot_month_records = [record for record in month_records if record.pilot.id == pilot.id]

    total_pilot_share = Decimal('0')
    total_company_share = Decimal('0')
    total_base_salary = Decimal('0')

    for record in pilot_month_records:
        record_date = utc_to_local(record.start_time).date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)

        total_pilot_share += commission_amounts['pilot_amount']
        total_company_share += commission_amounts['company_amount']
        total_base_salary += record.base_salary

    return {'total_pilot_share': total_pilot_share, 'total_company_share': total_company_share, 'total_base_salary': total_base_salary}


def calculate_pilot_monthly_rebate_stats(pilot, year, month, owner_id=None):
    """计算主播月度返点统计。"""
    month_start = datetime(year, month, 1, 0, 0, 0, 0)
    if month == 12:
        next_month_start = datetime(year + 1, 1, 1, 0, 0, 0, 0)
    else:
        next_month_start = datetime(year, month + 1, 1, 0, 0, 0, 0)
    month_end = next_month_start - timedelta(microseconds=1)

    # 检查是否为当前月，如果是则使用昨天作为结束时间
    now_utc = get_current_utc_time()
    now_local = utc_to_local(now_utc)
    current_month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    if month_start == current_month_start:
        yesterday_local = now_local - timedelta(days=1)
        report_date = yesterday_local.replace(hour=23, minute=59, second=59, microsecond=999999)
    else:
        report_date = month_end

    return calculate_pilot_rebate(pilot, report_date, owner_id)


@report_bp.route('/recruits/daily-report')
@roles_accepted('gicho', 'kancho')
def recruit_daily_report():
    """主播招募日报页面"""
    date_str = request.args.get('date')
    if not date_str:
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_date = today_local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        report_date = get_local_date_from_string(date_str)
        if not report_date:
            logger.error('无效的日期参数：%s', date_str)
            return '无效的日期格式', 400
        report_date = report_date.replace(hour=0, minute=0, second=0, microsecond=0)

    recruiter_id = request.args.get('recruiter', 'all')
    if recruiter_id == '':
        recruiter_id = 'all'

    logger.info('访问招募日报页面，报表日期：%s，招募负责人：%s', report_date.strftime('%Y-%m-%d'), recruiter_id)

    pagination = {
        'date': report_date.strftime('%Y-%m-%d'),
        'prev_date': (report_date - timedelta(days=1)).strftime('%Y-%m-%d'),
        'next_date': (report_date + timedelta(days=1)).strftime('%Y-%m-%d')
    }

    return render_template('recruit_reports/daily.html', pagination=pagination, selected_recruiter=recruiter_id)


@report_bp.route('/recruits/daily-report/detail')
@roles_accepted('gicho', 'kancho')
def recruit_report_detail():
    """主播招募日报详情页面"""
    date_str = request.args.get('date')
    range_param = request.args.get('range')  # report_day, last_7_days, last_14_days
    metric = request.args.get('metric')  # appointments, interviews, trials, new_recruits
    recruiter_id = request.args.get('recruiter', 'all')

    if not date_str or not range_param or not metric:
        logger.error('缺少必要参数：date=%s, range=%s, metric=%s', date_str, range_param, metric)
        return '缺少必要参数', 400

    report_date = get_local_date_from_string(date_str)
    if not report_date:
        logger.error('无效的日期参数：%s', date_str)
        return '无效的日期格式', 400
    report_date = report_date.replace(hour=0, minute=0, second=0, microsecond=0)

    valid_ranges = ['report_day', 'last_7_days', 'last_14_days']
    if range_param not in valid_ranges:
        logger.error('无效的范围参数：%s', range_param)
        return '无效的范围参数', 400

    valid_metrics = ['appointments', 'interviews', 'trials', 'new_recruits']
    if metric not in valid_metrics:
        logger.error('无效的指标参数：%s', metric)
        return '无效的指标参数', 400

    logger.info('访问招募日报详情页面：日期=%s，范围=%s，指标=%s，招募负责人=%s', date_str, range_param, metric, recruiter_id)

    page_title = '招募日报详情加载中…'
    return_url = url_for('report.recruit_daily_report', date=date_str, recruiter=recruiter_id)

    return render_template('recruit_reports/detail.html',
                           page_title=page_title,
                           report_date=date_str,
                           range_param=range_param,
                           metric=metric,
                           recruiter_id=recruiter_id,
                           return_url=return_url)


# —— 开播周报 ——

# ============ 底薪申请管理路由 ============


@report_bp.route('/base-salary-applications')
@roles_accepted('gicho', 'kancho')
def base_salary_applications_list():
    """底薪申请列表页面"""
    date_str = request.args.get('date')
    if not date_str:
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        app_date = today_local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        app_date = get_local_date_from_string(date_str)
        if not app_date:
            logger.error('无效的日期参数：%s', date_str)
            return '无效的日期格式', 400
        app_date = app_date.replace(hour=0, minute=0, second=0, microsecond=0)

    logger.info('生成底薪申请列表，查询日期：%s', app_date.strftime('%Y-%m-%d'))

    pagination = {
        'date': app_date.strftime('%Y-%m-%d'),
        'prev_date': (app_date - timedelta(days=1)).strftime('%Y-%m-%d'),
        'next_date': (app_date + timedelta(days=1)).strftime('%Y-%m-%d')
    }

    return render_template('reports/base_salary_applications.html', pagination=pagination)


@report_bp.route('/base-salary-applications/detail')
@roles_accepted('gicho', 'kancho')
def base_salary_application_detail():
    """底薪申请详情页面"""
    return render_template('reports/base_salary_application_detail.html')
