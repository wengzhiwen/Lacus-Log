# -*- coding: utf-8 -*-
"""主播招募月报 REST API。"""
from flask import Blueprint, jsonify, request

from utils.jwt_roles import jwt_roles_accepted
from utils.logging_setup import get_logger
from utils.recruit_monthly_report_serializers import (
    MONTHLY_METRIC_LABELS, build_monthly_detail_payload,
    build_monthly_summary_payload)
from utils.recruit_serializers import (create_error_response,
                                       create_success_response)
from utils.recruit_stats import (calculate_recruit_monthly_stats,
                                 get_recruit_monthly_detail_records)

logger = get_logger('recruit_monthly_reports_api')

recruit_monthly_reports_api_bp = Blueprint('recruit_monthly_reports_api',
                                           __name__)


@recruit_monthly_reports_api_bp.route('/api/recruit-reports/monthly',
                                      methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def get_recruit_monthly_report():
    """返回招募月报汇总数据。"""
    recruiter_id = request.args.get('recruiter', 'all') or 'all'

    logger.info('获取招募月报数据，招募负责人=%s', recruiter_id)

    try:
        # 计算月报统计数据
        monthly_stats = calculate_recruit_monthly_stats(recruiter_id)

        # 构建响应数据
        data = build_monthly_summary_payload(monthly_stats)

        meta = {
            'filters': {
                'recruiter': recruiter_id,
            },
            'labels': {
                'metrics': MONTHLY_METRIC_LABELS,
            }
        }

        return jsonify(create_success_response(data, meta))

    except Exception as exc:
        logger.error('获取招募月报数据失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR',
                                             '获取月报数据失败')), 500


@recruit_monthly_reports_api_bp.route('/api/recruit-reports/monthly/detail',
                                      methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def get_recruit_monthly_detail():
    """返回招募月报明细数据。"""
    recruiter_id = request.args.get('recruiter', 'all') or 'all'

    logger.info('获取招募月报明细数据，招募负责人=%s', recruiter_id)

    try:
        # 获取月报明细记录
        recruit_data_list = get_recruit_monthly_detail_records(recruiter_id)

        # 构建响应数据
        data = build_monthly_detail_payload(recruit_data_list)

        meta = {
            'filters': {
                'recruiter': recruiter_id,
            }
        }

        return jsonify(create_success_response(data, meta))

    except Exception as exc:
        logger.error('获取招募月报明细数据失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR',
                                             '获取月报明细数据失败')), 500
