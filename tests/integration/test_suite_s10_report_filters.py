"""
套件S10：报表筛选功能测试

覆盖 API：/new-reports/api/*, /new-reports-fast/api/*, /api/base-salary-monthly/*

测试原则：
1. 不直接操作数据库
2. 所有操作通过REST API
3. 测试所有报表的筛选功能
4. 验证筛选逻辑和数据一致性
"""

import pytest
from datetime import datetime


@pytest.mark.suite("S10")
@pytest.mark.report_filters
class TestS10ReportFilters:
    """报表筛选功能测试套件"""

    def test_s10_tc1_daily_report_mode_filters(self, admin_client):
        """
        S10-TC1 日报mode筛选测试

        步骤：测试现有数据的筛选 → GET /new-reports/api/daily 测试mode筛选 → 验证数据一致性
        """

        # 验证mode=all筛选
        response_all = admin_client.get('/new-reports/api/daily', params={
            'date': '2025-10-01',
            'mode': 'all'
        })
        assert response_all['success'] is True
        all_count = len(response_all['data']['details'])

        # 验证mode=offline筛选
        response_offline = admin_client.get('/new-reports/api/daily', params={
            'date': '2025-10-01',
            'mode': 'offline'
        })
        assert response_offline['success'] is True
        offline_count = len(response_offline['data']['details'])

        # 验证mode=online筛选
        response_online = admin_client.get('/new-reports/api/daily', params={
            'date': '2025-10-01',
            'mode': 'online'
        })
        assert response_online['success'] is True
        online_count = len(response_online['data']['details'])

        # 验证筛选逻辑：all = offline + online
        assert all_count == offline_count + online_count, \
            f"日报mode筛选逻辑错误: all({all_count}) != offline({offline_count}) + online({online_count})"

        # 验证所有记录都有正确的mode字段
        for record in response_all['data']['details']:
            assert 'work_mode' in record
            assert record['work_mode'] in ['线上', '线下']

    def test_s10_tc2_daily_report_owner_filters(self, admin_client):
        """
        S10-TC2 日报owner筛选测试

        步骤：测试现有数据的筛选 → GET /new-reports/api/daily 测试owner筛选 → 验证数据一致性
        """

        # 测试owner=all筛选
        response_all = admin_client.get('/new-reports/api/daily', params={
            'date': '2025-10-01',
            'owner': 'all'
        })
        assert response_all['success'] is True
        all_count = len(response_all['data']['details'])

        # 测试owner按具体用户ID筛选（使用数据库中真实存在的用户ID）
        test_user_id = '68c2d7121c46e47894a93733'  # 从之前测试中获得的真实用户ID
        response_owner = admin_client.get('/new-reports/api/daily', params={
            'date': '2025-10-01',
            'owner': test_user_id
        })
        assert response_owner['success'] is True
        owner_count = len(response_owner['data']['details'])

        # 验证筛选结果
        assert isinstance(all_count, int) and all_count >= 0
        assert isinstance(owner_count, int) and owner_count >= 0

        # 验证owner筛选逻辑：owner筛选结果应该小于等于all结果
        assert owner_count <= all_count, \
            f"日报owner筛选逻辑错误: owner({owner_count}) 不应该大于 all({all_count})"

        # 验证owner筛选的记录都有正确的owner字段
        if owner_count > 0:
            for record in response_owner['data']['details']:
                assert 'owner' in record

    def test_s10_tc3_weekly_report_mode_filters(self, admin_client):
        """
        S10-TC3 周报mode筛选测试

        步骤：测试现有数据的筛选 → GET /new-reports/api/weekly 测试mode筛选 → 验证数据一致性
        """

        test_start_date = '2025-10-01'

        # 验证mode=all筛选
        response_all = admin_client.get('/new-reports/api/weekly', params={
            'start_date': test_start_date,
            'mode': 'all'
        })
        assert response_all['success'] is True
        all_count = len(response_all['data']['details'])

        # 验证mode=offline筛选
        response_offline = admin_client.get('/new-reports/api/weekly', params={
            'start_date': test_start_date,
            'mode': 'offline'
        })
        assert response_offline['success'] is True
        offline_count = len(response_offline['data']['details'])

        # 验证mode=online筛选
        response_online = admin_client.get('/new-reports/api/weekly', params={
            'start_date': test_start_date,
            'mode': 'online'
        })
        assert response_online['success'] is True
        online_count = len(response_online['data']['details'])

        # 验证筛选逻辑：all = offline + online
        assert all_count == offline_count + online_count, \
            f"周报mode筛选逻辑错误: all({all_count}) != offline({offline_count}) + online({online_count})"

    def test_s10_tc4_weekly_report_owner_filters(self, admin_client):
        """
        S10-TC4 周报owner筛选测试

        步骤：测试现有数据的筛选 → GET /new-reports/api/weekly 测试owner筛选 → 验证数据一致性
        """

        test_start_date = '2025-10-01'

        # 测试owner=all筛选
        response_all = admin_client.get('/new-reports/api/weekly', params={
            'start_date': test_start_date,
            'owner': 'all'
        })
        assert response_all['success'] is True
        all_count = len(response_all['data']['details'])

        # 测试owner按具体用户ID筛选（使用数据库中真实存在的用户ID）
        test_user_id = '68c2d7121c46e47894a93733'  # 从之前测试中获得的真实用户ID
        response_owner = admin_client.get('/new-reports/api/weekly', params={
            'start_date': test_start_date,
            'owner': test_user_id
        })
        assert response_owner['success'] is True
        owner_count = len(response_owner['data']['details'])

        # 验证筛选结果
        assert isinstance(all_count, int) and all_count >= 0
        assert isinstance(owner_count, int) and owner_count >= 0

        # 验证owner筛选逻辑：owner筛选结果应该小于等于all结果
        assert owner_count <= all_count, \
            f"周报owner筛选逻辑错误: owner({owner_count}) 不应该大于 all({all_count})"

    def test_s10_tc5_monthly_report_mode_filters(self, admin_client):
        """
        S10-TC5 快速月报mode筛选测试

        步骤：测试现有数据的筛选 → GET /new-reports-fast/api/monthly 测试mode筛选 → 验证数据一致性
        """

        test_month = '2025-10'

        # 验证mode=all筛选
        response_all = admin_client.get('/new-reports-fast/api/monthly', params={
            'month': test_month,
            'mode': 'all'
        })
        assert response_all['success'] is True
        all_summary = response_all['data']['summary']
        all_pilot_count = all_summary.get('pilot_count', 0)
        all_revenue = all_summary.get('revenue_sum', 0)

        # 验证mode=offline筛选
        response_offline = admin_client.get('/new-reports-fast/api/monthly', params={
            'month': test_month,
            'mode': 'offline'
        })
        assert response_offline['success'] is True
        offline_summary = response_offline['data']['summary']
        offline_pilot_count = offline_summary.get('pilot_count', 0)
        offline_revenue = offline_summary.get('revenue_sum', 0)

        # 验证mode=online筛选
        response_online = admin_client.get('/new-reports-fast/api/monthly', params={
            'month': test_month,
            'mode': 'online'
        })
        assert response_online['success'] is True
        online_summary = response_online['data']['summary']
        online_pilot_count = online_summary.get('pilot_count', 0)
        online_revenue = online_summary.get('revenue_sum', 0)

        # 验证数据类型
        assert isinstance(all_pilot_count, int) and all_pilot_count >= 0
        assert isinstance(offline_pilot_count, int) and offline_pilot_count >= 0
        assert isinstance(online_pilot_count, int) and online_pilot_count >= 0

        # 验证流水汇总逻辑
        assert all_revenue == offline_revenue + online_revenue, \
            f"月报流水汇总逻辑错误: all({all_revenue}) != offline({offline_revenue}) + online({online_revenue})"

    def test_s10_tc6_monthly_report_owner_filters(self, admin_client):
        """
        S10-TC6 快速月报owner筛选测试

        步骤：测试现有数据的筛选 → GET /new-reports-fast/api/monthly 测试owner筛选 → 验证数据一致性
        """

        test_month = '2025-10'

        # 测试owner=all筛选
        response_all = admin_client.get('/new-reports-fast/api/monthly', params={
            'month': test_month,
            'owner': 'all'
        })
        assert response_all['success'] is True
        all_summary = response_all['data']['summary']
        all_pilot_count = all_summary.get('pilot_count', 0)

        # 测试owner按具体用户ID筛选（使用数据库中真实存在的用户ID）
        test_user_id = '68c2d7121c46e47894a93733'  # 从之前测试中获得的真实用户ID
        response_owner = admin_client.get('/new-reports-fast/api/monthly', params={
            'month': test_month,
            'owner': test_user_id
        })
        assert response_owner['success'] is True
        owner_summary = response_owner['data']['summary']
        owner_pilot_count = owner_summary.get('pilot_count', 0)

        # 验证数据类型
        assert isinstance(all_pilot_count, int) and all_pilot_count >= 0
        assert isinstance(owner_pilot_count, int) and owner_pilot_count >= 0

        # 验证owner筛选逻辑（owner=all应该包含所有记录）
        assert owner_pilot_count <= all_pilot_count, \
            f"月报owner筛选逻辑错误: owner({owner_pilot_count}) 不应该大于 all({all_pilot_count})"

    def test_s10_tc7_base_salary_monthly_mode_filters(self, admin_client):
        """
        S10-TC7 底薪月报mode筛选测试

        步骤：测试现有数据的筛选 → GET /api/base-salary-monthly 测试mode筛选 → 验证数据一致性
        """

        test_month = '2025-10'

        # 测试所有mode筛选
        modes = ['offline', 'online', 'all']
        results = {}

        for mode in modes:
            response = admin_client.get('/api/base-salary-monthly', params={
                'month': test_month,
                'mode': mode,
                'settlement': 'all'
            })
            assert response['success'] is True
            summary = response['data']['summary']
            results[mode] = summary['total_records']

        # 验证筛选逻辑：all = offline + online
        assert results['all'] == results['offline'] + results['online'], \
            f"底薪月报mode筛选逻辑错误: all({results['all']}) != offline({results['offline']}) + online({results['online']})"

        # 验证数据类型
        for mode, count in results.items():
            assert isinstance(count, int) and count >= 0, \
                f"底薪月报{mode}筛选结果数据类型错误: {count}"

    def test_s10_tc8_base_salary_monthly_settlement_filters(self, admin_client):
        """
        S10-TC8 底薪月报结算方式筛选测试

        步骤：测试现有数据的筛选 → GET /api/base-salary-monthly 测试settlement筛选 → 验证数据一致性
        """

        test_month = '2025-10'
        mode = 'all'

        # 测试所有settlement筛选
        settlements = ['monthly_base', 'daily_base', 'none', 'all']
        results = {}

        for settlement in settlements:
            response = admin_client.get('/api/base-salary-monthly', params={
                'month': test_month,
                'mode': mode,
                'settlement': settlement
            })
            assert response['success'] is True
            summary = response['data']['summary']
            results[settlement] = {
                'total_records': summary['total_records'],
                'application_count': summary['application_count']
            }

        # 验证筛选逻辑
        # all应该包含所有类型的记录
        all_records = results['all']['total_records']
        monthly_records = results['monthly_base']['total_records']
        daily_records = results['daily_base']['total_records']
        none_records = results['none']['total_records']

        # 注意：由于可能存在重复申请，all可能不等于各分项之和
        # 我们主要验证all包含所有类型的数据
        assert all_records >= monthly_records, \
            f"底薪月报settlement筛选逻辑错误: all({all_records}) 应该包含monthly_base({monthly_records})"
        assert all_records >= daily_records, \
            f"底薪月报settlement筛选逻辑错误: all({all_records}) 应该包含daily_base({daily_records})"
        assert all_records >= none_records, \
            f"底薪月报settlement筛选逻辑错误: all({all_records}) 应该包含none({none_records})"

        # 验证数据类型
        for settlement, data in results.items():
            assert isinstance(data['total_records'], int) and data['total_records'] >= 0
            assert isinstance(data['application_count'], int) and data['application_count'] >= 0

    def test_s10_tc9_filter_data_consistency(self, admin_client):
        """
        S10-TC9 筛选数据一致性测试

        步骤：测试现有数据的一致性 → 使用不同API筛选 → 验证数据交叉一致性
        """

        test_date = '2025-10-01'
        test_month = '2025-10'

        # 获取日报数据
        daily_response = admin_client.get('/new-reports/api/daily', params={
            'date': test_date,
            'mode': 'all'
        })
        assert daily_response['success'] is True
        daily_records = daily_response['data']['details']

        # 获取快速月报数据
        monthly_response = admin_client.get('/new-reports-fast/api/monthly', params={
            'month': test_month,
            'mode': 'all'
        })
        assert monthly_response['success'] is True
        monthly_summary = monthly_response['data']['summary']

        # 获取底薪月报数据
        salary_response = admin_client.get('/api/base-salary-monthly', params={
            'month': test_month,
            'mode': 'all',
            'settlement': 'all'
        })
        assert salary_response['success'] is True
        salary_summary = salary_response['data']['summary']

        # 验证基本数据一致性
        assert isinstance(daily_records, list)
        assert isinstance(monthly_summary, dict)
        assert isinstance(salary_summary, dict)

        # 验证时间范围正确性
        for record in daily_records:
            assert 'start_time' in record
            start_date = record['start_time'][:10]  # 取日期部分
            assert start_date == test_date, f"日报记录时间错误: {start_date} != {test_date}"

        # 验证核心指标类型
        assert isinstance(monthly_summary.get('revenue_sum', 0), (int, float))
        assert isinstance(salary_summary.get('total_records', 0), int)
        assert isinstance(salary_summary.get('total_revenue', 0), (int, float))

    def test_s10_tc10_filter_edge_cases(self, admin_client):
        """
        S10-TC10 筛选边界情况测试

        步骤：测试各种边界参数 → 验证错误处理和边界情况
        """

        # 测试无效日期格式
        response_invalid_date = admin_client.get('/new-reports/api/daily', params={
            'date': 'invalid-date',
            'mode': 'all'
        })
        assert response_invalid_date['success'] is False or response_invalid_date.status_code == 400

        # 测试无效mode参数
        response_invalid_mode = admin_client.get('/new-reports/api/daily', params={
            'date': '2025-10-01',
            'mode': 'invalid-mode'
        })
        # 应该回退到默认值或返回错误
        assert response_invalid_mode['success'] is True or response_invalid_mode.status_code == 400

        # 测试无效月份格式
        response_invalid_month = admin_client.get('/new-reports-fast/api/monthly', params={
            'month': 'invalid-month',
            'mode': 'all'
        })
        assert response_invalid_month['success'] is False or response_invalid_month.status_code == 400

        # 测试底薪月报无效参数
        response_invalid_settlement = admin_client.get('/api/base-salary-monthly', params={
            'month': '2025-10',
            'mode': 'all',
            'settlement': 'invalid-settlement'
        })
        # 应该回退到默认值或返回错误
        assert response_invalid_settlement['success'] is True or response_invalid_settlement.status_code == 400

        # 测试空参数
        response_empty_params = admin_client.get('/new-reports/api/daily')
        # 应该使用默认值或返回错误
        assert response_empty_params['success'] is True or response_empty_params.status_code == 400

    def test_s10_tc11_filter_performance_impact(self, admin_client):
        """
        S10-TC11 筛选性能影响测试

        步骤：测试不同筛选条件下的响应时间 → 验证性能在可接受范围内
        """

        import time

        test_cases = [
            {
                'name': '日报mode=all',
                'url': '/new-reports/api/daily',
                'params': {'date': '2025-10-01', 'mode': 'all'}
            },
            {
                'name': '快速月报mode=all',
                'url': '/new-reports-fast/api/monthly',
                'params': {'month': '2025-10', 'mode': 'all'}
            },
            {
                'name': '底薪月报all筛选',
                'url': '/api/base-salary-monthly',
                'params': {'month': '2025-10', 'mode': 'all', 'settlement': 'all'}
            }
        ]

        for test_case in test_cases:
            start_time = time.time()
            response = admin_client.get(test_case['url'], params=test_case['params'])
            end_time = time.time()

            assert response['success'] is True, f"{test_case['name']}请求失败"

            response_time = end_time - start_time
            assert response_time < 5.0, f"{test_case['name']}响应时间过长: {response_time:.2f}秒"

            print(f"✅ {test_case['name']}: {response_time:.2f}秒")

    def test_s10_tc12_filter_response_format(self, admin_client):
        """
        S10-TC12 筛选响应格式测试

        步骤：测试所有筛选API的响应格式 → 验证格式一致性
        """

        # 测试日报API响应格式
        response_daily = admin_client.get('/new-reports/api/daily', params={
            'date': '2025-10-01',
            'mode': 'all'
        })
        assert response_daily['success'] is True
        assert 'data' in response_daily
        assert 'summary' in response_daily['data']
        assert 'details' in response_daily['data']
        assert isinstance(response_daily['data']['details'], list)

        # 测试快速月报API响应格式
        response_monthly = admin_client.get('/new-reports-fast/api/monthly', params={
            'month': '2025-10',
            'mode': 'all'
        })
        assert response_monthly['success'] is True
        assert 'data' in response_monthly
        assert 'summary' in response_monthly['data']
        assert 'details' in response_monthly['data']
        assert isinstance(response_monthly['data']['details'], list)

        # 测试底薪月报API响应格式
        response_salary = admin_client.get('/api/base-salary-monthly', params={
            'month': '2025-10',
            'mode': 'all',
            'settlement': 'all'
        })
        assert response_salary['success'] is True
        assert 'data' in response_salary
        assert 'summary' in response_salary['data']
        assert 'details' in response_salary['data']
        assert isinstance(response_salary['data']['details'], list)

        # 验证错误响应格式
        response_error = admin_client.get('/new-reports/api/daily', params={
            'date': '2025-13-32',  # 无效日期
            'mode': 'all'
        })
        # 可能成功（使用默认日期）或失败，但格式应该一致
        if 'success' in response_error:
            assert isinstance(response_error['success'], bool)
        if 'error' in response_error:
            assert isinstance(response_error['error'], (str, dict))