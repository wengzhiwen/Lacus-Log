"""作战记录业务逻辑的单元测试。

覆盖：
- 时间计算：播时计算、时间范围验证
- 金额验证：流水、底薪的数值范围
- 参战形式规则：线下必填坐标、线上可空坐标
- 业务规则：开始时间不能晚于结束时间
"""

# pylint: disable=import-error,no-member
from datetime import datetime
from decimal import Decimal

import pytest

from models.battle_record import BattleRecord
from models.pilot import WorkMode
from tests.fixtures.factory import (create_battle_record, create_pilot, create_user)


@pytest.mark.unit
class TestBattleRecordTimeLogic:

    @pytest.fixture
    def pilot(self):
        owner = create_user('owner_user')
        return create_pilot('作战机师', owner=owner)

    def test_duration_calculation(self, pilot):
        """测试播时计算"""
        start_time = datetime(2025, 9, 10, 10, 0)
        end_time = datetime(2025, 9, 10, 12, 30)  # 2.5小时

        record = create_battle_record(pilot, start_time, end_time)

        expected_duration = 2.5
        actual_duration = (record.end_time - record.start_time).total_seconds() / 3600
        assert abs(actual_duration - expected_duration) < 0.01

    def test_cross_day_duration(self, pilot):
        """测试跨天播时计算"""
        start_time = datetime(2025, 9, 10, 22, 0)  # 晚上10点
        end_time = datetime(2025, 9, 11, 2, 0)  # 次日凌晨2点

        record = create_battle_record(pilot, start_time, end_time)

        expected_duration = 4.0  # 4小时
        actual_duration = (record.end_time - record.start_time).total_seconds() / 3600
        assert abs(actual_duration - expected_duration) < 0.01

    def test_invalid_time_range(self, pilot):
        """测试无效时间范围"""
        start_time = datetime(2025, 9, 10, 12, 0)
        end_time = datetime(2025, 9, 10, 10, 0)  # 结束时间早于开始时间

        import pytest
        with pytest.raises(Exception):
            create_battle_record(pilot, start_time, end_time)


@pytest.mark.unit
class TestBattleRecordAmountValidation:

    @pytest.fixture
    def pilot(self):
        owner = create_user('owner_user')
        return create_pilot('作战机师', owner=owner)

    def test_valid_amounts(self, pilot):
        """测试有效金额"""
        start_time = datetime(2025, 9, 10, 10, 0)
        end_time = datetime(2025, 9, 10, 12, 0)

        record = create_battle_record(pilot, start_time, end_time, revenue=Decimal('150.50'), base_salary=Decimal('75.25'))

        assert record.revenue_amount == Decimal('150.50')
        assert record.base_salary == Decimal('75.25')

    def test_zero_amounts(self, pilot):
        """测试零金额"""
        start_time = datetime(2025, 9, 10, 10, 0)
        end_time = datetime(2025, 9, 10, 12, 0)

        record = create_battle_record(pilot, start_time, end_time, revenue=Decimal('0.00'), base_salary=Decimal('0.00'))

        assert record.revenue_amount == Decimal('0.00')
        assert record.base_salary == Decimal('0.00')

    def test_large_amounts(self, pilot):
        """测试大金额"""
        start_time = datetime(2025, 9, 10, 10, 0)
        end_time = datetime(2025, 9, 10, 12, 0)

        record = create_battle_record(pilot, start_time, end_time, revenue=Decimal('99999.99'), base_salary=Decimal('50000.00'))

        assert record.revenue_amount == Decimal('99999.99')
        assert record.base_salary == Decimal('50000.00')


@pytest.mark.unit
class TestBattleRecordWorkModeRules:

    @pytest.fixture
    def pilot(self):
        owner = create_user('owner_user')
        return create_pilot('作战机师', owner=owner)

    def test_offline_mode_requires_coordinates(self, pilot):
        """测试线下模式需要坐标"""
        start_time = datetime(2025, 9, 10, 10, 0)
        end_time = datetime(2025, 9, 10, 12, 0)

        record = create_battle_record(pilot, start_time, end_time, x='X1', y='Y1', z='1', work_mode=WorkMode.OFFLINE)

        assert record.work_mode == WorkMode.OFFLINE
        assert record.x_coord == 'X1'
        assert record.y_coord == 'Y1'
        assert record.z_coord == '1'

    def test_online_mode_coordinates_optional(self, pilot):
        """测试线上模式坐标可选"""
        start_time = datetime(2025, 9, 10, 10, 0)
        end_time = datetime(2025, 9, 10, 12, 0)

        record = create_battle_record(pilot, start_time, end_time, x='', y='', z='', work_mode=WorkMode.ONLINE)

        assert record.work_mode == WorkMode.ONLINE
        assert record.x_coord == ''
        assert record.y_coord == ''
        assert record.z_coord == ''

    def test_work_mode_display(self, pilot):
        """测试参战形式显示"""
        start_time = datetime(2025, 9, 10, 10, 0)
        end_time = datetime(2025, 9, 10, 12, 0)

        offline_record = create_battle_record(pilot, start_time, end_time, work_mode=WorkMode.OFFLINE)
        assert offline_record.work_mode.value == '线下'

        online_record = create_battle_record(pilot, start_time, end_time, work_mode=WorkMode.ONLINE)
        assert online_record.work_mode.value == '线上'


@pytest.mark.unit
class TestBattleRecordBusinessRules:

    @pytest.fixture
    def pilot(self):
        owner = create_user('owner_user')
        return create_pilot('作战机师', owner=owner)

    def test_owner_snapshot_preservation(self, pilot):
        """测试所属快照保存"""
        start_time = datetime(2025, 9, 10, 10, 0)
        end_time = datetime(2025, 9, 10, 12, 0)

        record = create_battle_record(pilot, start_time, end_time)

        assert record.owner_snapshot is not None
        assert record.owner_snapshot.id == pilot.owner.id

    def test_registered_by_tracking(self, pilot):
        """测试登记人跟踪"""
        start_time = datetime(2025, 9, 10, 10, 0)
        end_time = datetime(2025, 9, 10, 12, 0)

        record = create_battle_record(pilot, start_time, end_time)

        assert record.registered_by is not None

    def test_notes_field(self, pilot):
        """测试备注字段"""
        start_time = datetime(2025, 9, 10, 10, 0)
        end_time = datetime(2025, 9, 10, 12, 0)

        record = create_battle_record(pilot, start_time, end_time)
        record.notes = '测试备注'
        record.save()

        assert record.notes == '测试备注'


@pytest.mark.integration
@pytest.mark.requires_db
class TestBattleRecordIntegration:

    @pytest.fixture(autouse=True)
    def setup_db(self):
        """依赖 conftest 的全局连接与用例清库。"""
        yield

    def test_battle_record_crud_operations(self):
        """测试作战记录CRUD操作"""
        owner = create_user('owner_user')
        pilot = create_pilot('作战机师', owner=owner)

        start_time = datetime(2025, 9, 10, 10, 0)
        end_time = datetime(2025, 9, 10, 12, 0)
        record = create_battle_record(pilot, start_time, end_time, revenue=Decimal('200.00'), base_salary=Decimal('100.00'))

        saved_record = BattleRecord.objects(id=record.id).first()
        assert saved_record is not None
        assert saved_record.pilot.id == pilot.id
        assert saved_record.revenue_amount == Decimal('200.00')

        saved_record.revenue_amount = Decimal('250.00')
        saved_record.save()

        updated_record = BattleRecord.objects(id=record.id).first()
        assert updated_record.revenue_amount == Decimal('250.00')

        record_id = record.id
        record.delete()

        deleted_record = BattleRecord.objects(id=record_id).first()
        assert deleted_record is None
