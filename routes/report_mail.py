"""
管理员专用 - 邮件报告模块（未开播提醒）

本模块提供基于按钮触发的离线报表，通过邮件发送结果。
"""
# pylint: disable=no-member,consider-using-f-string
from datetime import datetime, timedelta
from math import floor
from typing import Dict, List

from flask import (Blueprint, jsonify, redirect, render_template, request, url_for)
from flask_security import current_user, roles_required

from models.announcement import Announcement
from models.battle_record import BattleRecord, BattleRecordStatus, BaseSalaryApplication, BaseSalaryApplicationStatus
from models.user import User
from utils.job_token import JobPlan
from utils.logging_setup import get_logger
from utils.mail_utils import send_email_md
from utils.new_report_calculations import (calculate_daily_details, calculate_daily_summary)
from utils.new_report_fast_calculations import calculate_monthly_summary_fast
from utils.new_report_serializers import (serialize_daily_details, serialize_daily_summary, serialize_monthly_summary)
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)

logger = get_logger('report_mail')

report_mail_bp = Blueprint('report_mail', __name__)


def _build_recruit_daily_markdown(statistics: dict) -> str:
    """将招募日报统计数据渲染为Markdown表格。
    
    Args:
        statistics: 统计数据字典
        
    Returns:
        str: Markdown格式的表格内容
    """
    report_day = statistics['report_day']
    last_7_days = statistics['last_7_days']
    last_14_days = statistics['last_14_days']

    averages = statistics.get('averages', {})
    avg_7_days = averages.get('last_7_days', {})
    avg_14_days = averages.get('last_14_days', {})

    header = "| 统计范围 | 约面 | 到面 | 试播 | 新开播 |\n| --- | ---: | ---: | ---: | ---: |"

    lines = [header]

    report_line = (f"| 报表日 | {report_day['appointments']} | "
                   f"{report_day['interviews']} | "
                   f"{report_day['trials']} | "
                   f"{report_day['new_recruits']} |")
    lines.append(report_line)

    week_line = (f"| 近7日 | {last_7_days['appointments']} (日均{avg_7_days.get('appointments', 0)}) | "
                 f"{last_7_days['interviews']} (日均{avg_7_days.get('interviews', 0)}) | "
                 f"{last_7_days['trials']} (日均{avg_7_days.get('trials', 0)}) | "
                 f"{last_7_days['new_recruits']} (日均{avg_7_days.get('new_recruits', 0)}) |")
    lines.append(week_line)

    fortnight_line = (f"| 近14日 | {last_14_days['appointments']} (日均{avg_14_days.get('appointments', 0)}) | "
                      f"{last_14_days['interviews']} (日均{avg_14_days.get('interviews', 0)}) | "
                      f"{last_14_days['trials']} (日均{avg_14_days.get('trials', 0)}) | "
                      f"{last_14_days['new_recruits']} (日均{avg_14_days.get('new_recruits', 0)}) |")
    lines.append(fortnight_line)

    return "\n".join(lines)


def run_recruit_daily_report_job(report_date: str = None, triggered_by: str = 'scheduler') -> dict:
    """执行招募日报邮件发送任务。
    
    Args:
        report_date: 报表日期字符串（YYYY-MM-DD格式），默认为昨天
        triggered_by: 触发来源
        
    Returns:
        dict: {"sent": bool, "count": int}
    """
    logger.info('触发招募日报邮件发送，来源：%s，报表日期：%s', triggered_by or '未知', report_date or '昨天')

    if not report_date:
        now_utc = get_current_utc_time()
        yesterday_local = utc_to_local(now_utc) - timedelta(days=1)
        report_date = yesterday_local.strftime('%Y-%m-%d')

    try:
        report_date_obj = datetime.strptime(report_date, '%Y-%m-%d')
    except ValueError:
        logger.error('报表日期格式错误：%s', report_date)
        return {'sent': False, 'count': 0}

    statistics = _calculate_recruit_statistics(report_date_obj)

    md_content = _build_recruit_daily_markdown(statistics)

    full_content = f"""# 主播招募日报

**报表日期：** {report_date}


{md_content}


- **约面**：当天创建的招募数量
- **到面**：当天发生的面试决策数量（完成面试决策的数量，不论是决定预约试播，还是决定不招募都算）
- **试播**：当天发生的开播决策数量（完成开播决策的数量，不论是决定招募，还是决定不招募）
- **新开播**：当天在开播决策中决定招募的数量（不招募不算）

---
*本报表由 Lacus-Log 系统自动生成*
"""

    recipients = []
    recipients.extend(User.get_emails_by_role(role_name='gicho', only_active=True))  # 管理员
    recipients.extend(User.get_emails_by_role(role_name='kancho', only_active=True))  # 运营

    if not recipients:
        logger.error('收件人为空，未找到任何运营或管理员的邮箱')
        return {'sent': False, 'count': 0}

    recipients = list(set(recipients))

    subject = f"[Lacus-Log] 主播招募日报 - {report_date}"

    ok = send_email_md(recipients, subject, full_content)
    if ok:
        logger.info('招募日报邮件已发送，收件人：%s', ', '.join(recipients))
        return {'sent': True, 'count': len(recipients)}

    logger.error('招募日报邮件发送失败；主题：%s；收件人：%s', subject, ', '.join(recipients))
    return {'sent': False, 'count': len(recipients)}


def _calculate_recruit_statistics(report_date):
    """计算招募统计数据（复用招募日报的计算逻辑）
    
    Args:
        report_date: 报表日期（本地时间）
        
    Returns:
        dict: 包含报表日、近7日、近14日的统计数据
    """
    from utils.recruit_stats import calculate_recruit_daily_stats
    return calculate_recruit_daily_stats(report_date)


def _build_daily_report_markdown(day_summary, details):
    """将开播日报数据渲染为Markdown格式（仅日报）。
    
    Args:
        day_summary: 日报汇总数据
        details: 日报明细数据
        
    Returns:
        str: Markdown格式的邮件内容
    """
    day_table = """| 指标 | 数值 |
| --- | ---: |
| 总主播数量 | {pilot_count} |
| 有效主播数量 | {effective_pilot_count} |
| 累计流水 | ¥{revenue_sum:,.2f} |
| 累计底薪支出 | ¥{basepay_sum:,.2f} |
| 累计主播分成 | ¥{pilot_share_sum:,.2f} |
| 累计公司分成 | ¥{company_share_sum:,.2f} |""".format(**day_summary)

    if details:
        detail_table = """| 主播 | 性别年龄 | 直属运营 | 播时 | 流水 | 底薪 | 当日毛利 |
| --- | --- | --- | ---: | ---: | ---: | ---: |"""

        for detail in details:
            row = (f"| {detail['pilot_display']} | {detail['gender_age']} | {detail['owner']} | "
                   f"{detail['duration']:.1f}小时 | ¥{detail['revenue']:,.2f} | ¥{detail['base_salary']:,.2f} | "
                   f"¥{detail['daily_profit']:,.2f} |")
            detail_table += "\n" + row
    else:
        detail_table = "暂无开播记录"

    return f"""
{day_table}


{detail_table}

"""


def run_daily_report_job(report_date: str = None, triggered_by: str = 'scheduler') -> dict:
    """执行开播日报邮件发送任务。
    
    Args:
        report_date: 报表日期字符串（YYYY-MM-DD格式），默认为昨天
        triggered_by: 触发来源
        
    Returns:
        dict: {"sent": bool, "count": int}
    """
    logger.info('触发开播日报邮件发送，来源：%s，报表日期：%s', triggered_by or '未知', report_date or '昨天')

    if not report_date:
        now_utc = get_current_utc_time()
        yesterday_local = utc_to_local(now_utc) - timedelta(days=1)
        report_date = yesterday_local.strftime('%Y-%m-%d')

    try:
        report_date_obj = datetime.strptime(report_date, '%Y-%m-%d')
    except ValueError:
        logger.error('报表日期格式错误：%s', report_date)
        return {'sent': False, 'count': 0}

    day_summary_raw = calculate_daily_summary(report_date_obj)
    details_raw = calculate_daily_details(report_date_obj)

    day_summary = serialize_daily_summary(day_summary_raw)
    details = serialize_daily_details(details_raw)

    md_content = _build_daily_report_markdown(day_summary, details)

    full_content = f"""# 开播日报

**报表日期：** {report_date}

{md_content}

---
*本报表由 Lacus-Log 系统自动生成*
"""

    recipients = []
    recipients.extend(User.get_emails_by_role(role_name='gicho', only_active=True))  # 管理员
    recipients.extend(User.get_emails_by_role(role_name='kancho', only_active=True))  # 运营

    if not recipients:
        logger.error('收件人为空，未找到任何运营或管理员的邮箱')
        return {'sent': False, 'count': 0}

    recipients = list(set(recipients))

    subject = f"[Lacus-Log] 开播日报 - {report_date}"

    ok = send_email_md(recipients, subject, full_content)
    if ok:
        logger.info('开播日报邮件已发送，收件人：%s', ', '.join(recipients))
        return {'sent': True, 'count': len(recipients)}

    logger.error('开播日报邮件发送失败；主题：%s；收件人：%s', subject, ', '.join(recipients))
    return {'sent': False, 'count': len(recipients)}


def _build_monthly_mail_markdown(month_summary, details):
    """将开播月报数据渲染为Markdown格式（用于邮件）。

    采用精简列，便于邮件阅读。
    """
    month_table = """| 指标 | 数值 |
| --- | ---: |
| 总主播数量 | {pilot_count} |
| 累计流水 | ¥{revenue_sum:,.2f} |
| 累计底薪支出 | ¥{basepay_sum:,.2f} |
| 累计主播分成 | ¥{pilot_share_sum:,.2f} |
| 累计公司分成 | ¥{company_share_sum:,.2f} |
| 运营利润估算 | ¥{operating_profit:,.2f} |""".format(**month_summary)

    if details:
        # 精简明细列：主播 | 直属运营 | 记录数 | 月均播时 | 月累计流水 | 月累计公司分成 | 月累计返点 | 月累计底薪 | 月累计毛利
        detail_table = """| 主播 | 直属运营 | 记录数 | 月均播时 | 月累计流水 | 月累计公司分成 | 月累计返点 | 月累计底薪 | 月累计毛利 |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |"""

        for d in details:
            row = (f"| {d['pilot_display']} | {d['owner']} | {d['records_count']} | {d['avg_duration']:.1f}小时 | "
                   f"¥{d['total_revenue']:,.2f} | ¥{d['total_company_share']:,.2f} | "
                   f"¥{d['rebate_amount']:,.2f} | ¥{d['total_base_salary']:,.2f} | "
                   f"¥{d['total_profit']:,.2f} |")
            detail_table += "\n" + row
    else:
        detail_table = "暂无月度开播记录"

    return f"""
{month_table}


{detail_table}

"""


def run_monthly_mail_report_job(report_month: str = None, triggered_by: str = 'scheduler') -> dict:
    """执行开播邮件月报发送任务。

    - 默认发送“前一自然日所在月”的月报
    - 邮件内容参考开播月报并做邮件阅读优化
    """
    logger.info('触发开播邮件月报发送，来源：%s，报表月份：%s', triggered_by or '未知', report_month or '昨天所在月')

    if not report_month:
        now_utc = get_current_utc_time()
        yesterday_local = utc_to_local(now_utc) - timedelta(days=1)
        year = yesterday_local.year
        month = yesterday_local.month
        month_str = yesterday_local.strftime('%Y-%m')
    else:
        try:
            dt = datetime.strptime(report_month, '%Y-%m')
            year, month = dt.year, dt.month
            month_str = report_month
        except ValueError:
            logger.error('月份参数格式错误：%s', report_month)
            return {'sent': False, 'count': 0}

    month_summary_raw = calculate_monthly_summary_fast(year, month)
    # 快速月报没有明细函数，所以这里需要重新设计或者移除明细功能
    # 由于用户要求只保留快速月报，我们暂时使用月度汇总数据
    details_raw = []

    month_summary = serialize_monthly_summary(month_summary_raw)
    details = details_raw  # 简化处理，暂时不提供明细

    md_content = _build_monthly_mail_markdown(month_summary, details)

    full_content = f"""# 开播月报

**报表月份：** {month_str}

{md_content}

---
*本报表由 Lacus-Log 系统自动生成*
"""

    recipients = []
    recipients.extend(User.get_emails_by_role(role_name='gicho', only_active=True))  # 管理员
    recipients.extend(User.get_emails_by_role(role_name='kancho', only_active=True))  # 运营

    if not recipients:
        logger.error('收件人为空，未找到任何运营或管理员的邮箱')
        return {'sent': False, 'count': 0}

    recipients = list(set(recipients))

    subject = f"[Lacus-Log] 开播月报 - {month_str}"

    ok = send_email_md(recipients, subject, full_content)
    if ok:
        logger.info('开播邮件月报已发送，收件人：%s', ', '.join(recipients))
        return {'sent': True, 'count': len(recipients)}

    logger.error('开播邮件月报发送失败；主题：%s；收件人：%s', subject, ', '.join(recipients))
    return {'sent': False, 'count': len(recipients)}


def _build_unstarted_markdown(items: List[dict]) -> str:
    if not items:
        return ''

    header = ("| 主播昵称 | 直属运营-主播分类 | 开播地点 | 计划开播时间（GMT+8） | 计划播时（小时） | 当前超时（小时） | 备注 |\n"
              "| --- | --- | --- | --- | ---: | ---: | --- |")

    lines = [header]
    for it in items:
        line = (f"| {it['pilot_name']} | {it['owner_rank']} | {it['region']} | "
                f"{it['start_local']} | {it['plan_duration_hours']} | {it['overdue_hours']} | {it.get('note','')} |")
        lines.append(line)
    return "\n".join(lines)


def _build_live_overtime_markdown(items: List[Dict[str, str]]) -> str:
    if not items:
        return ''

    header = ("| 主播昵称 | 真实姓名 | 直属运营-主播分类 | 开播地点 | 开播开始时间（GMT+8） | 当前持续时长（小时） | 备注 |\n"
              "| --- | --- | --- | --- | --- | ---: | --- |")

    lines = [header]
    for it in items:
        line = (f"| {it['pilot_name']} | {it['real_name']} | {it['owner_rank']} | "
                f"{it['location']} | {it['start_local']} | "
                f"{it['duration_hours']} | {it['note']} |")
        lines.append(line)

    return "\n".join(lines)


def _build_online_pilot_unstarted_markdown(items: List[dict], report_date: str, check_day: str) -> str:
    """将线上主播未开播提醒数据渲染为Markdown格式。

    Args:
        items: 线上主播未开播数据列表
        report_date: 报表日期
        check_day: 检查日期

    Returns:
        str: Markdown格式的邮件内容
    """
    if not items:
        return f'# 线上主播未开播提醒\n\n**报表日期：** {report_date}\n\n检查结果显示：所有线上主播在{check_day}均有正常开播记录，无遗漏情况。\n\n---\n*本报表由 Lacus-Log 系统自动生成*'

    header = ("| 主播昵称 | 真实姓名 | 直属运营-主播分类 | 最近开播日期 | 近3天线上次数 | 检查日 | 备注 |\n"
              "| --- | --- | --- | --- | ---: | --- | --- |")

    lines = [header]
    for it in items:
        line = (f"| {it['pilot_name']} | {it['real_name']} | {it['owner_rank']} | "
                f"{it['latest_date']} | {it['recent_online_count']} | {it['check_day']} | {it['note']} |")
        lines.append(line)

    table_content = "\n".join(lines)

    summary = f"""
**检查范围说明：**
- 检查窗口：{report_date}前4日至{report_date}前2日（3天内）
- 检查日：{report_date}前1日
- 筛选条件：在检查窗口内有过线上开播记录的主播
- 提醒条件：检查日无任何开播记录的主播

**统计结果：**
- 需要提醒的主播数量：{len(items)}人
"""

    return f"""
# 线上主播未开播提醒

**报表日期：** {report_date}

{summary}

{table_content}

---
*本报表由 Lacus-Log 系统自动生成*
"""


def _build_base_salary_reminder_markdown(items: List[dict]) -> str:
    """将底薪发放提醒数据渲染为Markdown格式。

    Args:
        items: 底薪发放提醒数据列表

    Returns:
        str: Markdown格式的邮件内容
    """
    if not items:
        return "# 底薪发放提醒\n\n当前没有需要处理的底薪申请。\n\n---\n*本报表由 Lacus-Log 系统自动生成*"

    header = ("| 主播昵称 | 真实姓名 | 直属运营-主播分类 | 开播日期 | 申请时间 | 超时小时 | 底薪金额 | 备注 |\n"
              "| --- | --- | --- | --- | --- | ---: | ---: | --- |")

    lines = [header]
    for it in items:
        line = (f"| {it['pilot_name']} | {it['real_name']} | {it['owner_rank']} | "
                f"{it['battle_date']} | {it['apply_time']} | {it['overdue_hours']} | "
                f"¥{it['base_salary']:,.2f} | {it['note']} |")
        lines.append(line)

    table_content = "\n".join(lines)

    summary = f"""
**提醒说明：**
- 筛选条件：状态为"未处理"且申请时间已超过12小时的底薪申请
- 提醒时间：每天18:00（GMT+8）
- 处理方式：请管理员及时在结算管理中审核相关申请

**统计结果：**
- 需要处理的申请数量：{len(items)}条
"""

    return f"""
# 底薪发放提醒

{summary}

{table_content}

---
*本报表由 Lacus-Log 系统自动生成*
"""


@report_mail_bp.route('/mail')
@roles_required('gicho')
def mail_reports_page():
    """展示邮件报告入口页面（仅管理员可见）。"""
    try:
        now_minute = get_current_utc_time().strftime('%Y%m%d%H%M')
        unstarted_plan = (JobPlan.objects(job_code='daily_unstarted_report', fire_minute__gte=now_minute).order_by('fire_minute').first()) or (JobPlan.objects(
            job_code='daily_unstarted_report').order_by('-fire_minute').first())
        unstarted_next_local = None
        if unstarted_plan:
            fire_dt_utc = datetime.strptime(unstarted_plan.fire_minute, '%Y%m%d%H%M')
            unstarted_next_local = utc_to_local(fire_dt_utc).strftime('%Y-%m-%d %H:%M')

        live_overtime_plan = (JobPlan.objects(job_code='daily_live_overtime_report', fire_minute__gte=now_minute).order_by('fire_minute').first()) or (
            JobPlan.objects(job_code='daily_live_overtime_report').order_by('-fire_minute').first())
        live_overtime_next_local = None
        if live_overtime_plan:
            fire_dt_utc = datetime.strptime(live_overtime_plan.fire_minute, '%Y%m%d%H%M')
            live_overtime_next_local = utc_to_local(fire_dt_utc).strftime('%Y-%m-%d %H:%M')

        online_pilot_unstarted_plan = (JobPlan.objects(job_code='daily_online_pilot_unstarted_report',
                                                       fire_minute__gte=now_minute).order_by('fire_minute').first()) or (JobPlan.objects(
                                                           job_code='daily_online_pilot_unstarted_report').order_by('-fire_minute').first())
        online_pilot_unstarted_next_local = None
        if online_pilot_unstarted_plan:
            fire_dt_utc = datetime.strptime(online_pilot_unstarted_plan.fire_minute, '%Y%m%d%H%M')
            online_pilot_unstarted_next_local = utc_to_local(fire_dt_utc).strftime('%Y-%m-%d %H:%M')

        base_salary_reminder_plan = (JobPlan.objects(job_code='daily_base_salary_reminder', fire_minute__gte=now_minute).order_by('fire_minute').first()) or (
            JobPlan.objects(job_code='daily_base_salary_reminder').order_by('-fire_minute').first())
        base_salary_reminder_next_local = None
        if base_salary_reminder_plan:
            fire_dt_utc = datetime.strptime(base_salary_reminder_plan.fire_minute, '%Y%m%d%H%M')
            base_salary_reminder_next_local = utc_to_local(fire_dt_utc).strftime('%Y-%m-%d %H:%M')

        recruit_plan = (JobPlan.objects(job_code='daily_recruit_daily_report', fire_minute__gte=now_minute).order_by('fire_minute').first()) or (
            JobPlan.objects(job_code='daily_recruit_daily_report').order_by('-fire_minute').first())
        recruit_next_local = None
        if recruit_plan:
            fire_dt_utc = datetime.strptime(recruit_plan.fire_minute, '%Y%m%d%H%M')
            recruit_next_local = utc_to_local(fire_dt_utc).strftime('%Y-%m-%d %H:%M')

        daily_plan = (JobPlan.objects(job_code='daily_report', fire_minute__gte=now_minute).order_by('fire_minute').first()) or (JobPlan.objects(
            job_code='daily_report').order_by('-fire_minute').first())
        daily_next_local = None
        if daily_plan:
            fire_dt_utc = datetime.strptime(daily_plan.fire_minute, '%Y%m%d%H%M')
            daily_next_local = utc_to_local(fire_dt_utc).strftime('%Y-%m-%d %H:%M')

        monthly_mail_plan = (JobPlan.objects(job_code='daily_monthly_mail_report', fire_minute__gte=now_minute).order_by('fire_minute').first()) or (
            JobPlan.objects(job_code='daily_monthly_mail_report').order_by('-fire_minute').first())
        monthly_mail_next_local = None
        if monthly_mail_plan:
            fire_dt_utc = datetime.strptime(monthly_mail_plan.fire_minute, '%Y%m%d%H%M')
            monthly_mail_next_local = utc_to_local(fire_dt_utc).strftime('%Y-%m-%d %H:%M')

    except Exception as exc:  # pylint: disable=broad-except
        logger.error('读取任务下一次触发时间失败：%s', exc)
        unstarted_next_local = None
        live_overtime_next_local = None
        online_pilot_unstarted_next_local = None
        base_salary_reminder_next_local = None
        recruit_next_local = None
        daily_next_local = None
        monthly_mail_next_local = None

    next_times = {
        'unstarted': unstarted_next_local,
        'live_overtime': live_overtime_next_local,
        'online_pilot_unstarted': online_pilot_unstarted_next_local,
        'base_salary_reminder': base_salary_reminder_next_local,
        'recruit_daily': recruit_next_local,
        'daily_report': daily_next_local,
        'monthly_mail_report': monthly_mail_next_local
    }
    return render_template('reports/mail_reports.html', next_times=next_times)


def run_live_overtime_report_job(triggered_by: str = 'scheduler') -> dict:
    """执行"未下播提醒"报表计算与邮件发送。"""
    logger.info('触发未下播提醒报表，来源：%s', triggered_by or '未知')

    now_utc = get_current_utc_time()
    threshold_utc = now_utc - timedelta(hours=8)

    live_records = BattleRecord.objects.filter(status=BattleRecordStatus.LIVE, start_time__lte=threshold_utc).order_by('-start_time')

    try:
        logger.debug('候选开播中记录数量（超过8小时）：%d', live_records.count())
    except Exception:  # pylint: disable=broad-except
        logger.debug('候选开播中记录数量（超过8小时）：统计失败')

    overtime_items: List[Dict[str, str]] = []

    for record in live_records:
        start_utc = record.start_time
        if start_utc is None:
            continue

        duration_hours = (now_utc - start_utc).total_seconds() / 3600
        if duration_hours <= 8:
            continue

        start_local = utc_to_local(start_utc)
        pilot = record.pilot

        owner_display = ''
        try:
            if getattr(pilot, 'owner', None):
                owner_display = getattr(pilot.owner, 'nickname', None) or getattr(pilot.owner, 'username', '')
        except Exception:  # pylint: disable=broad-except
            owner_display = ''

        rank_display = ''
        try:
            rank_display = pilot.rank.value if getattr(pilot, 'rank', None) else ''
        except Exception:  # pylint: disable=broad-except
            rank_display = ''

        item = {
            'pilot_name': getattr(pilot, 'nickname', ''),
            'real_name': getattr(pilot, 'real_name', ''),
            'owner_rank': f"{owner_display}-{rank_display}".strip('-'),
            'work_mode': record.get_work_mode_display(),
            'location': record.battle_location,
            'start_local': start_local.strftime('%Y-%m-%d %H:%M') if start_local else '未知',
            'duration_hours': f"{duration_hours:.1f}",
            'note': f'开播已经超过{duration_hours:.1f}小时，请确认是否已下播'
        }

        overtime_items.append(item)

    recipients = User.get_emails_by_role(role_name=None, only_active=True)
    subject = f"[Lacus-Log] 未下播提醒 - {utc_to_local(now_utc).strftime('%Y-%m-%d %H:%M')}"

    if not overtime_items:
        logger.info('未发现超过8小时的开播中记录，已跳过发送。来源：%s', triggered_by or '未知')
        return {'sent': False, 'count': 0}

    if not recipients:
        logger.error('收件人为空，用户模块未取得任何有效邮箱，无法发送未下播提醒邮件')
        return {'sent': False, 'count': len(overtime_items)}

    if send_email_md(recipients, subject, _build_live_overtime_markdown(overtime_items)):
        logger.info('未下播提醒已发送，共%d条；收件人：%s', len(overtime_items), ', '.join(recipients))
        return {'sent': True, 'count': len(overtime_items)}

    logger.error('未下播提醒发送失败；主题：%s；收件人：%s', subject, ', '.join(recipients))
    return {'sent': False, 'count': len(overtime_items)}


def run_unstarted_report_job(triggered_by: str = 'scheduler') -> dict:
    """执行"未开播提醒"报表计算与邮件发送（供任务与路由复用）。

    返回：{"sent": bool, "count": int}
    """
    logger.info('触发未开播提醒报表，来源：%s', triggered_by or '未知')

    now_utc = get_current_utc_time()
    window_start_utc = now_utc - timedelta(hours=48)

    candidate_plans = Announcement.objects.filter(start_time__gte=window_start_utc).order_by('-start_time')

    logger.debug('候选计划数量（48小时内）：%d', candidate_plans.count())

    unstarted_items: List[dict] = []
    sample_logged = 0
    for ann in candidate_plans:
        start_utc = ann.start_time
        deadline_utc = start_utc + timedelta(hours=6)

        if now_utc < deadline_utc:
            continue

        start_local = utc_to_local(start_utc)
        day_start_local = start_local.replace(hour=0, minute=0, second=0, microsecond=0)

        day_start_utc = local_to_utc(day_start_local)
        day_end_utc = local_to_utc(day_start_local + timedelta(days=1))

        pilot = ann.pilot
        same_day_record = BattleRecord.objects.filter(pilot=pilot, start_time__gte=day_start_utc, start_time__lt=day_end_utc).first()

        if same_day_record is not None:
            continue

        overdue_delta = now_utc - deadline_utc
        overdue_hours = floor(max(0, overdue_delta.total_seconds()) / 3600)

        owner_display = ''
        try:
            if getattr(pilot, 'owner', None):
                owner_display = getattr(pilot.owner, 'nickname', None) or getattr(pilot.owner, 'username', '')
        except Exception:
            owner_display = ''

        rank_display = ''
        try:
            rank_display = pilot.rank.value if getattr(pilot, 'rank', None) else ''
        except Exception:
            rank_display = ''

        region = f"{getattr(ann, 'x_coord', '')}-{getattr(ann, 'y_coord', '')}-{getattr(ann, 'z_coord', '')}"

        item = {
            'pilot_name': getattr(pilot, 'nickname', ''),
            'owner_rank': f"{owner_display}-{rank_display}".strip('-'),
            'region': region,
            'start_local': start_local.strftime('%Y-%m-%d %H:%M'),
            'plan_duration_hours': f"{getattr(ann, 'duration_hours', 0):.1f}",
            'overdue_hours': overdue_hours,
            'note': '请确认是否漏填开播记录'
        }

        if sample_logged < 5:
            logger.debug('未开播样例：%s', item)
            sample_logged += 1

        unstarted_items.append(item)

    recipients = User.get_emails_by_role(role_name=None, only_active=True)
    subject_ts = utc_to_local(now_utc).strftime('%Y-%m-%d %H:%M')
    subject = f"[Lacus-Log] 未开播提醒（近48小时） - {subject_ts}"

    if not unstarted_items:
        logger.info('无未开播计划，已跳过发送。来源：%s', triggered_by or '未知')
        return {'sent': False, 'count': 0}

    md = _build_unstarted_markdown(unstarted_items)

    if not recipients:
        logger.error('收件人为空，用户模块未取得任何有效邮箱，无法发送未开播提醒邮件')
        return {'sent': False, 'count': len(unstarted_items)}

    ok = send_email_md(recipients, subject, md)
    if ok:
        logger.info('未开播提醒已发送，共%d条；收件人：%s', len(unstarted_items), ', '.join(recipients))
        return {'sent': True, 'count': len(unstarted_items)}

    logger.error('未开播提醒发送失败；主题：%s；收件人：%s', subject, ', '.join(recipients))
    return {'sent': False, 'count': len(unstarted_items)}


def run_online_pilot_unstarted_report_job(triggered_by: str = 'scheduler') -> dict:
    """执行"线上主播未开播提醒"邮件报表发送任务。

    针对线上主播，找到报表日前4日开始的3天内有过线上开播记录的主播，
    如果该主播在报表日的前1天没有开播记录，则发送提醒。

    Args:
        triggered_by: 触发来源

    Returns:
        dict: {"sent": bool, "count": int}
    """
    logger.info('触发线上主播未开播提醒邮件发送，来源：%s', triggered_by or '未知')

    now_utc = get_current_utc_time()
    now_local = utc_to_local(now_utc)

    # 报表日为当前日期（GMT+8）
    report_date_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    # 检查窗口：报表日前4日开始的3天（即报表日-4, 报表日-3, 报表日-2）
    check_start_local = report_date_local - timedelta(days=4)
    check_end_local = report_date_local - timedelta(days=1)

    # 检查日：报表日前1天（即报表日-1）
    check_day_local = report_date_local - timedelta(days=1)

    # 转换为UTC时间用于数据库查询
    check_start_utc = local_to_utc(check_start_local)
    check_end_utc = local_to_utc(check_end_local + timedelta(days=1))
    check_day_start_utc = local_to_utc(check_day_local)
    check_day_end_utc = local_to_utc(check_day_local + timedelta(days=1))

    logger.debug('报表日：%s（本地）', report_date_local.strftime('%Y-%m-%d'))
    logger.debug('检查窗口：%s 至 %s（本地）', check_start_local.strftime('%Y-%m-%d'), check_end_local.strftime('%Y-%m-%d'))
    logger.debug('检查日：%s（本地）', check_day_local.strftime('%Y-%m-%d'))

    # 查询在检查窗口内有过线上开播记录的主播
    from models.pilot import WorkMode
    online_records_in_window = BattleRecord.objects.filter(start_time__gte=check_start_utc, start_time__lt=check_end_utc,
                                                           work_mode=WorkMode.ONLINE).distinct('pilot')

    logger.debug('检查窗口内有线上开播记录的主播数量：%d', len(online_records_in_window))

    unstarted_online_pilots: List[dict] = []
    sample_logged = 0

    for pilot in online_records_in_window:
        # 检查该主播在检查日是否有开播记录（不限线上/线下）
        records_on_check_day = BattleRecord.objects.filter(pilot=pilot, start_time__gte=check_day_start_utc, start_time__lt=check_day_end_utc).first()

        if records_on_check_day is not None:
            # 检查日有开播记录，跳过
            continue

        # 检查日无开播记录，需要提醒
        # 查询该主播最近的一次开播记录
        latest_record = BattleRecord.objects.filter(pilot=pilot).order_by('-start_time').first()

        if latest_record:
            latest_date_local = utc_to_local(latest_record.start_time)
            latest_date_str = latest_date_local.strftime('%Y-%m-%d')
        else:
            latest_date_str = '无记录'

        # 获取主播信息
        owner_display = ''
        try:
            if getattr(pilot, 'owner', None):
                owner_display = getattr(pilot.owner, 'nickname', None) or getattr(pilot.owner, 'username', '')
        except Exception:
            owner_display = ''

        rank_display = ''
        try:
            rank_display = pilot.rank.value if getattr(pilot, 'rank', None) else ''
        except Exception:
            rank_display = ''

        # 统计最近3天线上开播次数
        recent_online_count = BattleRecord.objects.filter(pilot=pilot, start_time__gte=check_start_utc, start_time__lt=check_end_utc,
                                                          work_mode=WorkMode.ONLINE).count()

        item = {
            'pilot_name': getattr(pilot, 'nickname', ''),
            'real_name': getattr(pilot, 'real_name', ''),
            'owner_rank': f"{owner_display}-{rank_display}".strip('-'),
            'latest_date': latest_date_str,
            'recent_online_count': recent_online_count,
            'check_day': check_day_local.strftime('%Y-%m-%d'),
            'note': f'{check_day_local.strftime("%m月%d日")}未登记开播记录，请确认是否漏记'
        }

        if sample_logged < 5:
            logger.debug('线上主播未开播样例：%s', item)
            sample_logged += 1

        unstarted_online_pilots.append(item)

    recipients = []
    recipients.extend(User.get_emails_by_role(role_name='gicho', only_active=True))  # 管理员
    recipients.extend(User.get_emails_by_role(role_name='kancho', only_active=True))  # 运营

    if not recipients:
        logger.error('收件人为空，未找到任何运营或管理员的邮箱')
        return {'sent': False, 'count': 0}

    recipients = list(set(recipients))

    report_date_str = report_date_local.strftime('%Y-%m-%d')
    subject = f"[Lacus-Log] 线上主播未开播提醒 - {report_date_str}"

    if not unstarted_online_pilots:
        logger.info('无线主播未开播情况，已跳过发送。来源：%s', triggered_by or '未知')
        return {'sent': False, 'count': 0}

    md = _build_online_pilot_unstarted_markdown(unstarted_online_pilots, report_date_str, check_day_local.strftime('%Y-%m-%d'))

    ok = send_email_md(recipients, subject, md)
    if ok:
        logger.info('线上主播未开播提醒已发送，共%d条；收件人：%s', len(unstarted_online_pilots), ', '.join(recipients))
        return {'sent': True, 'count': len(unstarted_online_pilots)}

    logger.error('线上主播未开播提醒发送失败；主题：%s；收件人：%s', subject, ', '.join(recipients))
    return {'sent': False, 'count': len(unstarted_online_pilots)}


def run_base_salary_reminder_job(triggered_by: str = 'scheduler') -> dict:
    """执行底薪发放提醒邮件发送任务。

    筛选状态为"未处理"且创建时间超过12小时的底薪申请，发送邮件提醒。

    Args:
        triggered_by: 触发来源

    Returns:
        dict: {"sent": bool, "count": int}
    """
    logger.info('触发底薪发放提醒邮件发送，来源：%s', triggered_by or '未知')

    now_utc = get_current_utc_time()
    threshold_utc = now_utc - timedelta(hours=12)

    # 查询状态为PENDING且创建时间超过12小时的底薪申请
    pending_applications = BaseSalaryApplication.objects.filter(status=BaseSalaryApplicationStatus.PENDING,
                                                                created_at__lte=threshold_utc).order_by('created_at')

    logger.debug('符合条件的底薪申请数量：%d', pending_applications.count())

    reminder_items: List[dict] = []
    sample_logged = 0

    for app in pending_applications:
        pilot = app.pilot_id
        battle_record = app.battle_record_id

        # 获取申请和超时时间信息
        created_utc = app.created_at
        created_local = utc_to_local(created_utc)
        overdue_delta = now_utc - created_utc
        overdue_hours = floor(overdue_delta.total_seconds() / 3600)

        # 获取开播记录日期
        battle_date_local = utc_to_local(battle_record.start_time).strftime('%Y-%m-%d')

        # 获取主播信息
        owner_display = ''
        try:
            if getattr(pilot, 'owner', None):
                owner_display = getattr(pilot.owner, 'nickname', None) or getattr(pilot.owner, 'username', '')
        except Exception:
            owner_display = ''

        rank_display = ''
        try:
            rank_display = pilot.rank.value if getattr(pilot, 'rank', None) else ''
        except Exception:
            rank_display = ''

        item = {
            'pilot_name': getattr(pilot, 'nickname', ''),
            'real_name': getattr(pilot, 'real_name', ''),
            'owner_rank': f"{owner_display}-{rank_display}".strip('-'),
            'battle_date': battle_date_local,
            'apply_time': created_local.strftime('%Y-%m-%d %H:%M'),
            'overdue_hours': overdue_hours,
            'base_salary': float(app.base_salary_amount),
            'note': f'申请已超过{overdue_hours}小时未处理，请及时审核'
        }

        if sample_logged < 5:
            logger.debug('底薪发放提醒样例：%s', item)
            sample_logged += 1

        reminder_items.append(item)

    recipients = []
    recipients.extend(User.get_emails_by_role(role_name='gicho', only_active=True))  # 管理员
    recipients.extend(User.get_emails_by_role(role_name='kancho', only_active=True))  # 运营

    if not recipients:
        logger.error('收件人为空，未找到任何运营或管理员的邮箱')
        return {'sent': False, 'count': 0}

    recipients = list(set(recipients))

    current_time_str = utc_to_local(now_utc).strftime('%Y-%m-%d %H:%M')
    subject = f"[Lacus-Log] 底薪发放提醒 - {current_time_str}"

    if not reminder_items:
        logger.info('无需要处理的底薪申请，已跳过发送。来源：%s', triggered_by or '未知')
        return {'sent': False, 'count': 0}

    md = _build_base_salary_reminder_markdown(reminder_items)

    ok = send_email_md(recipients, subject, md)
    if ok:
        logger.info('底薪发放提醒已发送，共%d条；收件人：%s', len(reminder_items), ', '.join(recipients))
        return {'sent': True, 'count': len(reminder_items)}

    logger.error('底薪发放提醒发送失败；主题：%s；收件人：%s', subject, ', '.join(recipients))
    return {'sent': False, 'count': len(reminder_items)}


@report_mail_bp.route('/mail/unstarted', methods=['POST'])
@roles_required('gicho')
def trigger_unstarted_report():
    """触发"未开播提醒"报表计算与邮件发送（异步最小实现：请求内完成）。"""
    username = getattr(current_user, 'username', '未知')
    result = run_unstarted_report_job(triggered_by=username)
    status = {'status': 'started', 'sent': result.get('sent', False), 'count': result.get('count', 0)}
    return jsonify(status), (200 if result.get('sent') or result.get('count') == 0 else 500)


@report_mail_bp.route('/mail/live-overtime', methods=['POST'])
@roles_required('gicho')
def trigger_live_overtime_report():
    """触发"未下播提醒"邮件发送。"""
    username = getattr(current_user, 'username', '未知')
    result = run_live_overtime_report_job(triggered_by=username)
    status = {'status': 'started', 'sent': result.get('sent', False), 'count': result.get('count', 0)}
    return jsonify(status), (200 if result.get('sent') or result.get('count') == 0 else 500)


@report_mail_bp.route('/mail/recruit-daily', methods=['GET', 'POST'])
@roles_required('gicho')
def trigger_recruit_daily_report():
    """触发或显示招募日报。GET请求用于显示，POST请求用于触发邮件。"""
    if request.method == 'GET':
        return redirect(url_for('report.recruit_daily_report', **request.args))

    username = getattr(current_user, 'username', '未知')

    report_date = request.json.get('report_date') if request.is_json else None

    result = run_recruit_daily_report_job(report_date=report_date, triggered_by=username)
    status = {'status': 'started', 'sent': result.get('sent', False), 'count': result.get('count', 0)}
    return jsonify(status), (200 if result.get('sent') or result.get('count') == 0 else 500)


@report_mail_bp.route('/mail/daily-report', methods=['POST'])
@roles_required('gicho')
def trigger_daily_report():
    """触发开播日报邮件发送。"""
    username = getattr(current_user, 'username', '未知')

    report_date = request.json.get('report_date') if request.is_json else None

    result = run_daily_report_job(report_date=report_date, triggered_by=username)
    status = {'status': 'started', 'sent': result.get('sent', False), 'count': result.get('count', 0)}
    return jsonify(status), (200 if result.get('sent') or result.get('count') == 0 else 500)


@report_mail_bp.route('/mail/monthly-report', methods=['POST'])
@roles_required('gicho')
def trigger_monthly_mail_report():
    """触发开播月报（邮件）发送。

    请求JSON：{"report_month": "YYYY-MM"}，留空则按"前一自然日所在月"。
    """
    username = getattr(current_user, 'username', '未知')

    report_month = request.json.get('report_month') if request.is_json else None

    result = run_monthly_mail_report_job(report_month=report_month, triggered_by=username)
    status = {'status': 'started', 'sent': result.get('sent', False), 'count': result.get('count', 0)}
    return jsonify(status), (200 if result.get('sent') or result.get('count') == 0 else 500)


@report_mail_bp.route('/mail/online-pilot-unstarted', methods=['POST'])
@roles_required('gicho')
def trigger_online_pilot_unstarted_report():
    """触发线上主播未开播提醒邮件发送。"""
    username = getattr(current_user, 'username', '未知')

    result = run_online_pilot_unstarted_report_job(triggered_by=username)
    status = {'status': 'started', 'sent': result.get('sent', False), 'count': result.get('count', 0)}
    return jsonify(status), (200 if result.get('sent') or result.get('count') == 0 else 500)


@report_mail_bp.route('/mail/base-salary-reminder', methods=['POST'])
@roles_required('gicho')
def trigger_base_salary_reminder_report():
    """触发底薪发放提醒邮件发送。"""
    username = getattr(current_user, 'username', '未知')

    result = run_base_salary_reminder_job(triggered_by=username)
    status = {'status': 'started', 'sent': result.get('sent', False), 'count': result.get('count', 0)}
    return jsonify(status), (200 if result.get('sent') or result.get('count') == 0 else 500)
