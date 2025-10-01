"""招募服务层：提供招募相关的原子性业务操作。"""
# pylint: disable=no-member
from mongoengine import ValidationError

from models.pilot import Rank, Status, WorkMode
from models.recruit import FinalDecision, RecruitStatus, TrainingDecision
from models.user import User
from utils.logging_setup import get_logger
from utils.timezone_helper import get_current_utc_time

logger = get_logger('recruit_service')


class RecruitServiceError(Exception):
    """招募服务异常"""


def training_recruit_atomic(recruit, training_decision, training_time, pilot_basic_info, introduction_fee, remarks, current_user, _ip_address):
    """原子性试播招募。

    Args:
        recruit: 招募对象
        training_decision: 试播招募决策
        training_time: 试播时间（仅当决策为招募时需要）
        pilot_basic_info: 主播基本信息字典（real_name, birth_year, work_mode）
        introduction_fee: 介绍费
        remarks: 备注
        current_user: 当前用户
        _ip_address: IP地址
    
    Returns:
        bool: 操作是否成功
    
    Raises:
        RecruitServiceError: 服务层异常
    """

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
        logger.debug('招募记录更新成功：ID=%s', recruit.id)

        if training_decision == TrainingDecision.RECRUIT_AS_TRAINEE:
            recruit.pilot.rank = Rank.TRAINEE
            recruit.pilot.status = Status.RECRUITED

            if pilot_basic_info.get('real_name'):
                recruit.pilot.real_name = pilot_basic_info['real_name']
            if pilot_basic_info.get('birth_year'):
                recruit.pilot.birth_year = pilot_basic_info['birth_year']
            if pilot_basic_info.get('work_mode'):
                recruit.pilot.work_mode = WorkMode(pilot_basic_info['work_mode'])
        else:
            recruit.pilot.status = Status.NOT_RECRUITING

        recruit.pilot.save()

        logger.info('试播招募成功：ID=%s，主播=%s，决策=%s', recruit.id, recruit.pilot.nickname, training_decision.value)
        return True

    except ValidationError as e:
        logger.error('试播招募验证失败：%s', str(e))
        _rollback_recruit_and_pilot(recruit, original_recruit_data, original_pilot_data)
        raise RecruitServiceError(f"数据验证失败：{str(e)}") from e

    except Exception as e:
        logger.error('试播招募失败：%s', str(e))
        _rollback_recruit_and_pilot(recruit, original_recruit_data, original_pilot_data)
        raise RecruitServiceError(f"试播招募失败，请重试：{str(e)}") from e


def final_recruit_atomic(recruit, final_decision, pilot_assignment_info, introduction_fee, remarks, current_user, _ip_address):
    """原子性结束招募。

    Args:
        recruit: 招募对象
        final_decision: 结束招募决策
        pilot_assignment_info: 主播分配信息字典（owner, platform）
        introduction_fee: 介绍费
        remarks: 备注
        current_user: 当前用户
        _ip_address: IP地址
    
    Returns:
        bool: 操作是否成功
    
    Raises:
        RecruitServiceError: 服务层异常
    """

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
        recruit.final_decision = final_decision
        recruit.final_decision_maker = current_user
        recruit.final_decision_time = get_current_utc_time()
        recruit.status = RecruitStatus.ENDED
        recruit.introduction_fee = introduction_fee
        recruit.remarks = remarks
        recruit.save()

        logger.debug('招募记录更新成功：ID=%s', recruit.id)

        if final_decision in [FinalDecision.OFFICIAL, FinalDecision.INTERN]:
            if final_decision == FinalDecision.OFFICIAL:
                recruit.pilot.rank = Rank.OFFICIAL
            elif final_decision == FinalDecision.INTERN:
                recruit.pilot.rank = Rank.INTERN

            recruit.pilot.status = Status.RECRUITED

            if pilot_assignment_info.get('owner'):
                owner = User.objects.get(id=pilot_assignment_info['owner'])
                recruit.pilot.owner = owner

            if pilot_assignment_info.get('platform'):
                from models.pilot import Platform
                recruit.pilot.platform = Platform(pilot_assignment_info['platform'])
        else:
            recruit.pilot.status = Status.NOT_RECRUITING

        recruit.pilot.save()

        logger.info('结束招募成功：ID=%s，主播=%s，决策=%s', recruit.id, recruit.pilot.nickname, final_decision.value)
        return True

    except ValidationError as e:
        logger.error('结束招募验证失败：%s', str(e))
        _rollback_recruit_and_pilot(recruit, original_recruit_data, original_pilot_data)
        raise RecruitServiceError(f"数据验证失败：{str(e)}") from e

    except Exception as e:
        logger.error('结束招募失败：%s', str(e))
        _rollback_recruit_and_pilot(recruit, original_recruit_data, original_pilot_data)
        raise RecruitServiceError(f"结束招募失败，请重试：{str(e)}") from e


def _rollback_recruit_and_pilot(recruit, original_recruit_data, original_pilot_data):
    """回滚招募与主播数据。"""
    try:
        for field, value in original_pilot_data.items():
            setattr(recruit.pilot, field, value)
        recruit.pilot.save()

        for field, value in original_recruit_data.items():
            setattr(recruit, field, value)
        recruit.save()

        logger.debug('数据回滚成功')
    except Exception as rollback_error:
        logger.error('数据回滚失败：%s', str(rollback_error))


def confirm_recruit_atomic(recruit, introduction_fee, remarks, _current_user, _ip_address):
    """原子性确认招募（已废弃，保留用于兼容性）。"""
    logger.warning('使用已废弃的confirm_recruit_atomic方法，建议使用三步制流程')

    original_recruit_status = recruit.status
    original_recruit_fee = recruit.introduction_fee
    original_recruit_remarks = recruit.remarks
    original_pilot_status = recruit.pilot.status
    original_pilot_rank = recruit.pilot.rank

    try:
        recruit.introduction_fee = introduction_fee
        recruit.remarks = remarks
        recruit.status = RecruitStatus.ENDED
        recruit.save()

        logger.debug('招募记录更新成功：ID=%s', recruit.id)

        recruit.pilot.rank = Rank.TRAINEE
        recruit.pilot.status = Status.RECRUITED
        recruit.pilot.save()

        logger.info('招募确认成功：ID=%s，主播=%s', recruit.id, recruit.pilot.nickname)
        return True

    except ValidationError as e:
        logger.error('招募确认验证失败：%s', str(e))
        try:
            recruit.status = original_recruit_status
            recruit.introduction_fee = original_recruit_fee
            recruit.remarks = original_recruit_remarks
            recruit.save()
            logger.debug('招募记录回滚成功')
        except Exception as rollback_error:
            logger.error('招募记录回滚失败：%s', str(rollback_error))

        raise RecruitServiceError(f"数据验证失败：{str(e)}") from e

    except Exception as e:
        logger.error('招募确认失败：%s', str(e))
        try:
            recruit.pilot.status = original_pilot_status
            recruit.pilot.rank = original_pilot_rank
            recruit.pilot.save()

            recruit.status = original_recruit_status
            recruit.introduction_fee = original_recruit_fee
            recruit.remarks = original_recruit_remarks
            recruit.save()

            logger.debug('招募确认回滚成功')
        except Exception as rollback_error:
            logger.error('招募确认回滚失败：%s', str(rollback_error))

        raise RecruitServiceError(f"招募确认失败，请重试：{str(e)}") from e


def abandon_recruit_atomic(recruit, _current_user, _ip_address):
    """原子性放弃招募（已废弃，保留用于兼容性）。"""
    logger.warning('使用已废弃的abandon_recruit_atomic方法，建议使用三步制流程')

    original_recruit_status = recruit.status
    original_pilot_status = recruit.pilot.status

    try:
        recruit.status = RecruitStatus.ENDED
        recruit.save()

        logger.debug('招募记录状态更新成功：ID=%s', recruit.id)

        recruit.pilot.status = Status.NOT_RECRUITING
        recruit.pilot.save()

        logger.info('招募放弃成功：ID=%s，主播=%s', recruit.id, recruit.pilot.nickname)
        return True

    except ValidationError as e:
        logger.error('招募放弃验证失败：%s', str(e))
        try:
            recruit.status = original_recruit_status
            recruit.save()
            logger.debug('招募记录回滚成功')
        except Exception as rollback_error:
            logger.error('招募记录回滚失败：%s', str(rollback_error))

        raise RecruitServiceError(f"数据验证失败：{str(e)}") from e

    except Exception as e:
        logger.error('招募放弃失败：%s', str(e))
        try:
            recruit.pilot.status = original_pilot_status
            recruit.pilot.save()

            recruit.status = original_recruit_status
            recruit.save()

            logger.debug('招募放弃回滚成功')
        except Exception as rollback_error:
            logger.error('招募放弃回滚失败：%s', str(rollback_error))

        raise RecruitServiceError(f"招募放弃失败，请重试：{str(e)}") from e
