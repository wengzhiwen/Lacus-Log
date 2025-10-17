"""
底薪申请管理数据序列化工具
提供底薪申请记录、变更日志等对象的JSON序列化功能
"""

from typing import Any, Dict, List, Optional

from models.battle_record import BaseSalaryApplication, BaseSalaryApplicationChangeLog
from utils.timezone_helper import utc_to_local


def serialize_base_salary_application(application: BaseSalaryApplication) -> Dict[str, Any]:
    """序列化单个底薪申请记录"""
    pilot_data = None
    if application.pilot_id:
        pilot = application.pilot_id
        pilot_data = {
            'id': str(pilot.id),
            'nickname': pilot.nickname,
            'real_name': pilot.real_name,
            'owner': {
                'id': str(pilot.owner.id),
                'nickname': pilot.owner.nickname,
            } if pilot.owner else None,
        }

    battle_record_data = None
    if application.battle_record_id:
        try:
            br = application.battle_record_id
            battle_record_data = {
                'id': str(br.id),
                'start_time': utc_to_local(br.start_time).isoformat() if br.start_time else None,
                'end_time': utc_to_local(br.end_time).isoformat() if br.end_time else None,
                'revenue_amount': str(br.revenue_amount) if br.revenue_amount else '0.00',
                'duration_hours': br.duration_hours,
            }
        except Exception:  # noqa: BLE001
            battle_record_data = {'id': str(application.battle_record_id.id)} if application.battle_record_id else None

    applicant_data = None
    if application.applicant_id:
        applicant = application.applicant_id
        applicant_data = {
            'id': str(applicant.id),
            'nickname': applicant.nickname,
        }

    return {
        'id': str(application.id),
        'pilot': pilot_data,
        'pilot_id': str(application.pilot_id.id) if application.pilot_id else None,
        'battle_record': battle_record_data,
        'battle_record_id': str(application.battle_record_id.id) if application.battle_record_id else None,
        'settlement_type': application.settlement_type,
        'base_salary_amount': str(application.base_salary_amount),
        'applicant': applicant_data,
        'applicant_id': str(application.applicant_id.id) if application.applicant_id else None,
        'status': application.status.value if application.status else None,
        'status_display': application.status_display,
        'created_at': utc_to_local(application.created_at).isoformat() if application.created_at else None,
        'updated_at': utc_to_local(application.updated_at).isoformat() if application.updated_at else None,
    }


def serialize_base_salary_application_list(applications: List[BaseSalaryApplication]) -> List[Dict[str, Any]]:
    """序列化底薪申请记录列表"""
    return [serialize_base_salary_application(app) for app in applications]


def serialize_base_salary_application_change_log(log: BaseSalaryApplicationChangeLog) -> Dict[str, Any]:
    """序列化单个底薪申请变更记录"""
    return {
        'id': str(log.id),
        'application_id': str(log.application_id.id) if log.application_id else None,
        'field_name': log.field_name,
        'field_display_name': log.field_display_name,
        'old_value': log.old_value,
        'new_value': log.new_value,
        'remark': log.remark,
        'user': {
            'id': str(log.user_id.id),
            'nickname': log.user_id.nickname,
        } if log.user_id else None,
        'ip_address': log.ip_address,
        'change_time': utc_to_local(log.change_time).isoformat() if log.change_time else None,
    }


def serialize_base_salary_application_change_log_list(logs: List[BaseSalaryApplicationChangeLog]) -> List[Dict[str, Any]]:
    """序列化底薪申请变更记录列表"""
    return [serialize_base_salary_application_change_log(log) for log in logs]


def create_success_response(data: Any, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建成功响应格式"""
    return {"success": True, "data": data, "error": None, "meta": meta or {}}


def create_error_response(code: str, message: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建错误响应格式"""
    return {"success": False, "data": None, "error": {"code": code, "message": message}, "meta": meta or {}}
