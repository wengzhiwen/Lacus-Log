# -*- coding: utf-8 -*-
"""主播招募日报 REST API。"""
from datetime import timedelta

from flask import Blueprint, jsonify, request

from routes.report import get_local_date_from_string
from utils.jwt_roles import jwt_roles_accepted
from utils.logging_setup import get_logger
from utils.recruit_report_serializers import (METRIC_LABELS, RANGE_LABELS, build_daily_detail_payload, build_daily_summary_payload)
from utils.recruit_serializers import (create_error_response, create_success_response)
from utils.recruit_stats import (calculate_recruit_daily_stats, get_recruit_records_for_detail)
from utils.timezone_helper import get_current_utc_time, utc_to_local

logger = get_logger('recruit_reports_api')

recruit_reports_api_bp = Blueprint('recruit_reports_api', __name__)


@recruit_reports_api_bp.route('/api/recruit-reports/daily', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def get_recruit_daily_report():
    """返回招募日报汇总或详情数据。"""
    date_str = request.args.get('date')
    view = request.args.get('view', 'summary') or 'summary'
    recruiter_id = request.args.get('recruiter', 'all') or 'all'

    if date_str:
        report_date = get_local_date_from_string(date_str)
        if not report_date:
            logger.error('招募日报日期参数无效：%s', date_str)
            return jsonify(create_error_response('INVALID_DATE', '无效的日期格式')), 400
        report_date = report_date.replace(hour=0, minute=0, second=0, microsecond=0)
    else:
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_date = today_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if view not in ('summary', 'detail'):
        logger.error('未知的招募日报视图参数：%s', view)
        return jsonify(create_error_response('INVALID_VIEW', 'view 参数仅支持 summary/detail')), 400

    logger.info('获取招募日报数据，日期=%s，视图=%s，招募负责人=%s', report_date.strftime('%Y-%m-%d'), view, recruiter_id)

    pagination = {
        'date': report_date.strftime('%Y-%m-%d'),
        'prev_date': (report_date - timedelta(days=1)).strftime('%Y-%m-%d'),
        'next_date': (report_date + timedelta(days=1)).strftime('%Y-%m-%d'),
    }

    if view == 'summary':
        stats = calculate_recruit_daily_stats(report_date, recruiter_id)
        data = build_daily_summary_payload(report_date, stats)
        data['pagination'] = pagination
        meta = {
            'filters': {
                'recruiter': recruiter_id,
            },
            'labels': {
                'ranges': RANGE_LABELS,
                'metrics': METRIC_LABELS,
            }
        }
        return jsonify(create_success_response(data, meta))

    range_param = request.args.get('range')
    metric = request.args.get('metric')

    if range_param not in RANGE_LABELS:
        logger.error('招募日报详情 range 参数无效：%s', range_param)
        return jsonify(create_error_response('INVALID_RANGE', '无效的 range 参数')), 400

    if metric not in METRIC_LABELS:
        logger.error('招募日报详情 metric 参数无效：%s', metric)
        return jsonify(create_error_response('INVALID_METRIC', '无效的 metric 参数')), 400

    recruits = get_recruit_records_for_detail(report_date, range_param, metric, recruiter_id)
    data = build_daily_detail_payload(report_date, range_param, metric, recruits)
    data['pagination'] = pagination

    meta = {
        'filters': {
            'recruiter': recruiter_id,
        },
        'labels': {
            'range': RANGE_LABELS[range_param],
            'metric': METRIC_LABELS[metric],
        }
    }

    return jsonify(create_success_response(data, meta))
