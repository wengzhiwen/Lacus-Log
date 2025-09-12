"""作战记录时间验证逻辑的单元测试。

覆盖：
- 结束时间必须大于开始时间（不能等于）
- 验证边界情况
"""

# pylint: disable=import-error,no-member
from datetime import datetime

import pytest
from mongoengine import ValidationError

from models.battle_record import BattleRecord
from models.pilot import WorkMode
from tests.fixtures.factory import create_pilot, create_user


@pytest.mark.unit
class TestBattleRecordTimeValidation:
    """作战记录时间验证测试"""

    @pytest.fixture
    def pilot(self):
        """创建测试机师"""
        owner = create_user('owner_user')
        return create_pilot('测试机师', owner=owner)

    @pytest.fixture
    def registrar(self):
        """创建登记人"""
        return create_user('registrar_user')

    def test_end_time_equals_start_time_should_fail(self, pilot, registrar):
        """结束时间等于开始时间应该失败"""
        start_time = datetime(2025, 9, 10, 10, 0, 0)
        end_time = datetime(2025, 9, 10, 10, 0, 0)  # 相同时间

        record = BattleRecord(pilot=pilot,
                              start_time=start_time,
                              end_time=end_time,
                              work_mode=WorkMode.ONLINE,
                              owner_snapshot=pilot.owner,
                              registered_by=registrar)

        with pytest.raises(ValidationError) as exc_info:
            record.clean()

        assert "结束时间必须大于开始时间" in str(exc_info.value)

    def test_end_time_before_start_time_should_fail(self, pilot, registrar):
        """结束时间早于开始时间应该失败"""
        start_time = datetime(2025, 9, 10, 10, 0, 0)
        end_time = datetime(2025, 9, 10, 9, 0, 0)  # 结束时间早于开始时间

        record = BattleRecord(pilot=pilot,
                              start_time=start_time,
                              end_time=end_time,
                              work_mode=WorkMode.ONLINE,
                              owner_snapshot=pilot.owner,
                              registered_by=registrar)

        with pytest.raises(ValidationError) as exc_info:
            record.clean()

        assert "结束时间必须大于开始时间" in str(exc_info.value)

    def test_valid_time_range_should_pass(self, pilot, registrar):
        """有效的时间范围应该通过验证"""
        start_time = datetime(2025, 9, 10, 10, 0, 0)
        end_time = datetime(2025, 9, 10, 12, 0, 0)  # 结束时间晚于开始时间

        record = BattleRecord(pilot=pilot,
                              start_time=start_time,
                              end_time=end_time,
                              work_mode=WorkMode.ONLINE,
                              owner_snapshot=pilot.owner,
                              registered_by=registrar)

        # 不应该抛出异常
        record.clean()
        assert record.duration_hours == 2.0

    def test_minimal_time_difference_should_pass(self, pilot, registrar):
        """最小的时间差应该通过验证"""
        start_time = datetime(2025, 9, 10, 10, 0, 0)
        end_time = datetime(2025, 9, 10, 10, 0, 1)  # 只差1秒

        record = BattleRecord(pilot=pilot,
                              start_time=start_time,
                              end_time=end_time,
                              work_mode=WorkMode.ONLINE,
                              owner_snapshot=pilot.owner,
                              registered_by=registrar)

        # 不应该抛出异常
        record.clean()
        assert record.duration_hours is not None
        assert record.duration_hours > 0

    def test_none_time_should_not_validate(self, pilot, registrar):
        """空时间不应该进行验证"""
        record = BattleRecord(pilot=pilot, start_time=None, end_time=None, work_mode=WorkMode.ONLINE, owner_snapshot=pilot.owner, registered_by=registrar)

        # 不应该抛出时间验证异常
        record.clean()
