"""
议长专用 - 邮件报告模块（未开播提醒）

本模块提供基于按钮触发的离线报表，通过邮件发送结果。
"""
# pylint: disable=no-member
from datetime import datetime, timedelta
from math import floor
from typing import List

from flask import Blueprint, jsonify, render_template, request
from flask_security import current_user, roles_required
from mongoengine import Q

from models.announcement import Announcement
from models.battle_record import BattleRecord
from models.recruit import BroadcastDecision, FinalDecision, Recruit
from models.user import User
from utils.job_token import JobPlan
from utils.logging_setup import get_logger
from utils.mail_utils import send_email_md
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)

logger = get_logger('report_mail')

report_mail_bp = Blueprint('report_mail', __name__)


def _build_recruit_daily_markdown(statistics: dict) -> str:
    """将征召日报统计数据渲染为Markdown表格。
    
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

    # 计算百分比
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

    # 报表日行
    report_line = (f"| 报表日 | {report_day['appointments']} ({percentages['report_day']['appointments']}%) | "
                   f"{report_day['interviews']} ({percentages['report_day']['interviews']}%) | "
                   f"{report_day['trials']} ({percentages['report_day']['trials']}%) | "
                   f"{report_day['new_recruits']} ({percentages['report_day']['new_recruits']}%) |")
    lines.append(report_line)

    # 近7日行
    week_line = (f"| 近7日 | {last_7_days['appointments']} ({percentages['last_7_days']['appointments']}%) | "
                 f"{last_7_days['interviews']} ({percentages['last_7_days']['interviews']}%) | "
                 f"{last_7_days['trials']} ({percentages['last_7_days']['trials']}%) | "
                 f"{last_7_days['new_recruits']} ({percentages['last_7_days']['new_recruits']}%) |")
    lines.append(week_line)

    # 近14日行
    fortnight_line = (f"| 近14日 | {last_14_days['appointments']} | "
                      f"{last_14_days['interviews']} | "
                      f"{last_14_days['trials']} | "
                      f"{last_14_days['new_recruits']} |")
    lines.append(fortnight_line)

    return "\n".join(lines)


def run_recruit_daily_report_job(report_date: str = None, triggered_by: str = 'scheduler') -> dict:
    """执行征召日报邮件发送任务。
    
    Args:
        report_date: 报表日期字符串（YYYY-MM-DD格式），默认为昨天
        triggered_by: 触发来源
        
    Returns:
        dict: {"sent": bool, "count": int}
    """
    logger.info('触发征召日报邮件发送，来源：%s，报表日期：%s', triggered_by or '未知', report_date or '昨天')

    # 确定报表日期
    if not report_date:
        # 默认发送昨天的报表
        now_utc = get_current_utc_time()
        yesterday_local = utc_to_local(now_utc) - timedelta(days=1)
        report_date = yesterday_local.strftime('%Y-%m-%d')

    # 解析报表日期
    try:
        report_date_obj = datetime.strptime(report_date, '%Y-%m-%d')
    except ValueError:
        logger.error('报表日期格式错误：%s', report_date)
        return {'sent': False, 'count': 0}

    # 计算统计数据（复用征召日报的计算逻辑）
    statistics = _calculate_recruit_statistics(report_date_obj)

    # 生成邮件内容
    md_content = _build_recruit_daily_markdown(statistics)

    # 添加说明文字
    full_content = f"""# 机师征召日报

**报表日期：** {report_date}

## 统计概览

{md_content}

## 指标说明

- **约面**：当天创建的征召数量
- **到面**：当天发生的面试决策数量（完成面试决策的数量，不论是决定预约训练，还是决定不征召都算）
- **试播**：当天发生的开播决策数量（完成开播决策的数量，不论是决定征召，还是决定不征召）
- **新开播**：当天在开播决策中决定征召的数量（不征召不算）

---
*本报表由 Lacus-Log 系统自动生成*
"""

    # 获取收件人：舰长和议长
    recipients = []
    recipients.extend(User.get_emails_by_role(role_name='gicho', only_active=True))  # 议长
    recipients.extend(User.get_emails_by_role(role_name='kancho', only_active=True))  # 舰长

    if not recipients:
        logger.error('收件人为空，未找到任何舰长或议长的邮箱')
        return {'sent': False, 'count': 0}

    # 去重
    recipients = list(set(recipients))

    # 生成邮件主题
    subject = f"[Lacus-Log] 机师征召日报 - {report_date}"

    # 发送邮件
    ok = send_email_md(recipients, subject, full_content)
    if ok:
        logger.info('征召日报邮件已发送，收件人：%s', ', '.join(recipients))
        return {'sent': True, 'count': len(recipients)}

    logger.error('征召日报邮件发送失败；主题：%s；收件人：%s', subject, ', '.join(recipients))
    return {'sent': False, 'count': len(recipients)}


def _calculate_recruit_statistics(report_date):
    """计算征召统计数据（复用征召日报的计算逻辑）
    
    Args:
        report_date: 报表日期（本地时间）
        
    Returns:
        dict: 包含报表日、近7日、近14日的统计数据
    """

    # 计算时间范围
    report_day_start = report_date
    report_day_end = report_day_start + timedelta(days=1)

    last_7_days_start = report_date - timedelta(days=6)  # 包含报表日，共7天
    last_14_days_start = report_date - timedelta(days=13)  # 包含报表日，共14天

    # 转换为UTC时间范围
    report_day_start_utc = local_to_utc(report_day_start)
    report_day_end_utc = local_to_utc(report_day_end)
    last_7_days_start_utc = local_to_utc(last_7_days_start)
    last_14_days_start_utc = local_to_utc(last_14_days_start)

    # 计算报表日数据
    report_day_stats = _calculate_period_stats(report_day_start_utc, report_day_end_utc)

    # 计算近7日数据
    last_7_days_stats = _calculate_period_stats(last_7_days_start_utc, report_day_end_utc)

    # 计算近14日数据
    last_14_days_stats = _calculate_period_stats(last_14_days_start_utc, report_day_end_utc)

    return {'report_day': report_day_stats, 'last_7_days': last_7_days_stats, 'last_14_days': last_14_days_stats}


def _calculate_period_stats(start_utc, end_utc):
    """计算指定时间范围内的征召统计数据
    
    Args:
        start_utc: 开始时间（UTC）
        end_utc: 结束时间（UTC）
        
    Returns:
        dict: 包含约面、到面、试播、新开播的统计数据
    """

    # 约面：当天创建的征召数量
    appointments = Recruit.objects.filter(created_at__gte=start_utc, created_at__lt=end_utc).count()

    # 到面：当天发生的面试决策数量（新六步制 + 历史兼容）
    # 新六步制：使用 interview_decision_time
    # 历史兼容：使用 training_decision_time_old
    interviews_query = (Q(interview_decision_time__gte=start_utc, interview_decision_time__lt=end_utc)
                        | Q(training_decision_time_old__gte=start_utc, training_decision_time_old__lt=end_utc))
    interviews = Recruit.objects.filter(interviews_query).count()

    # 试播：当天发生的开播决策数量（新六步制 + 历史兼容）
    # 新六步制：使用 broadcast_decision_time
    # 历史兼容：使用 final_decision_time
    trials_query = (Q(broadcast_decision_time__gte=start_utc, broadcast_decision_time__lt=end_utc)
                    | Q(final_decision_time__gte=start_utc, final_decision_time__lt=end_utc))
    trials = Recruit.objects.filter(trials_query).count()

    # 新开播：当天在开播决策中决定征召的数量（不征召不算）
    # 新六步制：使用 broadcast_decision_time 和 broadcast_decision
    # 历史兼容：使用 final_decision_time 和 final_decision
    new_recruits_query = (
        Q(broadcast_decision_time__gte=start_utc,
          broadcast_decision_time__lt=end_utc,
          broadcast_decision__in=[BroadcastDecision.OFFICIAL, BroadcastDecision.INTERN])
        | Q(final_decision_time__gte=start_utc, final_decision_time__lt=end_utc, final_decision__in=[FinalDecision.OFFICIAL, FinalDecision.INTERN]))
    new_recruits = Recruit.objects.filter(new_recruits_query).count()

    return {'appointments': appointments, 'interviews': interviews, 'trials': trials, 'new_recruits': new_recruits}


def _build_unstarted_markdown(items: List[dict]) -> str:
    if not items:
        return ''

    header = ("| 主播昵称 | 所属-阶级 | 作战区域 | 计划开播时间（GMT+8） | 计划播时（小时） | 当前超时（小时） | 备注 |\n"
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
    """展示邮件报告入口页面（仅议长可见）。"""
    # 读取 MongoDB 中的下一次触发计划（UTC），界面显示为 GMT+8
    try:
        now_minute = get_current_utc_time().strftime('%Y%m%d%H%M')
        # 未开播提醒
        unstarted_plan = (JobPlan.objects(job_code='daily_unstarted_report', fire_minute__gte=now_minute).order_by('fire_minute').first()) or (JobPlan.objects(
            job_code='daily_unstarted_report').order_by('-fire_minute').first())
        unstarted_next_local = None
        if unstarted_plan:
            fire_dt_utc = datetime.strptime(unstarted_plan.fire_minute, '%Y%m%d%H%M')
            unstarted_next_local = utc_to_local(fire_dt_utc).strftime('%Y-%m-%d %H:%M')

        # 征召日报
        recruit_plan = (JobPlan.objects(job_code='daily_recruit_daily_report', fire_minute__gte=now_minute).order_by('fire_minute').first()) or (
            JobPlan.objects(job_code='daily_recruit_daily_report').order_by('-fire_minute').first())
        recruit_next_local = None
        if recruit_plan:
            fire_dt_utc = datetime.strptime(recruit_plan.fire_minute, '%Y%m%d%H%M')
            recruit_next_local = utc_to_local(fire_dt_utc).strftime('%Y-%m-%d %H:%M')

    except Exception as exc:  # pylint: disable=broad-except
        logger.error('读取任务下一次触发时间失败：%s', exc)
        unstarted_next_local = None
        recruit_next_local = None

    next_times = {'unstarted': unstarted_next_local, 'recruit_daily': recruit_next_local}
    return render_template('reports/mail_reports.html', next_times=next_times)


def run_unstarted_report_job(triggered_by: str = 'scheduler') -> dict:
    """执行“未开播提醒”报表计算与邮件发送（供任务与路由复用）。

    返回：{"sent": bool, "count": int}
    """
    logger.info('触发未开播提醒报表，来源：%s', triggered_by or '未知')

    # 统一使用项目的UTC naive时间口径，避免aware/naive相减报错
    now_utc = get_current_utc_time()
    window_start_utc = now_utc - timedelta(hours=48)
    deadline_threshold_utc = now_utc - timedelta(hours=4)

    # 说明：此处将“计划的接受时间”按现有数据模型暂以 Announcement.start_time 代替
    # 过滤48小时窗口内、且已超过4小时阈值的作战计划
    candidate_plans = Announcement.objects.filter(start_time__gte=window_start_utc, start_time__lte=deadline_threshold_utc).order_by('-start_time')

    logger.debug('候选计划数量（48小时内且超4小时）：%d', candidate_plans.count())

    unstarted_items: List[dict] = []
    sample_logged = 0
    for ann in candidate_plans:
        # 若存在与该计划关联的作战记录，则视为已开播
        exists_record = BattleRecord.objects.filter(related_announcement=ann).first() is not None
        if exists_record:
            continue

        start_utc = ann.start_time
        deadline_utc = start_utc + timedelta(hours=4)

        start_local = utc_to_local(start_utc)

        overdue_delta = now_utc - deadline_utc
        overdue_hours = floor(max(0, overdue_delta.total_seconds()) / 3600)

        pilot = ann.pilot
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
            'note': '请确认是否漏填作战记录'
        }

        if sample_logged < 5:
            logger.debug('未开播样例：%s', item)
            sample_logged += 1

        unstarted_items.append(item)

    # 收件人：从用户模块获取所有激活用户的邮箱（去重、稳定排序）
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


@report_mail_bp.route('/mail/recruit-daily', methods=['POST'])
@roles_required('gicho')
def trigger_recruit_daily_report():
    """触发征召日报邮件发送（手动触发）。"""
    username = getattr(current_user, 'username', '未知')

    # 获取请求参数
    report_date = request.json.get('report_date') if request.is_json else None

    result = run_recruit_daily_report_job(report_date=report_date, triggered_by=username)
    status = {'status': 'started', 'sent': result.get('sent', False), 'count': result.get('count', 0)}
    return jsonify(status), (200 if result.get('sent') or result.get('count') == 0 else 500)
