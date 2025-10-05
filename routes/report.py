"""开播日报与月报路由。"""
# pylint: disable=no-member
import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import quote

from flask import Blueprint, Response, render_template, request, url_for
from flask_security import roles_accepted

from models.battle_record import BattleRecord
from models.pilot import WorkMode
from utils.commission_helper import (calculate_commission_amounts, get_pilot_commission_rate_for_date)
from utils.logging_setup import get_logger
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)
from utils.cache_helper import cached_monthly_report

logger = get_logger('report')

report_bp = Blueprint('report', __name__)


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
    start_utc = local_to_utc(start_local_date)
    end_utc = local_to_utc(end_local_date)

    records = BattleRecord.objects.filter(start_time__gte=start_utc, start_time__lt=end_utc)

    if (owner_id and owner_id != 'all') or (mode and mode != 'all'):
        from models.user import User
        try:
            owner_user = None
            if owner_id and owner_id != 'all':
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
                if mode and mode != 'all':
                    target_mode = WorkMode.ONLINE if mode == 'online' else WorkMode.OFFLINE
                    mode_ok = (last_rec.work_mode == target_mode)

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
    qualified_stages = [
        s for s in rebate_stages if valid_days_count >= s['min_days'] and total_duration >= s['min_hours'] and total_revenue >= s['min_revenue']
    ]
    if qualified_stages:
        best_stage = max(qualified_stages, key=lambda x: x['stage'])
        rebate_amount = total_revenue * Decimal(str(best_stage['rate']))
        return {
            'rebate_amount': rebate_amount,
            'rebate_rate': best_stage['rate'],
            'rebate_stage': best_stage['stage'],
            'valid_days_count': valid_days_count,
            'total_duration': total_duration,
            'total_revenue': total_revenue,
            'qualified_stages': qualified_stages
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

    total_rebate = Decimal('0')

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


@cached_monthly_report()
def _calculate_day_summary(report_date, owner_id=None, mode: str = 'all'):
    """计算日报汇总（仅报表日）。"""
    day_start = report_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    day_records = get_battle_records_for_date_range(day_start, day_end + timedelta(microseconds=1), owner_id, mode)

    pilot_ids = set()
    effective_pilot_ids = set()  # 播时≥6小时的主播
    pilot_duration = {}  # 主播ID -> 累计播时

    total_revenue = Decimal('0')
    total_base_salary = Decimal('0')
    total_pilot_share = Decimal('0')
    total_company_share = Decimal('0')

    for record in day_records:
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
        'conversion_rate': conversion_rate
    }


@cached_monthly_report()
def _calculate_daily_details(report_date, owner_id=None, mode: str = 'all'):
    """计算日报明细。"""
    day_start = report_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    day_records = get_battle_records_for_date_range(day_start, day_end + timedelta(microseconds=1), owner_id, mode)

    details = []

    for record in day_records:
        pilot = record.pilot
        local_start = utc_to_local(record.start_time)

        pilot_display = f"{pilot.nickname}"
        if pilot.real_name:
            pilot_display += f"（{pilot.real_name}）"

        gender_icon = "♂" if pilot.gender.value == 0 else "♀" if pilot.gender.value == 1 else "?"
        current_year = datetime.now().year
        age = current_year - pilot.birth_year if pilot.birth_year else "未知"
        gender_age = f"{age}-{gender_icon}"

        owner = record.owner_snapshot.nickname if record.owner_snapshot else (pilot.owner.nickname if pilot.owner else "未知")
        rank = pilot.rank.value  # BattleRecord没有rank_snapshot字段，直接使用pilot的rank

        battle_area = f"{record.work_mode.value}@{record.x_coord}-{record.y_coord}-{record.z_coord}"

        duration = record.duration_hours if record.duration_hours else 0.0

        record_date = local_start.date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)

        rebate_info = calculate_pilot_rebate(pilot, report_date, owner_id, mode)

        daily_profit = commission_amounts['company_amount'] + rebate_info['rebate_amount'] - record.base_salary

        three_day_avg_revenue = calculate_pilot_three_day_avg_revenue(pilot, report_date, owner_id, mode)

        monthly_stats = calculate_pilot_monthly_stats(pilot, report_date, owner_id, mode)

        month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
        month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1), owner_id, mode)
        pilot_month_records = [record for record in month_records if record.pilot.id == pilot.id]

        month_total_pilot_share = Decimal('0')
        month_total_company_share = Decimal('0')
        month_total_base_salary = Decimal('0')

        for month_record in pilot_month_records:
            month_record_date = utc_to_local(month_record.start_time).date()
            month_commission_rate, _, _ = get_pilot_commission_rate_for_date(pilot.id, month_record_date)
            month_commission_amounts = calculate_commission_amounts(month_record.revenue_amount, month_commission_rate)

            month_total_pilot_share += month_commission_amounts['pilot_amount']
            month_total_company_share += month_commission_amounts['company_amount']
            month_total_base_salary += month_record.base_salary

        month_total_profit = month_total_company_share + rebate_info['rebate_amount'] - month_total_base_salary

        monthly_commission_stats = {
            'month_total_pilot_share': month_total_pilot_share,
            'month_total_company_share': month_total_company_share,
            'month_total_profit': month_total_profit
        }

        month_rebate_amount = rebate_info['rebate_amount']

        detail = {
            'pilot_id': str(pilot.id),
            'pilot_display': pilot_display,
            'gender_age': gender_age,
            'owner': owner,
            'rank': rank,
            'battle_area': battle_area,
            'duration': duration,
            'revenue': record.revenue_amount,
            'commission_rate': commission_rate,
            'pilot_share': commission_amounts['pilot_amount'],
            'company_share': commission_amounts['company_amount'],
            'rebate_rate': rebate_info['rebate_rate'],
            'rebate_amount': rebate_info['rebate_amount'],
            'base_salary': record.base_salary,
            'daily_profit': daily_profit,
            'three_day_avg_revenue': three_day_avg_revenue,
            'monthly_stats': monthly_stats,
            'monthly_commission_stats': monthly_commission_stats,
            'month_rebate_amount': month_rebate_amount
        }

        details.append(detail)

    details.sort(key=lambda x: (x['monthly_commission_stats']['month_total_profit'], -x['revenue']))

    return details


@report_bp.route('/daily')
@roles_accepted('gicho', 'kancho')
def daily_report():
    """开播日报页面"""
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

    owner_id = request.args.get('owner', 'all')
    if owner_id == '':
        owner_id = 'all'

    mode = request.args.get('mode', 'all') or 'all'
    if mode not in ['all', 'online', 'offline']:
        mode = 'all'

    logger.info('生成开播日报，报表日期：%s，直属运营：%s，开播方式：%s', report_date.strftime('%Y-%m-%d'), owner_id, mode)

    pagination = {
        'date': report_date.strftime('%Y-%m-%d'),
        'prev_date': (report_date - timedelta(days=1)).strftime('%Y-%m-%d'),
        'next_date': (report_date + timedelta(days=1)).strftime('%Y-%m-%d')
    }

    return render_template('reports/daily.html', pagination=pagination, selected_owner=owner_id, selected_mode=mode)


@report_bp.route('/daily/export.csv')
@roles_accepted('gicho', 'kancho')
def export_daily_csv():
    """导出开播日报CSV"""
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

    owner_id = request.args.get('owner', 'all')
    if owner_id == '':
        owner_id = 'all'

    mode = request.args.get('mode', 'all') or 'all'
    if mode not in ['all', 'online', 'offline']:
        mode = 'all'

    logger.info('导出开播日报CSV，报表日期：%s，直属运营：%s，开播方式：%s', report_date.strftime('%Y-%m-%d'), owner_id, mode)

    details = _calculate_daily_details(report_date, owner_id, mode)

    output = io.StringIO()
    writer = csv.writer(output)

    output.write('\ufeff')

    headers = [
        '主播', '性别年龄', '直属运营', '主播分类', '开播地点', '播时(小时)', '流水(元)', '当前分成比例(%)', '主播分成(元)', '公司分成(元)', '返点比例(%)', '产生返点(元)', '底薪(元)', '当日毛利(元)', '3日平均流水(元)',
        '月累计天数', '月日均播时(小时)', '月累计流水(元)', '月累计主播分成(元)', '月累计公司分成(元)', '月累计返点(元)', '月累计底薪(元)', '月累计毛利(元)'
    ]
    writer.writerow(headers)

    for detail in details:
        row = [
            detail['pilot_display'], detail['gender_age'], detail['owner'], detail['rank'], detail['battle_area'], f"{detail['duration']:.1f}",
            f"{detail['revenue']:.2f}", f"{detail['commission_rate']:.0f}", f"{detail['pilot_share']:.2f}", f"{detail['company_share']:.2f}",
            f"{detail['rebate_rate'] * 100:.0f}", f"{detail['rebate_amount']:.2f}", f"{detail['base_salary']:.2f}", f"{detail['daily_profit']:.2f}",
            f"{detail['three_day_avg_revenue']:.2f}" if detail['three_day_avg_revenue'] else "", detail['monthly_stats']['month_days_count'],
            f"{detail['monthly_stats']['month_avg_duration']:.1f}", f"{detail['monthly_stats']['month_total_revenue']:.2f}",
            f"{detail['monthly_commission_stats']['month_total_pilot_share']:.2f}", f"{detail['monthly_commission_stats']['month_total_company_share']:.2f}",
            f"{detail['month_rebate_amount']:.2f}", f"{detail['monthly_stats']['month_total_base_salary']:.2f}",
            f"{detail['monthly_commission_stats']['month_total_profit']:.2f}"
        ]
        writer.writerow(row)

    csv_content = output.getvalue()
    output.close()

    filename = f"开播日报_{report_date.strftime('%Y%m%d')}.csv"
    encoded_filename = quote(filename.encode('utf-8'))

    response = Response(csv_content, mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename*=UTF-8\'\'{encoded_filename}'})

    return response


def _calculate_recruit_statistics(report_date, recruiter_id=None):
    """计算招募统计数据。"""
    from utils.recruit_stats import calculate_recruit_daily_stats
    return calculate_recruit_daily_stats(report_date, recruiter_id)


def _get_recruit_users():
    """获取招募负责人用户列表（管理员与运营）。"""
    from models.user import Role, User

    gicho_role = Role.objects(name='gicho').first()
    kancho_role = Role.objects(name='kancho').first()

    users = []
    if gicho_role:
        users.extend(User.objects(roles=gicho_role, active=True))
    if kancho_role:
        users.extend(User.objects(roles=kancho_role, active=True))

    unique_users = {}
    for user in users:
        if user.id not in unique_users:
            unique_users[user.id] = user

    return sorted(unique_users.values(), key=lambda u: u.nickname or u.username)


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
    """获取指定月份开播记录。"""
    month_start = datetime(year, month, 1, 0, 0, 0, 0)
    if month == 12:
        next_month_start = datetime(year + 1, 1, 1, 0, 0, 0, 0)
    else:
        next_month_start = datetime(year, month + 1, 1, 0, 0, 0, 0)
    month_end = next_month_start - timedelta(microseconds=1)

    return get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1), owner_id, mode)


def calculate_pilot_monthly_commission_stats(pilot, year, month, owner_id=None):
    """计算主播月度分成统计（按日累加）。"""
    month_start = datetime(year, month, 1, 0, 0, 0, 0)
    if month == 12:
        next_month_start = datetime(year + 1, 1, 1, 0, 0, 0, 0)
    else:
        next_month_start = datetime(year, month + 1, 1, 0, 0, 0, 0)
    month_end = next_month_start - timedelta(microseconds=1)

    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1), owner_id)
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
    if month == 12:
        next_month_start = datetime(year + 1, 1, 1, 0, 0, 0, 0)
    else:
        next_month_start = datetime(year, month + 1, 1, 0, 0, 0, 0)
    month_end = next_month_start - timedelta(microseconds=1)

    return calculate_pilot_rebate(pilot, month_end, owner_id)


@cached_monthly_report()
def _calculate_monthly_summary(year, month, owner_id=None, mode: str = 'all'):
    """计算月度汇总。"""
    month_records = get_battle_records_for_month(year, month, owner_id, mode)

    pilot_ids = set()
    pilot_duration = {}  # 主播ID -> 累计播时
    pilot_records_count = {}  # 主播ID -> 开播记录数

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

        if pilot_id not in pilot_records_count:
            pilot_records_count[pilot_id] = 0
        pilot_records_count[pilot_id] += 1

        total_revenue += record.revenue_amount
        total_base_salary += record.base_salary

        record_date = utc_to_local(record.start_time).date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(record.pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)

        total_pilot_share += commission_amounts['pilot_amount']
        total_company_share += commission_amounts['company_amount']

    total_rebate = Decimal('0')

    operating_profit = total_company_share + total_rebate - total_base_salary

    conversion_rate = None
    if total_base_salary > 0:
        conversion_rate = int((total_revenue / total_base_salary) * 100)

    return {
        'pilot_count': len(pilot_ids),
        'revenue_sum': total_revenue,
        'basepay_sum': total_base_salary,
        'rebate_sum': total_rebate,
        'pilot_share_sum': total_pilot_share,
        'company_share_sum': total_company_share,
        'operating_profit': operating_profit,
        'conversion_rate': conversion_rate
    }


@cached_monthly_report()
def _calculate_monthly_details(year, month, owner_id=None, mode: str = 'all'):
    """计算月度明细数据。"""
    month_records = get_battle_records_for_month(year, month, owner_id, mode)

    pilot_stats = {}

    for record in month_records:
        pilot_id = str(record.pilot.id)

        if pilot_id not in pilot_stats:
            pilot_stats[pilot_id] = {
                'pilot': record.pilot,
                'records_count': 0,
                'total_duration': 0,
                'total_revenue': Decimal('0'),
                'total_base_salary': Decimal('0')
            }

        pilot_stats[pilot_id]['records_count'] += 1
        if record.duration_hours:
            pilot_stats[pilot_id]['total_duration'] += record.duration_hours
        pilot_stats[pilot_id]['total_revenue'] += record.revenue_amount
        pilot_stats[pilot_id]['total_base_salary'] += record.base_salary

    details = []

    for pilot_id, stats in pilot_stats.items():
        pilot = stats['pilot']

        pilot_display = f"{pilot.nickname}"
        if pilot.real_name:
            pilot_display += f"（{pilot.real_name}）"

        gender_icon = "♂" if pilot.gender.value == 0 else "♀" if pilot.gender.value == 1 else "?"
        current_year = datetime.now().year
        age = current_year - pilot.birth_year if pilot.birth_year else "未知"
        gender_age = f"{age}-{gender_icon}"

        owner = pilot.owner.nickname if pilot.owner else "未知"

        rank = pilot.rank.value

        records_count = stats['records_count']

        avg_duration = stats['total_duration'] / records_count if records_count > 0 else 0

        total_revenue = stats['total_revenue']

        commission_stats = calculate_pilot_monthly_commission_stats(pilot, year, month, owner_id)

        rebate_stats = calculate_pilot_monthly_rebate_stats(pilot, year, month, owner_id)

        total_profit = commission_stats['total_company_share'] + rebate_stats['rebate_amount'] - commission_stats['total_base_salary']

        detail = {
            'pilot_id': pilot_id,
            'pilot_display': pilot_display,
            'gender_age': gender_age,
            'owner': owner,
            'rank': rank,
            'records_count': records_count,
            'avg_duration': round(avg_duration, 1),
            'total_revenue': total_revenue,
            'total_pilot_share': commission_stats['total_pilot_share'],
            'total_company_share': commission_stats['total_company_share'],
            'rebate_rate': rebate_stats['rebate_rate'],
            'rebate_amount': rebate_stats['rebate_amount'],
            'total_base_salary': commission_stats['total_base_salary'],
            'total_profit': total_profit
        }

        details.append(detail)

    details.sort(key=lambda x: x['total_profit'])

    return details


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

    logger.info('生成征召日报，报表日期：%s，招募负责人：%s', report_date.strftime('%Y-%m-%d'), recruiter_id)

    statistics = _calculate_recruit_statistics(report_date, recruiter_id)

    users = _get_recruit_users()

    pagination = {
        'date': report_date.strftime('%Y-%m-%d'),
        'prev_date': (report_date - timedelta(days=1)).strftime('%Y-%m-%d'),
        'next_date': (report_date + timedelta(days=1)).strftime('%Y-%m-%d')
    }

    return render_template('recruit_reports/daily.html', statistics=statistics, pagination=pagination, users=users, selected_recruiter=recruiter_id)


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

    logger.info('生成招募日报详情：日期=%s，范围=%s，指标=%s，招募负责人=%s', date_str, range_param, metric, recruiter_id)

    recruits = _get_recruit_records_for_detail(report_date, range_param, metric, recruiter_id)

    range_names = {'report_day': '报表日', 'last_7_days': '近7日', 'last_14_days': '近14日'}
    metric_names = {'appointments': '约面', 'interviews': '到面', 'trials': '试播', 'new_recruits': '新开播'}

    recruiter_name = ''
    if recruiter_id and recruiter_id != 'all':
        from models.user import User
        try:
            recruiter = User.objects.get(id=recruiter_id)
            recruiter_name = recruiter.nickname or recruiter.username
        except Exception:
            recruiter_name = '未知'

    if recruiter_name:
        page_title = f"{report_date.strftime('%Y年%m月%d日')} {range_names[range_param]} {metric_names[metric]}（{recruiter_name}）：{len(recruits)}"
    else:
        page_title = f"{report_date.strftime('%Y年%m月%d日')} {range_names[range_param]} {metric_names[metric]}：{len(recruits)}"

    return_url = url_for('report.recruit_daily_report', date=date_str, recruiter=recruiter_id)

    return render_template('recruit_reports/detail.html',
                           page_title=page_title,
                           report_date=date_str,
                           range_param=range_param,
                           metric=metric,
                           recruiter_id=recruiter_id,
                           recruiter_name=recruiter_name,
                           recruits=recruits,
                           return_url=return_url)


@report_bp.route('/monthly')
@roles_accepted('gicho', 'kancho')
def monthly_report():
    """开播月报页面"""
    month_str = request.args.get('month')
    if not month_str:
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_month = today_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        report_month = get_local_month_from_string(month_str)
        if not report_month:
            logger.error('无效的月份参数：%s', month_str)
            return '无效的月份格式', 400
        report_month = report_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    owner_id = request.args.get('owner', 'all')
    if owner_id == '':
        owner_id = 'all'

    mode = request.args.get('mode', 'all') or 'all'
    if mode not in ['all', 'online', 'offline']:
        mode = 'all'

    logger.info('生成开播月报，报表月份：%s，直属运营：%s，开播方式：%s', report_month.strftime('%Y-%m'), owner_id, mode)

    pagination = {
        'month': report_month.strftime('%Y-%m'),
        'prev_month': (report_month.replace(day=1) - timedelta(days=1)).strftime('%Y-%m'),
        'next_month': (report_month.replace(day=28) + timedelta(days=4)).replace(day=1).strftime('%Y-%m')
    }

    return render_template('reports/monthly.html', pagination=pagination, selected_owner=owner_id, selected_mode=mode)


@report_bp.route('/monthly/export.csv')
@roles_accepted('gicho', 'kancho')
def export_monthly_csv():
    """导出开播月报CSV"""
    month_str = request.args.get('month')
    if not month_str:
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_month = today_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        report_month = get_local_month_from_string(month_str)
        if not report_month:
            logger.error('无效的月份参数：%s', month_str)
            return '无效的月份格式', 400
        report_month = report_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    owner_id = request.args.get('owner', 'all')
    if owner_id == '':
        owner_id = 'all'

    mode = request.args.get('mode', 'all') or 'all'
    if mode not in ['all', 'online', 'offline']:
        mode = 'all'

    logger.info('导出开播月报CSV，报表月份：%s，直属运营：%s，开播方式：%s', report_month.strftime('%Y-%m'), owner_id, mode)

    details = _calculate_monthly_details(report_month.year, report_month.month, owner_id, mode)

    output = io.StringIO()
    writer = csv.writer(output)

    output.write('\ufeff')

    headers = ['主播', '性别年龄', '直属运营', '主播分类', '月累计开播记录数', '月均播时(小时)', '月累计流水(元)', '月累计主播分成(元)', '月累计公司分成(元)', '月最新返点比例(%)', '月累计返点(元)', '月累计底薪(元)', '月累计毛利(元)']
    writer.writerow(headers)

    for detail in details:
        row = [
            detail['pilot_display'], detail['gender_age'], detail['owner'], detail['rank'], detail['records_count'], f"{detail['avg_duration']:.1f}",
            f"{detail['total_revenue']:.2f}", f"{detail['total_pilot_share']:.2f}", f"{detail['total_company_share']:.2f}",
            f"{detail['rebate_rate'] * 100:.0f}", f"{detail['rebate_amount']:.2f}", f"{detail['total_base_salary']:.2f}", f"{detail['total_profit']:.2f}"
        ]
        writer.writerow(row)

    csv_content = output.getvalue()
    output.close()

    filename = f"开播月报_{report_month.strftime('%Y%m')}.csv"
    encoded_filename = quote(filename.encode('utf-8'))

    response = Response(csv_content, mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename*=UTF-8\'\'{encoded_filename}'})

    return response


# —— 开播周报 ——


@cached_monthly_report()
def _calculate_weekly_summary(week_start_local: datetime, owner_id: str = None, mode: str = 'all'):
    """计算周度汇总（周二至次周一，不计返点）。"""
    week_end_local = week_start_local + timedelta(days=7) - timedelta(microseconds=1)
    week_records = get_battle_records_for_date_range(week_start_local, week_end_local + timedelta(microseconds=1), owner_id, mode)

    pilot_ids = set()
    total_revenue = Decimal('0')
    total_base_salary = Decimal('0')
    total_pilot_share = Decimal('0')
    total_company_share = Decimal('0')

    for record in week_records:
        pilot_ids.add(str(record.pilot.id))
        total_revenue += record.revenue_amount
        total_base_salary += record.base_salary
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
        'conversion_rate': conversion_rate
    }


@cached_monthly_report()
def _calculate_weekly_details(week_start_local: datetime, owner_id: str = None, mode: str = 'all'):
    """计算周度明细（按主播聚合，不计返点）。"""
    week_end_local = week_start_local + timedelta(days=7) - timedelta(microseconds=1)
    week_records = get_battle_records_for_date_range(week_start_local, week_end_local + timedelta(microseconds=1), owner_id, mode)

    pilot_stats = {}
    for record in week_records:
        pilot_id = str(record.pilot.id)
        if pilot_id not in pilot_stats:
            pilot_stats[pilot_id] = {
                'pilot': record.pilot,
                'records_count': 0,
                'total_duration': 0.0,
                'total_revenue': Decimal('0'),
                'total_base_salary': Decimal('0')
            }
        pilot_stats[pilot_id]['records_count'] += 1
        if record.duration_hours:
            pilot_stats[pilot_id]['total_duration'] += record.duration_hours
        pilot_stats[pilot_id]['total_revenue'] += record.revenue_amount
        pilot_stats[pilot_id]['total_base_salary'] += record.base_salary

    details = []
    for pilot_id, stats in pilot_stats.items():
        pilot = stats['pilot']
        pilot_display = f"{pilot.nickname}"
        if pilot.real_name:
            pilot_display += f"（{pilot.real_name}）"
        gender_icon = "♂" if pilot.gender.value == 0 else "♀" if pilot.gender.value == 1 else "?"
        current_year = datetime.now().year
        age = current_year - pilot.birth_year if pilot.birth_year else "未知"
        gender_age = f"{age}-{gender_icon}"
        owner = pilot.owner.nickname if pilot.owner else "未知"
        rank = pilot.rank.value

        records_count = stats['records_count']
        avg_duration = stats['total_duration'] / records_count if records_count > 0 else 0

        # 分成（逐条按日比例计算并累加）
        total_pilot_share = Decimal('0')
        total_company_share = Decimal('0')
        for record in week_records:
            if str(record.pilot.id) != pilot_id:
                continue
            record_date = utc_to_local(record.start_time).date()
            commission_rate, _, _ = get_pilot_commission_rate_for_date(pilot.id, record_date)
            commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)
            total_pilot_share += commission_amounts['pilot_amount']
            total_company_share += commission_amounts['company_amount']

        total_profit = total_company_share - stats['total_base_salary']

        detail = {
            'pilot_id': pilot_id,
            'pilot_display': pilot_display,
            'gender_age': gender_age,
            'owner': owner,
            'rank': rank,
            'records_count': records_count,
            'avg_duration': round(avg_duration, 1),
            'total_revenue': stats['total_revenue'],
            'total_pilot_share': total_pilot_share,
            'total_company_share': total_company_share,
            'total_base_salary': stats['total_base_salary'],
            'total_profit': total_profit
        }
        details.append(detail)

    details.sort(key=lambda x: x['total_profit'])
    return details


@report_bp.route('/weekly')
@roles_accepted('gicho', 'kancho')
def weekly_report():
    """开播周报页面（周二-次周一，默认当前日期的前一周）。"""
    week_start_str = request.args.get('week_start')
    if week_start_str:
        week_start_local = get_local_date_from_string_safe(week_start_str)
        if not week_start_local:
            logger.error('无效的周起始参数：%s', week_start_str)
            return '无效的周起始格式', 400
        week_start_local = get_week_start_tuesday(week_start_local)
    else:
        week_start_local = get_default_week_start_for_now_prev_week()

    owner_id = request.args.get('owner', 'all') or 'all'
    mode = request.args.get('mode', 'all') or 'all'
    if mode not in ['all', 'online', 'offline']:
        mode = 'all'

    logger.info('生成开播周报，起始周二：%s，直属运营：%s，开播方式：%s', week_start_local.strftime('%Y-%m-%d'), owner_id, mode)

    pagination = {
        'week_start': week_start_local.strftime('%Y-%m-%d'),
        'prev_week_start': (week_start_local - timedelta(days=7)).strftime('%Y-%m-%d'),
        'next_week_start': (week_start_local + timedelta(days=7)).strftime('%Y-%m-%d')
    }

    return render_template('reports/weekly.html', pagination=pagination, selected_owner=owner_id, selected_mode=mode)


@report_bp.route('/weekly/export.csv')
@roles_accepted('gicho', 'kancho')
def export_weekly_csv():
    """导出开播周报CSV（不含返点列）。"""
    week_start_str = request.args.get('week_start')
    if week_start_str:
        week_start_local = get_local_date_from_string_safe(week_start_str)
        if not week_start_local:
            logger.error('无效的周起始参数：%s', week_start_str)
            return '无效的周起始格式', 400
        week_start_local = get_week_start_tuesday(week_start_local)
    else:
        week_start_local = get_default_week_start_for_now_prev_week()

    owner_id = request.args.get('owner', 'all') or 'all'
    mode = request.args.get('mode', 'all') or 'all'
    if mode not in ['all', 'online', 'offline']:
        mode = 'all'

    logger.info('导出开播周报CSV，起始周二：%s，直属运营：%s，开播方式：%s', week_start_local.strftime('%Y-%m-%d'), owner_id, mode)

    details = _calculate_weekly_details(week_start_local, owner_id, mode)

    output = io.StringIO()
    writer = csv.writer(output)
    output.write('\ufeff')

    headers = ['主播', '性别年龄', '直属运营', '主播分类', '周累计开播记录数', '周均播时(小时)', '周累计流水(元)', '周累计主播分成(元)', '周累计公司分成(元)', '周累计底薪(元)', '周累计毛利(元)']
    writer.writerow(headers)

    for detail in details:
        row = [
            detail['pilot_display'], detail['gender_age'], detail['owner'], detail['rank'], detail['records_count'], f"{detail['avg_duration']:.1f}",
            f"{detail['total_revenue']:.2f}", f"{detail['total_pilot_share']:.2f}", f"{detail['total_company_share']:.2f}",
            f"{detail['total_base_salary']:.2f}", f"{detail['total_profit']:.2f}"
        ]
        writer.writerow(row)

    csv_content = output.getvalue()
    output.close()

    filename = f"开播周报_{week_start_local.strftime('%Y%m%d')}.csv"
    encoded_filename = quote(filename.encode('utf-8'))

    response = Response(csv_content, mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f"attachment; filename*=UTF-8''{encoded_filename}"})
    return response
