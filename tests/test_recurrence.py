import json
from datetime import datetime

import pytest

from models.announcement import Announcement, RecurrenceType
from models.battle_area import BattleArea
from models.pilot import Pilot
from models.user import User


def build_base_announcement(start_iso: str,
                            recurrence_type: RecurrenceType,
                            pattern: dict,
                            recurrence_end_iso: str):
    pilot = Pilot(nickname="测试机师")
    user = User(username="tester")
    area = BattleArea(x_coord="无锡360", y_coord="无烟房", z_coord="5")

    base = Announcement(pilot=pilot,
                        battle_area=area,
                        x_coord=area.x_coord,
                        y_coord=area.y_coord,
                        z_coord=area.z_coord,
                        start_time=datetime.fromisoformat(start_iso),
                        duration_hours=6.0,
                        created_by=user,
                        recurrence_type=recurrence_type,
                        recurrence_pattern=json.dumps(pattern),
                        recurrence_end=datetime.fromisoformat(recurrence_end_iso))
    return base


def extract_dates(anns):
    return sorted([a.start_time.strftime('%Y-%m-%d %H:%M') for a in anns])


def test_weekly_from_sunday_generates_next_monday_first():
    # 2025-09-14 是周日，选择周一至周五，应从 09/15 开始
    base = build_base_announcement(
        start_iso="2025-09-14T10:00:00",
        recurrence_type=RecurrenceType.WEEKLY,
        pattern={"interval": 1, "days_of_week": [1, 2, 3, 4, 5]},
        recurrence_end_iso="2025-09-30T23:59:00",
    )

    instances = Announcement.generate_recurrence_instances(base)

    # 不应生成与 base.start_time 相同的额外实例
    same_day_count = sum(1 for a in instances if a.start_time == base.start_time)
    assert same_day_count == 1

    dates = extract_dates(instances)
    # 应包含 9/15 工作日开始的多天
    assert "2025-09-15 10:00" in dates
    assert "2025-09-16 10:00" in dates
    assert "2025-09-17 10:00" in dates
    assert "2025-09-18 10:00" in dates
    assert "2025-09-19 10:00" in dates


def test_weekly_from_monday_no_duplicate_on_base_day():
    # 2025-09-15 是周一，选择周一至周五，列表中不应出现两个 9/15
    base = build_base_announcement(
        start_iso="2025-09-15T10:00:00",
        recurrence_type=RecurrenceType.WEEKLY,
        pattern={"interval": 1, "days_of_week": [1, 2, 3, 4, 5]},
        recurrence_end_iso="2025-09-30T23:59:00",
    )

    instances = Announcement.generate_recurrence_instances(base)

    # base 当天只能出现一次
    dates = [a.start_time.strftime('%Y-%m-%d') for a in instances]
    assert dates.count("2025-09-15") == 1


def test_coords_snapshot_copied_to_instances():
    base = build_base_announcement(
        start_iso="2025-09-15T10:00:00",
        recurrence_type=RecurrenceType.DAILY,
        pattern={"interval": 1},
        recurrence_end_iso="2025-09-17T23:59:00",
    )

    instances = Announcement.generate_recurrence_instances(base)
    # 至少应包含 base + 2 天
    assert len(instances) >= 3

    for a in instances:
        assert a.x_coord == "无锡360"
        assert a.y_coord == "无烟房"
        assert a.z_coord == "5"


def test_weekly_days_type_robustness_accepts_string_numbers():
    # 即使 pattern 中意外包含字符串数字，也不应报错
    base = build_base_announcement(
        start_iso="2025-09-14T10:00:00",
        recurrence_type=RecurrenceType.WEEKLY,
        pattern={"interval": 1, "days_of_week": ["1", "2", 3, 4, 5]},
        recurrence_end_iso="2025-09-16T23:59:00",
    )

    instances = Announcement.generate_recurrence_instances(base)
    dates = extract_dates(instances)
    # 应包含 9/15 (周一)
    assert "2025-09-15 10:00" in dates


