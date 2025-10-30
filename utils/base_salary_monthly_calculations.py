# pylint: disable=duplicate-code,too-many-locals,too-many-nested-blocks
"""底薪月报计算逻辑模块"""

from datetime import datetime
from typing import List, Dict, Any, Tuple, Optional

from mongoengine import Q

from models.pilot import WorkMode
from models.battle_record import BattleRecord
from models.battle_record import BaseSalaryApplication
from utils.logging_setup import get_logger
from utils.timezone_helper import local_to_utc, utc_to_local

logger = get_logger('base_salary_monthly_calculations')


def calculate_base_salary_monthly_report(year: int,
                                         month: int,
                                         mode: str = 'offline',
                                         settlement: str = 'monthly_base') -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """
    计算底薪月报数据

    Args:
        year: 年份
        month: 月份
        mode: 开播方式筛选 (online/offline/all)
        settlement: 结算方式筛选 (daily_base/monthly_base/none/all)

    Returns:
        tuple: (明细数据列表, 汇总数据)
    """
    logger.info('开始计算底薪月报数据：%d-%d，开播方式：%s，结算方式：%s', year, month, mode, settlement)

    # 计算月份的起止时间（本地时间）
    month_start_local = datetime(year, month, 1, 0, 0, 0)
    if month == 12:
        month_end_local = datetime(year + 1, 1, 1, 0, 0, 0)
    else:
        month_end_local = datetime(year, month + 1, 1, 0, 0, 0)

    # 转换为UTC时间进行查询
    month_start_utc = local_to_utc(month_start_local)
    month_end_utc = local_to_utc(month_end_local)

    logger.debug('查询时间范围（UTC）：%s 至 %s', month_start_utc, month_end_utc)

    # 构建开播记录查询条件
    record_query = Q(start_time__gte=month_start_utc) & Q(start_time__lt=month_end_utc)

    # 应用开播方式筛选
    if mode == 'online':
        record_query &= Q(work_mode=WorkMode.ONLINE)
    elif mode == 'offline':
        record_query &= Q(work_mode=WorkMode.OFFLINE)

    # 查询开播记录，预取关联数据
    records = BattleRecord.objects(record_query).select_related()

    logger.info('查询到开播记录数量：%d', len(records))

    # 查询所有相关的底薪申请记录
    record_ids = [record.id for record in records]
    applications_query = Q(battle_record_id__in=record_ids)

    applications = BaseSalaryApplication.objects(applications_query).select_related()

    logger.info('查询到底薪申请数量：%d', len(applications))

    # 按开播记录分组申请数据
    applications_by_record = {}
    for app in applications:
        record_id_str = str(app.battle_record_id.id)
        if record_id_str not in applications_by_record:
            applications_by_record[record_id_str] = []
        applications_by_record[record_id_str].append(app)

    # 构建明细数据
    details = []
    for record in records:
        record_id_str = str(record.id)
        record_applications = applications_by_record.get(record_id_str, [])

        # 根据结算方式筛选决定是否跳过
        if not record_applications:
            # 没有申请记录：只有筛选"全部"或"无底薪"时才显示
            if settlement not in ('all', 'none'):
                continue
        else:
            # 有申请记录：当筛选"全部"时显示所有申请，其他时只显示符合条件的申请
            if settlement != 'all':
                has_matching_app = any(app.settlement_type == settlement for app in record_applications)
                if not has_matching_app:
                    continue

        # 计算开播时长
        duration_seconds = (record.end_time - record.start_time).total_seconds()
        duration_hours = duration_seconds / 3600.0

        # 获取主播信息
        pilot = record.pilot
        pilot_nickname = pilot.nickname if pilot else '未知主播'
        pilot_real_name = pilot.real_name if pilot and pilot.real_name else ''

        # 获取运营信息
        owner = record.owner_snapshot
        owner_name = owner.username if owner else '未知'
        # 尝试获取用户昵称作为显示名称
        if owner and hasattr(owner, 'nickname') and owner.nickname:
            owner_name = owner.nickname

        # 转换时间为本地时间显示
        start_time_local = utc_to_local(record.start_time)
        start_time_str = start_time_local.strftime('%Y-%m-%d %H:%M:%S')

        # 如果有申请记录，为每个符合条件的申请创建一行
        if record_applications:
            filtered_applications = record_applications
            if settlement != 'all':
                filtered_applications = [app for app in record_applications if app.settlement_type == settlement]

            for app in filtered_applications:
                # 判断是否为重复申请（一个开播记录多个申请）
                is_duplicate = len(record_applications) > 1

                # 申请时间转换为本地时间
                app_time_local = utc_to_local(app.created_at)
                app_time_str = app_time_local.strftime('%Y-%m-%d %H:%M:%S')

                detail_row = {
                    'record_id': record_id_str,
                    'pilot_nickname': pilot_nickname,
                    'pilot_real_name': pilot_real_name,
                    'start_time': start_time_str,
                    'duration_hours': round(duration_hours, 2),
                    'revenue_amount': float(record.revenue_amount or 0),
                    'work_mode': '线上' if record.work_mode == WorkMode.ONLINE else '线下',
                    'owner_name': owner_name,
                    'application_id': str(app.id),
                    'application_time': app_time_str,
                    'application_amount': float(app.base_salary_amount),
                    'settlement_type': app.settlement_type_display,
                    'settlement_type_code': app.settlement_type,
                    'application_status': app.status_display,
                    'application_status_code': app.status.value,
                    'is_duplicate': is_duplicate,
                    'applicant_name': app.applicant_id.username if app.applicant_id else '未知'
                }

                # 尝试获取申请人的昵称作为显示名称
                if app.applicant_id and hasattr(app.applicant_id, 'nickname') and app.applicant_id.nickname:
                    detail_row['applicant_name'] = app.applicant_id.nickname

                details.append(detail_row)
        else:
            # 没有申请记录，仍然显示开播记录
            detail_row = {
                'record_id': record_id_str,
                'pilot_nickname': pilot_nickname,
                'pilot_real_name': pilot_real_name,
                'start_time': start_time_str,
                'duration_hours': round(duration_hours, 2),
                'revenue_amount': float(record.revenue_amount or 0),
                'work_mode': '线上' if record.work_mode == WorkMode.ONLINE else '线下',
                'owner_name': owner_name,
                'application_id': '',
                'application_time': '',
                'application_amount': 0.0,
                'settlement_type': '无底薪',
                'settlement_type_code': 'none',
                'application_status': '',
                'application_status_code': '',
                'is_duplicate': False,
                'applicant_name': ''
            }
            details.append(detail_row)

    # 计算汇总数据
    summary = calculate_monthly_summary(details)

    logger.info('底薪月报计算完成，明细记录数：%d', len(details))

    return details, summary


def calculate_monthly_summary(details: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    计算月报汇总数据

    Args:
        details: 明细数据列表

    Returns:
        dict: 汇总数据
    """
    if not details:
        return {
            'total_records': 0,
            'total_revenue': 0.0,
            'total_base_salary': 0.0,
            'application_count': 0,
            'approved_count': 0,
            'approved_amount': 0.0,
            'pending_count': 0,
            'rejected_count': 0
        }

    total_records = len(set(detail['record_id'] for detail in details))  # 不重复的开播记录数
    total_revenue = sum(detail['revenue_amount'] for detail in details)
    total_base_salary = sum(detail['application_amount'] for detail in details)

    # 统计申请情况
    application_details = [detail for detail in details if detail['application_id']]
    application_count = len(application_details)

    approved_count = len([d for d in application_details if d['application_status_code'] == 'approved'])
    pending_count = len([d for d in application_details if d['application_status_code'] == 'pending'])
    rejected_count = len([d for d in application_details if d['application_status_code'] == 'rejected'])

    approved_amount = sum(d['application_amount'] for d in application_details if d['application_status_code'] == 'approved')

    summary = {
        'total_records': total_records,
        'total_revenue': round(total_revenue, 2),
        'total_base_salary': round(total_base_salary, 2),
        'application_count': application_count,
        'approved_count': approved_count,
        'approved_amount': round(approved_amount, 2),
        'pending_count': pending_count,
        'rejected_count': rejected_count
    }

    logger.debug('月报汇总数据：%s', summary)

    return summary


def get_local_month_from_string(month_str: str) -> Optional[datetime]:
    """
    从字符串解析本地月份时间

    Args:
        month_str: 月份字符串，格式为 YYYY-MM

    Returns:
        datetime: 该月1号00:00:00的本地时间，解析失败返回None
    """
    try:
        year, month = map(int, month_str.split('-'))
        return datetime(year, month, 1, 0, 0, 0)
    except (ValueError, AttributeError):
        return None
