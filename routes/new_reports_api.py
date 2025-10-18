# -*- coding: utf-8 -*-
"""开播新日报/周报/月报 REST API 路由集合。"""

from datetime import timedelta

from flask import Blueprint, jsonify, request

from utils.cache_helper import clear_daily_report_cache
from utils.jwt_roles import jwt_roles_accepted
from utils.logging_setup import get_logger
from utils.new_report_calculations import (calculate_daily_details, calculate_daily_summary, calculate_monthly_details, calculate_monthly_summary,
                                           calculate_weekly_details, calculate_weekly_summary, get_default_week_start_for_now_prev_week,
                                           get_local_date_from_string, get_local_date_from_string_safe, get_local_month_from_string, get_week_start_tuesday)
from utils.new_report_serializers import (create_error_response, create_success_response, serialize_daily_details, serialize_daily_summary,
                                          serialize_monthly_details, serialize_monthly_summary, serialize_weekly_details, serialize_weekly_summary)
from utils.timezone_helper import get_current_utc_time, utc_to_local

logger = get_logger('new_reports_api')

new_reports_api_bp = Blueprint('new_reports_api', __name__)


def _parse_owner_param() -> str:
    owner_id = request.args.get('owner', 'all')
    if owner_id in (None, ''):
        return 'all'
    return owner_id


def _parse_mode_param() -> str:
    mode = request.args.get('mode', 'all') or 'all'
    if mode not in ('all', 'online', 'offline'):
        logger.warning('非法开播方式参数：%s，已回退到 all', mode)
        return 'all'
    return mode


@new_reports_api_bp.route('/daily', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def daily_report_data():
    """返回开播新日报数据。"""
    date_str = request.args.get('date')
    if not date_str:
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_date = today_local.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        report_date = get_local_date_from_string(date_str)
        if not report_date:
            logger.error('无效的新日报日期参数：%s', date_str)
            return jsonify(create_error_response('INVALID_DATE', '无效的日期格式')), 400
        report_date = report_date.replace(hour=0, minute=0, second=0, microsecond=0)

    owner_id = _parse_owner_param()
    mode = _parse_mode_param()

    logger.info('获取开播新日报数据，日期：%s，直属运营：%s，开播方式：%s', report_date.strftime('%Y-%m-%d'), owner_id, mode)

    summary_raw = calculate_daily_summary(report_date, owner_id, mode)
    details_raw = calculate_daily_details(report_date, owner_id, mode)

    pagination = {
        'date': report_date.strftime('%Y-%m-%d'),
        'prev_date': (report_date - timedelta(days=1)).strftime('%Y-%m-%d'),
        'next_date': (report_date + timedelta(days=1)).strftime('%Y-%m-%d'),
    }

    data = {
        'date': pagination['date'],
        'summary': serialize_daily_summary(summary_raw),
        'details': serialize_daily_details(details_raw),
        'pagination': pagination,
    }

    meta = {
        'filters': {
            'owner': owner_id,
            'mode': mode,
        }
    }

    return jsonify(create_success_response(data, meta))


@new_reports_api_bp.route('/daily/cache/refresh', methods=['POST'])
@jwt_roles_accepted('gicho', 'kancho')
def refresh_daily_report_cache():
    """刷新开播新日报缓存。"""
    logger.info('收到开播新日报缓存刷新请求')
    try:
        clear_daily_report_cache()
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('刷新开播新日报缓存失败：%s', exc)
        return jsonify(create_error_response('CACHE_REFRESH_FAILED', '刷新开播新日报缓存失败，请稍后重试')), 500

    return jsonify(create_success_response({'message': '开播新日报缓存已刷新'})), 200


@new_reports_api_bp.route('/weekly', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def weekly_report_data():
    """返回开播新周报数据（周二-次周一）。"""
    week_start_str = request.args.get('week_start')
    if week_start_str:
        week_start_local = get_local_date_from_string_safe(week_start_str)
        if not week_start_local:
            logger.error('无效的新周报周起始参数：%s', week_start_str)
            return jsonify(create_error_response('INVALID_WEEK_START', '无效的周起始格式')), 400
        week_start_local = get_week_start_tuesday(week_start_local)
    else:
        week_start_local = get_default_week_start_for_now_prev_week()

    owner_id = _parse_owner_param()
    mode = _parse_mode_param()

    logger.info('获取开播新周报数据，周二起始：%s，直属运营：%s，开播方式：%s', week_start_local.strftime('%Y-%m-%d'), owner_id, mode)

    summary_raw = calculate_weekly_summary(week_start_local, owner_id, mode)
    details_raw = calculate_weekly_details(week_start_local, owner_id, mode)

    pagination = {
        'week_start': week_start_local.strftime('%Y-%m-%d'),
        'prev_week_start': (week_start_local - timedelta(days=7)).strftime('%Y-%m-%d'),
        'next_week_start': (week_start_local + timedelta(days=7)).strftime('%Y-%m-%d'),
    }

    data = {
        'week_start': pagination['week_start'],
        'summary': serialize_weekly_summary(summary_raw),
        'details': serialize_weekly_details(details_raw),
        'pagination': pagination,
    }

    meta = {
        'filters': {
            'owner': owner_id,
            'mode': mode,
        }
    }

    return jsonify(create_success_response(data, meta))


@new_reports_api_bp.route('/monthly', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def monthly_report_data():
    """返回开播新月报数据。"""
    month_str = request.args.get('month')
    if not month_str:
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_month = today_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        report_month = get_local_month_from_string(month_str)
        if not report_month:
            logger.error('无效的新月报月份参数：%s', month_str)
            return jsonify(create_error_response('INVALID_MONTH', '无效的月份格式')), 400
        report_month = report_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    owner_id = _parse_owner_param()
    mode = _parse_mode_param()

    logger.info('获取开播新月报数据，月份：%s，直属运营：%s，开播方式：%s', report_month.strftime('%Y-%m'), owner_id, mode)

    summary_raw = calculate_monthly_summary(report_month.year, report_month.month, owner_id, mode)
    details_raw = calculate_monthly_details(report_month.year, report_month.month, owner_id, mode)

    prev_month_ref = (report_month.replace(day=1) - timedelta(days=1)).replace(day=1)
    next_month_ref = (report_month.replace(day=28) + timedelta(days=4)).replace(day=1)

    pagination = {
        'month': report_month.strftime('%Y-%m'),
        'prev_month': prev_month_ref.strftime('%Y-%m'),
        'next_month': next_month_ref.strftime('%Y-%m'),
    }

    data = {
        'month': pagination['month'],
        'summary': serialize_monthly_summary(summary_raw),
        'details': serialize_monthly_details(details_raw),
        'pagination': pagination,
    }

    meta = {
        'filters': {
            'owner': owner_id,
            'mode': mode,
        }
    }

    return jsonify(create_success_response(data, meta))
