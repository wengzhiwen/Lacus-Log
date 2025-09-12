"""征召服务层模块

提供征召相关的业务逻辑服务，确保数据操作的原子性和一致性。
"""
# pylint: disable=no-member
from mongoengine import ValidationError

from models.pilot import Rank, Status, WorkMode
from models.recruit import FinalDecision, RecruitStatus, TrainingDecision
from models.user import User
from utils.logging_setup import get_logger
from utils.timezone_helper import get_current_utc_time

logger = get_logger('recruit_service')


class RecruitServiceError(Exception):
    """征召服务异常"""


def training_recruit_atomic(recruit, training_decision, training_time, pilot_basic_info, introduction_fee, remarks, current_user, _ip_address):
    """原子性训练征召
    
    执行训练征召决策，更新征召状态和机师状态。
    
    Args:
        recruit: 征召对象
        training_decision: 训练征召决策
        training_time: 训练时间（仅当决策为征召时需要）
        pilot_basic_info: 机师基本信息字典（real_name, birth_year, work_mode）
        introduction_fee: 介绍费
        remarks: 备注
        current_user: 当前用户
        _ip_address: IP地址
        
    Returns:
        bool: 操作是否成功
        
    Raises:
        RecruitServiceError: 服务层异常
    """

    # 保存原始状态用于回滚
    original_recruit_data = {
        'status': recruit.status,
        'introduction_fee': recruit.introduction_fee,
        'remarks': recruit.remarks,
        'training_decision': recruit.training_decision,
        'training_decision_maker': recruit.training_decision_maker,
        'training_decision_time': recruit.training_decision_time,
        'training_time': recruit.training_time,
    }

    original_pilot_data = {
        'rank': recruit.pilot.rank,
        'status': recruit.pilot.status,
        'real_name': recruit.pilot.real_name,
        'birth_year': recruit.pilot.birth_year,
        'work_mode': recruit.pilot.work_mode,
    }

    try:
        # 第一步：更新征召记录
        recruit.training_decision = training_decision
        recruit.training_decision_maker = current_user
        recruit.training_decision_time = get_current_utc_time()
        recruit.introduction_fee = introduction_fee
        recruit.remarks = remarks

        if training_decision == TrainingDecision.RECRUIT_AS_TRAINEE:
            recruit.status = RecruitStatus.TRAINING_RECRUITING
            recruit.training_time = training_time
        else:
            recruit.status = RecruitStatus.ENDED

        recruit.save()
        logger.debug('征召记录更新成功：ID=%s', recruit.id)

        # 第二步：更新机师信息
        if training_decision == TrainingDecision.RECRUIT_AS_TRAINEE:
            # 征召为训练机师
            recruit.pilot.rank = Rank.TRAINEE
            recruit.pilot.status = Status.RECRUITED

            # 更新机师基本信息
            if pilot_basic_info.get('real_name'):
                recruit.pilot.real_name = pilot_basic_info['real_name']
            if pilot_basic_info.get('birth_year'):
                recruit.pilot.birth_year = pilot_basic_info['birth_year']
            if pilot_basic_info.get('work_mode'):
                recruit.pilot.work_mode = WorkMode(pilot_basic_info['work_mode'])
        else:
            # 不征召
            recruit.pilot.status = Status.NOT_RECRUITING

        recruit.pilot.save()

        logger.info('训练征召成功：ID=%s，机师=%s，决策=%s', recruit.id, recruit.pilot.nickname, training_decision.value)
        return True

    except ValidationError as e:
        logger.error('训练征召验证失败：%s', str(e))
        _rollback_recruit_and_pilot(recruit, original_recruit_data, original_pilot_data)
        raise RecruitServiceError(f"数据验证失败：{str(e)}") from e

    except Exception as e:
        logger.error('训练征召失败：%s', str(e))
        _rollback_recruit_and_pilot(recruit, original_recruit_data, original_pilot_data)
        raise RecruitServiceError(f"训练征召失败，请重试：{str(e)}") from e


def final_recruit_atomic(recruit, final_decision, pilot_assignment_info, introduction_fee, remarks, current_user, _ip_address):
    """原子性结束征召
    
    执行结束征召决策，更新征召状态和机师状态。
    
    Args:
        recruit: 征召对象
        final_decision: 结束征召决策
        pilot_assignment_info: 机师分配信息字典（owner, platform）
        introduction_fee: 介绍费
        remarks: 备注
        current_user: 当前用户
        _ip_address: IP地址
        
    Returns:
        bool: 操作是否成功
        
    Raises:
        RecruitServiceError: 服务层异常
    """

    # 保存原始状态用于回滚
    original_recruit_data = {
        'status': recruit.status,
        'introduction_fee': recruit.introduction_fee,
        'remarks': recruit.remarks,
        'final_decision': recruit.final_decision,
        'final_decision_maker': recruit.final_decision_maker,
        'final_decision_time': recruit.final_decision_time,
    }

    original_pilot_data = {
        'rank': recruit.pilot.rank,
        'status': recruit.pilot.status,
        'owner': recruit.pilot.owner,
        'platform': recruit.pilot.platform,
    }

    try:
        # 第一步：更新征召记录
        recruit.final_decision = final_decision
        recruit.final_decision_maker = current_user
        recruit.final_decision_time = get_current_utc_time()
        recruit.status = RecruitStatus.ENDED
        recruit.introduction_fee = introduction_fee
        recruit.remarks = remarks
        recruit.save()

        logger.debug('征召记录更新成功：ID=%s', recruit.id)

        # 第二步：更新机师信息
        if final_decision in [FinalDecision.OFFICIAL, FinalDecision.INTERN]:
            # 征召成功，根据决策自动设置阶级
            if final_decision == FinalDecision.OFFICIAL:
                recruit.pilot.rank = Rank.OFFICIAL
            elif final_decision == FinalDecision.INTERN:
                recruit.pilot.rank = Rank.INTERN

            recruit.pilot.status = Status.RECRUITED

            # 分配所属
            if pilot_assignment_info.get('owner'):
                owner = User.objects.get(id=pilot_assignment_info['owner'])
                recruit.pilot.owner = owner

            # 设置战区
            if pilot_assignment_info.get('platform'):
                from models.pilot import Platform
                recruit.pilot.platform = Platform(pilot_assignment_info['platform'])
        else:
            # 不征召
            recruit.pilot.status = Status.NOT_RECRUITING

        recruit.pilot.save()

        logger.info('结束征召成功：ID=%s，机师=%s，决策=%s', recruit.id, recruit.pilot.nickname, final_decision.value)
        return True

    except ValidationError as e:
        logger.error('结束征召验证失败：%s', str(e))
        _rollback_recruit_and_pilot(recruit, original_recruit_data, original_pilot_data)
        raise RecruitServiceError(f"数据验证失败：{str(e)}") from e

    except Exception as e:
        logger.error('结束征召失败：%s', str(e))
        _rollback_recruit_and_pilot(recruit, original_recruit_data, original_pilot_data)
        raise RecruitServiceError(f"结束征召失败，请重试：{str(e)}") from e


def _rollback_recruit_and_pilot(recruit, original_recruit_data, original_pilot_data):
    """回滚征召和机师数据"""
    try:
        # 回滚机师数据
        for field, value in original_pilot_data.items():
            setattr(recruit.pilot, field, value)
        recruit.pilot.save()

        # 回滚征召数据
        for field, value in original_recruit_data.items():
            setattr(recruit, field, value)
        recruit.save()

        logger.debug('数据回滚成功')
    except Exception as rollback_error:
        logger.error('数据回滚失败：%s', str(rollback_error))


def confirm_recruit_atomic(recruit, introduction_fee, remarks, _current_user, _ip_address):
    """原子性确认征召（已废弃，保留用于兼容性）
    
    此方法已被三步制流程替代，保留用于现有代码的兼容性。
    """
    logger.warning('使用已废弃的confirm_recruit_atomic方法，建议使用三步制流程')

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

        raise RecruitServiceError(f"数据验证失败：{str(e)}") from e

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

        raise RecruitServiceError(f"征召确认失败，请重试：{str(e)}") from e


def abandon_recruit_atomic(recruit, _current_user, _ip_address):
    """原子性放弃征召（已废弃，保留用于兼容性）
    
    此方法已被三步制流程替代，建议在训练征召或结束征召步骤中选择"不征召"。
    """
    logger.warning('使用已废弃的abandon_recruit_atomic方法，建议使用三步制流程')

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

        raise RecruitServiceError(f"数据验证失败：{str(e)}") from e

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

        raise RecruitServiceError(f"征召放弃失败，请重试：{str(e)}") from e
