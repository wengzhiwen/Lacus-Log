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

        # 设置每日重复，间隔1天，到9月15日结束
        ann.recurrence_type = RecurrenceType.DAILY
        ann.recurrence_pattern = '{"type": "daily", "interval": 1}'
        ann.recurrence_end = datetime(2025, 9, 15, 23, 59, 59)
        ann.save()

        instances = Announcement.generate_recurrence_instances(ann)

        # 应该生成6个实例：9/10, 9/11, 9/12, 9/13, 9/14, 9/15
        assert len(instances) == 6
        assert instances[0].start_time.date() == datetime(2025, 9, 10).date()
        assert instances[1].start_time.date() == datetime(2025, 9, 11).date()
        assert instances[5].start_time.date() == datetime(2025, 9, 15).date()

    def test_weekly_recurrence_generation(self, pilot, area):
        """测试每周重复生成"""
        base_start = datetime(2025, 9, 9, 10)  # 周一
        ann = create_announcement(pilot, area, base_start, duration_hours=2.0)

        # 设置每周重复，间隔1周，周一和周三，到9月30日结束
        ann.recurrence_type = RecurrenceType.WEEKLY
        ann.recurrence_pattern = '{"type": "weekly", "interval": 1, "days_of_week": [0, 2]}'  # 周一、周三
        ann.recurrence_end = datetime(2025, 9, 30, 23, 59, 59)
        ann.save()

        instances = Announcement.generate_recurrence_instances(ann)

        # 应该生成多个实例，每个周一和周三
        assert len(instances) > 0
        # 验证第一个是周一
        assert instances[0].start_time.weekday() == 0  # 周一
        # 验证第二个是周三
        assert instances[1].start_time.weekday() == 2  # 周三

    def test_custom_dates_recurrence(self, pilot, area):
        """测试自定义日期列表重复"""
        base_start = datetime(2025, 9, 10, 10)
        ann = create_announcement(pilot, area, base_start, duration_hours=2.0)

        # 设置自定义日期：9/10, 9/15, 9/20
        ann.recurrence_type = RecurrenceType.CUSTOM
        ann.recurrence_pattern = '{"type": "custom", "specific_dates": ["2025-09-10", "2025-09-15", "2025-09-20"]}'
        ann.save()

        instances = Announcement.generate_recurrence_instances(ann)

        # 应该生成3个实例
        assert len(instances) == 3
        assert instances[0].start_time.date() == datetime(2025, 9, 10).date()
        assert instances[1].start_time.date() == datetime(2025, 9, 15).date()
        assert instances[2].start_time.date() == datetime(2025, 9, 20).date()


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
        # 创建第一个通告：9月10日10:00-12:00
        ann1 = create_announcement(pilot1, area1, datetime(2025, 9, 10, 10), duration_hours=2.0)

        # 创建第二个通告：同一区域，时间重叠 9月10日11:00-13:00
        ann2 = create_announcement(pilot2, area1, datetime(2025, 9, 10, 11), duration_hours=2.0)

        # 检查ann2的冲突
        conflicts = ann2.check_conflicts(exclude_self=True)

        assert len(conflicts['area_conflicts']) == 1
        assert conflicts['area_conflicts'][0]['announcement'].id == ann1.id
        assert len(conflicts['pilot_conflicts']) == 0

    def test_pilot_conflict_detection(self, pilot1, area1, area2):
        """测试机师冲突检测"""
        # 创建第一个通告：机师1在区域1，9月10日10:00-12:00
        ann1 = create_announcement(pilot1, area1, datetime(2025, 9, 10, 10), duration_hours=2.0)

        # 创建第二个通告：同一机师在不同区域，时间重叠 9月10日11:00-13:00
        ann2 = create_announcement(pilot1, area2, datetime(2025, 9, 10, 11), duration_hours=2.0)

        # 检查ann2的冲突
        conflicts = ann2.check_conflicts(exclude_self=True)

        assert len(conflicts['pilot_conflicts']) == 1
        assert conflicts['pilot_conflicts'][0]['announcement'].id == ann1.id
        assert len(conflicts['area_conflicts']) == 0

    def test_no_conflict_scenario(self, pilot1, pilot2, area1, area2):
        """测试无冲突场景"""
        # 创建第一个通告：机师1在区域1，9月10日10:00-12:00
        create_announcement(pilot1, area1, datetime(2025, 9, 10, 10), duration_hours=2.0)

        # 创建第二个通告：机师2在区域2，不同时间 9月10日14:00-16:00
        ann2 = create_announcement(pilot2, area2, datetime(2025, 9, 10, 14), duration_hours=2.0)

        # 检查ann2的冲突
        conflicts = ann2.check_conflicts(exclude_self=True)

        assert len(conflicts['area_conflicts']) == 0
        assert len(conflicts['pilot_conflicts']) == 0

    def test_edge_case_same_start_time(self, pilot1, pilot2, area1):
        """测试边界情况：相同开始时间"""
        start_time = datetime(2025, 9, 10, 10)

        # 创建第一个通告
        ann1 = create_announcement(pilot1, area1, start_time, duration_hours=2.0)

        # 创建第二个通告：相同开始时间
        ann2 = create_announcement(pilot2, area1, start_time, duration_hours=1.5)

        # 检查ann2的冲突
        conflicts = ann2.check_conflicts(exclude_self=True)

        assert len(conflicts['area_conflicts']) == 1
        assert conflicts['area_conflicts'][0]['announcement'].id == ann1.id


@pytest.mark.integration
@pytest.mark.requires_db
class TestAnnouncementIntegration:

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
        Announcement.objects().delete()

        yield

        # 测试结束后清理数据
        try:
            Announcement.objects().delete()
        except Exception:
            pass
        disconnect()

    def test_complex_recurrence_with_conflicts(self):
        """测试复杂重复场景与冲突处理"""
        owner = create_user('owner_user')
        pilot = create_pilot('复杂机师', owner=owner)
        area = create_battle_area('X1', 'Y1', '1')

        # 创建每日重复的通告
        base_start = datetime(2025, 9, 10, 10)
        ann = create_announcement(pilot, area, base_start, duration_hours=2.0)

        ann.recurrence_type = RecurrenceType.DAILY
        ann.recurrence_pattern = '{"type": "daily", "interval": 1}'
        ann.recurrence_end = datetime(2025, 9, 12, 23, 59, 59)
        ann.save()

        # 生成重复实例
        instances = Announcement.generate_recurrence_instances(ann)

        # 保存所有实例
        for instance in instances[1:]:  # 跳过第一个（已保存）
            instance.save()

        # 验证所有实例都已保存
        saved_announcements = Announcement.objects(pilot=pilot).order_by('start_time')
        assert saved_announcements.count() == 3

        # 验证时间正确
        dates = [ann.start_time.date() for ann in saved_announcements]
        assert datetime(2025, 9, 10).date() in dates
        assert datetime(2025, 9, 11).date() in dates
        assert datetime(2025, 9, 12).date() in dates
