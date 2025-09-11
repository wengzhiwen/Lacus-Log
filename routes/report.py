"""作战日报路由

实现作战日报的日视图和CSV导出功能。
注意：mongoengine 的动态属性在pylint中会触发 no-member 误报，这里统一抑制。
"""
# pylint: disable=no-member
import csv
import io
from datetime import datetime, timedelta
from decimal import Decimal
from urllib.parse import quote

from flask import Blueprint, Response, render_template, request
from flask_security import current_user, roles_accepted

from models.battle_record import BattleRecord
from models.pilot import Pilot
from utils.logging_setup import get_logger
from utils.timezone_helper import (get_current_utc_time, local_to_utc,
                                   utc_to_local)

# 创建日志器（按模块分文件）
logger = get_logger('report')

report_bp = Blueprint('report', __name__)


def get_local_date_from_string(date_str):
    """将日期字符串解析为本地日期对象
    
    Args:
        date_str: 日期字符串，格式为YYYY-MM-DD
        
    Returns:
        datetime: 本地日期对象（时间设为00:00:00）
    """
    if not date_str:
        return None
    try:
        return datetime.strptime(date_str, '%Y-%m-%d')
    except ValueError:
        return None


def get_battle_records_for_date_range(start_local_date, end_local_date):
    """获取指定本地日期范围内的作战记录
    
    Args:
        start_local_date: 开始日期（本地时间）
        end_local_date: 结束日期（本地时间）
        
    Returns:
        QuerySet: 作战记录查询集
    """
    # 转换为UTC时间范围
    start_utc = local_to_utc(start_local_date)
    end_utc = local_to_utc(end_local_date)

    # 查询作战记录（按开始时间归属日期）
    return BattleRecord.objects.filter(start_time__gte=start_utc, start_time__lt=end_utc)


def calculate_pilot_three_day_avg_revenue(pilot, report_date):
    """计算机师3日平均流水
    
    该机师最近3个"有作战记录的自然日"的总流水/3；
    若最近7日内开播不足3天则为空
    
    Args:
        pilot: 机师对象
        report_date: 报表日期（本地时间）
        
    Returns:
        Decimal: 3日平均流水，若不足3天则返回None
    """
    # 向前滚动7个自然日
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

    # 若在7天内未能凑齐3天，返回None
    if len(days_with_records) < 3:
        return None

    # 取最近3天的平均值
    total_revenue = sum(days_with_records[:3])
    return total_revenue / 3


def calculate_pilot_monthly_stats(pilot, report_date):
    """计算机师月度统计数据
    
    Args:
        pilot: 机师对象
        report_date: 报表日期（本地时间）
        
    Returns:
        dict: 包含月累计天数、月日均播时、月累计流水、月累计底薪
    """
    # 计算月范围：当月1号00:00 至 报表日23:59:59
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    # 获取本月作战记录
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1))
    pilot_month_records = month_records.filter(pilot=pilot)

    # 月累计天数：有作战记录的去重自然日
    record_dates = set()
    total_duration = 0
    total_revenue = Decimal('0')
    total_base_salary = Decimal('0')

    for record in pilot_month_records:
        # 按开始时间换算到本地日归属
        local_start = utc_to_local(record.start_time)
        record_date = local_start.date()
        record_dates.add(record_date)

        # 累计播时
        if record.duration_hours:
            total_duration += record.duration_hours

        # 累计流水和底薪
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


@report_bp.route('/daily')
@roles_accepted('gicho', 'kancho')
def daily_report():
    """作战日报页面"""
    logger.info(f"用户 {current_user.username} 访问作战日报")

    # 获取报表日期（默认今天）
    date_str = request.args.get('date')
    if date_str:
        report_date = get_local_date_from_string(date_str)
        if not report_date:
            # 日期格式错误，使用今天
            report_date = utc_to_local(get_current_utc_time()).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        # 默认今天
        report_date = utc_to_local(get_current_utc_time()).replace(hour=0, minute=0, second=0, microsecond=0)

    # 计算月度数据范围（当月1号至报表日）
    month_start = report_date.replace(day=1)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    # 计算日报数据范围（仅报表日）
    day_start = report_date
    day_end = day_start + timedelta(days=1)

    # 获取月度作战记录
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1))

    # 获取日报作战记录
    day_records = get_battle_records_for_date_range(day_start, day_end)

    # 计算月度汇总数据
    month_pilots = set()
    month_effective_pilots = set()
    month_total_revenue = Decimal('0')
    month_total_base_salary = Decimal('0')

    # 按机师聚合月度数据
    pilot_month_duration = {}
    for record in month_records:
        pilot_id = str(record.pilot.id)
        month_pilots.add(pilot_id)
        month_total_revenue += record.revenue_amount
        month_total_base_salary += record.base_salary

        # 累计播时
        if pilot_id not in pilot_month_duration:
            pilot_month_duration[pilot_id] = 0
        if record.duration_hours:
            pilot_month_duration[pilot_id] += record.duration_hours

    # 计算月度有效机师（播时≥6小时）
    for pilot_id, duration in pilot_month_duration.items():
        if duration >= 6:
            month_effective_pilots.add(pilot_id)

    # 计算日报汇总数据
    day_pilots = set()
    day_effective_pilots = set()
    day_total_revenue = Decimal('0')
    day_total_base_salary = Decimal('0')

    # 按机师聚合日报数据
    pilot_day_duration = {}
    for record in day_records:
        pilot_id = str(record.pilot.id)
        day_pilots.add(pilot_id)
        day_total_revenue += record.revenue_amount
        day_total_base_salary += record.base_salary

        # 累计播时
        if pilot_id not in pilot_day_duration:
            pilot_day_duration[pilot_id] = 0
        if record.duration_hours:
            pilot_day_duration[pilot_id] += record.duration_hours

    # 计算日报有效机师（播时≥6小时）
    for pilot_id, duration in pilot_day_duration.items():
        if duration >= 6:
            day_effective_pilots.add(pilot_id)

    # 构建明细数据
    details = []
    for record in day_records.order_by('-revenue_amount', '-start_time'):
        pilot = record.pilot

        # 计算3日平均流水
        three_day_avg = calculate_pilot_three_day_avg_revenue(pilot, report_date)

        # 计算月度统计
        monthly_stats = calculate_pilot_monthly_stats(pilot, report_date)

        # 构建所属和阶级显示（优先快照，无快照显示当前）
        owner_display = ''
        if record.owner_snapshot:
            owner_display = record.owner_snapshot.nickname or record.owner_snapshot.username
        elif pilot.owner:
            owner_display = pilot.owner.nickname or pilot.owner.username

        rank_display = pilot.rank.value if pilot.rank else ''

        # 构建作战区域显示（不论线上/线下，始终显示快照X/Y/Z）
        battle_area = f"{record.work_mode.value}@{record.x_coord}-{record.y_coord}-{record.z_coord}"

        # 性别图标
        gender_icon = "♂" if pilot.gender.value == 0 else "♀" if pilot.gender.value == 1 else "?"

        details.append({
            'pilot_display': f"{pilot.nickname}（{pilot.real_name or ''}）" if pilot.real_name else pilot.nickname,
            'gender_age': f"{pilot.age}-{gender_icon}" if pilot.age else f"-{gender_icon}",
            'owner': owner_display,
            'rank': rank_display,
            'battle_area': battle_area,
            'duration': record.duration_hours,
            'revenue': record.revenue_amount,
            'three_day_avg_revenue': three_day_avg,
            'monthly_stats': monthly_stats,
        })

    # 构建响应数据
    month_summary = {
        'pilot_count': len(month_pilots),
        'effective_pilot_count': len(month_effective_pilots),
        'revenue_sum': month_total_revenue,
        'basepay_sum': month_total_base_salary
    }

    day_summary = {
        'pilot_count': len(day_pilots),
        'effective_pilot_count': len(day_effective_pilots),
        'revenue_sum': day_total_revenue,
        'basepay_sum': day_total_base_salary
    }

    # 计算分页导航
    prev_date = report_date - timedelta(days=1)
    next_date = report_date + timedelta(days=1)

    pagination = {'date': report_date.strftime('%Y-%m-%d'), 'prev_date': prev_date.strftime('%Y-%m-%d'), 'next_date': next_date.strftime('%Y-%m-%d')}

    return render_template('reports/daily.html', month_summary=month_summary, day_summary=day_summary, details=details, pagination=pagination)


@report_bp.route('/daily/export.csv')
@roles_accepted('gicho', 'kancho')
def export_daily_csv():
    """导出作战日报CSV"""
    logger.info(f"用户 {current_user.username} 导出作战日报CSV")

    # 获取报表日期
    date_str = request.args.get('date')
    if date_str:
        report_date = get_local_date_from_string(date_str)
        if not report_date:
            report_date = utc_to_local(get_current_utc_time()).replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        report_date = utc_to_local(get_current_utc_time()).replace(hour=0, minute=0, second=0, microsecond=0)

    # 获取日报数据（复用上面的逻辑）
    day_start = report_date
    day_end = day_start + timedelta(days=1)
    day_records = get_battle_records_for_date_range(day_start, day_end)

    # 创建CSV输出
    output = io.StringIO()
    writer = csv.writer(output, delimiter=',', quotechar='"', quoting=csv.QUOTE_ALL, lineterminator='\r\n')

    # 写入BOM头（用于Excel正确识别UTF-8）
    output.write('\ufeff')

    # 写入表头
    headers = ['机师', '性别年龄', '所属', '阶级', '作战区域', '播时', '流水', '3日平均流水', '月累计天数', '月日均播时', '月累计流水', '月累计底薪']
    writer.writerow(headers)

    # 写入数据行
    for record in day_records.order_by('-revenue_amount', '-start_time'):
        pilot = record.pilot

        # 计算3日平均流水
        three_day_avg = calculate_pilot_three_day_avg_revenue(pilot, report_date)

        # 计算月度统计
        monthly_stats = calculate_pilot_monthly_stats(pilot, report_date)

        # 构建各字段值
        pilot_display = f"{pilot.nickname}（{pilot.real_name or ''}）" if pilot.real_name else pilot.nickname

        gender_icon = "♂" if pilot.gender.value == 0 else "♀" if pilot.gender.value == 1 else "?"
        gender_age = f"{pilot.age}-{gender_icon}" if pilot.age else f"-{gender_icon}"

        owner_display = ''
        if record.owner_snapshot:
            owner_display = record.owner_snapshot.nickname or record.owner_snapshot.username
        elif pilot.owner:
            owner_display = pilot.owner.nickname or pilot.owner.username

        rank_display = pilot.rank.value if pilot.rank else ''

        # 不论线上/线下，始终显示快照X/Y/Z
        battle_area = f"{record.work_mode.value}@{record.x_coord}-{record.y_coord}-{record.z_coord}"

        duration_str = f"{record.duration_hours:.1f}" if record.duration_hours else "0.0"
        revenue_str = f"{record.revenue_amount:.2f}"
        three_day_avg_str = f"{three_day_avg:.2f}" if three_day_avg else ""
        month_days_str = str(monthly_stats['month_days_count'])
        month_avg_duration_str = f"{monthly_stats['month_avg_duration']:.1f}"
        month_revenue_str = f"{monthly_stats['month_total_revenue']:.2f}"
        month_base_salary_str = f"{monthly_stats['month_total_base_salary']:.2f}"

        row = [
            pilot_display, gender_age, owner_display, rank_display, battle_area, duration_str, revenue_str, three_day_avg_str, month_days_str,
            month_avg_duration_str, month_revenue_str, month_base_salary_str
        ]
        writer.writerow(row)

    # 准备响应
    output.seek(0)
    response_data = output.getvalue()
    output.close()

    # 生成文件名（为避免开发服务器对Header使用latin-1编码导致报错，这里提供ASCII安全的filename，并通过RFC 5987提供filename*）
    filename_utf8 = f"作战日报_{report_date.strftime('%Y%m%d')}.csv"
    filename_ascii = f"daily_report_{report_date.strftime('%Y%m%d')}.csv"
    content_disposition = f"attachment; filename=\"{filename_ascii}\"; filename*=UTF-8''{quote(filename_utf8)}"

    response = Response(response_data, mimetype='text/csv', headers={'Content-Disposition': content_disposition, 'Content-Type': 'text/csv; charset=utf-8'})

    return response
