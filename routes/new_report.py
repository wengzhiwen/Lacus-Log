"""开播新日报/周报/月报页面路由。"""
# pylint: disable=too-many-locals

import csv
import io
from datetime import timedelta
from urllib.parse import quote

from flask import Blueprint, Response, render_template, request
from flask_security import roles_accepted

from utils.logging_setup import get_logger
from utils.new_report_calculations import (calculate_daily_details, calculate_weekly_details, calculate_weekly_summary,
                                           get_default_week_start_for_now_prev_week, get_local_date_from_string, get_local_date_from_string_safe,
                                           get_local_month_from_string, get_week_start_tuesday)
from utils.timezone_helper import get_current_utc_time, utc_to_local

logger = get_logger('new_report')

new_report_bp = Blueprint('new_report', __name__)


def _parse_owner_param() -> str:
    owner_id = request.args.get('owner', 'all')
    if owner_id == '':
        owner_id = 'all'
    return owner_id


def _parse_mode_param() -> str:
    mode = request.args.get('mode', 'all') or 'all'
    if mode not in ('all', 'online', 'offline'):
        mode = 'all'
    return mode


@new_report_bp.route('/daily')
@roles_accepted('gicho', 'kancho')
def daily_report():
    """开播新日报页面。"""
    date_str = request.args.get('date')
    if not date_str:
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_date = today_local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        report_date = get_local_date_from_string(date_str)
        if not report_date:
            logger.error('无效的新日报日期参数：%s', date_str)
            return '无效的日期格式', 400
        report_date = report_date.replace(hour=0, minute=0, second=0, microsecond=0)

    owner_id = _parse_owner_param()
    mode = _parse_mode_param()

    logger.info('访问开播新日报页面，报表日期：%s，直属运营：%s，开播方式：%s', report_date.strftime('%Y-%m-%d'), owner_id, mode)

    pagination = {
        'date': report_date.strftime('%Y-%m-%d'),
        'prev_date': (report_date - timedelta(days=1)).strftime('%Y-%m-%d'),
        'next_date': (report_date + timedelta(days=1)).strftime('%Y-%m-%d')
    }

    return render_template('new_reports/daily.html', pagination=pagination, selected_owner=owner_id, selected_mode=mode)


@new_report_bp.route('/daily/export.csv')
@roles_accepted('gicho', 'kancho')
def export_daily_csv():
    """导出开播新日报 CSV。"""
    date_str = request.args.get('date')
    if not date_str:
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_date = today_local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        report_date = get_local_date_from_string(date_str)
        if not report_date:
            logger.error('无效的新日报日期参数：%s', date_str)
            return '无效的日期格式', 400
        report_date = report_date.replace(hour=0, minute=0, second=0, microsecond=0)

    owner_id = _parse_owner_param()
    mode = _parse_mode_param()

    logger.info('导出开播新日报 CSV，报表日期：%s，直属运营：%s，开播方式：%s', report_date.strftime('%Y-%m-%d'), owner_id, mode)

    details = calculate_daily_details(report_date, owner_id, mode)

    output = io.StringIO()
    writer = csv.writer(output)
    output.write('\ufeff')

    headers = [
        '主播', '性别年龄', '直属运营', '主播分类', '开播地点', '播时(小时)', '状态', '流水(元)', '当前分成比例(%)', '主播分成(元)', '公司分成(元)', '底薪(元)', '当日毛利(元)', '3日平均流水(元)', '月累计天数', '月日均播时(小时)',
        '月累计流水(元)', '月累计主播分成(元)', '月累计公司分成(元)', '月累计底薪(元)', '月累计毛利(元)'
    ]
    writer.writerow(headers)

    for detail in details:
        row = [
            detail['pilot_display'], detail['gender_age'], detail['owner'], detail['rank'], detail['battle_area'], f"{detail['duration']:.1f}",
            detail['status_display'], f"{detail['revenue']:.2f}", f"{detail['commission_rate']:.0f}", f"{detail['pilot_share']:.2f}",
            f"{detail['company_share']:.2f}", f"{detail['base_salary']:.2f}", f"{detail['daily_profit']:.2f}",
            f"{detail['three_day_avg_revenue']:.2f}" if detail['three_day_avg_revenue'] else "", detail['monthly_stats']['month_days_count'],
            f"{detail['monthly_stats']['month_avg_duration']:.1f}", f"{detail['monthly_stats']['month_total_revenue']:.2f}",
            f"{detail['monthly_commission_stats']['month_total_pilot_share']:.2f}", f"{detail['monthly_commission_stats']['month_total_company_share']:.2f}",
            f"{detail['monthly_stats']['month_total_base_salary']:.2f}", f"{detail['monthly_commission_stats']['month_total_profit']:.2f}"
        ]
        writer.writerow(row)

    csv_content = output.getvalue()
    output.close()

    filename = f"开播新日报_{report_date.strftime('%Y%m%d')}.csv"
    encoded_filename = quote(filename.encode('utf-8'))

    response = Response(csv_content, mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename*=UTF-8\'\'{encoded_filename}'})
    return response


@new_report_bp.route('/weekly')
@roles_accepted('gicho', 'kancho')
def weekly_report():
    """开播新周报页面。"""
    week_start_str = request.args.get('week_start')
    if week_start_str:
        week_start_local = get_local_date_from_string_safe(week_start_str)
        if not week_start_local:
            logger.error('无效的新周报周起始参数：%s', week_start_str)
            return '无效的周起始格式', 400
        week_start_local = get_week_start_tuesday(week_start_local)
    else:
        week_start_local = get_default_week_start_for_now_prev_week()

    owner_id = _parse_owner_param()
    mode = _parse_mode_param()

    logger.info('访问开播新周报页面，周二起始：%s，直属运营：%s，开播方式：%s', week_start_local.strftime('%Y-%m-%d'), owner_id, mode)

    pagination = {
        'week_start': week_start_local.strftime('%Y-%m-%d'),
        'prev_week_start': (week_start_local - timedelta(days=7)).strftime('%Y-%m-%d'),
        'next_week_start': (week_start_local + timedelta(days=7)).strftime('%Y-%m-%d'),
    }

    return render_template('new_reports/weekly.html', pagination=pagination, selected_owner=owner_id, selected_mode=mode)


@new_report_bp.route('/weekly/export.csv')
@roles_accepted('gicho', 'kancho')
def export_weekly_csv():
    """导出开播新周报 CSV。"""
    week_start_str = request.args.get('week_start')
    if week_start_str:
        week_start_local = get_local_date_from_string_safe(week_start_str)
        if not week_start_local:
            logger.error('无效的新周报周起始参数：%s', week_start_str)
            return '无效的周起始格式', 400
        week_start_local = get_week_start_tuesday(week_start_local)
    else:
        week_start_local = get_default_week_start_for_now_prev_week()

    owner_id = _parse_owner_param()
    mode = _parse_mode_param()

    logger.info('导出开播新周报 CSV，周二起始：%s，直属运营：%s，开播方式：%s', week_start_local.strftime('%Y-%m-%d'), owner_id, mode)

    summary = calculate_weekly_summary(week_start_local, owner_id, mode)
    details = calculate_weekly_details(week_start_local, owner_id, mode)

    output = io.StringIO()
    writer = csv.writer(output)
    output.write('\ufeff')

    writer.writerow(['汇总指标'])
    writer.writerow(['主播数', summary['pilot_count']])
    writer.writerow(['总流水(元)', f"{summary['revenue_sum']:.2f}"])
    writer.writerow(['总底薪(元)', f"{summary['basepay_sum']:.2f}"])
    writer.writerow(['主播分成(元)', f"{summary['pilot_share_sum']:.2f}"])
    writer.writerow(['公司分成(元)', f"{summary['company_share_sum']:.2f}"])
    writer.writerow(['7日毛利(元)', f"{summary['profit_7d']:.2f}"])
    writer.writerow(['底薪转化率(%)', summary['conversion_rate'] or ''])
    writer.writerow([])

    headers = ['主播', '性别年龄', '直属运营', '主播分类', '开播记录数', '平均播时(小时)', '总流水(元)', '主播分成(元)', '公司分成(元)', '底薪(元)', '毛利(元)']
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

    filename = f"开播新周报_{week_start_local.strftime('%Y%m%d')}.csv"
    encoded_filename = quote(filename.encode('utf-8'))

    response = Response(csv_content, mimetype='text/csv; charset=utf-8', headers={'Content-Disposition': f'attachment; filename*=UTF-8\'\'{encoded_filename}'})
    return response
