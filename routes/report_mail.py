"""
管理员专用 - 邮件报告模块（未开播提醒）

本模块提供基于按钮触发的离线报表，通过邮件发送结果。
"""
# pylint: disable=no-member,consider-using-f-string
from datetime import datetime, timedelta
from math import floor
from typing import List

from flask import (Blueprint, jsonify, redirect, render_template, request,
                   url_for)
from flask_security import current_user, roles_required

from models.announcement import Announcement
from models.battle_record import BattleRecord
from models.user import User
from utils.job_token import JobPlan
from utils.logging_setup import get_logger
from utils.mail_utils import send_email_md
from utils.timezone_helper import (get_current_utc_time, local_to_utc,
                                   utc_to_local)

logger = get_logger('report_mail')

report_mail_bp = Blueprint('report_mail', __name__)


def _build_recruit_daily_markdown(statistics: dict) -> str:
    """将招募日报统计数据渲染为Markdown表格。
    
    Args:
        statistics: 统计数据字典
        
    Returns:
        str: Markdown格式的表格内容
    """

    def safe_percentage(numerator, denominator):
        """安全计算百分比，避免除零错误"""
        if denominator == 0:
            return 0
        return round((numerator / denominator) * 100)

    report_day = statistics['report_day']
    last_7_days = statistics['last_7_days']
    last_14_days = statistics['last_14_days']

    percentages = {
        'report_day': {
            'appointments': safe_percentage(report_day['appointments'], last_7_days['appointments']),
            'interviews': safe_percentage(report_day['interviews'], last_7_days['interviews']),
            'trials': safe_percentage(report_day['trials'], last_7_days['trials']),
            'new_recruits': safe_percentage(report_day['new_recruits'], last_7_days['new_recruits'])
        },
        'last_7_days': {
            'appointments': safe_percentage(last_7_days['appointments'], last_14_days['appointments']),
            'interviews': safe_percentage(last_7_days['interviews'], last_14_days['interviews']),
            'trials': safe_percentage(last_7_days['trials'], last_14_days['trials']),
            'new_recruits': safe_percentage(last_7_days['new_recruits'], last_14_days['new_recruits'])
        }
    }

    header = "| 统计范围 | 约面 | 到面 | 试播 | 新开播 |\n| --- | ---: | ---: | ---: | ---: |"

    lines = [header]

    report_line = (f"| 报表日 | {report_day['appointments']} ({percentages['report_day']['appointments']}%) | "
                   f"{report_day['interviews']} ({percentages['report_day']['interviews']}%) | "
                   f"{report_day['trials']} ({percentages['report_day']['trials']}%) | "
                   f"{report_day['new_recruits']} ({percentages['report_day']['new_recruits']}%) |")
    lines.append(report_line)

    week_line = (f"| 近7日 | {last_7_days['appointments']} ({percentages['last_7_days']['appointments']}%) | "
                 f"{last_7_days['interviews']} ({percentages['last_7_days']['interviews']}%) | "
                 f"{last_7_days['trials']} ({percentages['last_7_days']['trials']}%) | "
                 f"{last_7_days['new_recruits']} ({percentages['last_7_days']['new_recruits']}%) |")
    lines.append(week_line)

    fortnight_line = (f"| 近14日 | {last_14_days['appointments']} | "
                      f"{last_14_days['interviews']} | "
                      f"{last_14_days['trials']} | "
                      f"{last_14_days['new_recruits']} |")
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

    from routes.report import _calculate_daily_details, _calculate_day_summary

    day_summary = _calculate_day_summary(report_date_obj)
    details = _calculate_daily_details(report_date_obj)

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

    from routes.report import (_calculate_monthly_details,
                               _calculate_monthly_summary)

    month_summary = _calculate_monthly_summary(year, month)
    details = _calculate_monthly_details(year, month)

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
        recruit_next_local = None
        daily_next_local = None
        monthly_mail_next_local = None

    next_times = {
        'unstarted': unstarted_next_local,
        'recruit_daily': recruit_next_local,
        'daily_report': daily_next_local,
        'monthly_mail_report': monthly_mail_next_local
    }
    return render_template('reports/mail_reports.html', next_times=next_times)


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


@report_mail_bp.route('/mail/unstarted', methods=['POST'])
@roles_required('gicho')
def trigger_unstarted_report():
    """触发"未开播提醒"报表计算与邮件发送（异步最小实现：请求内完成）。"""
    username = getattr(current_user, 'username', '未知')
    result = run_unstarted_report_job(triggered_by=username)
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

    请求JSON：{"report_month": "YYYY-MM"}，留空则按“前一自然日所在月”。
    """
    username = getattr(current_user, 'username', '未知')

    report_month = request.json.get('report_month') if request.is_json else None

    result = run_monthly_mail_report_job(report_month=report_month, triggered_by=username)
    status = {'status': 'started', 'sent': result.get('sent', False), 'count': result.get('count', 0)}
    return jsonify(status), (200 if result.get('sent') or result.get('count') == 0 else 500)
