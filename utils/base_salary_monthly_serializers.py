# pylint: disable=duplicate-code
"""底薪月报数据序列化工具"""

from typing import List, Dict, Any, Optional


def create_success_response(data: Any, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建成功响应格式"""
    response = {"success": True, "data": data, "error": None}
    if meta:
        response["meta"] = meta
    else:
        response["meta"] = {}
    return response


def create_error_response(code: str, message: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建错误响应格式"""
    response = {"success": False, "data": None, "error": {"code": code, "message": message}}
    if meta:
        response["meta"] = meta
    else:
        response["meta"] = {}
    return response


def serialize_base_salary_monthly_details(details: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    序列化底薪月报明细数据

    Args:
        details: 原始明细数据列表

    Returns:
        List[Dict]: 序列化后的明细数据
    """
    serialized = []
    for detail in details:
        serialized_detail = {
            'record_id': detail.get('record_id', ''),
            'pilot_nickname': detail.get('pilot_nickname', ''),
            'pilot_real_name': detail.get('pilot_real_name', ''),
            'start_time': detail.get('start_time', ''),
            'duration_hours': detail.get('duration_hours', 0),
            'revenue_amount': detail.get('revenue_amount', 0),
            'work_mode': detail.get('work_mode', ''),
            'owner_name': detail.get('owner_name', ''),
            'application_id': detail.get('application_id', ''),
            'application_time': detail.get('application_time', ''),
            'application_amount': detail.get('application_amount', 0),
            'settlement_type': detail.get('settlement_type', ''),
            'settlement_type_code': detail.get('settlement_type_code', ''),
            'application_status': detail.get('application_status', ''),
            'application_status_code': detail.get('application_status_code', ''),
            'is_duplicate': detail.get('is_duplicate', False),
            'applicant_name': detail.get('applicant_name', '')
        }
        serialized.append(serialized_detail)
    return serialized


def serialize_base_salary_monthly_summary(summary: Dict[str, Any]) -> Dict[str, Any]:
    """
    序列化底薪月报汇总数据

    Args:
        summary: 原始汇总数据

    Returns:
        Dict: 序列化后的汇总数据
    """
    return {
        'total_records': summary.get('total_records', 0),
        'total_revenue': summary.get('total_revenue', 0),
        'total_base_salary': summary.get('total_base_salary', 0),
        'application_count': summary.get('application_count', 0),
        'approved_count': summary.get('approved_count', 0),
        'approved_amount': summary.get('approved_amount', 0),
        'pending_count': summary.get('pending_count', 0),
        'rejected_count': summary.get('rejected_count', 0)
    }


def serialize_base_salary_monthly_report(month: str, details: List[Dict[str, Any]], summary: Dict[str, Any], pagination: Dict[str, Any]) -> Dict[str, Any]:
    """
    序列化完整的底薪月报数据

    Args:
        month: 报告月份
        details: 明细数据
        summary: 汇总数据
        pagination: 分页信息

    Returns:
        Dict: 序列化后的完整报告数据
    """
    return {
        'month': month,
        'summary': serialize_base_salary_monthly_summary(summary),
        'details': serialize_base_salary_monthly_details(details),
        'pagination': pagination
    }


def prepare_csv_data(details: List[Dict[str, Any]], summary: Dict[str, Any]) -> List[List[str]]:
    """
    准备CSV导出数据

    Args:
        details: 明细数据列表
        summary: 汇总数据

    Returns:
        List[List[str]]: CSV格式的数据行
    """
    csv_data = []

    # 汇总数据行
    csv_data.append(['底薪月报汇总'])
    csv_data.append(['开播记录总数', str(summary.get('total_records', 0))])
    csv_data.append(['总流水金额(元)', f"{summary.get('total_revenue', 0):.2f}"])
    csv_data.append(['总底薪申请金额(元)', f"{summary.get('total_base_salary', 0):.2f}"])
    csv_data.append(['底薪申请数量', str(summary.get('application_count', 0))])
    csv_data.append(['已发放申请数量', str(summary.get('approved_count', 0))])
    csv_data.append(['已发放金额(元)', f"{summary.get('approved_amount', 0):.2f}"])
    csv_data.append(['待处理申请数量', str(summary.get('pending_count', 0))])
    csv_data.append(['拒绝发放数量', str(summary.get('rejected_count', 0))])
    csv_data.append([])  # 空行

    # 明细数据标题行
    headers = ['主播昵称', '真实姓名', '开播时间', '开播时长(小时)', '流水金额(元)', '开播方式', '直属运营', '申请时间', '申请金额(元)', '结算方式', '申请状态', '申请人', '是否重复申请']
    csv_data.append(headers)

    # 明细数据行
    for detail in details:
        row = [
            detail.get('pilot_nickname', ''),
            detail.get('pilot_real_name', ''),
            detail.get('start_time', ''),
            str(detail.get('duration_hours', 0)), f"{detail.get('revenue_amount', 0):.2f}",
            detail.get('work_mode', ''),
            detail.get('owner_name', ''),
            detail.get('application_time', ''), f"{detail.get('application_amount', 0):.2f}",
            detail.get('settlement_type', ''),
            detail.get('application_status', ''),
            detail.get('applicant_name', ''), '是' if detail.get('is_duplicate', False) else '否'
        ]
        csv_data.append(row)

    return csv_data
