"""征召服务层模块

提供征召相关的业务逻辑服务，确保数据操作的原子性和一致性。
"""

from decimal import Decimal

from mongoengine import ValidationError

from utils.logging_setup import get_logger

logger = get_logger('recruit_service')


class RecruitServiceError(Exception):
    """征召服务异常"""
    pass


def confirm_recruit_atomic(recruit, introduction_fee, remarks, current_user, ip_address):
    """原子性确认征召
    
    确保征召状态和机师状态的更新是原子性的。如果任何一步失败，
    都会回滚到原始状态并提示用户重试。
    
    Args:
        recruit: 征召对象
        introduction_fee: 介绍费
        remarks: 备注
        current_user: 当前用户
        ip_address: IP地址
        
    Returns:
        bool: 操作是否成功
        
    Raises:
        RecruitServiceError: 服务层异常
    """
    from models.pilot import Rank, Status
    from models.recruit import RecruitStatus

    # 保存原始状态用于回滚
    original_recruit_status = recruit.status
    original_recruit_fee = recruit.introduction_fee
    original_recruit_remarks = recruit.remarks
    original_pilot_status = recruit.pilot.status
    original_pilot_rank = recruit.pilot.rank

    try:
        # 第一步：更新征召记录
        recruit.introduction_fee = introduction_fee
        recruit.remarks = remarks
        recruit.status = RecruitStatus.ENDED
        recruit.save()

        logger.debug('征召记录更新成功：ID=%s', recruit.id)

        # 第二步：更新机师状态和阶级
        recruit.pilot.rank = Rank.TRAINEE
        recruit.pilot.status = Status.RECRUITED
        recruit.pilot.save()

        logger.info('征召确认成功：ID=%s，机师=%s', recruit.id, recruit.pilot.nickname)
        return True

    except ValidationError as e:
        logger.error('征召确认验证失败：%s', str(e))
        # 回滚征召记录
        try:
            recruit.status = original_recruit_status
            recruit.introduction_fee = original_recruit_fee
            recruit.remarks = original_recruit_remarks
            recruit.save()
            logger.debug('征召记录回滚成功')
        except Exception as rollback_error:
            logger.error('征召记录回滚失败：%s', str(rollback_error))

        raise RecruitServiceError(f"数据验证失败：{str(e)}")

    except Exception as e:
        logger.error('征召确认失败：%s', str(e))
        # 回滚操作
        try:
            # 回滚机师状态
            recruit.pilot.status = original_pilot_status
            recruit.pilot.rank = original_pilot_rank
            recruit.pilot.save()

            # 回滚征召记录
            recruit.status = original_recruit_status
            recruit.introduction_fee = original_recruit_fee
            recruit.remarks = original_recruit_remarks
            recruit.save()

            logger.debug('征召确认回滚成功')
        except Exception as rollback_error:
            logger.error('征召确认回滚失败：%s', str(rollback_error))

        raise RecruitServiceError(f"征召确认失败，请重试：{str(e)}")


def abandon_recruit_atomic(recruit, current_user, ip_address):
    """原子性放弃征召
    
    确保征召状态和机师状态的更新是原子性的。
    
    Args:
        recruit: 征召对象
        current_user: 当前用户
        ip_address: IP地址
        
    Returns:
        bool: 操作是否成功
        
    Raises:
        RecruitServiceError: 服务层异常
    """
    from models.pilot import Status
    from models.recruit import RecruitStatus

    # 保存原始状态用于回滚
    original_recruit_status = recruit.status
    original_pilot_status = recruit.pilot.status

    try:
        # 第一步：更新征召记录
        recruit.status = RecruitStatus.ENDED
        recruit.save()

        logger.debug('征召记录状态更新成功：ID=%s', recruit.id)

        # 第二步：更新机师状态
        recruit.pilot.status = Status.NOT_RECRUITING
        recruit.pilot.save()

        logger.info('征召放弃成功：ID=%s，机师=%s', recruit.id, recruit.pilot.nickname)
        return True

    except ValidationError as e:
        logger.error('征召放弃验证失败：%s', str(e))
        # 回滚征召记录
        try:
            recruit.status = original_recruit_status
            recruit.save()
            logger.debug('征召记录回滚成功')
        except Exception as rollback_error:
            logger.error('征召记录回滚失败：%s', str(rollback_error))

        raise RecruitServiceError(f"数据验证失败：{str(e)}")

    except Exception as e:
        logger.error('征召放弃失败：%s', str(e))
        # 回滚操作
        try:
            # 回滚机师状态
            recruit.pilot.status = original_pilot_status
            recruit.pilot.save()

            # 回滚征召记录
            recruit.status = original_recruit_status
            recruit.save()

            logger.debug('征召放弃回滚成功')
        except Exception as rollback_error:
            logger.error('征召放弃回滚失败：%s', str(rollback_error))

        raise RecruitServiceError(f"征召放弃失败，请重试：{str(e)}")
