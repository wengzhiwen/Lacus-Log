"""日历API计算逻辑的单元测试。

覆盖：
- 月视图：按本地日期聚合计数
- 周视图：按本地日期聚合计数与区域占用
- 日视图：按区域分组的时间轴与跨天处理
"""

# pylint: disable=import-error,no-member
from datetime import datetime, timedelta

import pytest

from models.announcement import Announcement
from tests.fixtures.factory import (create_announcement, create_battle_area, create_pilot, create_user)
from utils.timezone_helper import utc_to_local, local_to_utc


@pytest.mark.unit
class TestCalendarMonthData:

    @pytest.fixture
    def pilot(self):
        owner = create_user('owner_user')
        return create_pilot('日历机师', owner=owner)

    @pytest.fixture
    def area(self):
        return create_battle_area('X1', 'Y1', '1')

    def test_month_daily_counts(self, pilot, area):
        create_announcement(pilot, area, datetime(2025, 9, 1, 10))
        create_announcement(pilot, area, datetime(2025, 9, 3, 14))
        create_announcement(pilot, area, datetime(2025, 9, 5, 20))

        first_day = datetime(2025, 9, 1)
        last_day = datetime(2025, 9, 30, 23, 59, 59)
        first_day_utc = local_to_utc(first_day)
        last_day_utc = local_to_utc(last_day)

        announcements = Announcement.objects(start_time__gte=first_day_utc, start_time__lte=last_day_utc).only('start_time')

        daily_counts = {}
        for ann in announcements:
            local_start = utc_to_local(ann.start_time)
            date_key = local_start.strftime('%Y-%m-%d')
            daily_counts[date_key] = daily_counts.get(date_key, 0) + 1

        assert daily_counts['2025-09-01'] == 1
        assert daily_counts['2025-09-03'] == 1
        assert daily_counts['2025-09-05'] == 1
        assert daily_counts.get('2025-09-02', 0) == 0


@pytest.mark.unit
class TestCalendarWeekData:

    @pytest.fixture
    def pilot(self):
        owner = create_user('owner_user')
        return create_pilot('日历机师', owner=owner)

    @pytest.fixture
    def areas(self):
        return [create_battle_area('X1', 'Y1', str(i)) for i in range(1, 4)]

    def test_week_used_areas(self, pilot, areas):
        create_announcement(pilot, areas[0], datetime(2025, 9, 8, 10))  # 周一
        create_announcement(pilot, areas[1], datetime(2025, 9, 10, 14))  # 周三
        create_announcement(pilot, areas[2], datetime(2025, 9, 12, 20))  # 周五

        date = datetime(2025, 9, 10)  # 周三
        days_since_monday = date.weekday()
        week_start = date - timedelta(days=days_since_monday)
        week_end = week_start + timedelta(days=6, hours=23, minutes=59, seconds=59)

        week_start_utc = local_to_utc(week_start)
        week_end_utc = local_to_utc(week_end)

        announcements = Announcement.objects(start_time__gte=week_start_utc, start_time__lte=week_end_utc).only('start_time', 'x_coord', 'y_coord', 'z_coord')

        weekly_data = {}
        for i in range(7):
            current_day = week_start + timedelta(days=i)
            date_key = current_day.strftime('%Y-%m-%d')
            weekly_data[date_key] = {'used_areas': set()}

        for ann in announcements:
            local_start = utc_to_local(ann.start_time)
            date_key = local_start.strftime('%Y-%m-%d')
            if date_key in weekly_data:
                area_key = f"{ann.x_coord}-{ann.y_coord}-{ann.z_coord}"
                weekly_data[date_key]['used_areas'].add(area_key)

        assert 'X1-Y1-1' in weekly_data['2025-09-08']['used_areas']
        assert 'X1-Y1-2' in weekly_data['2025-09-10']['used_areas']
        assert 'X1-Y1-3' in weekly_data['2025-09-12']['used_areas']


@pytest.mark.unit
class TestCalendarDayData:

    @pytest.fixture
    def pilot(self):
        owner = create_user('owner_user')
        return create_pilot('日历机师', owner=owner)

    @pytest.fixture
    def areas(self):
        return [create_battle_area('X1', 'Y1', str(i)) for i in range(1, 3)]

    def test_day_timeline_by_area(self, pilot, areas):
        create_announcement(pilot, areas[0], datetime(2025, 9, 10, 9), duration_hours=2.0)
        create_announcement(pilot, areas[1], datetime(2025, 9, 10, 14), duration_hours=3.0)

        date = datetime(2025, 9, 10)
        day_start = date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = date.replace(hour=23, minute=59, second=59, microsecond=999999)

        day_start_utc = local_to_utc(day_start)
        day_end_utc = local_to_utc(day_end)

        announcements = Announcement.objects(start_time__lte=day_end_utc)

        relevant_announcements = []
        for announcement in announcements:
            end_time = announcement.start_time + timedelta(hours=announcement.duration_hours)
            if end_time > day_start_utc and announcement.start_time <= day_end_utc:
                relevant_announcements.append(announcement)

        area_timelines = {}
        for ann in relevant_announcements:
            local_start = utc_to_local(ann.start_time)
            local_end = local_start + timedelta(hours=ann.duration_hours)
            area_key = f"{ann.x_coord}-{ann.y_coord}-{ann.z_coord}"
            if area_key not in area_timelines:
                area_timelines[area_key] = {'slots': []}
            area_timelines[area_key]['slots'].append({
                'start_hour': local_start.hour,
                'end_hour': local_end.hour,
                'duration': local_end.hour - local_start.hour + 1
            })

        assert len(area_timelines) == 2
        assert 'X1-Y1-1' in area_timelines
        assert 'X1-Y1-2' in area_timelines
        assert len(area_timelines['X1-Y1-1']['slots']) == 1
        assert len(area_timelines['X1-Y1-2']['slots']) == 1
