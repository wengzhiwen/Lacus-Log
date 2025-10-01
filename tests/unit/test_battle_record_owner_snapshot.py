"""作战记录所属快照机制的单元测试。

覆盖：
- 有所属机师的快照正常
- 无所属机师的快照为空（不使用当前用户）
- 模型允许owner_snapshot为空
"""

# pylint: disable=import-error,no-member
from datetime import datetime

import pytest

from models.battle_record import BattleRecord
from models.pilot import WorkMode
from tests.fixtures.factory import create_pilot, create_user


@pytest.mark.unit
class TestBattleRecordOwnerSnapshot:
    """作战记录所属快照测试"""

    @pytest.fixture
    def registrar(self):
        """创建登记人"""
        return create_user('registrar_user')

    def test_pilot_with_owner_snapshot_should_use_owner(self, registrar):
        """有所属的机师应该使用机师的所属作为快照"""
        owner = create_user('owner_user')
        pilot = create_pilot('有所属机师', owner=owner)

        record = BattleRecord(
            pilot=pilot,
            start_time=datetime(2025, 9, 10, 10, 0, 0),
            end_time=datetime(2025, 9, 10, 12, 0, 0),
            work_mode=WorkMode.ONLINE,
            owner_snapshot=pilot.owner,  # 使用机师的所属
            registered_by=registrar)

        record.clean()
        assert record.owner_snapshot == owner
        assert record.owner_snapshot == pilot.owner

    def test_pilot_without_owner_snapshot_should_be_none(self, registrar):
        """无所属的机师快照应该为空"""
        pilot = create_pilot('无所属机师', owner=None)

        record = BattleRecord(
            pilot=pilot,
            start_time=datetime(2025, 9, 10, 10, 0, 0),
            end_time=datetime(2025, 9, 10, 12, 0, 0),
            work_mode=WorkMode.ONLINE,
            owner_snapshot=None,  # 无所属机师不设置快照
            registered_by=registrar)

        record.clean()
        assert record.owner_snapshot is None
        assert pilot.owner is None

    def test_owner_snapshot_field_allows_none(self, registrar):
        """owner_snapshot字段应该允许为空"""
        pilot = create_pilot('测试机师', owner=None)

        record = BattleRecord(pilot=pilot,
                              start_time=datetime(2025, 9, 10, 10, 0, 0),
                              end_time=datetime(2025, 9, 10, 12, 0, 0),
                              work_mode=WorkMode.ONLINE,
                              owner_snapshot=None,
                              registered_by=registrar)

        record.clean()
        assert record.owner_snapshot is None

    def test_owner_snapshot_preserves_historical_data(self, registrar):
        """所属快照应该保存历史数据"""
        owner = create_user('原所属')
        pilot = create_pilot('机师', owner=owner)

        record = BattleRecord(
            pilot=pilot,
            start_time=datetime(2025, 9, 10, 10, 0, 0),
            end_time=datetime(2025, 9, 10, 12, 0, 0),
            work_mode=WorkMode.ONLINE,
            owner_snapshot=pilot.owner,  # 当时的所属
            registered_by=registrar)

        record.clean()
        original_owner = record.owner_snapshot

        new_owner = create_user('新所属')
        pilot.owner = new_owner

        assert record.owner_snapshot == original_owner
        assert record.owner_snapshot != pilot.owner
