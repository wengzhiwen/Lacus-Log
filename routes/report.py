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
from utils.commission_helper import (calculate_commission_amounts, get_pilot_commission_rate_for_date)
from utils.logging_setup import get_logger
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)

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


def calculate_pilot_rebate(pilot, report_date):
    """计算机师返点金额
    
    基于月度任务完成情况计算返点，任务分为5个阶段：
    阶段一：≥12天，≥42小时，≥1000元，返点5%
    阶段二：≥18天，≥100小时，≥5000元，返点7%
    阶段三：≥18天，≥100小时，≥10000元，返点11%
    阶段四：≥22天，≥130小时，≥30000元，返点14%
    阶段五：≥22天，≥130小时，≥80000元，返点18%
    
    注意：流水条件为"达到"而非"区间"，主播可能同时符合多个阶段，取最高档次
    
    Args:
        pilot: 机师对象
        report_date: 报表日期（本地时间）
        
    Returns:
        dict: 包含返点金额、返点比例、任务完成情况等详细信息
    """
    logger.debug(f"开始计算机师 {pilot.nickname} 的返点，报表日期: {report_date}")

    # 计算月范围：当月1号00:00 至 报表日23:59:59
    month_start = report_date.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    month_end = report_date.replace(hour=23, minute=59, second=59, microsecond=999999)

    logger.debug(f"返点计算范围: {month_start} 至 {month_end}")

    # 获取本月作战记录
    month_records = get_battle_records_for_date_range(month_start, month_end + timedelta(microseconds=1))
    pilot_month_records = month_records.filter(pilot=pilot)

    logger.debug(f"机师 {pilot.nickname} 本月作战记录数量: {pilot_month_records.count()}")

    # 计算各项指标
    valid_days = set()  # 有效天数（单次播时≥60分钟的自然日）
    total_duration = 0  # 总播时（小时）
    total_revenue = Decimal('0')  # 总流水（元）

    for record in pilot_month_records:
        # 按开始时间换算到本地日归属
        local_start = utc_to_local(record.start_time)
        record_date = local_start.date()

        # 累计播时
        if record.duration_hours:
            total_duration += record.duration_hours

            # 判断是否为有效天（单次播时≥60分钟）
            if record.duration_hours >= 1.0:  # 60分钟 = 1小时
                valid_days.add(record_date)
                logger.debug(f"有效天记录: {record_date}, 播时: {record.duration_hours}小时")

        # 累计流水
        total_revenue += record.revenue_amount

        logger.debug(f"作战记录: {record_date}, 播时: {record.duration_hours}小时, 流水: {record.revenue_amount}元")

    valid_days_count = len(valid_days)

    logger.debug(f"机师 {pilot.nickname} 返点计算指标:")
    logger.debug(f"  - 直播有效天数: {valid_days_count}天")
    logger.debug(f"  - 直播有效时长: {total_duration:.1f}小时")
    logger.debug(f"  - 视频直播流水: {total_revenue:.2f}元")

    # 定义返点阶段条件（流水条件为"达到"而非"区间"）
    rebate_stages = [{
        'stage': 1,
        'min_days': 12,
        'min_hours': 42,
        'min_revenue': Decimal('1000'),
        'rate': 0.05,
        'rate_percent': '5%'
    }, {
        'stage': 2,
        'min_days': 18,
        'min_hours': 100,
        'min_revenue': Decimal('5000'),
        'rate': 0.07,
        'rate_percent': '7%'
    }, {
        'stage': 3,
        'min_days': 18,
        'min_hours': 100,
        'min_revenue': Decimal('10000'),
        'rate': 0.11,
        'rate_percent': '11%'
    }, {
        'stage': 4,
        'min_days': 22,
        'min_hours': 130,
        'min_revenue': Decimal('30000'),
        'rate': 0.14,
        'rate_percent': '14%'
    }, {
        'stage': 5,
        'min_days': 22,
        'min_hours': 130,
        'min_revenue': Decimal('80000'),
        'rate': 0.18,
        'rate_percent': '18%'
    }]

    # 检查每个阶段的条件
    qualified_stages = []
    for stage in rebate_stages:
        days_ok = valid_days_count >= stage['min_days']
        hours_ok = total_duration >= stage['min_hours']
        revenue_ok = total_revenue >= stage['min_revenue']

        stage_qualified = days_ok and hours_ok and revenue_ok

        logger.debug(f"阶段{stage['stage']}检查: 天数{days_ok}({valid_days_count}>={stage['min_days']}), "
                     f"时长{hours_ok}({total_duration:.1f}>={stage['min_hours']}), "
                     f"流水{revenue_ok}({total_revenue:.2f}>={stage['min_revenue']}), "
                     f"符合条件: {stage_qualified}")

        if stage_qualified:
            qualified_stages.append(stage)

    # 取最高档次的返点
    if qualified_stages:
        # 按阶段号降序排列，取最高档
        qualified_stages.sort(key=lambda x: x['stage'], reverse=True)
        best_stage = qualified_stages[0]

        rebate_amount = total_revenue * Decimal(str(best_stage['rate']))

        logger.debug(f"机师 {pilot.nickname} 返点结果:")
        logger.debug(f"  - 符合条件阶段: {[s['stage'] for s in qualified_stages]}")
        logger.debug(f"  - 选择阶段: {best_stage['stage']} ({best_stage['rate_percent']})")
        logger.debug(f"  - 返点金额: {total_revenue:.2f} × {best_stage['rate']} = {rebate_amount:.2f}元")

        return {
            'rebate_amount': rebate_amount,
            'rebate_rate': best_stage['rate'],
            'rebate_stage': best_stage['stage'],
            'valid_days_count': valid_days_count,
            'total_duration': total_duration,
            'total_revenue': total_revenue,
            'qualified_stages': qualified_stages
        }
    logger.debug(f"机师 {pilot.nickname} 未达到任何返点阶段条件")
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
    month_total_rebate = Decimal('0')  # 累计返点
    month_total_pilot_share = Decimal('0')  # 累计机师分成
    month_total_company_share = Decimal('0')  # 累计公司分成

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

        # 计算分成金额
        record_date = utc_to_local(record.start_time).date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(record.pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)

        month_total_pilot_share += commission_amounts['pilot_amount']
        month_total_company_share += commission_amounts['company_amount']

        logger.debug(f"月度记录分成计算: 机师={record.pilot.nickname}, 日期={record_date}, "
                     f"流水={record.revenue_amount}元, 分成比例={commission_rate}%, "
                     f"机师分成={commission_amounts['pilot_amount']:.2f}元, "
                     f"公司分成={commission_amounts['company_amount']:.2f}元")

    # 计算月度有效机师（播时≥6小时）
    for pilot_id, duration in pilot_month_duration.items():
        if duration >= 6:
            month_effective_pilots.add(pilot_id)

    # 计算月度累计返点
    logger.info(f"开始计算月度累计返点，涉及机师数量: {len(month_pilots)}")
    unique_month_pilots = list(set(record.pilot for record in month_records))
    for pilot in unique_month_pilots:
        rebate_info = calculate_pilot_rebate(pilot, report_date)
        month_total_rebate += rebate_info['rebate_amount']
        logger.debug(f"机师 {pilot.nickname} 返点: {rebate_info['rebate_amount']:.2f}元")

    logger.info(f"月度累计返点总计: {month_total_rebate:.2f}元")

    # 计算日报汇总数据
    day_pilots = set()
    day_effective_pilots = set()
    day_total_revenue = Decimal('0')
    day_total_base_salary = Decimal('0')
    day_total_pilot_share = Decimal('0')  # 日报机师分成
    day_total_company_share = Decimal('0')  # 日报公司分成

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

        # 计算分成金额
        record_date = utc_to_local(record.start_time).date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(record.pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)

        day_total_pilot_share += commission_amounts['pilot_amount']
        day_total_company_share += commission_amounts['company_amount']

        logger.debug(f"日报记录分成计算: 机师={record.pilot.nickname}, 日期={record_date}, "
                     f"流水={record.revenue_amount}元, 分成比例={commission_rate}%, "
                     f"机师分成={commission_amounts['pilot_amount']:.2f}元, "
                     f"公司分成={commission_amounts['company_amount']:.2f}元")

    # 计算日报有效机师（播时≥6小时）
    for pilot_id, duration in pilot_day_duration.items():
        if duration >= 6:
            day_effective_pilots.add(pilot_id)

    # 构建明细数据 - 使用优化版本批量计算
    day_records_ordered = day_records.order_by('-revenue_amount', '-start_time')
    unique_pilots = list(set(record.pilot for record in day_records_ordered))

    # 批量计算所有机师的统计数据
    from utils.report_optimizer import batch_calculate_pilot_stats
    pilot_stats_cache = batch_calculate_pilot_stats(unique_pilots, report_date)

    details = []
    for record in day_records_ordered:
        pilot = record.pilot
        pilot_id = str(pilot.id)

        # 从缓存获取统计数据
        pilot_stats = pilot_stats_cache.get(pilot_id, {})
        three_day_avg = pilot_stats.get('three_day_avg_revenue')
        monthly_stats = pilot_stats.get('monthly_stats', {
            'month_days_count': 0,
            'month_avg_duration': 0,
            'month_total_revenue': 0,
            'month_total_base_salary': 0
        })
        monthly_commission_stats = pilot_stats.get('monthly_commission_stats', {
            'month_total_pilot_share': 0,
            'month_total_company_share': 0,
            'month_total_profit': 0
        })

        # 计算返点信息
        rebate_info = calculate_pilot_rebate(pilot, report_date)

        # 计算分成信息
        record_date = utc_to_local(record.start_time).date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)

        # 计算当日毛利
        daily_profit = commission_amounts['company_amount'] + (record.revenue_amount * Decimal(str(rebate_info['rebate_rate']))) - record.base_salary

        logger.debug(f"明细记录计算: 机师={pilot.nickname}, 日期={record_date}, "
                     f"流水={record.revenue_amount}元, 分成比例={commission_rate}%, "
                     f"机师分成={commission_amounts['pilot_amount']:.2f}元, "
                     f"公司分成={commission_amounts['company_amount']:.2f}元, "
                     f"返点比例={rebate_info['rebate_rate']:.2%}, "
                     f"产生返点={record.revenue_amount * Decimal(str(rebate_info['rebate_rate'])):.2f}元, "
                     f"底薪={record.base_salary}元, "
                     f"当日毛利={daily_profit:.2f}元")

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
            'commission_rate': commission_rate,
            'pilot_share': commission_amounts['pilot_amount'],
            'company_share': commission_amounts['company_amount'],
            'rebate_rate': rebate_info['rebate_rate'],
            'rebate_amount': record.revenue_amount * Decimal(str(rebate_info['rebate_rate'])),
            'base_salary': record.base_salary,
            'daily_profit': daily_profit,
            'three_day_avg_revenue': three_day_avg,
            'monthly_stats': monthly_stats,
            'month_rebate_amount': rebate_info['rebate_amount'],
            'monthly_commission_stats': monthly_commission_stats,
        })

    # 计算运营利润估算
    operating_profit = month_total_company_share + month_total_rebate - month_total_base_salary

    logger.info("月度汇总数据:")
    logger.info(f"  - 总机师数量: {len(month_pilots)}")
    logger.info(f"  - 有效机师数量: {len(month_effective_pilots)}")
    logger.info(f"  - 累计流水: {month_total_revenue:.2f}元")
    logger.info(f"  - 累计底薪支出: {month_total_base_salary:.2f}元")
    logger.info(f"  - 累计返点: {month_total_rebate:.2f}元")
    logger.info(f"  - 累计机师分成: {month_total_pilot_share:.2f}元")
    logger.info(f"  - 累计公司分成: {month_total_company_share:.2f}元")
    logger.info(f"  - 运营利润估算: {operating_profit:.2f}元")

    logger.info("日报汇总数据:")
    logger.info(f"  - 总机师数量: {len(day_pilots)}")
    logger.info(f"  - 有效机师数量: {len(day_effective_pilots)}")
    logger.info(f"  - 累计流水: {day_total_revenue:.2f}元")
    logger.info(f"  - 累计底薪支出: {day_total_base_salary:.2f}元")
    logger.info(f"  - 累计机师分成: {day_total_pilot_share:.2f}元")
    logger.info(f"  - 累计公司分成: {day_total_company_share:.2f}元")

    # 构建响应数据
    month_summary = {
        'pilot_count': len(month_pilots),
        'effective_pilot_count': len(month_effective_pilots),
        'revenue_sum': month_total_revenue,
        'basepay_sum': month_total_base_salary,
        'rebate_sum': month_total_rebate,
        'pilot_share_sum': month_total_pilot_share,
        'company_share_sum': month_total_company_share,
        'operating_profit': operating_profit
    }

    day_summary = {
        'pilot_count': len(day_pilots),
        'effective_pilot_count': len(day_effective_pilots),
        'revenue_sum': day_total_revenue,
        'basepay_sum': day_total_base_salary,
        'pilot_share_sum': day_total_pilot_share,
        'company_share_sum': day_total_company_share
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
    headers = [
        '机师', '性别年龄', '所属', '阶级', '作战区域', '播时', '流水', '当前分成比例', '机师分成', '公司分成', '返点比例', '产生返点', '底薪', '当日毛利', '3日平均流水', '月累计天数', '月日均播时', '月累计流水', '月累计机师分成',
        '月累计公司分成', '月累计返点', '月累计底薪', '月累计毛利'
    ]
    writer.writerow(headers)

    # 写入数据行 - 使用优化版本批量计算
    day_records_ordered = day_records.order_by('-revenue_amount', '-start_time')
    unique_pilots = list(set(record.pilot for record in day_records_ordered))

    # 批量计算所有机师的统计数据
    from utils.report_optimizer import batch_calculate_pilot_stats
    pilot_stats_cache = batch_calculate_pilot_stats(unique_pilots, report_date)

    for record in day_records_ordered:
        pilot = record.pilot
        pilot_id = str(pilot.id)

        # 从缓存获取统计数据
        pilot_stats = pilot_stats_cache.get(pilot_id, {})
        three_day_avg = pilot_stats.get('three_day_avg_revenue')
        monthly_stats = pilot_stats.get('monthly_stats', {
            'month_days_count': 0,
            'month_avg_duration': 0,
            'month_total_revenue': 0,
            'month_total_base_salary': 0
        })
        monthly_commission_stats = pilot_stats.get('monthly_commission_stats', {
            'month_total_pilot_share': 0,
            'month_total_company_share': 0,
            'month_total_profit': 0
        })

        # 计算返点信息
        rebate_info = calculate_pilot_rebate(pilot, report_date)

        # 计算分成信息
        record_date = utc_to_local(record.start_time).date()
        commission_rate, _, _ = get_pilot_commission_rate_for_date(pilot.id, record_date)
        commission_amounts = calculate_commission_amounts(record.revenue_amount, commission_rate)

        # 计算当日毛利
        daily_profit = commission_amounts['company_amount'] + (record.revenue_amount * Decimal(str(rebate_info['rebate_rate']))) - record.base_salary

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
        revenue_str = f"{record.revenue_amount:,.2f}"
        commission_rate_str = f"{commission_rate:.0f}%"
        pilot_share_str = f"{commission_amounts['pilot_amount']:,.2f}"
        company_share_str = f"{commission_amounts['company_amount']:,.2f}"
        rebate_rate_str = f"{rebate_info['rebate_rate']:.0%}"
        rebate_amount_str = f"{record.revenue_amount * Decimal(str(rebate_info['rebate_rate'])):,.2f}"
        base_salary_str = f"{record.base_salary:,.2f}"
        daily_profit_str = f"{daily_profit:,.2f}"
        three_day_avg_str = f"{three_day_avg:,.2f}" if three_day_avg else ""
        month_days_str = str(monthly_stats['month_days_count'])
        month_avg_duration_str = f"{monthly_stats['month_avg_duration']:.1f}"
        month_revenue_str = f"{monthly_stats['month_total_revenue']:,.2f}"
        month_pilot_share_str = f"{monthly_commission_stats['month_total_pilot_share']:,.2f}"
        month_company_share_str = f"{monthly_commission_stats['month_total_company_share']:,.2f}"
        month_rebate_str = f"{rebate_info['rebate_amount']:,.2f}"
        month_base_salary_str = f"{monthly_stats['month_total_base_salary']:,.2f}"
        month_profit_str = f"{monthly_commission_stats['month_total_profit']:,.2f}"

        row = [
            pilot_display, gender_age, owner_display, rank_display, battle_area, duration_str, revenue_str, commission_rate_str, pilot_share_str,
            company_share_str, rebate_rate_str, rebate_amount_str, base_salary_str, daily_profit_str, three_day_avg_str, month_days_str, month_avg_duration_str,
            month_revenue_str, month_pilot_share_str, month_company_share_str, month_rebate_str, month_base_salary_str, month_profit_str
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
