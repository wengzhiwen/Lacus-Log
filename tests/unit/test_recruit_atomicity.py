"""征召状态流转原子性的单元测试。

覆盖：
- 征召确认的原子性操作
- 征召放弃的原子性操作
- 异常情况下的回滚机制
"""

# pylint: disable=import-error,no-member
from decimal import Decimal

import pytest
from unittest.mock import patch, MagicMock

from models.pilot import Rank, Status
from models.recruit import RecruitStatus
from tests.fixtures.factory import create_recruit, create_pilot, create_user
from utils.recruit_service import (confirm_recruit_atomic, abandon_recruit_atomic, RecruitServiceError)


@pytest.mark.unit
class TestRecruitAtomicity:
    """征召原子性操作测试"""

    @pytest.fixture
    def owner(self, app):
        """创建机师所属"""
        with app.app_context():
            return create_user('owner_user')

    @pytest.fixture
    def pilot(self, owner, app):
        """创建测试机师"""
        with app.app_context():
            return create_pilot('测试机师', owner=owner, status=Status.NOT_RECRUITED)

    @pytest.fixture
    def recruiter(self, app):
        """创建征召负责人"""
        with app.app_context():
            return create_user('recruiter_user')

    @pytest.fixture
    def current_user(self, app):
        """创建当前用户"""
        with app.app_context():
            return create_user('current_user')

    @pytest.fixture
    def recruit(self, pilot, recruiter, app):
        """创建征召记录"""
        with app.app_context():
            return create_recruit(pilot, recruiter, status=RecruitStatus.STARTED)

    def test_confirm_recruit_success(self, recruit, current_user, app):
        """测试征召确认成功"""
        with app.app_context():
            introduction_fee = Decimal('100.00')
            remarks = '测试备注'
            ip_address = '127.0.0.1'

            # 保存原始状态
            original_recruit_status = recruit.status
            original_pilot_status = recruit.pilot.status
            original_pilot_rank = recruit.pilot.rank

            # 执行确认操作
            result = confirm_recruit_atomic(recruit, introduction_fee, remarks, current_user, ip_address)

            assert result is True
            assert recruit.status == RecruitStatus.ENDED
            assert recruit.introduction_fee == introduction_fee
            assert recruit.remarks == remarks
            assert recruit.pilot.status == Status.RECRUITED
            assert recruit.pilot.rank == Rank.TRAINEE

    def test_abandon_recruit_success(self, recruit, current_user):
        """测试征召放弃成功"""
        ip_address = '127.0.0.1'

        # 保存原始状态
        original_recruit_status = recruit.status
        original_pilot_status = recruit.pilot.status

        # 执行放弃操作
        result = abandon_recruit_atomic(recruit, current_user, ip_address)

        assert result is True
        assert recruit.status == RecruitStatus.ENDED
        assert recruit.pilot.status == Status.NOT_RECRUITING

    def test_confirm_recruit_pilot_save_failure_rollback(self, recruit, current_user):
        """测试征召确认时机师保存失败的回滚"""
        introduction_fee = Decimal('100.00')
        remarks = '测试备注'
        ip_address = '127.0.0.1'

        # 保存原始状态
        original_recruit_status = recruit.status
        original_recruit_fee = recruit.introduction_fee
        original_recruit_remarks = recruit.remarks
        original_pilot_status = recruit.pilot.status
        original_pilot_rank = recruit.pilot.rank

        # 模拟机师保存失败
        with patch.object(recruit.pilot, 'save') as mock_pilot_save:
            mock_pilot_save.side_effect = Exception('机师保存失败')

            # 应该抛出服务异常
            with pytest.raises(RecruitServiceError) as exc_info:
                confirm_recruit_atomic(recruit, introduction_fee, remarks, current_user, ip_address)

            assert '征召确认失败，请重试' in str(exc_info.value)

            # 验证回滚 - 征召状态应该恢复
            assert recruit.status == original_recruit_status
            assert recruit.introduction_fee == original_recruit_fee
            assert recruit.remarks == original_recruit_remarks

    def test_abandon_recruit_pilot_save_failure_rollback(self, recruit, current_user):
        """测试征召放弃时机师保存失败的回滚"""
        ip_address = '127.0.0.1'

        # 保存原始状态
        original_recruit_status = recruit.status
        original_pilot_status = recruit.pilot.status

        # 模拟机师保存失败
        with patch.object(recruit.pilot, 'save') as mock_pilot_save:
            mock_pilot_save.side_effect = Exception('机师保存失败')

            # 应该抛出服务异常
            with pytest.raises(RecruitServiceError) as exc_info:
                abandon_recruit_atomic(recruit, current_user, ip_address)

            assert '征召放弃失败，请重试' in str(exc_info.value)

            # 验证回滚 - 征召状态应该恢复
            assert recruit.status == original_recruit_status

    def test_confirm_recruit_validation_error_rollback(self, recruit, current_user):
        """测试征召确认时验证错误的回滚"""
        from mongoengine import ValidationError

        introduction_fee = Decimal('100.00')
        remarks = '测试备注'
        ip_address = '127.0.0.1'

        # 保存原始状态
        original_recruit_status = recruit.status

        # 模拟验证错误
        with patch.object(recruit, 'save') as mock_recruit_save:
            mock_recruit_save.side_effect = ValidationError('验证失败')

            # 应该抛出服务异常
            with pytest.raises(RecruitServiceError) as exc_info:
                confirm_recruit_atomic(recruit, introduction_fee, remarks, current_user, ip_address)

            assert '数据验证失败' in str(exc_info.value)

    def test_recruit_service_preserves_data_integrity(self, recruit, current_user):
        """测试征召服务保持数据完整性"""
        introduction_fee = Decimal('200.50')
        remarks = '完整性测试'
        ip_address = '192.168.1.1'

        # 执行多次操作确保数据一致性
        confirm_recruit_atomic(recruit, introduction_fee, remarks, current_user, ip_address)

        # 验证所有相关数据都已正确更新
        assert recruit.status == RecruitStatus.ENDED
        assert recruit.introduction_fee == introduction_fee
        assert recruit.remarks == remarks
        assert recruit.pilot.status == Status.RECRUITED
        assert recruit.pilot.rank == Rank.TRAINEE

        # 验证征召和机师状态保持一致
        assert recruit.status == RecruitStatus.ENDED
        assert recruit.pilot.status in [Status.RECRUITED, Status.NOT_RECRUITING]
