"""通告重复事件生成数量限制的单元测试。

覆盖：
- 每日重复最多生成60个实例
- 每周重复最多生成60个实例
- 自定义重复最多生成60个实例
"""

# pylint: disable=import-error,no-member
import json
from datetime import datetime, timedelta

import pytest

from models.announcement import Announcement, RecurrenceType
from tests.fixtures.factory import (create_announcement, create_battle_area, create_pilot, create_user)


@pytest.mark.unit
class TestAnnouncementRecurrenceLimit:
    """通告重复事件生成数量限制测试"""

    @pytest.fixture
    def pilot(self):
        """创建测试机师"""
        owner = create_user('owner_user')
        return create_pilot('测试机师', owner=owner)

    @pytest.fixture
    def area(self):
        """创建测试战斗区域"""
        return create_battle_area('X1', 'Y1', '1')

    @pytest.fixture
    def creator(self):
        """创建用户"""
        return create_user('creator_user')

    def test_daily_recurrence_limited_to_60_instances(self, pilot, area, creator):
        """测试每日重复最多生成60个实例"""
        base_announcement = Announcement(
            pilot=pilot,
            battle_area=area,
            x_coord=area.x_coord,
            y_coord=area.y_coord,
            z_coord=area.z_coord,
            start_time=datetime(2025, 1, 1, 10, 0, 0),
            duration_hours=2.0,
            recurrence_type=RecurrenceType.DAILY,
            recurrence_pattern=json.dumps({
                'type': 'daily',
                'interval': 1  # 每天重复
            }),
            recurrence_end=datetime(2025, 12, 31, 23, 59, 59),  # 365天
            created_by=creator)

        instances = Announcement.generate_recurrence_instances(base_announcement)

        # 包含原始通告，所以总数应该是61（1个原始 + 60个生成）
        assert len(instances) == 61
        assert instances[0] == base_announcement
        assert len(instances[1:]) == 60  # 生成的实例

    def test_weekly_recurrence_limited_to_60_instances(self, pilot, area, creator):
        """测试每周重复最多生成60个实例"""
        base_announcement = Announcement(
            pilot=pilot,
            battle_area=area,
            x_coord=area.x_coord,
            y_coord=area.y_coord,
            z_coord=area.z_coord,
            start_time=datetime(2025, 1, 1, 10, 0, 0),  # 周三
            duration_hours=2.0,
            recurrence_type=RecurrenceType.WEEKLY,
            recurrence_pattern=json.dumps({
                'type': 'weekly',
                'interval': 1,
                'days_of_week': [1, 3, 5]  # 周一、三、五（每周3次）
            }),
            recurrence_end=datetime(2025, 12, 31, 23, 59, 59),  # 一年
            created_by=creator)

        instances = Announcement.generate_recurrence_instances(base_announcement)

        # 包含原始通告，生成的实例应该被限制在60个以内
        assert len(instances) == 61  # 1个原始 + 60个生成
        assert instances[0] == base_announcement
        assert len(instances[1:]) == 60

    def test_custom_recurrence_limited_to_60_instances(self, pilot, area, creator):
        """测试自定义重复最多生成60个实例"""
        # 生成70个日期的列表
        specific_dates = []
        base_date = datetime(2025, 1, 1, 10, 0, 0)
        for i in range(1, 71):  # 生成70个日期（不包含原始日期）
            date = base_date + timedelta(days=i)
            specific_dates.append(date.isoformat())

        base_announcement = Announcement(pilot=pilot,
                                         battle_area=area,
                                         x_coord=area.x_coord,
                                         y_coord=area.y_coord,
                                         z_coord=area.z_coord,
                                         start_time=base_date,
                                         duration_hours=2.0,
                                         recurrence_type=RecurrenceType.CUSTOM,
                                         recurrence_pattern=json.dumps({
                                             'type': 'custom',
                                             'specific_dates': specific_dates
                                         }),
                                         created_by=creator)

        instances = Announcement.generate_recurrence_instances(base_announcement)

        # 包含原始通告，生成的实例应该被限制在60个
        assert len(instances) == 61  # 1个原始 + 60个生成
        assert instances[0] == base_announcement
        assert len(instances[1:]) == 60

    def test_recurrence_under_limit_works_normally(self, pilot, area, creator):
        """测试在限制以下的重复正常工作"""
        base_announcement = Announcement(
            pilot=pilot,
            battle_area=area,
            x_coord=area.x_coord,
            y_coord=area.y_coord,
            z_coord=area.z_coord,
            start_time=datetime(2025, 1, 1, 10, 0, 0),
            duration_hours=2.0,
            recurrence_type=RecurrenceType.DAILY,
            recurrence_pattern=json.dumps({
                'type': 'daily',
                'interval': 1
            }),
            recurrence_end=datetime(2025, 1, 10, 23, 59, 59),  # 10天
            created_by=creator)

        instances = Announcement.generate_recurrence_instances(base_announcement)

        # 应该生成原始通告 + 9个重复实例 = 10个
        assert len(instances) == 10
        assert instances[0] == base_announcement
        assert len(instances[1:]) == 9

    def test_no_recurrence_returns_base_only(self, pilot, area, creator):
        """测试无重复时只返回原始通告"""
        base_announcement = Announcement(pilot=pilot,
                                         battle_area=area,
                                         x_coord=area.x_coord,
                                         y_coord=area.y_coord,
                                         z_coord=area.z_coord,
                                         start_time=datetime(2025, 1, 1, 10, 0, 0),
                                         duration_hours=2.0,
                                         recurrence_type=RecurrenceType.NONE,
                                         created_by=creator)

        instances = Announcement.generate_recurrence_instances(base_announcement)

        # 只应该有原始通告
        assert len(instances) == 1
        assert instances[0] == base_announcement
