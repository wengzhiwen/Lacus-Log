# -*- coding: utf-8 -*-
"""主播招募月报页面路由。"""
from flask import Blueprint, render_template, request
from flask_security import roles_accepted

from utils.logging_setup import get_logger

logger = get_logger('recruit_monthly_reports')

recruit_monthly_reports_bp = Blueprint('recruit_monthly_reports', __name__)


@recruit_monthly_reports_bp.route('/recruit-reports/monthly', methods=['GET'])
@roles_accepted('gicho', 'kancho')
def monthly_report_page():
    """主播招募月报页面。"""
    try:
        # 获取URL参数
        recruiter_id = request.args.get('recruiter', 'all')

        logger.info('访问主播招募月报页面，招募负责人=%s', recruiter_id)

        return render_template('recruit_reports/monthly.html',
                               recruiter_id=recruiter_id)

    except Exception as exc:
        logger.error('访问主播招募月报页面失败：%s', exc, exc_info=True)
        return render_template('errors/500.html'), 500
