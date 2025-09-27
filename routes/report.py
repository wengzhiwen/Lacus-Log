"""开播日报路由

实现开播日报的日视图和CSV导出功能。
注意：mongoengine 的动态属性在pylint中会触发 no-member 误报，这里统一抑制。
"""
# pylint: disable=no-member
import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import quote

from flask import Blueprint, Response, render_template, request
from flask_security import roles_accepted

from models.battle_record import BattleRecord
from utils.commission_helper import (calculate_commission_amounts, get_pilot_commission_rate_for_date)
from utils.logging_setup import get_logger
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)

# 创建日志器（按模块分文件）
logger = get_logger('report')

report_bp = Blueprint('report', __name__)


def get_local_date_from_string(date_str):
    """将日期字符串解析为本地日期对象"""
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return None


def get_battle_records_for_date_range(start_local_date, end_local_date):
    """获取指定本地日期范围内的开播记录"""
    start_utc = local_to_utc(start_local_date)
    end_utc = local_to_utc(end_local_date)
    return BattleRecord.objects.filter(start_time__gte=start_utc, start_time__lt=end_utc)


def calculate_pilot_three_day_avg_revenue(pilot, report_date):
    """计算主播3日平均流水"""
    days_with_records = []
    for i in range(7):
        check_date = report_date - timedelta(days=i)
        check_date_start = check_date.replace(hour=0, minute=0, second=0, microsecond=0)
        check_date_end = check_date_start + timedelta(days=1)
        daily_records = get_battle_records_for_date_range(check_date_start, check_date_end)
        pilot_daily_records = daily_records.filter(pilot=pilot)
        if pilot_daily_records.count() > 0:
            daily_revenue = sum(record.revenue_amount for record in pilot_daily_records)
            days_with_records.append(daily_revenue)
            if len(days_with_records) >= 3:
                break
    if len(days_with_records) < 3:
        return None
    total_revenue = sum(days_with_records[:3])
    return total_revenue / 3


def calculate_pilot_rebate(pilot, report_date):
    """计算主播返点金额"""
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1))
    pilot_month_records = month_records.filter(pilot=pilot)
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


def calculate_pilot_monthly_stats(pilot, report_date):
    """计算主播月度统计数据"""
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1))
    pilot_month_records = month_records.filter(pilot=pilot)
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


def _calculate_month_summary(report_date):
    """计算月度数据（截至报表日）"""
    # 计算月范围：当月1号00:00 至 报表日23:59:59
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    # 获取本月所有作战记录
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1))

    # 统计主播数量（去重）
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

        # 累计播时
        if record.duration_hours:
            if pilot_id not in pilot_duration:
                pilot_duration[pilot_id] = 0
            pilot_duration[pilot_id] += record.duration_hours

        # 累计金额
        total_revenue += record.revenue_amount
        total_base_salary += record.base_salary

        # 计算分成
        record_date = utc_to_local(record.start_time).date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(record.pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)

        total_pilot_share += commission_amounts['pilot_amount']
        total_company_share += commission_amounts['company_amount']

    # 计算有效主播数量
    for pilot_id, duration in pilot_duration.items():
        if duration >= 6.0:
            effective_pilot_ids.add(pilot_id)

    # 计算返点（简化版，实际应该按主播分别计算）
    # 这里先返回0，后续可以优化
    total_rebate = Decimal('0')

    # 运营利润估算
    operating_profit = total_company_share + total_rebate - total_base_salary

    return {
        'pilot_count': len(pilot_ids),
        'effective_pilot_count': len(effective_pilot_ids),
        'revenue_sum': total_revenue,
        'basepay_sum': total_base_salary,
        'rebate_sum': total_rebate,
        'pilot_share_sum': total_pilot_share,
        'company_share_sum': total_company_share,
        'operating_profit': operating_profit
    }


def _calculate_day_summary(report_date):
    """计算日报汇总（仅报表日）"""
    # 计算报表日范围：00:00:00 至 23:59:59
    day_start = report_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    # 获取报表日所有作战记录
    day_records = get_battle_records_for_date_range(day_start, day_end + timedelta(microseconds=1))

    # 统计主播数量（去重）
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

        # 累计播时
        if record.duration_hours:
            if pilot_id not in pilot_duration:
                pilot_duration[pilot_id] = 0
            pilot_duration[pilot_id] += record.duration_hours

        # 累计金额
        total_revenue += record.revenue_amount
        total_base_salary += record.base_salary

        # 计算分成
        record_date = utc_to_local(record.start_time).date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(record.pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)

        total_pilot_share += commission_amounts['pilot_amount']
        total_company_share += commission_amounts['company_amount']

    # 计算有效主播数量
    for pilot_id, duration in pilot_duration.items():
        if duration >= 6.0:
            effective_pilot_ids.add(pilot_id)

    return {
        'pilot_count': len(pilot_ids),
        'effective_pilot_count': len(effective_pilot_ids),
        'revenue_sum': total_revenue,
        'basepay_sum': total_base_salary,
        'pilot_share_sum': total_pilot_share,
        'company_share_sum': total_company_share
    }


def _calculate_daily_details(report_date):
    """计算日报明细"""
    # 计算报表日范围：00:00:00 至 23:59:59
    day_start = report_date.replace(hour=0, minute=0, second=0, microsecond=0)
    day_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    # 获取报表日所有作战记录
    day_records = get_battle_records_for_date_range(day_start, day_end + timedelta(microseconds=1))

    details = []

    for record in day_records:
        # 基本信息
        pilot = record.pilot
        local_start = utc_to_local(record.start_time)

        # 主播显示信息
        pilot_display = f"{pilot.nickname}"
        if pilot.real_name:
            pilot_display += f"（{pilot.real_name}）"

        # 性别年龄
        gender_icon = "♂" if pilot.gender == "male" else "♀" if pilot.gender == "female" else "?"
        current_year = datetime.now().year
        age = current_year - pilot.birth_year if pilot.birth_year else "未知"
        gender_age = f"{age}-{gender_icon}"

        # 所属和阶级（优先使用快照）
        owner = record.owner_snapshot.nickname if record.owner_snapshot else (pilot.owner.nickname if pilot.owner else "未知")
        rank = pilot.rank.value  # BattleRecord没有rank_snapshot字段，直接使用pilot的rank

        # 开播地点
        battle_area = f"{record.work_mode.value}@{record.x_coord}-{record.y_coord}-{record.z_coord}"

        # 播时
        duration = record.duration_hours if record.duration_hours else 0.0

        # 分成计算
        record_date = local_start.date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)

        # 返点计算（简化版）
        rebate_info = calculate_pilot_rebate(pilot, report_date)

        # 当日毛利
        daily_profit = commission_amounts['company_amount'] + rebate_info['rebate_amount'] - record.base_salary

        # 3日平均流水
        three_day_avg_revenue = calculate_pilot_three_day_avg_revenue(pilot, report_date)

        # 月度统计
        monthly_stats = calculate_pilot_monthly_stats(pilot, report_date)

        # 月度分成统计（简化版）
        monthly_commission_stats = {
            'month_total_pilot_share': commission_amounts['pilot_amount'],  # 简化，实际应该按月累计
            'month_total_company_share': commission_amounts['company_amount'],
            'month_total_profit': daily_profit
        }

        # 月累计返点（简化版）
        month_rebate_amount = rebate_info['rebate_amount']

        detail = {
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

    # 排序：按流水金额降序，其次按开始时间降序
    details.sort(key=lambda x: (-x['revenue'], -record.start_time.timestamp() if hasattr(record, 'start_time') else 0))

    return details


@report_bp.route('/daily')
@roles_accepted('gicho', 'kancho')
def daily_report():
    """开播日报页面"""
    # 获取日期参数，默认为今天
    date_str = request.args.get('date')
    if not date_str:
        # 默认使用今天的本地日期
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_date = today_local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        report_date = get_local_date_from_string(date_str)
        if not report_date:
            logger.error('无效的日期参数：%s', date_str)
            return '无效的日期格式', 400
        report_date = report_date.replace(hour=0, minute=0, second=0, microsecond=0)

    logger.info('生成开播日报，报表日期：%s', report_date.strftime('%Y-%m-%d'))

    # 计算月度数据（截至报表日）
    month_summary = _calculate_month_summary(report_date)

    # 计算日报汇总（仅报表日）
    day_summary = _calculate_day_summary(report_date)

    # 计算日报明细
    details = _calculate_daily_details(report_date)

    # 分页信息
    pagination = {
        'date': report_date.strftime('%Y-%m-%d'),
        'prev_date': (report_date - timedelta(days=1)).strftime('%Y-%m-%d'),
        'next_date': (report_date + timedelta(days=1)).strftime('%Y-%m-%d')
    }

    return render_template('reports/daily.html', month_summary=month_summary, day_summary=day_summary, details=details, pagination=pagination)


@report_bp.route('/daily/export.csv')
@roles_accepted('gicho', 'kancho')
def export_daily_csv():
    """导出开播日报CSV"""
    # 获取日期参数，默认为今天
    date_str = request.args.get('date')
    if not date_str:
        # 默认使用今天的本地日期
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_date = today_local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        report_date = get_local_date_from_string(date_str)
        if not report_date:
            logger.error('无效的日期参数：%s', date_str)
            return '无效的日期格式', 400
        report_date = report_date.replace(hour=0, minute=0, second=0, microsecond=0)

    logger.info('导出开播日报CSV，报表日期：%s', report_date.strftime('%Y-%m-%d'))

    # 计算日报明细
    details = _calculate_daily_details(report_date)

    # 创建CSV内容
    output = io.StringIO()
    writer = csv.writer(output)

    # 写入BOM（UTF-8 with BOM）
    output.write('\ufeff')

    # 写入表头
    headers = [
        '主播', '性别年龄', '直属运营', '主播分类', '开播地点', '播时(小时)', '流水(元)', '当前分成比例(%)', '主播分成(元)', '公司分成(元)', '返点比例(%)', '产生返点(元)', '底薪(元)', '当日毛利(元)', '3日平均流水(元)',
        '月累计天数', '月日均播时(小时)', '月累计流水(元)', '月累计主播分成(元)', '月累计公司分成(元)', '月累计返点(元)', '月累计底薪(元)', '月累计毛利(元)'
    ]
    writer.writerow(headers)

    # 写入数据
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

    # 生成响应
    csv_content = output.getvalue()
    output.close()

    # 创建响应，设置正确的Content-Type和文件名
    filename = f"开播日报_{report_date.strftime('%Y%m%d')}.csv"
    encoded_filename = quote(filename.encode('utf-8'))

    response = Response(csv_content, mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename*=UTF-8\'\'{encoded_filename}'})

    return response


# ==================== 征召日报相关函数 ====================
def _calculate_recruit_statistics(report_date):
    """计算招募统计数据
    
    Args:
        report_date: 报表日期（本地时间）
        
    Returns:
        dict: 包含报表日、近7日、近14日的统计数据，以及百分比数据
    """
    from utils.recruit_stats import calculate_recruit_daily_stats
    return calculate_recruit_daily_stats(report_date)


# _calculate_period_stats 函数已移至 utils/recruit_stats.py


@report_bp.route('/recruits/daily-report')
@roles_accepted('gicho', 'kancho')
def recruit_daily_report():
    """主播招募日报页面"""
    # 获取日期参数，默认为今天
    date_str = request.args.get('date')
    if not date_str:
        # 默认使用今天的本地日期
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_date = today_local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        report_date = get_local_date_from_string(date_str)
        if not report_date:
            logger.error('无效的日期参数：%s', date_str)
            return '无效的日期格式', 400
        report_date = report_date.replace(hour=0, minute=0, second=0, microsecond=0)

    logger.info('生成征召日报，报表日期：%s', report_date.strftime('%Y-%m-%d'))

    # 计算征召统计数据
    statistics = _calculate_recruit_statistics(report_date)

    # 分页信息
    pagination = {
        'date': report_date.strftime('%Y-%m-%d'),
        'prev_date': (report_date - timedelta(days=1)).strftime('%Y-%m-%d'),
        'next_date': (report_date + timedelta(days=1)).strftime('%Y-%m-%d')
    }

    return render_template('recruit_reports/daily.html', statistics=statistics, pagination=pagination)
