"""
新旧开播报表 API 对比测试

验证新报表 API 与旧报表 API 的数据一致性（除底薪及相关利润字段差异）。
"""
# pylint: disable=no-member,redefined-outer-name
from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Tuple

import os
import pytest

from models.battle_record import (BaseSalaryApplication, BaseSalaryApplicationStatus, BattleRecord, BattleRecordStatus)
from models.pilot import Gender, Pilot, Platform, Rank, Status, WorkMode
from models.user import User
from tests.fixtures.factories import UserFactory
from utils.cache_helper import clear_daily_report_cache, clear_monthly_report_cache
from utils.timezone_helper import local_to_utc


def _normalize_daily_detail(detail: Dict) -> Dict:
    """剔除底薪相关字段后返回拷贝，用于对比。"""
    cleaned = deepcopy(detail)
    cleaned.pop('base_salary', None)
    cleaned.pop('daily_profit', None)

    if 'monthly_stats' in cleaned:
        cleaned['monthly_stats'] = {k: v for k, v in cleaned['monthly_stats'].items() if k != 'month_total_base_salary'}

    if 'monthly_commission_stats' in cleaned:
        cleaned['monthly_commission_stats'] = {k: v for k, v in cleaned['monthly_commission_stats'].items() if k != 'month_total_profit'}

    return cleaned


def _normalize_weekly_detail(detail: Dict) -> Dict:
    cleaned = deepcopy(detail)
    cleaned.pop('total_base_salary', None)
    cleaned.pop('total_profit', None)
    return cleaned


def _normalize_monthly_detail(detail: Dict) -> Dict:
    cleaned = deepcopy(detail)
    cleaned.pop('total_base_salary', None)
    cleaned.pop('total_profit', None)
    return cleaned


def _normalized_detail_list(details: Iterable[Dict], key_fields: Tuple[str, ...], normalizer) -> List[Tuple[Tuple, Dict]]:
    normalized = []
    for item in details:
        key = tuple(item.get(field) for field in key_fields)
        normalized.append((key, normalizer(item)))
    normalized.sort(key=lambda pair: pair[0])
    return normalized


def _assert_summary_equal(old_summary: Dict, new_summary: Dict, allowed_keys: Iterable[str]):
    allowed = set(allowed_keys)
    assert {k: v for k, v in old_summary.items() if k not in allowed} == {k: v for k, v in new_summary.items() if k not in allowed}


@pytest.fixture()
def report_sample_data(app, admin_client):
    """构造用于报表对比的测试数据。"""
    user_data = UserFactory.create_user_data(role='kancho')
    create_resp = admin_client.post('/api/users', json=user_data)
    assert create_resp.get('success'), '创建测试运营账号失败'

    owner_id = create_resp['data']['id']
    created_record_ids: List = []
    created_application_ids: List = []

    with app.app_context():
        owner_user = User.objects.get(id=owner_id)  # type: ignore[attr-defined]
        admin_username = os.getenv('TEST_ADMIN_USERNAME', 'zala')
        admin_user = User.objects.get(username=admin_username)  # type: ignore[attr-defined]

        base_year = 2045
        base_month = 2
        record_days = (14, 16)

        pilot = Pilot(
            nickname=f"测试新报表主播_{owner_id[:6]}",
            real_name='测试主播',
            gender=Gender.MALE,
            hometown='测试城市',
            birth_year=1995,
            owner=owner_user,
            platform=Platform.KUAISHOU,
            work_mode=WorkMode.ONLINE,
            rank=Rank.OFFICIAL,
            status=Status.CONTRACTED,
        ).save()

        def create_record(local_start: datetime, duration_hours: int, revenue: str, base_salary: str, approved_amount: str):
            start_utc = local_to_utc(local_start)
            end_utc = local_to_utc(local_start + timedelta(hours=duration_hours))

            record = BattleRecord(
                pilot=pilot,
                start_time=start_utc,
                end_time=end_utc,
                work_mode=WorkMode.ONLINE,
                revenue_amount=Decimal(revenue),
                base_salary=Decimal(base_salary),
                registered_by=admin_user,
                owner_snapshot=owner_user,
                status=BattleRecordStatus.ENDED,
            ).save()

            application = BaseSalaryApplication(
                pilot_id=pilot,
                battle_record_id=record,
                settlement_type='daily_base',
                base_salary_amount=Decimal(approved_amount),
                applicant_id=admin_user,
                status=BaseSalaryApplicationStatus.APPROVED,
            ).save()

            created_record_ids.append(record.id)
            created_application_ids.append(application.id)

        # 同一自然周内两条记录，底薪申请金额与记录底薪不同
        create_record(datetime(base_year, base_month, record_days[0], 10, 0), 4, '1000', '200', '120')
        create_record(datetime(base_year, base_month, record_days[1], 13, 0), 3, '800', '50', '90')

        clear_daily_report_cache()
        clear_monthly_report_cache()

        yield {
            'owner_id': owner_id,
            'daily_dates': [f'{base_year}-{base_month:02d}-{record_days[0]:02d}', f'{base_year}-{base_month:02d}-{record_days[1]:02d}'],
            'week_start': f'{base_year}-{base_month:02d}-{record_days[0]:02d}',
            'month': f'{base_year}-{base_month:02d}',
        }

        BaseSalaryApplication.objects(id__in=created_application_ids).delete()  # type: ignore[attr-defined]
        BattleRecord.objects(id__in=created_record_ids).delete()  # type: ignore[attr-defined]
        Pilot.objects(id=pilot.id).delete()  # type: ignore[attr-defined]
        clear_daily_report_cache()
        clear_monthly_report_cache()

    admin_client.patch(f'/api/users/{owner_id}/activation', json={'active': False})


@pytest.mark.integration
def test_daily_report_new_vs_old(admin_client, report_sample_data):
    owner_id = report_sample_data['owner_id']

    for date_str in report_sample_data['daily_dates']:
        old_resp = admin_client.get(f"/reports/api/daily?date={date_str}&owner={owner_id}")
        new_resp = admin_client.get(f"/new-reports/api/daily?date={date_str}&owner={owner_id}")

        assert old_resp.get('success') and new_resp.get('success'), '日报接口返回失败'

        assert old_resp['data']['date'] == new_resp['data']['date']
        assert old_resp['data']['pagination'] == new_resp['data']['pagination']
        assert old_resp['meta'] == new_resp['meta']

        _assert_summary_equal(old_resp['data']['summary'], new_resp['data']['summary'], allowed_keys=['basepay_sum', 'conversion_rate'])
        assert old_resp['data']['summary']['basepay_sum'] != new_resp['data']['summary']['basepay_sum']

        old_details = _normalized_detail_list(old_resp['data']['details'], ('pilot_id', 'revenue'), _normalize_daily_detail)
        new_details = _normalized_detail_list(new_resp['data']['details'], ('pilot_id', 'revenue'), _normalize_daily_detail)
        if old_details != new_details:
            print('日报明细差异', date_str)
            print('旧报表', old_details)
            print('新报表', new_details)
        assert old_details == new_details


@pytest.mark.integration
def test_weekly_report_new_vs_old(admin_client, report_sample_data):
    owner_id = report_sample_data['owner_id']
    week_start = report_sample_data['week_start']

    old_resp = admin_client.get(f"/reports/api/weekly?week_start={week_start}&owner={owner_id}")
    new_resp = admin_client.get(f"/new-reports/api/weekly?week_start={week_start}&owner={owner_id}")

    assert old_resp.get('success') and new_resp.get('success'), '周报接口返回失败'

    assert old_resp['data']['week_start'] == new_resp['data']['week_start']
    assert old_resp['data']['pagination'] == new_resp['data']['pagination']
    assert old_resp['meta'] == new_resp['meta']

    _assert_summary_equal(old_resp['data']['summary'], new_resp['data']['summary'], allowed_keys=['basepay_sum', 'conversion_rate', 'profit_7d'])
    assert old_resp['data']['summary']['basepay_sum'] != new_resp['data']['summary']['basepay_sum']

    old_details = _normalized_detail_list(old_resp['data']['details'], ('pilot_id', ), _normalize_weekly_detail)
    new_details = _normalized_detail_list(new_resp['data']['details'], ('pilot_id', ), _normalize_weekly_detail)
    assert old_details == new_details


@pytest.mark.integration
def test_monthly_report_new_vs_old(admin_client, report_sample_data):
    owner_id = report_sample_data['owner_id']
    month = report_sample_data['month']

    old_resp = admin_client.get(f"/reports/api/monthly?month={month}&owner={owner_id}")
    new_resp = admin_client.get(f"/new-reports/api/monthly?month={month}&owner={owner_id}")

    assert old_resp.get('success') and new_resp.get('success'), '月报接口返回失败'

    assert old_resp['data']['month'] == new_resp['data']['month']
    assert old_resp['data']['pagination'] == new_resp['data']['pagination']
    assert old_resp['meta'] == new_resp['meta']

    _assert_summary_equal(old_resp['data']['summary'], new_resp['data']['summary'], allowed_keys=['basepay_sum', 'conversion_rate', 'operating_profit'])
    assert old_resp['data']['summary']['basepay_sum'] != new_resp['data']['summary']['basepay_sum']

    old_details = _normalized_detail_list(old_resp['data']['details'], ('pilot_id', ), _normalize_monthly_detail)
    new_details = _normalized_detail_list(new_resp['data']['details'], ('pilot_id', ), _normalize_monthly_detail)
    assert old_details == new_details
