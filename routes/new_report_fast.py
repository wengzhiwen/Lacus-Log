# pylint: disable=duplicate-code,too-many-locals
"""开播新月报（加速版）页面路由。"""

from datetime import timedelta
import io
import csv
from urllib.parse import quote

from flask import Blueprint, Response, render_template, request
from flask_security import roles_accepted

from utils.logging_setup import get_logger
from utils.new_report_fast_calculations import calculate_monthly_details_fast, calculate_monthly_summary_fast
from utils.new_report_calculations import get_local_month_from_string
from utils.timezone_helper import get_current_utc_time, utc_to_local

logger = get_logger('new_report_fast')

new_report_fast_bp = Blueprint('new_report_fast', __name__)


def _parse_owner_param() -> str:
    owner_id = request.args.get('owner', 'all')
    if owner_id in (None, ''):
        return 'all'
    return owner_id


def _parse_mode_param() -> str:
    mode = request.args.get('mode', 'all') or 'all'
    if mode not in ('all', 'online', 'offline'):
        logger.warning('非法开播方式参数：%s，已回退为 all', mode)
        return 'all'
    return mode


def _parse_status_param() -> str:
    status = request.args.get('status', 'all') or 'all'
    valid_statuses = ('all', 'not_recruited', 'not_recruiting', 'recruited', 'contracted', 'fallen')
    if status not in valid_statuses:
        logger.warning('非法状态参数：%s，已回退为 all', status)
        return 'all'
    return status


@new_report_fast_bp.route('/monthly')
@roles_accepted('gicho', 'kancho')
def monthly_report_fast():
    """开播新月报（加速版）页面。"""
    month_str = request.args.get('month')
    if not month_str:
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_month = today_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        report_month = get_local_month_from_string(month_str)
        if not report_month:
            logger.error('无效的新月报月份参数：%s', month_str)
            return '无效的月份格式', 400
        report_month = report_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    owner_id = _parse_owner_param()
    mode = _parse_mode_param()
    status = _parse_status_param()

    logger.info('访问开播新月报（加速版）页面，月份：%s，直属运营：%s，开播方式：%s，主播状态：%s', report_month.strftime('%Y-%m'), owner_id, mode, status)

    pagination = {
        'month': report_month.strftime('%Y-%m'),
        'prev_month': (report_month - timedelta(days=1)).replace(day=1).strftime('%Y-%m'),
        'next_month': (report_month + timedelta(days=31)).replace(day=1).strftime('%Y-%m')
    }

    return render_template('new_reports_fast/monthly.html', pagination=pagination, selected_owner=owner_id, selected_mode=mode, selected_status=status)


@new_report_fast_bp.route('/monthly/export.csv')
@roles_accepted('gicho', 'kancho')
def export_monthly_fast_csv():
    """导出开播新月报（加速版）CSV。"""
    month_str = request.args.get('month')
    if not month_str:
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_month = today_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        report_month = get_local_month_from_string(month_str)
        if not report_month:
            logger.error('无效的新月报月份参数：%s', month_str)
            return '无效的月份格式', 400
        report_month = report_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    owner_id = _parse_owner_param()
    mode = _parse_mode_param()
    status = _parse_status_param()

    logger.info('导出开播新月报（加速版）CSV，月份：%s，直属运营：%s，开播方式：%s，主播状态：%s', report_month.strftime('%Y-%m'), owner_id, mode, status)

    summary = calculate_monthly_summary_fast(report_month.year, report_month.month, owner_id, mode, status)
    details = calculate_monthly_details_fast(report_month.year, report_month.month, owner_id, mode, status)

    output = io.StringIO()
    writer = csv.writer(output)
    output.write('\ufeff')

    writer.writerow(['汇总指标（加速版）'])
    writer.writerow(['主播数', summary['pilot_count']])
    writer.writerow(['总流水(元)', f"{summary['revenue_sum']:.2f}"])
    writer.writerow(['总底薪(元)', f"{summary['basepay_sum']:.2f}"])
    writer.writerow(['总返点(元)', f"{summary['rebate_sum']:.2f}"])
    writer.writerow(['主播分成(元)', f"{summary['pilot_share_sum']:.2f}"])
    writer.writerow(['公司分成(元)', f"{summary['company_share_sum']:.2f}"])
    writer.writerow(['经营毛利(元)', f"{summary['operating_profit']:.2f}"])
    writer.writerow(['底薪转化率(%)', summary['conversion_rate'] or ''])
    writer.writerow([])

    headers = ['主播', '性别年龄', '直属运营', '主播分类', '月累计开播记录数', '月均播时(小时)', '月累计流水(元)', '月累计主播分成(元)', '月累计公司分成(元)', '月最新返点比例(%)', '月累计返点(元)', '月累计底薪(元)', '月累计毛利(元)']
    writer.writerow(headers)

    for detail in details:
        rate_display = f"{round(detail['rebate_rate'] * 100)}%" if detail['rebate_rate'] else '0%'
        row = [
            detail['pilot_display'], detail['gender_age'], detail['owner'], detail['rank'], detail['records_count'], f"{detail['avg_duration']:.1f}",
            f"{detail['total_revenue']:.2f}", f"{detail['total_pilot_share']:.2f}", f"{detail['total_company_share']:.2f}", rate_display,
            f"{detail['rebate_amount']:.2f}", f"{detail['total_base_salary']:.2f}", f"{detail['total_profit']:.2f}"
        ]
        writer.writerow(row)

    csv_content = output.getvalue()
    output.close()

    filename = f"开播新月报_加速版_{report_month.strftime('%Y%m')}.csv"
    encoded_filename = quote(filename.encode('utf-8'))

    response = Response(csv_content, mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename*=UTF-8\'\'{encoded_filename}'})
    return response
