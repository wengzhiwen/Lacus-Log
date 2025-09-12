"""
测试机师征召三步制流程

测试征召从启动到结束的完整流程，包括：
1. 启动征召
2. 训练征召（征召为训练机师/不征召）
3. 结束征召（正式机师/实习机师/不征召）
"""
import pytest
from datetime import timedelta
from decimal import Decimal

from models.pilot import Gender, Platform, Rank, Status, WorkMode
from models.recruit import (FinalDecision, Recruit, RecruitChannel, RecruitStatus, TrainingDecision)
from tests.fixtures.factory import create_pilot, create_user, ensure_roles
from utils.recruit_service import (RecruitServiceError, final_recruit_atomic, training_recruit_atomic)
from utils.timezone_helper import get_current_utc_time


@pytest.mark.unit
class TestRecruitThreeStepFlow:
    """测试三步制征召流程"""

    @pytest.fixture
    def roles(self):
        """确保角色存在"""
        return ensure_roles()

    @pytest.fixture
    def recruiter(self):
        """创建征召负责人"""
        return create_user('recruiter1', role_name='kancho')

    @pytest.fixture
    def owner(self):
        """创建所属舰长"""
        return create_user('owner1', role_name='kancho')

    @pytest.fixture
    def pilot(self, owner):
        """创建测试机师"""
        return create_pilot(
            '测试机师001',
            owner=owner,
            gender=Gender.FEMALE,
            rank=Rank.CANDIDATE,
            status=Status.NOT_RECRUITED,
            platform=Platform.KUAISHOU,  # 设置为快手而不是UNKNOWN
            work_mode=WorkMode.ONLINE  # 设置为ONLINE而不是UNKNOWN
        )

    @pytest.fixture
    def recruit(self, pilot, recruiter):
        """创建征召记录"""
        recruit = Recruit(pilot=pilot,
                          recruiter=recruiter,
                          appointment_time=get_current_utc_time() + timedelta(days=1),
                          channel=RecruitChannel.BOSS,
                          introduction_fee=Decimal('100.00'),
                          remarks='测试征召',
                          status=RecruitStatus.STARTED)
        recruit.save()
        return recruit

    def test_training_recruit_success_flow(self, recruit, recruiter):
        """测试训练征召成功流程"""
        # 准备训练时间
        training_time = recruit.appointment_time + timedelta(hours=2)

        # 准备机师基本信息
        pilot_basic_info = {'real_name': '张小明', 'birth_year': 1995, 'work_mode': WorkMode.ONLINE.value}

        # 执行训练征召
        result = training_recruit_atomic(recruit=recruit,
                                         training_decision=TrainingDecision.RECRUIT_AS_TRAINEE,
                                         training_time=training_time,
                                         pilot_basic_info=pilot_basic_info,
                                         introduction_fee=Decimal('150.00'),
                                         remarks='训练征召备注',
                                         current_user=recruiter,
                                         _ip_address='127.0.0.1')

        # 验证结果
        assert result is True

        # 重新加载数据
        recruit.reload()
        pilot = recruit.pilot
        pilot.reload()

        # 验证征召记录
        assert recruit.status == RecruitStatus.TRAINING_RECRUITING
        assert recruit.training_decision == TrainingDecision.RECRUIT_AS_TRAINEE
        assert recruit.training_decision_maker == recruiter
        # 时间比较允许微秒差异
        assert abs((recruit.training_time - training_time).total_seconds()) < 1
        assert recruit.introduction_fee == Decimal('150.00')
        assert recruit.remarks == '训练征召备注'
        assert recruit.training_decision_time is not None

        # 验证机师状态
        assert pilot.rank == Rank.TRAINEE
        assert pilot.status == Status.RECRUITED
        assert pilot.real_name == '张小明'
        assert pilot.birth_year == 1995
        assert pilot.work_mode == WorkMode.ONLINE

    def test_training_recruit_not_recruit_flow(self, recruit, recruiter):
        """测试训练征召不征召流程"""
        # 执行训练征召（不征召）
        result = training_recruit_atomic(recruit=recruit,
                                         training_decision=TrainingDecision.NOT_RECRUIT,
                                         training_time=None,
                                         pilot_basic_info={},
                                         introduction_fee=Decimal('50.00'),
                                         remarks='不征召备注',
                                         current_user=recruiter,
                                         _ip_address='127.0.0.1')

        # 验证结果
        assert result is True

        # 重新加载数据
        recruit.reload()
        pilot = recruit.pilot
        pilot.reload()

        # 验证征召记录
        assert recruit.status == RecruitStatus.ENDED
        assert recruit.training_decision == TrainingDecision.NOT_RECRUIT
        assert recruit.training_decision_maker == recruiter
        assert recruit.training_time is None
        assert recruit.introduction_fee == Decimal('50.00')
        assert recruit.remarks == '不征召备注'

        # 验证机师状态
        assert pilot.status == Status.NOT_RECRUITING
        # 机师其他信息应该保持不变
        assert pilot.rank == Rank.CANDIDATE

    def test_final_recruit_official_flow(self, recruit, recruiter, owner):
        """测试结束征召为正式机师流程"""
        # 先执行训练征召
        self.test_training_recruit_success_flow(recruit, recruiter)

        # 准备机师分配信息
        pilot_assignment_info = {'owner': str(owner.id), 'rank': Rank.OFFICIAL.value}

        # 执行结束征召
        result = final_recruit_atomic(recruit=recruit,
                                      final_decision=FinalDecision.OFFICIAL,
                                      pilot_assignment_info=pilot_assignment_info,
                                      introduction_fee=Decimal('200.00'),
                                      remarks='结束征召备注',
                                      current_user=recruiter,
                                      _ip_address='127.0.0.1')

        # 验证结果
        assert result is True

        # 重新加载数据
        recruit.reload()
        pilot = recruit.pilot
        pilot.reload()

        # 验证征召记录
        assert recruit.status == RecruitStatus.ENDED
        assert recruit.final_decision == FinalDecision.OFFICIAL
        assert recruit.final_decision_maker == recruiter
        assert recruit.introduction_fee == Decimal('200.00')
        assert recruit.remarks == '结束征召备注'
        assert recruit.final_decision_time is not None

        # 验证机师状态
        assert pilot.rank == Rank.OFFICIAL
        assert pilot.status == Status.RECRUITED
        assert pilot.owner == owner

    def test_final_recruit_intern_flow(self, recruit, recruiter, owner):
        """测试结束征召为实习机师流程"""
        # 先执行训练征召
        self.test_training_recruit_success_flow(recruit, recruiter)

        # 准备机师分配信息
        pilot_assignment_info = {'owner': str(owner.id), 'rank': Rank.INTERN.value}

        # 执行结束征召
        result = final_recruit_atomic(recruit=recruit,
                                      final_decision=FinalDecision.INTERN,
                                      pilot_assignment_info=pilot_assignment_info,
                                      introduction_fee=Decimal('180.00'),
                                      remarks='实习机师备注',
                                      current_user=recruiter,
                                      _ip_address='127.0.0.1')

        # 验证结果
        assert result is True

        # 重新加载数据
        recruit.reload()
        pilot = recruit.pilot
        pilot.reload()

        # 验证征召记录
        assert recruit.status == RecruitStatus.ENDED
        assert recruit.final_decision == FinalDecision.INTERN
        assert recruit.final_decision_maker == recruiter

        # 验证机师状态
        assert pilot.rank == Rank.INTERN
        assert pilot.status == Status.RECRUITED
        assert pilot.owner == owner

    def test_final_recruit_not_recruit_flow(self, recruit, recruiter):
        """测试结束征召不征召流程"""
        # 先执行训练征召
        self.test_training_recruit_success_flow(recruit, recruiter)

        # 执行结束征召（不征召）
        result = final_recruit_atomic(recruit=recruit,
                                      final_decision=FinalDecision.NOT_RECRUIT,
                                      pilot_assignment_info={},
                                      introduction_fee=Decimal('100.00'),
                                      remarks='最终不征召',
                                      current_user=recruiter,
                                      _ip_address='127.0.0.1')

        # 验证结果
        assert result is True

        # 重新加载数据
        recruit.reload()
        pilot = recruit.pilot
        pilot.reload()

        # 验证征召记录
        assert recruit.status == RecruitStatus.ENDED
        assert recruit.final_decision == FinalDecision.NOT_RECRUIT

        # 验证机师状态
        assert pilot.status == Status.NOT_RECRUITING
        # 机师应该保持训练机师阶级和相关信息
        assert pilot.rank == Rank.TRAINEE

    def test_training_time_validation(self, recruit, recruiter):
        """测试训练时间验证"""
        # 训练时间早于预约时间应该失败
        early_training_time = recruit.appointment_time - timedelta(hours=1)

        pilot_basic_info = {'real_name': '张小明', 'birth_year': 1995, 'work_mode': WorkMode.ONLINE.value}

        with pytest.raises(RecruitServiceError):
            training_recruit_atomic(recruit=recruit,
                                    training_decision=TrainingDecision.RECRUIT_AS_TRAINEE,
                                    training_time=early_training_time,
                                    pilot_basic_info=pilot_basic_info,
                                    introduction_fee=Decimal('150.00'),
                                    remarks='测试',
                                    current_user=recruiter,
                                    _ip_address='127.0.0.1')

    def test_data_validation_errors(self, recruit, recruiter):
        """测试数据验证错误处理"""
        # 测试征召决策时没有填写必填字段
        with pytest.raises(RecruitServiceError):
            training_recruit_atomic(
                recruit=recruit,
                training_decision=TrainingDecision.RECRUIT_AS_TRAINEE,
                training_time=recruit.appointment_time + timedelta(hours=2),
                pilot_basic_info={},  # 缺少必填的机师信息
                introduction_fee=Decimal('150.00'),
                remarks='测试',
                current_user=recruiter,
                _ip_address='127.0.0.1')

    def test_status_flow_validation(self, recruit, recruiter, owner):
        """测试状态流转验证"""
        # 只有训练征召中的征召才能执行结束征召
        with pytest.raises(RecruitServiceError):
            final_recruit_atomic(
                recruit=recruit,  # 状态是STARTED，不是TRAINING_RECRUITING
                final_decision=FinalDecision.OFFICIAL,
                pilot_assignment_info={
                    'owner': str(owner.id),
                    'rank': Rank.OFFICIAL.value
                },
                introduction_fee=Decimal('200.00'),
                remarks='测试',
                current_user=recruiter,
                _ip_address='127.0.0.1')
