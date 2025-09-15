"""议长专用 - 邮件报告模块（未开播提醒）

本模块提供基于按钮触发的离线报表，通过邮件发送结果。
"""
# pylint: disable=no-member
import os
from datetime import datetime, timedelta, timezone
from math import floor
from typing import List

from flask import Blueprint, jsonify, render_template
from flask_security import current_user, roles_required

from models.announcement import Announcement
from models.battle_record import BattleRecord
from utils.logging_setup import get_logger
from utils.mail_utils import send_email_md
from utils.timezone_helper import get_current_utc_time, utc_to_local

logger = get_logger('report_mail')

report_mail_bp = Blueprint('report_mail', __name__)


def _get_recipients_from_env() -> List[str]:
    """从环境变量读取报告收件人列表。"""
    addresses = os.getenv('REPORT_MAIL_ADDRESS', '').strip()
    if not addresses:
        return []
    return [addr.strip() for addr in addresses.split(',') if addr.strip()]


def _build_unstarted_markdown(items: List[dict]) -> str:
    """将未开播项目渲染为Markdown表格。

    列：主播昵称 | 所属-阶级 | 作战区域 | 计划开播时间（GMT+8） | 计划播时（小时） | 当前超时（小时） | 备注
    """
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
    return render_template('reports/mail_reports.html')


@report_mail_bp.route('/mail/unstarted', methods=['POST'])
@roles_required('gicho')
def trigger_unstarted_report():
    """触发“未开播提醒”报表计算与邮件发送（异步最小实现：请求内完成）。"""
    logger.info('用户 %s 触发未开播提醒报表', getattr(current_user, 'username', '未知'))

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

    recipients = _get_recipients_from_env()
    subject_ts = utc_to_local(now_utc).strftime('%Y-%m-%d %H:%M')
    subject = f"[Lacus-Log] 未开播提醒（近48小时） - {subject_ts}"

    if not unstarted_items:
        logger.info('无未开播计划，已跳过发送。触发人：%s', getattr(current_user, 'username', '未知'))
        return jsonify({'status': 'started', 'sent': False, 'count': 0})

    md = _build_unstarted_markdown(unstarted_items)

    if not recipients:
        logger.error('REPORT_MAIL_ADDRESS 未配置或为空，无法发送未开播提醒邮件')
        return jsonify({'status': 'started', 'sent': False, 'count': len(unstarted_items), 'error': 'no_recipients'}), 500

    ok = send_email_md(recipients, subject, md)
    if ok:
        logger.info('未开播提醒已发送，共%d条；收件人：%s', len(unstarted_items), ', '.join(recipients))
        return jsonify({'status': 'started', 'sent': True, 'count': len(unstarted_items)})

    logger.error('未开播提醒发送失败；主题：%s；收件人：%s', subject, ', '.join(recipients))
    return jsonify({'status': 'started', 'sent': False, 'count': len(unstarted_items)}), 500
