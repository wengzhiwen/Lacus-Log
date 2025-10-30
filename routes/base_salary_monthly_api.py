# pylint: disable=duplicate-code
"""底薪月报REST API路由"""

from datetime import timedelta
import io
import csv
from urllib.parse import quote

from flask import Blueprint, Response, jsonify, request

from utils.jwt_roles import jwt_roles_accepted
from utils.logging_setup import get_logger
from utils.base_salary_monthly_calculations import calculate_base_salary_monthly_report, get_local_month_from_string
from utils.base_salary_monthly_serializers import (create_error_response, create_success_response, serialize_base_salary_monthly_report, prepare_csv_data)
from utils.timezone_helper import get_current_utc_time, utc_to_local

logger = get_logger('base_salary_monthly_api')

base_salary_monthly_api_bp = Blueprint('base_salary_monthly_api', __name__)


def _parse_mode_param() -> str:
    """解析开播方式参数"""
    mode = request.args.get('mode', 'offline') or 'offline'
    if mode not in ('all', 'online', 'offline'):
        logger.warning('非法开播方式参数：%s，已回退到 offline', mode)
        return 'offline'
    return mode


def _parse_settlement_param() -> str:
    """解析结算方式参数"""
    settlement = request.args.get('settlement', 'monthly_base') or 'monthly_base'
    if settlement not in ('all', 'daily_base', 'monthly_base', 'none'):
        logger.warning('非法结算方式参数：%s，已回退到 monthly_base', settlement)
        return 'monthly_base'
    return settlement


@base_salary_monthly_api_bp.route('/base-salary-monthly', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def base_salary_monthly_data():
    """返回底薪月报数据"""
    month_str = request.args.get('month')
    if not month_str:
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_month = today_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        report_month = get_local_month_from_string(month_str)
        if not report_month:
            logger.error('无效的底薪月报月份参数：%s', month_str)
            return jsonify(create_error_response('INVALID_MONTH', '无效的月份格式')), 400
        report_month = report_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    mode = _parse_mode_param()
    settlement = _parse_settlement_param()

    logger.info('获取底薪月报数据，月份：%s，开播方式：%s，结算方式：%s', report_month.strftime('%Y-%m'), mode, settlement)

    try:
        # 计算月报数据
        details_raw, summary_raw = calculate_base_salary_monthly_report(report_month.year, report_month.month, mode, settlement)

        # 构建导航信息
        prev_month_ref = (report_month.replace(day=1) - timedelta(days=1)).replace(day=1)
        next_month_ref = (report_month.replace(day=28) + timedelta(days=4)).replace(day=1)

        pagination = {
            'month': report_month.strftime('%Y-%m'),
            'prev_month': prev_month_ref.strftime('%Y-%m'),
            'next_month': next_month_ref.strftime('%Y-%m'),
        }

        # 序列化数据
        data = serialize_base_salary_monthly_report(pagination['month'], details_raw, summary_raw, pagination)

        meta = {'filters': {'mode': mode, 'settlement': settlement}}

        return jsonify(create_success_response(data, meta))

    except Exception as e:
        logger.exception('获取底薪月报数据时发生错误：%s', str(e))
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@base_salary_monthly_api_bp.route('/base-salary-monthly/export.csv', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def export_base_salary_monthly_csv():
    """导出底薪月报CSV数据"""
    month_str = request.args.get('month')
    if not month_str:
        now_utc = get_current_utc_time()
        today_local = utc_to_local(now_utc)
        report_month = today_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    else:
        report_month = get_local_month_from_string(month_str)
        if not report_month:
            logger.error('无效的底薪月报月份参数：%s', month_str)
            return '无效的月份格式', 400
        report_month = report_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

    mode = _parse_mode_param()
    settlement = _parse_settlement_param()

    logger.info('导出底薪月报CSV，月份：%s，开播方式：%s，结算方式：%s', report_month.strftime('%Y-%m'), mode, settlement)

    try:
        # 计算所有数据（不分页）
        details_raw, summary_raw = calculate_base_salary_monthly_report(report_month.year, report_month.month, mode, settlement)

        # 准备CSV数据
        csv_rows = prepare_csv_data(details_raw, summary_raw)

        # 生成CSV内容
        output = io.StringIO()
        writer = csv.writer(output)
        output.write('\ufeff')  # 添加BOM以支持中文

        for row in csv_rows:
            writer.writerow(row)

        csv_content = output.getvalue()
        output.close()

        # 生成文件名
        now = utc_to_local(get_current_utc_time())
        timestamp = now.strftime('%Y%m%d_%H%M%S')
        filename = f"底薪月报_{report_month.strftime('%Y%m')}_{timestamp}.csv"
        encoded_filename = quote(filename.encode('utf-8'))

        # 构建响应
        response = Response(csv_content,
                            mimetype='text/csv; charset=utf-8',
                            headers={
                                'Content-Disposition': f'attachment; filename*=UTF-8\'\'{encoded_filename}',
                                'Cache-Control': 'no-cache, no-store, must-revalidate',
                                'Pragma': 'no-cache',
                                'Expires': '0'
                            })

        logger.info('底薪月报CSV导出完成，文件名：%s，数据行数：%d', filename, len(csv_rows))
        return response

    except Exception as e:
        logger.exception('导出底薪月报CSV时发生错误：%s', str(e))
        return '服务器内部错误', 500
