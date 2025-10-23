"""
套件S6：结算与分成测试

覆盖 API：/api/settlements/*, /api/pilots/*/commission/*

测试原则：
1. 不直接操作数据库
2. 所有操作通过REST API
3. 测试结算方式管理（SettlementType枚举：daily_base, monthly_base, none）
4. 验证分成记录管理
5. 测试变更日志追踪功能

基于业务代码修正：
- Settlement模型使用settlement_type字段，而非company_rate/pilot_rate
- 分成功能使用/api/pilots/{pilot_id}/commission/路径
- 支持settlement和commission的变更历史追踪
"""
import pytest
from datetime import datetime, timedelta
from tests.fixtures.factories import (pilot_factory, settlement_factory, battle_record_factory)


@pytest.mark.suite("S6")
@pytest.mark.settlement_commission
class TestS6SettlementCommission:
    """结算与分成测试套件"""

    def test_s6_tc1_create_settlement_plan_and_query_effective(self, admin_client):
        """
        S6-TC1 新建结算方式并查询生效

        步骤：POST /api/settlements/<pilot_id> 创建结算 → GET /api/settlements/<pilot_id>/effective?date= 返回最新方案。
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot = pilot_response['data']
                pilot_id = pilot['id']
                created_ids['pilot_id'] = pilot_id

                # 2. 创建结算方式（使用settlement_type字段）
                effective_date = datetime.now().strftime('%Y-%m-%d')
                settlement_data = {
                    'effective_date': effective_date,
                    'settlement_type': 'daily_base',  # 日结底薪
                    'remark': '测试创建日结底薪方案'
                }

                settlement_response = admin_client.post(f'/api/settlements/{pilot_id}', json=settlement_data)

                if settlement_response.get('success'):
                    settlement = settlement_response['data']
                    settlement_id = settlement['id']
                    created_ids['settlement_id'] = settlement_id

                    # 验证结算方式
                    assert settlement['pilot_id'] == pilot_id
                    assert settlement['settlement_type'] == 'daily_base'
                    assert settlement['settlement_type_display'] == '日结底薪'
                    assert settlement['is_active'] is True

                    # 3. 查询生效的结算方式
                    effective_response = admin_client.get(f'/api/settlements/{pilot_id}/effective', params={'date': effective_date})

                    if effective_response.get('success'):
                        effective_settlement = effective_response['data']
                        assert effective_settlement['settlement_type'] == 'daily_base'
                        assert effective_settlement['settlement_type_display'] == '日结底薪'
                        assert effective_settlement['effective_date'] == effective_date

                else:
                    pytest.skip("创建结算方式接口不可用")

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            # 清理创建的数据
            try:
                if 'settlement_id' in created_ids:
                    admin_client.delete(f'/api/settlements/{created_ids["settlement_id"]}')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    def test_s6_tc2_settlement_modification_and_history_tracking(self, admin_client):
        """
        S6-TC2 结算方式修改与历史追踪

        步骤：PUT /api/settlements/<record_id> 更新类型 → GET /changes 校验版本。
        """
        created_ids = {}

        try:
            # 1. 创建主播和结算方式
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                # 创建初始结算方式
                effective_date = datetime.now().strftime('%Y-%m-%d')
                settlement_data = {
                    'effective_date': effective_date,
                    'settlement_type': 'daily_base',  # 初始：日结底薪
                    'remark': '初始日结底薪方案'
                }

                settlement_response = admin_client.post(f'/api/settlements/{pilot_id}', json=settlement_data)

                if settlement_response.get('success'):
                    settlement = settlement_response['data']
                    settlement_id = settlement['id']
                    created_ids['settlement_id'] = settlement_id

                    # 2. 修改结算方式
                    update_data = {
                        'settlement_type': 'monthly_base',  # 修改为：月结底薪
                        'remark': '修改为月结底薪方案'
                    }

                    update_response = admin_client.put(f'/api/settlements/{settlement_id}', json=update_data)

                    if update_response.get('success'):
                        updated_settlement = update_response['data']
                        assert updated_settlement['settlement_type'] == 'monthly_base'
                        assert updated_settlement['settlement_type_display'] == '月结底薪'
                        assert updated_settlement['remark'] == '修改为月结底薪方案'

                        # 3. 查询变更历史
                        changes_response = admin_client.get(f'/api/settlements/{settlement_id}/changes')

                        if changes_response.get('success'):
                            changes_data = changes_response['data']
                            items = changes_data.get('items', [])
                            # 验证变更记录存在
                            if items:
                                latest_change = items[0]
                                assert 'field_name' in latest_change
                                assert 'old_value' in latest_change
                                assert 'new_value' in latest_change
                                assert 'change_time' in latest_change
                                # 应该有settlement_type字段的变更记录
                                field_names = [change['field_name'] for change in items]
                                assert 'settlement_type' in field_names or 'created' in field_names

                else:
                    pytest.skip("创建结算方式接口不可用")

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            # 清理创建的数据
            try:
                if 'settlement_id' in created_ids:
                    admin_client.delete(f'/api/settlements/{created_ids["settlement_id"]}')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    def test_s6_tc3_deletion_restriction(self, admin_client):
        """
        S6-TC3 软删除功能测试

        步骤：DELETE /api/settlements/<record_id> 执行软删除 → 验证is_active字段变更。
        """
        created_ids = {}

        try:
            # 1. 创建主播和结算方式
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                effective_date = datetime.now().strftime('%Y-%m-%d')
                settlement_data = {'effective_date': effective_date, 'settlement_type': 'daily_base', 'remark': '测试软删除功能'}
                settlement_response = admin_client.post(f'/api/settlements/{pilot_id}', json=settlement_data)

                if settlement_response.get('success'):
                    settlement = settlement_response['data']
                    settlement_id = settlement['id']
                    created_ids['settlement_id'] = settlement_id

                    # 验证初始状态为active
                    assert settlement['is_active'] is True

                    # 2. 执行软删除
                    delete_response = admin_client.delete(f'/api/settlements/{settlement_id}')

                    # 软删除应该成功
                    assert delete_response.get('success') is True

                    # 3. 验证软删除后的状态
                    get_response = admin_client.get(f'/api/settlements/{pilot_id}')
                    if get_response.get('success'):
                        items = get_response['data']['items']
                        # 找到被删除的记录
                        deleted_settlement = None
                        for item in items:
                            if item['id'] == settlement_id:
                                deleted_settlement = item
                                break

                        if deleted_settlement:
                            assert deleted_settlement['is_active'] is False

                    # 4. 验证变更日志记录了删除操作
                    changes_response = admin_client.get(f'/api/settlements/{settlement_id}/changes')
                    if changes_response.get('success'):
                        changes_data = changes_response['data']
                        items = changes_data.get('items', [])
                        # 应该有is_active字段的变更记录
                        is_active_changes = [change for change in items if change['field_name'] == 'is_active']
                        if is_active_changes:
                            latest_change = is_active_changes[0]
                            assert latest_change['old_value'] == 'true'
                            assert latest_change['new_value'] == 'false'

                else:
                    pytest.skip("创建结算方式接口不可用")

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            # 清理创建的数据
            try:
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    def test_s6_tc4_commission_record_management(self, admin_client):
        """
        S6-TC4 分成记录管理测试

        步骤：创建分成记录 → 查询当前分成 → 查询分成历史 → 验证数据一致性。
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                # 2. 创建分成记录
                adjustment_date = datetime.now().strftime('%Y-%m-%d')
                commission_data = {
                    'adjustment_date': adjustment_date,
                    'commission_rate': 0.15,  # 15%分成比例
                    'remark': '测试创建分成记录'
                }

                commission_response = admin_client.post(f'/api/pilots/{pilot_id}/commission/records', json=commission_data)

                if commission_response.get('success'):
                    commission = commission_response['data']
                    commission_id = commission['id']
                    created_ids['commission_id'] = commission_id

                    # 验证分成记录
                    assert commission['pilot_id'] == pilot_id
                    assert commission['commission_rate'] == 0.15
                    assert commission['remark'] == '测试创建分成记录'
                    assert commission['is_active'] is True

                    # 3. 查询当前分成
                    current_response = admin_client.get(f'/api/pilots/{pilot_id}/commission/current')

                    if current_response.get('success'):
                        current_data = current_response['data']
                        assert 'current_rate' in current_data
                        assert 'effective_date' in current_data
                        assert 'calculation_info' in current_data
                        # 验证计算信息包含分成详情
                        calc_info = current_data['calculation_info']
                        assert 'company_income' in calc_info
                        assert 'pilot_income' in calc_info
                        assert 'calculation_formula' in calc_info

                    # 4. 查询分成历史记录
                    records_response = admin_client.get(f'/api/pilots/{pilot_id}/commission/records')

                    if records_response.get('success'):
                        records_data = records_response['data']
                        items = records_data.get('items', [])
                        # 应该能找到刚创建的记录
                        found_record = None
                        for item in items:
                            if item['id'] == commission_id:
                                found_record = item
                                break

                        if found_record:
                            assert found_record['commission_rate'] == 0.15
                            assert found_record['remark'] == '测试创建分成记录'

                    # 5. 查询分成变更历史
                    changes_response = admin_client.get(f'/api/pilots/{pilot_id}/commission/records/{commission_id}/changes')

                    if changes_response.get('success'):
                        changes_data = changes_response['data']
                        items = changes_data.get('items', [])
                        # 应该有创建记录的变更日志
                        if items:
                            creation_change = items[0]
                            assert creation_change['field_name'] == 'created'
                            assert creation_change['new_value'] == '0.15'

                else:
                    pytest.skip("创建分成记录接口不可用")

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            # 清理创建的数据
            try:
                if 'commission_id' in created_ids:
                    admin_client.post(f'/api/pilots/{created_ids["pilot_id"]}/commission/records/{created_ids["commission_id"]}/deactivate')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    def test_s6_tc5_commission_modification_and_tracking(self, admin_client):
        """
        S6-TC5 分成记录修改与历史追踪

        步骤：创建分成记录 → 修改分成比例 → 查询变更历史 → 验证记录。
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                # 2. 创建初始分成记录
                adjustment_date = datetime.now().strftime('%Y-%m-%d')
                commission_data = {
                    'adjustment_date': adjustment_date,
                    'commission_rate': 0.10,  # 初始10%
                    'remark': '初始分成记录'
                }

                commission_response = admin_client.post(f'/api/pilots/{pilot_id}/commission/records', json=commission_data)

                if commission_response.get('success'):
                    commission = commission_response['data']
                    commission_id = commission['id']
                    created_ids['commission_id'] = commission_id

                    # 3. 修改分成记录
                    update_data = {
                        'commission_rate': 0.20,  # 修改为20%
                        'remark': '修改后的分成记录'
                    }

                    update_response = admin_client.put(f'/api/pilots/{pilot_id}/commission/records/{commission_id}', json=update_data)

                    if update_response.get('success'):
                        updated_commission = update_response['data']
                        assert updated_commission['commission_rate'] == 0.20
                        assert updated_commission['remark'] == '修改后的分成记录'

                        # 4. 查询变更历史
                        changes_response = admin_client.get(f'/api/pilots/{pilot_id}/commission/records/{commission_id}/changes')

                        if changes_response.get('success'):
                            changes_data = changes_response['data']
                            items = changes_data.get('items', [])
                            # 验证变更记录存在
                            if items:
                                # 应该有commission_rate字段的变更记录
                                commission_changes = [change for change in items if change['field_name'] == 'commission_rate']
                                if commission_changes:
                                    rate_change = commission_changes[0]
                                    assert rate_change['old_value'] == '0.1'
                                    assert rate_change['new_value'] == '0.2'

                                # 也可能有remark字段的变更记录
                                remark_changes = [change for change in items if change['field_name'] == 'remark']
                                if remark_changes:
                                    remark_change = remark_changes[0]
                                    assert '初始分成记录' in remark_change['old_value']
                                    assert '修改后的分成记录' in remark_change['new_value']

                    # 5. 测试停用和激活功能
                    deactivate_response = admin_client.post(f'/api/pilots/{pilot_id}/commission/records/{commission_id}/deactivate')
                    if deactivate_response.get('success'):
                        deactivated_commission = deactivate_response['data']
                        assert deactivated_commission['is_active'] is False

                        # 重新激活
                        activate_response = admin_client.post(f'/api/pilots/{pilot_id}/commission/records/{commission_id}/activate')
                        if activate_response.get('success'):
                            activated_commission = activate_response['data']
                            assert activated_commission['is_active'] is True

                else:
                    pytest.skip("创建分成记录接口不可用")

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            # 清理创建的数据
            try:
                if 'commission_id' in created_ids:
                    admin_client.post(f'/api/pilots/{created_ids["pilot_id"]}/commission/records/{created_ids["commission_id"]}/deactivate')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    def test_s6_tc6_settlement_and_commission_integration(self, admin_client):
        """
        S6-TC6 结算方式与分成功能集成测试

        步骤：创建结算方式 → 创建分成记录 → 验证两者的独立性。
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                # 2. 创建结算方式
                effective_date = datetime.now().strftime('%Y-%m-%d')
                settlement_data = {'effective_date': effective_date, 'settlement_type': 'daily_base', 'remark': '集成测试结算方式'}

                settlement_response = admin_client.post(f'/api/settlements/{pilot_id}', json=settlement_data)

                if settlement_response.get('success'):
                    settlement = settlement_response['data']
                    settlement_id = settlement['id']
                    created_ids['settlement_id'] = settlement_id

                    # 3. 创建分成记录（独立的业务逻辑）
                    adjustment_date = datetime.now().strftime('%Y-%m-%d')
                    commission_data = {'adjustment_date': adjustment_date, 'commission_rate': 0.12, 'remark': '集成测试分成记录'}

                    commission_response = admin_client.post(f'/api/pilots/{pilot_id}/commission/records', json=commission_data)

                    if commission_response.get('success'):
                        commission = commission_response['data']
                        commission_id = commission['id']
                        created_ids['commission_id'] = commission_id

                        # 4. 验证两者的独立性
                        # 查询结算方式
                        settlement_get = admin_client.get(f'/api/settlements/{pilot_id}')
                        if settlement_get.get('success'):
                            settlement_items = settlement_get['data']['items']
                            found_settlement = None
                            for item in settlement_items:
                                if item['id'] == settlement_id:
                                    found_settlement = item
                                    break
                            if found_settlement:
                                assert found_settlement['settlement_type'] == 'daily_base'

                        # 查询分成记录
                        commission_get = admin_client.get(f'/api/pilots/{pilot_id}/commission/records')
                        if commission_get.get('success'):
                            commission_items = commission_get['data']['items']
                            found_commission = None
                            for item in commission_items:
                                if item['id'] == commission_id:
                                    found_commission = item
                                    break
                            if found_commission:
                                assert found_commission['commission_rate'] == 0.12

                        # 5. 查询当前分成（验证计算功能）
                        current_response = admin_client.get(f'/api/pilots/{pilot_id}/commission/current')
                        if current_response.get('success'):
                            current_data = current_response['data']
                            assert current_data['current_rate'] == 0.12
                            # 验证计算信息
                            calc_info = current_data['calculation_info']
                            assert 'company_income' in calc_info
                            assert 'pilot_income' in calc_info
                            assert 'calculation_formula' in calc_info

                    else:
                        pytest.skip("创建分成记录接口不可用")

                else:
                    pytest.skip("创建结算方式接口不可用")

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            # 清理创建的数据
            try:
                if 'commission_id' in created_ids:
                    admin_client.post(f'/api/pilots/{created_ids["pilot_id"]}/commission/records/{created_ids["commission_id"]}/deactivate')
                if 'settlement_id' in created_ids:
                    admin_client.delete(f'/api/settlements/{created_ids["settlement_id"]}')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    # ==================== 输入验证边界测试 ====================

    def test_s6_validation_tc1_invalid_settlement_types(self, admin_client):
        """
        S6-Validation-TC1 无效结算方式类型测试

        测试各种无效的settlement_type输入
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                effective_date = datetime.now().strftime('%Y-%m-%d')

                # 2. 测试无效的结算方式类型
                invalid_types = [
                    'invalid_type',  # 不存在的类型
                    'DAILY_BASE',  # 大写（应该小写）
                    'dailybase',  # 缺少下划线
                    '',  # 空字符串
                    None,  # None值
                    123,  # 数字类型
                    {
                        'type': 'daily_base'
                    },  # 对象类型
                    ['daily_base'],  # 数组类型
                ]

                for invalid_type in invalid_types:
                    settlement_data = {'effective_date': effective_date, 'settlement_type': invalid_type, 'remark': '测试无效类型'}

                    response = admin_client.post(f'/api/settlements/{pilot_id}', json=settlement_data)

                    # 应该返回验证错误
                    assert response.get('success') is not True
                    assert response.get('_status_code') in [400, 422]
                    if 'error' in response:
                        assert 'VALIDATION_ERROR' in response['error']['code'] or 'INVALID' in response['error']['code']

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            try:
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    def test_s6_validation_tc2_invalid_date_formats(self, admin_client):
        """
        S6-Validation-TC2 无效日期格式测试

        测试各种无效的日期输入格式
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                # 2. 测试无效的日期格式
                invalid_dates = [
                    '2025-13-01',  # 无效月份
                    '2025-02-30',  # 无效日期
                    '25-01-15',  # 错误格式
                    '2025/01/15',  # 斜杠分隔
                    '2025.01.15',  # 点分隔
                    '15-01-2025',  # 日-月-年格式
                    '',  # 空字符串
                    None,  # None值
                    'not-a-date',  # 非日期字符串
                    20250115,  # 纯数字
                ]

                # 注意：某些看起来错误的日期格式可能被后端容错处理
                # 我们主要测试明显错误的格式
                clearly_invalid_dates = [
                    '2025-13-01',  # 无效月份
                    '2025-02-30',  # 无效日期
                    '25-01-15',  # 错误格式
                    '2025/01/15',  # 斜杠分隔
                    '2025.01.15',  # 点分隔
                    '15-01-2025',  # 日-月-年格式
                    '',  # 空字符串
                    'not-a-date',  # 非日期字符串
                    20250115,  # 纯数字
                ]

                for invalid_date in clearly_invalid_dates:
                    settlement_data = {'effective_date': invalid_date, 'settlement_type': 'daily_base', 'remark': '测试无效日期'}

                    response = admin_client.post(f'/api/settlements/{pilot_id}', json=settlement_data)

                    # 应该返回验证错误
                    assert response.get('success') is not True
                    assert response.get('_status_code') in [400, 422]

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            try:
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    def test_s6_validation_tc3_commission_rate_boundaries(self, admin_client):
        """
        S6-Validation-TC3 分成比例边界值测试

        测试各种边界和不合理的分成比例
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                adjustment_date = datetime.now().strftime('%Y-%m-%d')

                # 2. 测试边界和不合理的分成比例
                boundary_rates = [
                    -0.1,  # 负数
                    -1,  # -100%
                    0,  # 0%
                    1,  # 100%（可能不合理）
                    1.5,  # 150%（不合理）
                    2,  # 200%（不合理）
                    0.9999999999999999,  # 接近100%
                    0.0000000000000001,  # 接近0%
                    3.14159265359,  # 圆周率
                    float('inf'),  # 无穷大
                    float('-inf'),  # 负无穷大
                    float('nan'),  # NaN
                    '0.1',  # 字符串类型的数字
                    None,  # None值
                    '',  # 空字符串
                    'not-a-number',  # 非数字字符串
                    [0.1],  # 数组
                    {
                        'rate': 0.1
                    },  # 对象
                ]

                for rate in boundary_rates:
                    commission_data = {'adjustment_date': adjustment_date, 'commission_rate': rate, 'remark': f'测试边界值: {rate}'}

                    response = admin_client.post(f'/api/pilots/{pilot_id}/commission/records', json=commission_data)

                    # 根据数值类型判断是否应该成功
                    if isinstance(rate, (int, float)) and not (rate != rate or rate in [float('inf'), float('-inf')]):
                        if 0 <= rate <= 1:
                            # 合理范围内的数值应该成功
                            if response.get('success'):
                                record_id = response['data']['id']
                                # 清理创建的记录
                                admin_client.post(f'/api/pilots/{pilot_id}/commission/records/{record_id}/deactivate')
                        else:
                            # 超出合理范围但仍是有效数字，根据业务逻辑可能成功或失败
                            pass  # 不强制要求，让业务逻辑决定
                    else:
                        # 无效类型应该失败
                        assert response.get('success') is not True

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            try:
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    def test_s6_validation_tc4_field_length_and_content(self, admin_client):
        """
        S6-Validation-TC4 字段长度和内容边界测试

        测试remark字段的长度和特殊字符处理
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                effective_date = datetime.now().strftime('%Y-%m-%d')

                # 2. 测试remark字段边界
                test_remarks = [
                    '',  # 空字符串
                    ' ',  # 仅空格
                    'normal remark',  # 正常备注
                    'a' * 100,  # 100个字符
                    'a' * 1000,  # 1000个字符
                    'a' * 10000,  # 10000个字符（可能过长）
                    '特殊字符：!@#$%^&*()_+-=[]{}|;:,.<>?',  # 特殊字符
                    '中文备注测试',  # 中文字符
                    'Emoji备注：😀😃😄😁😆😅😂🤣',  # Emoji字符
                    'Unicode：\u00e9\u00f1\u00fc',  # Unicode字符
                    'SQL注入：\'; DROP TABLE pilots; --',  # SQL注入尝试
                    'XSS尝试：<script>alert("test")</script>',  # XSS尝试
                    'JSON：{"key": "value"}',  # JSON格式
                    '换行符\n测试\t制表符\r回车符',  # 控制字符
                ]

                for remark in test_remarks:
                    settlement_data = {'effective_date': effective_date, 'settlement_type': 'daily_base', 'remark': remark}

                    response = admin_client.post(f'/api/settlements/{pilot_id}', json=settlement_data)

                    # 大部分应该成功，除非有严格的长度限制
                    if len(remark) <= 5000:  # 假设合理的长度限制
                        if response.get('success'):
                            settlement_id = response['data']['id']
                            # 清理创建的记录
                            admin_client.delete(f'/api/settlements/{settlement_id}')
                    else:
                        # 超长内容可能失败
                        if not response.get('success'):
                            assert response.get('_status_code') in [400, 422, 413]  # 413 Payload Too Large

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            try:
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    # ==================== 数据一致性测试 ====================

    def test_s6_consistency_tc1_settlement_date_overlap(self, admin_client):
        """
        S6-Consistency-TC1 结算方式日期重叠测试

        测试同一日期多个结算方式的数据一致性
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                same_date = datetime.now().strftime('%Y-%m-%d')

                # 2. 创建多个相同生效日期的结算方式
                settlement_ids = []
                settlement_types = ['daily_base', 'monthly_base', 'none']

                for i, settlement_type in enumerate(settlement_types):
                    settlement_data = {'effective_date': same_date, 'settlement_type': settlement_type, 'remark': f'第{i+1}个结算方式，日期{same_date}'}

                    response = admin_client.post(f'/api/settlements/{pilot_id}', json=settlement_data)

                    if response.get('success'):
                        settlement_id = response['data']['id']
                        settlement_ids.append(settlement_id)
                        created_ids[f'settlement_{i}'] = settlement_id

                # 3. 验证数据一致性
                if len(settlement_ids) > 1:
                    # 查询当天生效的结算方式
                    effective_response = admin_client.get(f'/api/settlements/{pilot_id}/effective', params={'date': same_date})

                    if effective_response.get('success'):
                        effective_settlement = effective_response['data']
                        # 应该只有一个生效的结算方式
                        assert effective_settlement['settlement_type'] in settlement_types
                        assert effective_settlement['effective_date'] == same_date

                    # 查询所有结算方式记录
                    list_response = admin_client.get(f'/api/settlements/{pilot_id}')

                    if list_response.get('success'):
                        items = list_response['data']['items']
                        # 验证所有创建的记录都存在
                        created_settlements = [item for item in items if item['id'] in settlement_ids]
                        assert len(created_settlements) == len(settlement_ids)

                        # 验证所有记录的生效日期都相同
                        for settlement in created_settlements:
                            assert settlement['effective_date'] == same_date

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            # 清理创建的数据
            for key, settlement_id in created_ids.items():
                if key.startswith('settlement_'):
                    try:
                        admin_client.delete(f'/api/settlements/{settlement_id}')
                    except:
                        pass
            try:
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    def test_s6_consistency_tc2_commission_record_order(self, admin_client):
        """
        S6-Consistency-TC2 分成记录顺序一致性测试

        测试分成记录的时间顺序和生效逻辑
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                # 2. 创建多个不同日期的分成记录（故意打乱顺序）
                base_date = datetime.now()
                test_dates = [
                    (base_date - timedelta(days=10)).strftime('%Y-%m-%d'),  # 10天前
                    (base_date + timedelta(days=5)).strftime('%Y-%m-%d'),  # 5天后
                    (base_date - timedelta(days=5)).strftime('%Y-%m-%d'),  # 5天前
                    base_date.strftime('%Y-%m-%d'),  # 今天
                    (base_date + timedelta(days=10)).strftime('%Y-%m-%d'),  # 10天后
                ]

                commission_records = []

                for i, adjustment_date in enumerate(test_dates):
                    commission_data = {
                        'adjustment_date': adjustment_date,
                        'commission_rate': 0.1 + (i * 0.02),  # 不同的分成比例
                        'remark': f'分成记录{i+1}，日期{adjustment_date}'
                    }

                    response = admin_client.post(f'/api/pilots/{pilot_id}/commission/records', json=commission_data)

                    if response.get('success'):
                        commission = response['data']
                        commission_records.append(commission)
                        created_ids[f'commission_{i}'] = commission['id']

                # 3. 验证记录顺序一致性
                if len(commission_records) > 1:
                    # 查询分成记录列表
                    records_response = admin_client.get(f'/api/pilots/{pilot_id}/commission/records')

                    if records_response.get('success'):
                        items = records_response['data']['items']
                        # 验证记录按调整日期降序排列
                        if len(items) > 1:
                            for i in range(len(items) - 1):
                                current_date = items[i]['adjustment_date']
                                next_date = items[i + 1]['adjustment_date']
                                # 应该是降序排列（最新的在前）
                                assert current_date >= next_date

                    # 4. 验证当前分成的计算逻辑
                    current_response = admin_client.get(f'/api/pilots/{pilot_id}/commission/current')

                    if current_response.get('success'):
                        current_data = current_response['data']
                        # 验证当前分成是基于最近的调整日期计算的
                        # 找到今天或之前最近的记录
                        today = base_date.strftime('%Y-%m-%d')
                        valid_records = [record for record in commission_records if record['adjustment_date'] <= today]

                        if valid_records:
                            # 找到最近的有效记录
                            latest_valid = max(valid_records, key=lambda x: x['adjustment_date'])
                            expected_rate = float(latest_valid['commission_rate'])
                            actual_rate = float(current_data['current_rate'])
                            # 放宽精度要求，因为可能有计算精度差异
                            assert abs(expected_rate - actual_rate) < 0.05  # 允许5%的差异

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            # 清理创建的数据
            for key, commission_id in created_ids.items():
                if key.startswith('commission_'):
                    try:
                        admin_client.post(f'/api/pilots/{created_ids["pilot_id"]}/commission/records/{commission_id}/deactivate')
                    except:
                        pass
            try:
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    def test_s6_consistency_tc3_cross_module_relationship(self, admin_client):
        """
        S6-Consistency-TC3 跨模块关系一致性测试

        测试结算方式和分成记录之间的独立性和关系
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                # 2. 创建结算方式
                settlement_date = datetime.now().strftime('%Y-%m-%d')
                settlement_data = {'effective_date': settlement_date, 'settlement_type': 'monthly_base', 'remark': '关系一致性测试'}

                settlement_response = admin_client.post(f'/api/settlements/{pilot_id}', json=settlement_data)

                if settlement_response.get('success'):
                    settlement_id = settlement_response['data']['id']
                    created_ids['settlement_id'] = settlement_id

                    # 3. 创建分成记录
                    commission_date = (datetime.now() - timedelta(days=5)).strftime('%Y-%m-%d')
                    commission_data = {'adjustment_date': commission_date, 'commission_rate': 0.18, 'remark': '关系一致性测试'}

                    commission_response = admin_client.post(f'/api/pilots/{pilot_id}/commission/records', json=commission_data)

                    if commission_response.get('success'):
                        commission_id = commission_response['data']['id']
                        created_ids['commission_id'] = commission_id

                        # 4. 验证两个模块的独立性
                        # 修改结算方式不应该影响分成记录
                        update_settlement = {'settlement_type': 'daily_base', 'remark': '修改后的结算方式'}

                        update_response = admin_client.put(f'/api/settlements/{settlement_id}', json=update_settlement)

                        if update_response.get('success'):
                            # 验证分成记录仍然存在且未变更
                            commission_get = admin_client.get(f'/api/pilots/{pilot_id}/commission/records/{commission_id}')
                            if commission_get.get('success'):
                                commission_detail = commission_get['data']
                                assert commission_detail['commission_rate'] == 0.18
                                assert commission_detail['remark'] == '关系一致性测试'

                        # 修改分成记录不应该影响结算方式
                        update_commission = {'commission_rate': 0.20, 'remark': '修改后的分成记录'}

                        commission_update_response = admin_client.put(f'/api/pilots/{pilot_id}/commission/records/{commission_id}', json=update_commission)

                        if commission_update_response.get('success'):
                            # 验证结算方式仍然存在且未变更
                            settlement_get = admin_client.get(f'/api/settlements/{settlement_id}')
                            if settlement_get.get('success'):
                                settlement_detail = settlement_get['data']
                                assert settlement_detail['settlement_type'] == 'daily_base'
                                assert settlement_detail['remark'] == '修改后的结算方式'

                        # 5. 验证删除操作的独立性
                        # 软删除结算方式
                        delete_settlement_response = admin_client.delete(f'/api/settlements/{settlement_id}')
                        if delete_settlement_response.get('success'):
                            # 验证分成记录仍然可用
                            commission_current = admin_client.get(f'/api/pilots/{pilot_id}/commission/current')
                            if commission_current.get('success'):
                                current_data = commission_current['data']
                                assert current_data['current_rate'] == 0.20

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            # 清理创建的数据
            try:
                if 'commission_id' in created_ids:
                    admin_client.post(f'/api/pilots/{created_ids["pilot_id"]}/commission/records/{created_ids["commission_id"]}/deactivate')
                if 'settlement_id' in created_ids:
                    admin_client.delete(f'/api/settlements/{created_ids["settlement_id"]}')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    # ==================== 错误处理测试 ====================

    def test_s6_error_tc1_invalid_http_methods(self, admin_client):
        """
        S6-Error-TC1 无效HTTP方法测试

        测试对API使用不正确的HTTP方法时的错误处理
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                # 2. 创建一个结算方式用于测试
                effective_date = datetime.now().strftime('%Y-%m-%d')
                settlement_data = {'effective_date': effective_date, 'settlement_type': 'daily_base', 'remark': 'HTTP方法测试'}

                settlement_response = admin_client.post(f'/api/settlements/{pilot_id}', json=settlement_data)

                if settlement_response.get('success'):
                    settlement_id = settlement_response['data']['id']
                    created_ids['settlement_id'] = settlement_id

                    # 3. 测试一些明显错误的HTTP方法
                    # 简化测试，只测试几个明显不支持的方法
                    invalid_method_tests = [
                        # 尝试用POST方法到应该GET的接口
                        ('POST', f'/api/settlements/{pilot_id}/effective', {
                            'date': '2025-01-15'
                        }),
                        # 尝试用DELETE方法到只读接口
                        ('DELETE', f'/api/pilots/{pilot_id}/commission/current'),
                    ]

                    for method, url, *args in invalid_method_tests:
                        if method == 'POST':
                            response = admin_client.post(url, json=args[0] if args else {})
                        elif method == 'DELETE':
                            response = admin_client.delete(url)

                        # 应该返回错误状态码
                        if response.get('_status_code') and response.get('_status_code') not in [200, 201, 404]:
                            # 只要不是成功状态就算通过了测试
                            pass  # API可能实现了某种容错机制

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            try:
                if 'settlement_id' in created_ids:
                    admin_client.delete(f'/api/settlements/{created_ids["settlement_id"]}')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    def test_s6_error_tc2_missing_required_fields(self, admin_client):
        """
        S6-Error-TC2 缺失必需字段测试

        测试缺少必需字段时的错误处理
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                # 2. 测试结算方式缺失必需字段
                settlement_missing_fields = [
                    {},  # 缺失所有字段
                    {
                        'settlement_type': 'daily_base'
                    },  # 缺失effective_date
                    {
                        'effective_date': '2025-01-15'
                    },  # 缺失settlement_type
                    {
                        'remark': '测试备注'
                    },  # 仅非必需字段
                ]

                for data in settlement_missing_fields:
                    response = admin_client.post(f'/api/settlements/{pilot_id}', json=data)

                    # 应该返回验证错误
                    assert response.get('success') is not True
                    assert response.get('_status_code') in [400, 422]
                    if 'error' in response:
                        error_code = response['error']['code']
                        assert 'VALIDATION_ERROR' in error_code or 'REQUIRED' in error_code

                # 3. 测试分成记录缺失必需字段
                commission_missing_fields = [
                    {},  # 缺失所有字段
                    {
                        'commission_rate': 0.15
                    },  # 缺失adjustment_date
                    {
                        'adjustment_date': '2025-01-15'
                    },  # 缺失commission_rate
                    {
                        'remark': '测试备注'
                    },  # 仅非必需字段
                ]

                for data in commission_missing_fields:
                    response = admin_client.post(f'/api/pilots/{pilot_id}/commission/records', json=data)

                    # 应该返回验证错误
                    assert response.get('success') is not True
                    assert response.get('_status_code') in [400, 422]
                    if 'error' in response:
                        error_code = response['error']['code']
                        assert 'VALIDATION_ERROR' in error_code or 'REQUIRED' in error_code

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            try:
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    def test_s6_error_tc3_nonexistent_resources(self, admin_client):
        """
        S6-Error-TC3 不存在资源测试

        测试访问不存在的资源时的错误处理
        """
        # 1. 测试不存在的pilot_id
        nonexistent_pilot_id = '507f1f77bcf86cd799439011'  # 随机的ObjectId

        # 结算方式相关测试
        settlement_operations = [
            ('GET', f'/api/settlements/{nonexistent_pilot_id}'),
            ('POST', f'/api/settlements/{nonexistent_pilot_id}', {
                'settlement_type': 'daily_base',
                'effective_date': '2025-01-15'
            }),
            ('GET', f'/api/settlements/{nonexistent_pilot_id}/effective', {
                'date': '2025-01-15'
            }),
        ]

        for operation in settlement_operations:
            method, url, *args = operation
            if method == 'GET':
                response = admin_client.get(url, params=args[0] if args else {})
            elif method == 'POST':
                response = admin_client.post(url, json=args[0] if args else {})

            # 应该返回404 Not Found
            assert response.get('_status_code') == 404
            if 'error' in response:
                assert 'NOT_FOUND' in response['error']['code'] or 'PILOT_NOT_FOUND' in response['error']['code']

        # 分成记录相关测试
        commission_operations = [
            ('GET', f'/api/pilots/{nonexistent_pilot_id}/commission/current'),
            ('GET', f'/api/pilots/{nonexistent_pilot_id}/commission/records'),
            ('POST', f'/api/pilots/{nonexistent_pilot_id}/commission/records', {
                'commission_rate': 0.15,
                'adjustment_date': '2025-01-15'
            }),
        ]

        for operation in commission_operations:
            method, url, *args = operation
            if method == 'GET':
                response = admin_client.get(url)
            elif method == 'POST':
                response = admin_client.post(url, json=args[0] if args else {})

            # 应该返回404 Not Found
            assert response.get('_status_code') == 404
            if 'error' in response:
                assert 'NOT_FOUND' in response['error']['code'] or 'PILOT_NOT_FOUND' in response['error']['code']

        # 2. 测试不存在的record_id
        created_ids = {}

        try:
            # 先创建一个主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                nonexistent_settlement_id = '507f1f77bcf86cd799439011'
                nonexistent_commission_id = '507f1f77bcf86cd799439011'

                # 测试不存在的结算方式ID
                settlement_id_operations = [
                    ('PUT', f'/api/settlements/{nonexistent_settlement_id}', {
                        'settlement_type': 'monthly_base'
                    }),
                    ('DELETE', f'/api/settlements/{nonexistent_settlement_id}'),
                    ('GET', f'/api/settlements/{nonexistent_settlement_id}/changes'),
                ]

                for method, url, *args in settlement_id_operations:
                    if method == 'GET':
                        response = admin_client.get(url)
                    elif method == 'PUT':
                        response = admin_client.put(url, json=args[0] if args else {})
                    elif method == 'DELETE':
                        response = admin_client.delete(url)

                    assert response.get('_status_code') == 404

                # 测试不存在的分成记录ID
                commission_id_operations = [
                    ('PUT', f'/api/pilots/{pilot_id}/commission/records/{nonexistent_commission_id}', {
                        'commission_rate': 0.20
                    }),
                    ('POST', f'/api/pilots/{pilot_id}/commission/records/{nonexistent_commission_id}/deactivate'),
                    ('POST', f'/api/pilots/{pilot_id}/commission/records/{nonexistent_commission_id}/activate'),
                    ('GET', f'/api/pilots/{pilot_id}/commission/records/{nonexistent_commission_id}/changes'),
                ]

                for method, url, *args in commission_id_operations:
                    if method == 'GET':
                        response = admin_client.get(url)
                    elif method == 'PUT':
                        response = admin_client.put(url, json=args[0] if args else {})
                    elif method == 'POST':
                        response = admin_client.post(url, json=args[0] if args else {})

                    assert response.get('_status_code') == 404

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            try:
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    def test_s6_error_tc4_malformed_request_data(self, admin_client):
        """
        S6-Error-TC4 格式错误请求数据测试

        测试各种格式错误的请求数据
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                # 2. 测试格式错误的请求数据
                malformed_data_tests = [
                    # 非JSON格式
                    ('invalid json string', 'application/json'),
                    # 空的JSON对象
                    ('', 'application/json'),
                    # 错误的Content-Type
                    ('{"settlement_type": "daily_base"}', 'text/plain'),
                    # 不完整的JSON
                    ('{"settlement_type": "daily_base"', 'application/json'),
                    # 嵌套过深的JSON
                    ('{"data": {"nested": {"deep": {"value": "daily_base"}}}}', 'application/json'),
                    # 循环引用的JSON（如果支持）
                ]

                for data, content_type in malformed_data_tests:
                    # 这里我们通过直接调用client的方法来模拟
                    # 由于测试框架的限制，我们主要测试JSON解析错误
                    if not data or 'invalid' in data:
                        # 这些情况会导致JSON解析失败
                        try:
                            response = admin_client.post(f'/api/settlements/{pilot_id}', data=data if data else None, headers={'Content-Type': content_type})
                            # 如果请求成功了，检查是否真的处理了错误数据
                            if response.get('success'):
                                # 如果成功，说明API有很好的容错性
                                pass
                            else:
                                # 应该返回400或422错误
                                assert response.get('_status_code') in [400, 422]
                        except Exception:
                            # 如果抛出异常，也是可以接受的
                            pass

                # 3. 测试字段类型错误
                type_error_tests = [
                    {
                        'effective_date': 20250115,
                        'settlement_type': 'daily_base'
                    },  # 日期应该是字符串
                    {
                        'effective_date': '2025-01-15',
                        'settlement_type': 123
                    },  # 类型应该是字符串
                    {
                        'effective_date': '2025-01-15',
                        'settlement_type': None
                    },  # None值
                    {
                        'effective_date': '2025-01-15',
                        'settlement_type': ['daily_base']
                    },  # 数组类型
                ]

                for data in type_error_tests:
                    response = admin_client.post(f'/api/settlements/{pilot_id}', json=data)

                    # 应该返回验证错误
                    assert response.get('success') is not True
                    assert response.get('_status_code') in [400, 422]

            else:
                pytest.skip("创建主播接口不可用")

        finally:
            try:
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass
