"""报表（作战日报）统计函数的单元测试。

覆盖：
- get_local_date_from_string
- get_battle_records_for_date_range（间接，使用内存DB）
- calculate_pilot_three_day_avg_revenue
- calculate_pilot_monthly_stats
"""

# pylint: disable=import-error,no-member
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from models.pilot import Rank, Status, WorkMode
from tests.fixtures.factory import (create_battle_record, create_pilot, create_user)

from routes.report import (calculate_pilot_monthly_stats, calculate_pilot_three_day_avg_revenue, get_local_date_from_string)


@pytest.mark.unit
class TestReportHelpers:

    def test_get_local_date_from_string(self):
        assert get_local_date_from_string('2025-09-11') == datetime(2025, 9, 11)
        assert get_local_date_from_string('') is None
        assert get_local_date_from_string(None) is None
        assert get_local_date_from_string('bad') is None


@pytest.mark.unit
class TestReportCalculations:

    @pytest.fixture
    def pilot_with_owner(self):
        owner = create_user('owner_user')
        pilot = create_pilot('报告机师', owner=owner, rank=Rank.INTERN, status=Status.RECRUITED, work_mode=WorkMode.ONLINE)
        return pilot

    def test_three_day_avg_revenue_basic(self, pilot_with_owner):
        pilot = pilot_with_owner

        base_date = datetime(2025, 9, 10)
        create_battle_record(pilot, base_date.replace(hour=10), base_date.replace(hour=12), revenue=Decimal('100.00'))
        d1 = base_date - timedelta(days=1)
        create_battle_record(pilot, d1.replace(hour=10), d1.replace(hour=12), revenue=Decimal('200.00'))
        d3 = base_date - timedelta(days=3)
        create_battle_record(pilot, d3.replace(hour=10), d3.replace(hour=12), revenue=Decimal('300.00'))

        avg = calculate_pilot_three_day_avg_revenue(pilot, base_date)
        assert round(Decimal(avg), 2) == Decimal('200.00')

    def test_three_day_avg_revenue_insufficient_days(self, pilot_with_owner):
        pilot = pilot_with_owner
        base_date = datetime(2025, 9, 10)

        create_battle_record(pilot, base_date.replace(hour=10), base_date.replace(hour=12), revenue=Decimal('120.00'))

        assert calculate_pilot_three_day_avg_revenue(pilot, base_date) is None

    def test_monthly_stats(self, pilot_with_owner):
        pilot = pilot_with_owner
        report_date = datetime(2025, 9, 15)

        create_battle_record(pilot, datetime(2025, 9, 1, 10), datetime(2025, 9, 1, 12), revenue=Decimal('100.00'), base_salary=Decimal('30.00'))
        create_battle_record(pilot, datetime(2025, 9, 5, 9), datetime(2025, 9, 5, 12, 30), revenue=Decimal('200.00'), base_salary=Decimal('40.00'))
        create_battle_record(pilot, datetime(2025, 9, 8, 20), datetime(2025, 9, 8, 20, 30), revenue=Decimal('50.00'), base_salary=Decimal('10.00'))

        stats = calculate_pilot_monthly_stats(pilot, report_date)

        assert stats['month_days_count'] == 3
        assert stats['month_avg_duration'] == 2.0  # (2 + 3.5 + 0.5) / 3 = 2.0
        assert stats['month_total_revenue'] == Decimal('350.00')
        assert stats['month_total_base_salary'] == Decimal('80.00')
