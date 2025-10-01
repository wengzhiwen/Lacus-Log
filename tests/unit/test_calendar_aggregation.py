"""日历数据聚合的单元测试。

覆盖：
- 月视图数据聚合
- 周视图数据聚合
- 日视图数据聚合
- 统一处理逻辑的正确性
"""

# pylint: disable=import-error,no-member
from datetime import datetime, timedelta

import pytest

from tests.fixtures.factory import (create_announcement, create_battle_area, create_pilot, create_user)
from utils.calendar_aggregator import (aggregate_monthly_data, aggregate_weekly_data, aggregate_daily_data)


@pytest.mark.unit
class TestCalendarAggregation:
    """日历数据聚合测试"""

    @pytest.fixture
    def owner(self):
        """创建机师所属"""
        return create_user('owner_user')

    @pytest.fixture
    def pilot(self, owner):
        """创建测试机师"""
        return create_pilot('测试机师', owner=owner)

    @pytest.fixture
    def areas(self):
        """创建测试战斗区域"""
        return [create_battle_area('X1', 'Y1', '1'), create_battle_area('X1', 'Y1', '2'), create_battle_area('X2', 'Y2', '1')]

    def test_aggregate_monthly_data(self, pilot, areas):
        """测试月视图数据聚合"""
        create_announcement(pilot, areas[0], datetime(2025, 9, 1, 10))
        create_announcement(pilot, areas[1], datetime(2025, 9, 3, 14))
        create_announcement(pilot, areas[2], datetime(2025, 9, 5, 20))
        create_announcement(pilot, areas[0], datetime(2025, 9, 5, 22))  # 同一天多个

        result = aggregate_monthly_data(2025, 9)

        assert result['year'] == 2025
        assert result['month'] == 9
        assert 'daily_counts' in result

        daily_counts = result['daily_counts']
        assert daily_counts['2025-09-01'] == 1
        assert daily_counts['2025-09-03'] == 1
        assert daily_counts['2025-09-05'] == 2  # 同一天有2个通告
        assert daily_counts.get('2025-09-02', 0) == 0  # 没有通告的日期

    def test_aggregate_weekly_data(self, pilot, areas):
        """测试周视图数据聚合"""
        create_announcement(pilot, areas[0], datetime(2025, 9, 8, 10))  # 周一
        create_announcement(pilot, areas[1], datetime(2025, 9, 10, 14))  # 周三
        create_announcement(pilot, areas[2], datetime(2025, 9, 12, 20))  # 周五

        reference_date = datetime(2025, 9, 10)
        result = aggregate_weekly_data(reference_date)

        assert result['week_start'] == '2025-09-08'
        assert result['week_end'] == '2025-09-14'
        assert 'week_data' in result

        week_data = result['week_data']

        monday_data = week_data['2025-09-08']
        assert monday_data['day_name'] == '周一'
        assert monday_data['announcement_count'] == 1
        assert 'X1-Y1-1' in monday_data['used_areas']

        wednesday_data = week_data['2025-09-10']
        assert wednesday_data['day_name'] == '周三'
        assert wednesday_data['announcement_count'] == 1
        assert 'X1-Y1-2' in wednesday_data['used_areas']

        friday_data = week_data['2025-09-12']
        assert friday_data['day_name'] == '周五'
        assert friday_data['announcement_count'] == 1
        assert 'X2-Y2-1' in friday_data['used_areas']

        tuesday_data = week_data['2025-09-09']
        assert tuesday_data['day_name'] == '周二'
        assert tuesday_data['announcement_count'] == 0
        assert len(tuesday_data['used_areas']) == 0

    def test_aggregate_daily_data(self, pilot, areas):
        """测试日视图数据聚合"""
        create_announcement(pilot, areas[0], datetime(2025, 9, 10, 9), duration_hours=2.0)
        create_announcement(pilot, areas[1], datetime(2025, 9, 10, 14), duration_hours=3.0)

        target_date = datetime(2025, 9, 10)
        result = aggregate_daily_data(target_date)

        assert result['date'] == '2025-09-10'
        assert 'area_timelines' in result
        assert 'used_areas_count' in result

        area_timelines = result['area_timelines']
        assert len(area_timelines) == 2
        assert 'X1-Y1-1' in area_timelines
        assert 'X1-Y1-2' in area_timelines

        area1_timeline = area_timelines['X1-Y1-1']
        assert area1_timeline['area_display'] == 'X1-Y1-1'
        assert len(area1_timeline['slots']) == 1
        slot1 = area1_timeline['slots'][0]
        assert slot1['start_hour'] == 9
        assert slot1['end_hour'] == 11

        area2_timeline = area_timelines['X1-Y1-2']
        assert area2_timeline['area_display'] == 'X1-Y1-2'
        assert len(area2_timeline['slots']) == 1
        slot2 = area2_timeline['slots'][0]
        assert slot2['start_hour'] == 14
        assert slot2['end_hour'] == 17

        assert result['used_areas_count'] == 2

    def test_aggregate_monthly_data_empty(self):
        """测试空月份数据聚合"""
        result = aggregate_monthly_data(2025, 12)

        assert result['year'] == 2025
        assert result['month'] == 12
        assert result['daily_counts'] == {}

    def test_aggregate_weekly_data_empty(self):
        """测试空周数据聚合"""
        reference_date = datetime(2025, 12, 15)
        result = aggregate_weekly_data(reference_date)

        assert 'week_start' in result
        assert 'week_end' in result
        assert 'week_data' in result

        week_data = result['week_data']
        assert len(week_data) == 7

        for day_data in week_data.values():
            assert day_data['announcement_count'] == 0
            assert len(day_data['used_areas']) == 0

    def test_aggregate_daily_data_empty(self):
        """测试空日数据聚合"""
        target_date = datetime(2025, 12, 15)
        result = aggregate_daily_data(target_date)

        assert result['date'] == '2025-12-15'
        assert result['area_timelines'] == {}
        assert result['used_areas_count'] == 0

    def test_cross_day_announcement_handling(self, pilot, areas):
        """测试跨天通告的处理"""
        create_announcement(pilot, areas[0], datetime(2025, 9, 10, 23), duration_hours=3.0)

        result_day1 = aggregate_daily_data(datetime(2025, 9, 10))

        result_day2 = aggregate_daily_data(datetime(2025, 9, 11))

        assert len(result_day1['area_timelines']) == 1
        day1_slot = result_day1['area_timelines']['X1-Y1-1']['slots'][0]
        assert day1_slot['start_hour'] == 23
        assert day1_slot['end_hour'] == 23

        assert len(result_day2['area_timelines']) == 1
        day2_slot = result_day2['area_timelines']['X1-Y1-1']['slots'][0]
        assert day2_slot['start_hour'] == 0
        assert day2_slot['end_hour'] == 2
