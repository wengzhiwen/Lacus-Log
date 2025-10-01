"""通告重复生成与冲突检查的单元/集成测试。

覆盖：
- Announcement.generate_recurrence_instances：重复事件生成
- Announcement.check_conflicts：区域/机师冲突检查
- 边界条件：跨天、跨月、自定义日期列表
"""

# pylint: disable=import-error,no-member
from datetime import datetime

import pytest

from models.announcement import Announcement, RecurrenceType
from tests.fixtures.factory import (create_announcement, create_battle_area, create_pilot, create_user)


@pytest.mark.unit
class TestAnnouncementRecurrence:

    @pytest.fixture
    def pilot(self):
        owner = create_user('owner_user')
        return create_pilot('通告机师', owner=owner)

    @pytest.fixture
    def area(self):
        return create_battle_area('X1', 'Y1', '1')

    def test_daily_recurrence_generation(self, pilot, area):
        """测试每日重复生成"""
        base_start = datetime(2025, 9, 10, 10)  # 9月10日10点
        ann = create_announcement(pilot, area, base_start, duration_hours=2.0)

        ann.recurrence_type = RecurrenceType.DAILY
        ann.recurrence_pattern = '{"type": "每日", "interval": 1}'
        ann.recurrence_end = datetime(2025, 9, 15, 23, 59, 59)
        ann.save()

        instances = Announcement.generate_recurrence_instances(ann)

        assert len(instances) == 6
        assert instances[0].start_time.date() == datetime(2025, 9, 10).date()
        assert instances[1].start_time.date() == datetime(2025, 9, 11).date()
        assert instances[5].start_time.date() == datetime(2025, 9, 15).date()

    def test_weekly_recurrence_generation(self, pilot, area):
        """测试每周重复生成"""
        base_start = datetime(2025, 9, 8, 10)  # 周一
        ann = create_announcement(pilot, area, base_start, duration_hours=2.0)

        ann.recurrence_type = RecurrenceType.WEEKLY
        ann.recurrence_pattern = '{"type": "每周", "interval": 1, "days_of_week": [1, 3]}'  # 周一、周三
        ann.recurrence_end = datetime(2025, 9, 30, 23, 59, 59)
        ann.save()

        instances = Announcement.generate_recurrence_instances(ann)

        assert len(instances) > 0
        assert instances[0].start_time.weekday() == 0  # 周一
        assert instances[1].start_time.weekday() == 2  # 周三

    def test_custom_dates_recurrence(self, pilot, area):
        """测试自定义日期列表重复"""
        base_start = datetime(2025, 9, 10, 10)
        ann = create_announcement(pilot, area, base_start, duration_hours=2.0)

        ann.recurrence_type = RecurrenceType.CUSTOM
        ann.recurrence_pattern = '{"type": "自定义", "specific_dates": ["2025-09-10", "2025-09-15", "2025-09-20"]}'
        ann.save()

        instances = Announcement.generate_recurrence_instances(ann)

        assert len(instances) == 4
        assert instances[0].start_time.date() == datetime(2025, 9, 10).date()
        dates = {inst.start_time.date() for inst in instances}
        assert datetime(2025, 9, 15).date() in dates
        assert datetime(2025, 9, 20).date() in dates


@pytest.mark.unit
class TestAnnouncementConflicts:

    @pytest.fixture
    def pilot1(self):
        owner = create_user('owner1')
        return create_pilot('机师1', owner=owner)

    @pytest.fixture
    def pilot2(self):
        owner = create_user('owner2')
        return create_pilot('机师2', owner=owner)

    @pytest.fixture
    def area1(self):
        return create_battle_area('X1', 'Y1', '1')

    @pytest.fixture
    def area2(self):
        return create_battle_area('X1', 'Y1', '2')

    def test_area_conflict_detection(self, pilot1, pilot2, area1):
        """测试区域冲突检测"""
        ann1 = create_announcement(pilot1, area1, datetime(2025, 9, 10, 10), duration_hours=2.0)

        ann2 = create_announcement(pilot2, area1, datetime(2025, 9, 10, 11), duration_hours=2.0)

        conflicts = ann2.check_conflicts(exclude_self=True)

        assert len(conflicts['area_conflicts']) == 1
        assert conflicts['area_conflicts'][0]['announcement'].id == ann1.id
        assert len(conflicts['pilot_conflicts']) == 0

    def test_pilot_conflict_detection(self, pilot1, area1, area2):
        """测试机师冲突检测"""
        ann1 = create_announcement(pilot1, area1, datetime(2025, 9, 10, 10), duration_hours=2.0)

        ann2 = create_announcement(pilot1, area2, datetime(2025, 9, 10, 11), duration_hours=2.0)

        conflicts = ann2.check_conflicts(exclude_self=True)

        assert len(conflicts['pilot_conflicts']) == 1
        assert conflicts['pilot_conflicts'][0]['announcement'].id == ann1.id
        assert len(conflicts['area_conflicts']) == 0

    def test_no_conflict_scenario(self, pilot1, pilot2, area1, area2):
        """测试无冲突场景"""
        create_announcement(pilot1, area1, datetime(2025, 9, 10, 10), duration_hours=2.0)

        ann2 = create_announcement(pilot2, area2, datetime(2025, 9, 10, 14), duration_hours=2.0)

        conflicts = ann2.check_conflicts(exclude_self=True)

        assert len(conflicts['area_conflicts']) == 0
        assert len(conflicts['pilot_conflicts']) == 0

    def test_edge_case_same_start_time(self, pilot1, pilot2, area1):
        """测试边界情况：相同开始时间"""
        start_time = datetime(2025, 9, 10, 10)

        ann1 = create_announcement(pilot1, area1, start_time, duration_hours=2.0)

        ann2 = create_announcement(pilot2, area1, start_time, duration_hours=1.5)

        conflicts = ann2.check_conflicts(exclude_self=True)

        assert len(conflicts['area_conflicts']) == 1
        assert conflicts['area_conflicts'][0]['announcement'].id == ann1.id


@pytest.mark.integration
@pytest.mark.requires_db
class TestAnnouncementIntegration:

    @pytest.fixture(autouse=True)
    def setup_db(self):
        """依赖全局连接与用例级清库，由 conftest 提供。"""
        yield

    def test_complex_recurrence_with_conflicts(self):
        """测试复杂重复场景与冲突处理"""
        owner = create_user('owner_user')
        pilot = create_pilot('复杂机师', owner=owner)
        area = create_battle_area('X1', 'Y1', '1')

        base_start = datetime(2025, 9, 10, 10)
        ann = create_announcement(pilot, area, base_start, duration_hours=2.0)

        ann.recurrence_type = RecurrenceType.DAILY
        ann.recurrence_pattern = '{"type": "每日", "interval": 1}'
        ann.recurrence_end = datetime(2025, 9, 12, 23, 59, 59)
        ann.save()

        instances = Announcement.generate_recurrence_instances(ann)

        for instance in instances[1:]:  # 跳过第一个（已保存）
            instance.save()

        saved_announcements = Announcement.objects(pilot=pilot).order_by('start_time')
        assert saved_announcements.count() == 3

        dates = [ann.start_time.date() for ann in saved_announcements]
        assert datetime(2025, 9, 10).date() in dates
        assert datetime(2025, 9, 11).date() in dates
        assert datetime(2025, 9, 12).date() in dates
