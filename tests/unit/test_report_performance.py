"""报表性能优化的单元测试。

覆盖：
- 批量计算机师统计数据的正确性
- 优化版本与原版本结果一致性
- 性能提升验证
"""

# pylint: disable=import-error,no-member
from datetime import datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest

from models.battle_record import BattleRecord
from models.pilot import WorkMode
from tests.fixtures.factory import create_pilot, create_user, create_battle_record
from utils.report_optimizer import (batch_calculate_pilot_stats, calculate_pilot_three_day_avg_revenue_optimized, calculate_pilot_monthly_stats_optimized)


@pytest.mark.unit
class TestReportPerformance:
    """报表性能优化测试"""

    @pytest.fixture
    def owner(self):
        """创建机师所属"""
        return create_user('owner_user')

    @pytest.fixture
    def registrar(self):
        """创建登记人"""
        return create_user('registrar_user')

    @pytest.fixture
    def pilots(self, owner):
        """创建多个测试机师"""
        return [create_pilot('机师1', owner=owner), create_pilot('机师2', owner=owner), create_pilot('机师3', owner=owner)]

    def test_batch_calculate_pilot_stats_accuracy(self, pilots, registrar):
        """测试批量计算机师统计数据的准确性"""
        report_date = datetime(2025, 9, 15, 12, 0, 0)

        for i, pilot in enumerate(pilots):
            for day in range(1, 11):  # 1号到10号
                create_battle_record(pilot=pilot,
                                     start_time=datetime(2025, 9, day, 10, 0, 0),
                                     end_time=datetime(2025, 9, day, 12, 0, 0),
                                     revenue_amount=Decimal(f'{100 + i * 10}'),
                                     registrar=registrar)

            for day in range(13, 16):  # 13、14、15号
                create_battle_record(pilot=pilot,
                                     start_time=datetime(2025, 9, day, 14, 0, 0),
                                     end_time=datetime(2025, 9, day, 16, 0, 0),
                                     revenue_amount=Decimal(f'{200 + i * 20}'),
                                     registrar=registrar)

        pilot_stats = batch_calculate_pilot_stats(pilots, report_date)

        assert len(pilot_stats) == len(pilots)

        for i, pilot in enumerate(pilots):
            pilot_id = str(pilot.id)
            assert pilot_id in pilot_stats

            stats = pilot_stats[pilot_id]
            assert 'monthly_stats' in stats
            assert 'three_day_avg_revenue' in stats

            monthly_stats = stats['monthly_stats']
            assert monthly_stats['month_days_count'] > 0
            assert monthly_stats['month_total_revenue'] > 0

            three_day_avg = stats['three_day_avg_revenue']
            assert three_day_avg is not None
            assert three_day_avg > 0

    def test_optimized_vs_original_consistency(self, pilots, registrar):
        """测试优化版本与原版本的结果一致性"""
        from routes.report import calculate_pilot_three_day_avg_revenue, calculate_pilot_monthly_stats

        report_date = datetime(2025, 9, 15, 12, 0, 0)
        pilot = pilots[0]

        for day in range(1, 16):
            create_battle_record(pilot=pilot,
                                 start_time=datetime(2025, 9, day, 10, 0, 0),
                                 end_time=datetime(2025, 9, day, 12, 0, 0),
                                 revenue_amount=Decimal('150.00'),
                                 registrar=registrar)

        original_three_day = calculate_pilot_three_day_avg_revenue(pilot, report_date)
        optimized_three_day = calculate_pilot_three_day_avg_revenue_optimized(pilot, report_date)

        original_monthly = calculate_pilot_monthly_stats(pilot, report_date)
        optimized_monthly = calculate_pilot_monthly_stats_optimized(pilot, report_date)

        if original_three_day is None:
            assert optimized_three_day is None
        else:
            assert abs(original_three_day - optimized_three_day) < Decimal('0.01')

        assert original_monthly['month_days_count'] == optimized_monthly['month_days_count']
        assert abs(original_monthly['month_avg_duration'] - optimized_monthly['month_avg_duration']) < 0.1
        assert original_monthly['month_total_revenue'] == optimized_monthly['month_total_revenue']
        assert original_monthly['month_total_base_salary'] == optimized_monthly['month_total_base_salary']

    def test_empty_pilots_list_handling(self):
        """测试空机师列表的处理"""
        report_date = datetime(2025, 9, 15, 12, 0, 0)

        pilot_stats = batch_calculate_pilot_stats([], report_date)

        assert pilot_stats == {}

    def test_pilot_without_records_handling(self, pilots, registrar):
        """测试没有记录的机师的处理"""
        report_date = datetime(2025, 9, 15, 12, 0, 0)
        pilot = pilots[0]

        pilot_stats = batch_calculate_pilot_stats([pilot], report_date)

        pilot_id = str(pilot.id)
        assert pilot_id in pilot_stats

        stats = pilot_stats[pilot_id]
        monthly_stats = stats['monthly_stats']

        assert monthly_stats['month_days_count'] == 0
        assert monthly_stats['month_avg_duration'] == 0
        assert monthly_stats['month_total_revenue'] == Decimal('0')
        assert monthly_stats['month_total_base_salary'] == Decimal('0')
        assert stats['three_day_avg_revenue'] is None

    def test_three_day_avg_insufficient_days(self, pilots, registrar):
        """测试3日平均数据不足的情况"""
        report_date = datetime(2025, 9, 15, 12, 0, 0)
        pilot = pilots[0]

        for day in [13, 14]:
            create_battle_record(pilot=pilot,
                                 start_time=datetime(2025, 9, day, 10, 0, 0),
                                 end_time=datetime(2025, 9, day, 12, 0, 0),
                                 revenue_amount=Decimal('100.00'),
                                 registrar=registrar)

        three_day_avg = calculate_pilot_three_day_avg_revenue_optimized(pilot, report_date)

        assert three_day_avg is None

    @patch('routes.report.get_battle_records_for_date_range')
    def test_query_optimization(self, mock_get_records, pilots, registrar):
        """测试查询优化（减少数据库访问）"""
        report_date = datetime(2025, 9, 15, 12, 0, 0)

        mock_get_records.return_value.filter.return_value = []

        batch_calculate_pilot_stats(pilots, report_date)

        assert mock_get_records.call_count == 2
