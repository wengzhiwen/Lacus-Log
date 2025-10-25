# pylint: disable=duplicate-code
"""开播新月报（加速版）REST API。"""

from datetime import timedelta

from flask import Blueprint, jsonify, request

from utils.jwt_roles import jwt_roles_accepted
from utils.logging_setup import get_logger
from utils.new_report_fast_calculations import calculate_monthly_report_fast
from utils.new_report_serializers import (create_error_response, create_success_response, serialize_monthly_daily_series, serialize_monthly_details,
                                          serialize_monthly_summary)
from utils.new_report_calculations import get_local_month_from_string
from utils.timezone_helper import get_current_utc_time, utc_to_local

logger = get_logger('new_reports_fast_api')

new_reports_fast_api_bp = Blueprint('new_reports_fast_api', __name__)


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


@new_reports_fast_api_bp.route('/monthly', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def monthly_report_data_fast():
    """返回开播新月报（加速版）数据。"""
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

    logger.info('获取开播新月报（加速版）数据，月份：%s，直属运营：%s，开播方式：%s', report_month.strftime('%Y-%m'), owner_id, mode)

    summary_raw, details_raw, daily_series_raw = calculate_monthly_report_fast(report_month.year, report_month.month, owner_id, mode)

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
        'daily_series': serialize_monthly_daily_series(daily_series_raw),
        'pagination': pagination,
    }

    meta = {
        'filters': {
            'owner': owner_id,
            'mode': mode,
        }
    }

    return jsonify(create_success_response(data, meta))
