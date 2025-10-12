# -*- coding: utf-8 -*-
"""
招募操作记录工具模块
用于记录招募相关操作日志
"""
# pylint: disable=no-member

from typing import List, Optional

from flask import request
from mongoengine import DoesNotExist

from models.pilot import Pilot
from models.recruit import Recruit, RecruitOperationLog, RecruitOperationType
from models.user import User
from utils.logging_setup import get_logger
from utils.timezone_helper import utc_to_local

logger = get_logger('recruit_operation')


def record_recruit_operation(user_id: str, operation_type: RecruitOperationType, recruit_id: str, pilot_id: str, ip_address: Optional[str] = None):
    """
    记录招募操作日志

    Args:
        user_id: 用户ID
        operation_type: 操作类型 (RecruitOperationType)
        recruit_id: 招募记录ID
        pilot_id: 主播ID
        ip_address: IP地址
    """
    try:
        # 获取用户信息
        user = User.objects.get(id=user_id)

        # 获取招募记录信息
        recruit = Recruit.objects.get(id=recruit_id)

        # 获取主播信息
        pilot = Pilot.objects.get(id=pilot_id)

        # 获取IP地址
        if ip_address is None:
            ip_address = request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR')

        # 创建操作记录
        operation_log = RecruitOperationLog(user_id=user, operation_type=operation_type, recruit_id=recruit, pilot_id=pilot, ip_address=ip_address)

        operation_log.save()

        logger.info('记录招募操作：用户=%s，操作=%s，主播=%s，招募=%s', user.nickname or user.username, operation_type.value, pilot.nickname, recruit.id)

        # 推送实时事件（SSE）
        try:
            from utils.recruit_event_stream import publish_recruit_operation_event

            operation_data = serialize_recruit_operation(operation_log)
            publish_recruit_operation_event(operation_data)
        except Exception as exc:
            logger.warning('推送招募操作事件失败: %s', str(exc))

        return operation_log

    except DoesNotExist as e:
        logger.error('记录招募操作失败，相关数据不存在: %s', str(e))
        return None
    except Exception as e:
        logger.error('记录招募操作异常: %s', str(e), exc_info=True)
        return None


def get_recent_recruit_operations(limit: int = 10) -> List[RecruitOperationLog]:
    """
    获取最近的招募操作记录

    Args:
        limit: 返回记录数量限制

    Returns:
        list: 操作记录列表
    """
    try:
        operations = RecruitOperationLog.objects.order_by('-operation_time').limit(limit)
        return list(operations)
    except Exception as e:
        logger.error('获取招募操作记录失败: %s', str(e), exc_info=True)
        return []


def serialize_recruit_operation(operation: RecruitOperationLog) -> dict:
    """
    序列化招募操作记录

    Args:
        operation: RecruitOperationLog对象

    Returns:
        dict: 序列化后的操作记录
    """
    # 直接使用模型的属性，确保时间显示为GMT+8
    return {
        'id': str(operation.id),
        'user_id': str(operation.user_id.id),
        'user_nickname': operation.user_nickname,
        'operation_type': operation.operation_type.value,
        'operation_time_utc': operation.operation_time.isoformat() if operation.operation_time else None,
        'operation_time_gmt8': operation.operation_time_gmt8,
        'operation_time_gmt8_iso': utc_to_local(operation.operation_time).isoformat() if operation.operation_time else None,
        'recruit_id': str(operation.recruit_id.id),
        'pilot_id': str(operation.pilot_id.id),
        'pilot_nickname': operation.pilot_nickname,
        'ip_address': operation.ip_address
    }


def serialize_recruit_operation_list(operations: List[RecruitOperationLog]) -> list[dict]:
    """
    序列化招募操作记录列表

    Args:
        operations: RecruitOperationLog对象列表

    Returns:
        list: 序列化后的操作记录列表
    """
    return [serialize_recruit_operation(op) for op in operations]
