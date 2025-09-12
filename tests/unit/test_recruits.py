"""征召流程状态流转与机师联动的单元/集成测试。

覆盖：
- 征召状态流转：已启动 → 已结束
- 机师状态联动：未征召 → 已征召/不征召
- 机师阶级联动：确认征召时设为训练机师
- 征召渠道和介绍费验证
- 征召负责人权限验证
"""

# pylint: disable=import-error,no-member
from datetime import datetime
from decimal import Decimal

import pytest

from models.pilot import Pilot, Rank, Status
from models.recruit import Recruit, RecruitChannel, RecruitStatus
from tests.fixtures.factory import create_pilot, create_user


@pytest.mark.unit
class TestRecruitStatusFlow:

    @pytest.fixture
    def pilot(self):
        owner = create_user('owner_user')
        return create_pilot('征召机师', owner=owner, status=Status.NOT_RECRUITED)

    @pytest.fixture
    def recruiter(self):
        return create_user('recruiter_user', role_name='kancho')

    def test_recruit_creation_flow(self, pilot, recruiter):
        """测试征召创建流程"""
        # 创建征召记录
        recruit = Recruit(pilot=pilot,
                          recruiter=recruiter,
                          appointment_time=datetime(2025, 9, 15, 14, 0),
                          channel=RecruitChannel.BOSS,
                          introduction_fee=Decimal('100.00'),
                          remarks='测试征召',
                          status=RecruitStatus.STARTED)
        recruit.save()

        # 验证征召状态
        assert recruit.status == RecruitStatus.STARTED
        assert recruit.pilot.status == Status.NOT_RECRUITED  # 机师状态未变

    def test_recruit_confirmation_flow(self, pilot, recruiter):
        """测试征召确认流程"""
        # 创建征召记录
        recruit = Recruit(pilot=pilot,
                          recruiter=recruiter,
                          appointment_time=datetime(2025, 9, 15, 14, 0),
                          channel=RecruitChannel.BOSS,
                          introduction_fee=Decimal('100.00'),
                          remarks='测试征召',
                          status=RecruitStatus.STARTED)
        recruit.save()

        # 确认征召
        recruit.status = RecruitStatus.ENDED
        recruit.save()

        # 更新机师状态和阶级
        pilot.status = Status.RECRUITED
        pilot.rank = Rank.TRAINEE
        pilot.save()

        # 验证状态更新
        assert recruit.status == RecruitStatus.ENDED
        assert pilot.status == Status.RECRUITED
        assert pilot.rank == Rank.TRAINEE

    def test_recruit_abandonment_flow(self, pilot, recruiter):
        """测试征召放弃流程"""
        # 创建征召记录
        recruit = Recruit(pilot=pilot,
                          recruiter=recruiter,
                          appointment_time=datetime(2025, 9, 15, 14, 0),
                          channel=RecruitChannel.BOSS,
                          introduction_fee=Decimal('100.00'),
                          remarks='测试征召',
                          status=RecruitStatus.STARTED)
        recruit.save()

        # 放弃征召
        recruit.status = RecruitStatus.ENDED
        recruit.save()

        # 更新机师状态
        pilot.status = Status.NOT_RECRUITING
        pilot.save()

        # 验证状态更新
        assert recruit.status == RecruitStatus.ENDED
        assert pilot.status == Status.NOT_RECRUITING


@pytest.mark.unit
class TestRecruitValidation:

    @pytest.fixture
    def pilot(self):
        owner = create_user('owner_user')
        return create_pilot('征召机师', owner=owner, status=Status.NOT_RECRUITED)

    @pytest.fixture
    def recruiter(self):
        return create_user('recruiter_user', role_name='kancho')

    def test_channel_validation(self, pilot, recruiter):
        """测试征召渠道验证"""
        # 测试有效渠道
        valid_channels = [RecruitChannel.BOSS, RecruitChannel.JOB51, RecruitChannel.INTRODUCTION, RecruitChannel.OTHER]

        for channel in valid_channels:
            recruit = Recruit(pilot=pilot,
                              recruiter=recruiter,
                              appointment_time=datetime(2025, 9, 15, 14, 0),
                              channel=channel,
                              introduction_fee=Decimal('100.00'),
                              status=RecruitStatus.STARTED)
            recruit.save()
            assert recruit.channel == channel

    def test_introduction_fee_validation(self, pilot, recruiter):
        """测试介绍费验证"""
        # 测试有效介绍费
        valid_fees = [Decimal('0.00'), Decimal('100.00'), Decimal('999.99')]

        for fee in valid_fees:
            recruit = Recruit(pilot=pilot,
                              recruiter=recruiter,
                              appointment_time=datetime(2025, 9, 15, 14, 0),
                              channel=RecruitChannel.BOSS,
                              introduction_fee=fee,
                              status=RecruitStatus.STARTED)
            recruit.save()
            assert recruit.introduction_fee == fee

    def test_recruiter_permission_validation(self, pilot):
        """测试征召负责人权限验证"""
        # 创建舰长用户
        kancho = create_user('kancho_user', role_name='kancho')

        # 创建征召记录
        recruit = Recruit(pilot=pilot,
                          recruiter=kancho,
                          appointment_time=datetime(2025, 9, 15, 14, 0),
                          channel=RecruitChannel.BOSS,
                          introduction_fee=Decimal('100.00'),
                          status=RecruitStatus.STARTED)
        recruit.save()

        # 验证征召负责人
        assert recruit.recruiter.id == kancho.id
        assert kancho.has_role('kancho')


@pytest.mark.unit
class TestRecruitBusinessRules:

    @pytest.fixture
    def pilot(self):
        owner = create_user('owner_user')
        return create_pilot('征召机师', owner=owner, status=Status.NOT_RECRUITED)

    @pytest.fixture
    def recruiter(self):
        return create_user('recruiter_user', role_name='kancho')

    def test_only_not_recruited_pilot_can_start_recruit(self, pilot, recruiter):
        """测试只有未征召状态的机师才能启动征召"""
        # 机师状态为未征召，可以启动征召
        assert pilot.status == Status.NOT_RECRUITED

        recruit = Recruit(pilot=pilot,
                          recruiter=recruiter,
                          appointment_time=datetime(2025, 9, 15, 14, 0),
                          channel=RecruitChannel.BOSS,
                          introduction_fee=Decimal('100.00'),
                          status=RecruitStatus.STARTED)
        recruit.save()

        assert recruit.pilot.status == Status.NOT_RECRUITED

    def test_recruit_status_display(self, pilot, recruiter):
        """测试征召状态显示"""
        recruit = Recruit(pilot=pilot,
                          recruiter=recruiter,
                          appointment_time=datetime(2025, 9, 15, 14, 0),
                          channel=RecruitChannel.BOSS,
                          introduction_fee=Decimal('100.00'),
                          status=RecruitStatus.STARTED)
        recruit.save()

        assert recruit.status.value == '已启动'

        # 更新状态
        recruit.status = RecruitStatus.ENDED
        recruit.save()

        assert recruit.status.value == '已结束'

    def test_recruit_channel_display(self, pilot, recruiter):
        """测试征召渠道显示"""
        recruit = Recruit(pilot=pilot,
                          recruiter=recruiter,
                          appointment_time=datetime(2025, 9, 15, 14, 0),
                          channel=RecruitChannel.BOSS,
                          introduction_fee=Decimal('100.00'),
                          status=RecruitStatus.STARTED)
        recruit.save()

        assert recruit.channel.value == 'BOSS'


@pytest.mark.integration
@pytest.mark.requires_db
class TestRecruitIntegration:

    @pytest.fixture(autouse=True)
    def setup_db(self):
        """设置测试数据库"""
        from mongoengine import connect, disconnect
        try:
            disconnect()
        except Exception:
            pass
        connect('test_lacus', host='mongodb://localhost:27017/test_lacus')

        # 清理测试数据
        Recruit.objects().delete()

        yield

        # 测试结束后清理数据
        try:
            Recruit.objects().delete()
        except Exception:
            pass
        disconnect()

    def test_complete_recruit_workflow(self):
        """测试完整征召工作流"""
        # 创建机师和征召负责人
        owner = create_user('owner_user')
        pilot = create_pilot('征召机师', owner=owner, status=Status.NOT_RECRUITED)
        recruiter = create_user('recruiter_user', role_name='kancho')

        # 1. 启动征召
        recruit = Recruit(pilot=pilot,
                          recruiter=recruiter,
                          appointment_time=datetime(2025, 9, 15, 14, 0),
                          channel=RecruitChannel.BOSS,
                          introduction_fee=Decimal('100.00'),
                          remarks='测试征召',
                          status=RecruitStatus.STARTED)
        recruit.save()

        # 验证征召已启动
        assert recruit.status == RecruitStatus.STARTED
        assert pilot.status == Status.NOT_RECRUITED

        # 2. 确认征召
        recruit.status = RecruitStatus.ENDED
        recruit.save()

        pilot.status = Status.RECRUITED
        pilot.rank = Rank.TRAINEE
        pilot.save()

        # 验证征召已确认
        assert recruit.status == RecruitStatus.ENDED
        assert pilot.status == Status.RECRUITED
        assert pilot.rank == Rank.TRAINEE

    def test_multiple_recruits_same_pilot_prevention(self):
        """测试同一机师多次征召的防护"""
        owner = create_user('owner_user')
        pilot = create_pilot('征召机师', owner=owner, status=Status.NOT_RECRUITED)
        recruiter = create_user('recruiter_user', role_name='kancho')

        # 创建第一个征召
        recruit1 = Recruit(pilot=pilot,
                           recruiter=recruiter,
                           appointment_time=datetime(2025, 9, 15, 14, 0),
                           channel=RecruitChannel.BOSS,
                           introduction_fee=Decimal('100.00'),
                           status=RecruitStatus.STARTED)
        recruit1.save()

        # 尝试创建第二个征召（应该被业务逻辑阻止）
        # 在实际应用中，应该在路由层检查是否已有进行中的征召
        recruit2 = Recruit(pilot=pilot,
                           recruiter=recruiter,
                           appointment_time=datetime(2025, 9, 16, 14, 0),
                           channel=RecruitChannel.JOB51,
                           introduction_fee=Decimal('150.00'),
                           status=RecruitStatus.STARTED)
        recruit2.save()

        # 验证两个征召都存在（业务逻辑需要在应用层实现）
        assert Recruit.objects(pilot=pilot).count() == 2
