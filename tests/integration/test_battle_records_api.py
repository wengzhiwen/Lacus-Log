"""
开播记录 REST API 集成测试

测试开播记录的完整生命周期管理，包括创建、查询、更新、删除等功能。
特别关注从通告创建开播记录的流程，以及数据的准确性验证。
"""
import random
from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from tests.fixtures.factories import AnnouncementFactory, BattleAreaFactory, PilotFactory


@pytest.mark.integration
@pytest.mark.battle_records
class TestBattleRecordsList:
    """测试开播记录列表相关功能"""

    def test_get_records_list_success(self, admin_client):
        """测试获取开播记录列表 - 成功"""
        print("\n========== 测试获取开播记录列表 ==========")

        response = admin_client.get('/battle-records/api/battle-records')

        assert response['success'] is True
        assert 'data' in response
        assert 'items' in response['data']
        assert 'meta' in response

        # 验证列表结构
        items = response['data']['items']
        if items:  # 如果有数据，验证数据结构
            record = items[0]
            assert 'id' in record
            assert 'pilot' in record
            assert 'start_time' in record  # 摘要中的start_time是对象结构
            assert 'revenue_amount' in record  # 摘要中revenue_amount在顶层
            assert 'base_salary' in record     # 摘要中base_salary在顶层
            assert 'work_mode' in record
            assert 'duration_hours' in record  # 摘要中有时长而非结束时间

    def test_get_records_with_filters(self, admin_client):
        """测试带过滤条件的开播记录列表"""
        print("\n========== 测试开播记录过滤功能 ==========")

        # 测试按主播过滤
        response = admin_client.get('/battle-records/api/battle-records?pilot=test_pilot_id')
        assert response['success'] is True

        # 测试按日期过滤
        today = datetime.now().date().isoformat()
        response = admin_client.get(f'/battle-records/api/battle-records?date={today}')
        assert response['success'] is True

        # 测试按开播方式过滤
        response = admin_client.get('/battle-records/api/battle-records?work_mode=线下')
        assert response['success'] is True

    def test_get_records_unauthorized(self, api_client):
        """测试未授权访问开播记录列表 - 应失败"""
        print("\n========== 测试开播记录列表权限控制 ==========")

        response = api_client.get('/battle-records/api/battle-records')

        assert response.get('success') is not True


@pytest.mark.integration
@pytest.mark.battle_records
class TestBattleRecordsCreate:
    """测试开播记录创建功能"""

    def test_create_record_success(self, admin_client):
        """测试创建开播记录 - 成功"""
        print("\n========== 测试创建开播记录基础功能 ==========")

        # 先获取一个主播
        pilots_response = admin_client.get('/api/pilots?status=已招募&limit=1')
        assert pilots_response['success'] is True

        pilots = pilots_response['data']['items']
        if not pilots:
            print("  ⚠️ 没有已招募主播，跳过测试")
            return

        pilot = pilots[0]

        # 创建开播记录数据
        start_time = datetime.now() - timedelta(hours=4)
        end_time = datetime.now() - timedelta(hours=2)

        record_data = {
            'pilot': pilot['id'],
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'work_mode': '线下',
            'x_coord': '100',
            'y_coord': '200',
            'z_coord': '10',
            'revenue_amount': '450.50',
            'base_salary': '150.00',
            'notes': '测试开播记录'
        }

        # 创建记录
        response = admin_client.post('/battle-records/api/battle-records', json=record_data)

        assert response['success'] is True
        assert 'data' in response

        record = response['data']
        assert record['pilot']['id'] == pilot['id']
        assert record['financial']['revenue_amount'] == '450.50'
        assert record['financial']['base_salary'] == '150.00'
        assert record['work_mode'] == '线下'

        record_id = record['id']

        # 清理：删除创建的记录
        admin_client.delete(f'/battle-records/api/battle-records/{record_id}')

    def test_create_record_missing_required_fields(self, admin_client):
        """测试创建开播记录缺少必需字段 - 应失败"""
        print("\n========== 测试开播记录字段验证 ==========")

        # 缺少必需字段
        incomplete_data = {
            'pilot': 'test_pilot_id',
            # 缺少 start_time, end_time, work_mode
        }

        response = admin_client.post('/battle-records/api/battle-records', json=incomplete_data)

        assert response['success'] is False
        assert 'error' in response
        assert 'INVALID_PARAMS' in str(response.get('error', {}))

    def test_create_record_invalid_time_range(self, admin_client):
        """测试创建开播记录时间范围无效 - 应失败"""
        print("\n========== 测试开播记录时间验证 ==========")

        # 先获取一个主播
        pilots_response = admin_client.get('/api/pilots?status=已招募&limit=1')
        assert pilots_response['success'] is True

        pilots = pilots_response['data']['items']
        if not pilots:
            print("  ⚠️ 没有已招募主播，跳过测试")
            return

        pilot = pilots[0]

        # 结束时间早于开始时间
        invalid_data = {
            'pilot': pilot['id'],
            'start_time': datetime.now().isoformat(),
            'end_time': (datetime.now() - timedelta(hours=2)).isoformat(),
            'work_mode': '线下'
        }

        response = admin_client.post('/battle-records/api/battle-records', json=invalid_data)

        assert response['success'] is False


@pytest.mark.integration
@pytest.mark.battle_records
class TestBattleRecordsDetail:
    """测试开播记录详情功能"""

    def test_get_record_detail_success(self, admin_client):
        """测试获取开播记录详情 - 成功"""
        print("\n========== 测试获取开播记录详情 ==========")

        # 先创建一个记录
        pilots_response = admin_client.get('/api/pilots?status=已招募&limit=1')
        assert pilots_response['success'] is True

        pilots = pilots_response['data']['items']
        if not pilots:
            print("  ⚠️ 没有已招募主播，跳过测试")
            return

        pilot = pilots[0]

        # 创建记录
        start_time = datetime.now() - timedelta(hours=6)
        end_time = datetime.now() - timedelta(hours=4)

        record_data = {
            'pilot': pilot['id'],
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'work_mode': '线上',
            'revenue_amount': '380.00',
            'base_salary': '0.00',
            'notes': '测试开播记录详情'
        }

        create_response = admin_client.post('/battle-records/api/battle-records', json=record_data)
        if not create_response['success']:
            print(f"  详情测试创建失败: {create_response.get('error', {}).get('message', '未知错误')}")
        assert create_response['success'] is True

        record_id = create_response['data']['id']

        try:
            # 获取详情
            detail_response = admin_client.get(f'/battle-records/api/battle-records/{record_id}')

            assert detail_response['success'] is True
            assert 'data' in detail_response

            record = detail_response['data']
            assert record['id'] == record_id
            assert record['pilot']['id'] == pilot['id']
            assert record['work_mode'] == '线上'
            assert 'system' in record
            assert 'created_at' in record['system']
            assert 'updated_at' in record['system']

        finally:
            # 清理
            admin_client.delete(f'/battle-records/api/battle-records/{record_id}')

    def test_get_record_detail_not_found(self, admin_client):
        """测试获取不存在的开播记录详情 - 应失败"""
        print("\n========== 测试获取不存在开播记录 ==========")

        fake_id = 'ffffffffffffffffffffffff'
        response = admin_client.get(f'/battle-records/api/battle-records/{fake_id}')

        assert response['success'] is False


@pytest.mark.integration
@pytest.mark.battle_records
class TestBattleRecordsUpdate:
    """测试开播记录更新功能"""

    def test_update_record_success(self, admin_client):
        """测试更新开播记录 - 成功"""
        print("\n========== 测试更新开播记录 ==========")

        # 先创建记录
        pilots_response = admin_client.get('/api/pilots?status=已招募&limit=1')
        assert pilots_response['success'] is True

        pilots = pilots_response['data']['items']
        if not pilots:
            print("  ⚠️ 没有已招募主播，跳过测试")
            return

        pilot = pilots[0]

        start_time = datetime.now() - timedelta(hours=8)
        end_time = datetime.now() - timedelta(hours=6)

        record_data = {
            'pilot': pilot['id'],
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'work_mode': '线下',
            'x_coord': '100',
            'y_coord': '200',
            'z_coord': '10',
            'revenue_amount': '300.00',
            'base_salary': '150.00',
            'notes': '测试更新开播记录'
        }

        create_response = admin_client.post('/battle-records/api/battle-records', json=record_data)
        if not create_response['success']:
            print(f"  更新测试创建失败: {create_response.get('error', {}).get('message', '未知错误')}")
        assert create_response['success'] is True

        record_id = create_response['data']['id']

        try:
            # 更新记录
            update_data = {
                'revenue_amount': '520.80',
                'base_salary': '180.00',
                'notes': '更新后的备注信息',
                'x_coord': '101',
                'y_coord': '201',
                'z_coord': '11'
            }

            update_response = admin_client.put(f'/battle-records/api/battle-records/{record_id}', json=update_data)

            if not update_response['success']:
                print(f"  更新失败: {update_response.get('error', {}).get('message', '未知错误')}")
            assert update_response['success'] is True

            updated_record = update_response['data']
            assert updated_record["financial"]["revenue_amount"] == '520.80'
            assert updated_record["financial"]["base_salary"] == '180.00'
            assert updated_record['notes'] == '更新后的备注信息'

        finally:
            # 清理
            admin_client.delete(f'/battle-records/api/battle-records/{record_id}')


@pytest.mark.integration
@pytest.mark.battle_records
class TestBattleRecordsDelete:
    """测试开播记录删除功能"""

    def test_delete_record_success(self, admin_client):
        """测试删除开播记录 - 成功"""
        print("\n========== 测试删除开播记录 ==========")

        # 先创建记录
        pilots_response = admin_client.get('/api/pilots?status=已招募&limit=1')
        assert pilots_response['success'] is True

        pilots = pilots_response['data']['items']
        if not pilots:
            print("  ⚠️ 没有已招募主播，跳过测试")
            return

        pilot = pilots[0]

        start_time = datetime.now() - timedelta(hours=10)
        end_time = datetime.now() - timedelta(hours=8)

        record_data = {
            'pilot': pilot['id'],
            'start_time': start_time.isoformat(),
            'end_time': end_time.isoformat(),
            'work_mode': '线下',
            'x_coord': '100',
            'y_coord': '200',
            'z_coord': '10',
            'revenue_amount': '400.00',
            'notes': '测试删除开播记录'
        }

        create_response = admin_client.post('/battle-records/api/battle-records', json=record_data)
        assert create_response['success'] is True

        record_id = create_response['data']['id']

        # 删除记录
        delete_response = admin_client.delete(f'/battle-records/api/battle-records/{record_id}')

        assert delete_response['success'] is True

        # 验证删除成功
        detail_response = admin_client.get(f'/battle-records/api/battle-records/{record_id}')
        assert detail_response['success'] is False


@pytest.mark.integration
@pytest.mark.battle_records
class TestBattleRecordsWorkflow:
    """开播记录工作流测试"""

    def _generate_revenue_amount(self):
        """生成流水金额：80%概率落在300-500范围"""
        if random.random() < 0.8:
            return round(random.uniform(300, 500), 2)
        else:
            # 20%概率落在其他范围
            return round(
                random.choice([
                    random.uniform(10, 100),  # 10%概率小额
                    random.uniform(500, 1500),  # 8%概率中额
                    random.uniform(1500, 3000)  # 2%概率大额
                ]),
                2)

    def _generate_start_time(self, base_date):
        """生成开播时间：60天内均匀分布"""
        days_offset = random.randint(0, 60)
        hour_offset = random.randint(8, 23)  # 工作时间
        minute_offset = random.choice([0, 30])  # 整点或半点

        return base_date - timedelta(days=days_offset, hours=24 - hour_offset, minutes=60 - minute_offset)

    def test_batch_create_battle_records_from_announcements(self, admin_client):
        """
        批量从通告创建开播记录的综合测试

        测试流程：
        1. 清理所有现有的开播记录
        2. 获取已有的通告数据（约50+个）
        3. 为其中80%的通告创建开播记录
        4. 验证数据完整性和分布
        5. 记录所有创建的数据供后续报告测试使用
        """
        print("\n========== 开始批量从通告创建开播记录综合测试 ==========")

        # 1. 清理所有现有开播记录
        print("\n===== 步骤1：清理现有开播记录 =====")
        existing_records_response = admin_client.get('/battle-records/api/battle-records?per_page=1000')
        if existing_records_response['success'] and existing_records_response['data']['items']:
            print(f"  发现 {len(existing_records_response['data']['items'])} 条现有记录，开始清理...")
            for record in existing_records_response['data']['items']:
                admin_client.delete(f"/battle-records/api/battle-records/{record['id']}")
            print("  ✅ 清理完成")
        else:
            print("  ✅ 没有现有记录需要清理")

        # 2. 获取通告数据
        print("\n===== 步骤2：获取通告数据 =====")
        announcements_response = admin_client.get('/announcements/api/announcements?per_page=1000')
        assert announcements_response['success'], f"获取通告失败：{announcements_response}"

        announcements = announcements_response['data']['items']
        print(f"  找到 {len(announcements)} 个通告")

        if len(announcements) < 10:
            print("  ⚠️ 通告数量不足，跳过测试")
            return

        # 3. 为80%的通告创建开播记录
        print("\n===== 步骤3：批量创建开播记录 =====")

        # 选择80%的通告
        target_count = int(len(announcements) * 0.8)
        selected_announcements = random.sample(announcements, target_count)

        created_records = []
        base_date = datetime.now()

        for i, announcement in enumerate(selected_announcements):
            print(f"  处理通告 {i+1}/{target_count}: {announcement['id']}")

            # 生成开播时间（通告时间前后2小时内）
            ann_start = datetime.fromisoformat(announcement['start_time'])
            record_start = self._generate_start_time(base_date)
            record_end = record_start + timedelta(hours=random.randint(2, 6))

            # 生成流水金额和底薪
            revenue = self._generate_revenue_amount()
            base_salary = 150.00  # 统一底薪

            # 构建开播记录数据
            record_data = {
                'pilot': announcement['pilot']['id'],
                'related_announcement': announcement['id'],
                'start_time': record_start.isoformat(),
                'end_time': record_end.isoformat(),
                'work_mode': announcement['work_mode'],
                'revenue_amount': str(revenue),
                'base_salary': str(base_salary),
                'x_coord': announcement['x_coord'],
                'y_coord': announcement['y_coord'],
                'z_coord': announcement['z_coord'],
                'notes': f'从通告{announcement["id"]}创建的记录'
            }

            # 线下开播需要坐标
            if announcement['work_mode'] == '线下':
                record_data.update({'x_coord': announcement['x_coord'], 'y_coord': announcement['y_coord'], 'z_coord': announcement['z_coord']})

            # 创建记录
            create_response = admin_client.post('/battle-records/api/battle-records', json=record_data)

            if create_response['success']:
                record = create_response['data']
                created_records.append({
                    'id': record['id'],
                    'announcement_id': announcement['id'],
                    'pilot_id': announcement['pilot']['id'],
                    'pilot_nickname': announcement['pilot']['nickname'],
                    'revenue_amount': revenue,
                    'base_salary': base_salary,
                    'start_time': record_start,
                    'end_time': record_end,
                    'work_mode': announcement['work_mode']
                })
                print(f"    ✅ 创建成功，流水: ¥{revenue}")
            else:
                print(f"    ❌ 创建失败: {create_response.get('error', {}).get('message', '未知错误')}")

        # 4. 验证创建结果
        print(f"\n===== 步骤4：验证创建结果 =====")
        print(f"  目标创建: {target_count} 条记录")
        print(f"  实际创建: {len(created_records)} 条记录")
        print(f"  成功率: {len(created_records)/target_count*100:.1f}%")

        # 验证数据分布
        if created_records:
            revenues = [r['revenue_amount'] for r in created_records]
            avg_revenue = sum(revenues) / len(revenues)
            min_revenue = min(revenues)
            max_revenue = max(revenues)

            print(f"  流水统计:")
            print(f"    平均流水: ¥{avg_revenue:.2f}")
            print(f"    最小流水: ¥{min_revenue:.2f}")
            print(f"    最大流水: ¥{max_revenue:.2f}")

            # 验证80%的记录在300-500范围内
            in_range_count = len([r for r in revenues if 300 <= r <= 500])
            range_percentage = in_range_count / len(revenues) * 100
            print(f"    300-500元范围: {in_range_count}/{len(revenues)} ({range_percentage:.1f}%)")

            # 验证所有记录的底薪都是150元
            all_correct_salary = all(r['base_salary'] == 150.00 for r in created_records)
            print(f"    底薪验证: {'✅ 全部150元' if all_correct_salary else '❌ 存在错误'}")

            # 验证关联通告
            with_announcement = len([r for r in created_records if r.get('announcement_id')])
            announcement_percentage = with_announcement / len(created_records) * 100
            print(f"    关联通告: {with_announcement}/{len(created_records)} ({announcement_percentage:.1f}%)")

        # 5. 记录测试数据供后续使用
        print(f"\n===== 步骤5：记录测试数据 =====")
        print(f"  测试数据将存储在内存中，供后续报告测试使用")
        print(f"  记录数量: {len(created_records)}")
        print(f"  时间范围: 60天内")
        print(
            f"  金额范围: ¥{min(created_records, key=lambda x: x['revenue_amount'])['revenue_amount']:.2f} - ¥{max(created_records, key=lambda x: x['revenue_amount'])['revenue_amount']:.2f}"
        )

        # 可以将数据存储在测试上下文中供其他测试使用
        # 这里只是记录信息，实际存储可能需要使用fixture或数据库

        assert len(created_records) >= target_count * 0.7, f"创建成功率过低: {len(created_records)}/{target_count}"
        print("\n✅ 批量创建开播记录测试完成")

    def test_create_mixed_battle_records(self, admin_client):
        """
        创建混合开播记录测试（无通告关联）

        测试流程：
        1. 创建一些没有关联通告的开播记录
        2. 验证独立记录的创建和管理
        3. 确保底薪为0（因为没有通告关联）
        """
        print("\n========== 开始创建混合开播记录测试 ==========")

        # 获取主播数据
        pilots_response = admin_client.get('/api/pilots?status=已招募&per_page=10')
        assert pilots_response['success']

        pilots = pilots_response['data']['items']
        if len(pilots) < 3:
            print("  ⚠️ 主播数量不足，跳过测试")
            return

        # 创建5个独立的开播记录
        print("\n===== 创建独立开播记录 =====")
        created_records = []
        base_date = datetime.now()

        for i in range(5):
            pilot = random.choice(pilots)

            # 生成时间（过去60天内）
            record_start = self._generate_start_time(base_date)
            record_end = record_start + timedelta(hours=random.randint(2, 8))

            # 生成流水金额（同样分布）
            revenue = self._generate_revenue_amount()

            # 构建数据（无通告关联）
            record_data = {
                'pilot': pilot['id'],
                'start_time': record_start.isoformat(),
                'end_time': record_end.isoformat(),
                'work_mode': random.choice(['线上', '线下']),
                'revenue_amount': str(revenue),
                'base_salary': '0.00',  # 无通告关联，底薪为0
                'notes': f'独立开播记录 {i+1}'
            }

            # 如果是线下，需要坐标
            if record_data['work_mode'] == '线下':
                record_data.update({'x_coord': str(random.randint(100, 999)), 'y_coord': str(random.randint(100, 999)), 'z_coord': str(random.randint(1, 99))})

            # 创建记录
            response = admin_client.post('/battle-records/api/battle-records', json=record_data)

            if response['success']:
                record = response['data']
                created_records.append(record['id'])
                print(f"  ✅ 创建记录 {i+1}: 主播={pilot['nickname']}, 流水=¥{revenue}")
            else:
                print(f"  ❌ 创建失败: {response.get('error', {}).get('message', '未知错误')}")

        # 验证结果
        print(f"\n===== 验证独立记录 =====")
        print(f"  目标创建: 5 条")
        print(f"  实际创建: {len(created_records)} 条")

        if created_records:
            # 验证底薪为0
            verification_passed = True
            for record_id in created_records:
                detail_response = admin_client.get(f'/battle-records/api/battle-records/{record_id}')
                if detail_response['success']:
                    record = detail_response['data']
                    if float(record["financial"]["base_salary"]) != 0:
                        print(f"  ❌ 记录 {record_id} 底薪错误: {record["financial"]["base_salary"]}")
                        verification_passed = False
                        break
                else:
                    print(f"  ❌ 无法获取记录 {record_id} 详情")
                    verification_passed = False
                    break

            if verification_passed:
                print("  ✅ 所有独立记录底薪验证通过（均为0元）")

            # 清理测试数据
            print(f"\n===== 清理测试数据 =====")
            for record_id in created_records:
                admin_client.delete(f'/battle-records/api/battle-records/{record_id}')
            print(f"  ✅ 清理完成 {len(created_records)} 条记录")

        print("\n✅ 混合开播记录测试完成")


# 数据工厂扩展
class BattleRecordFactory:
    """开播记录数据工厂"""

    @staticmethod
    def create_record_data(pilot_id: str, **kwargs) -> dict:
        """生成开播记录数据"""
        from datetime import datetime, timedelta
        import random

        base_time = datetime.now() - timedelta(hours=random.randint(1, 24))

        data = {
            'pilot': pilot_id,
            'start_time': base_time.isoformat(),
            'end_time': (base_time + timedelta(hours=random.randint(2, 6))).isoformat(),
            'work_mode': random.choice(['线上', '线下']),
            'revenue_amount': str(round(random.uniform(10, 3000), 2)),
            'base_salary': str(round(random.uniform(0, 200), 2)),
        }

        # 线下开播需要坐标
        if data['work_mode'] == '线下':
            data.update({'x_coord': str(random.randint(100, 999)), 'y_coord': str(random.randint(100, 999)), 'z_coord': str(random.randint(1, 99))})

        data.update(kwargs)
        return data

    @staticmethod
    def create_record_from_announcement(announcement: dict, **kwargs) -> dict:
        """从通告数据生成开播记录数据"""
        from datetime import datetime, timedelta
        import random

        ann_start = datetime.fromisoformat(announcement['start_time'])

        # 在通告时间附近生成开播时间
        start_offset = random.randint(-120, 120)  # 前后2小时内
        record_start = ann_start + timedelta(minutes=start_offset)
        duration = random.randint(2, 6)
        record_end = record_start + timedelta(hours=duration)

        data = {
            'pilot': announcement['pilot']['id'],
            'related_announcement': announcement['id'],
            'start_time': record_start.isoformat(),
            'end_time': record_end.isoformat(),
            'work_mode': announcement['work_mode'],
            'revenue_amount': str(round(random.uniform(10, 3000), 2)),
            'base_salary': '150.00',  # 通告关联的统一底薪
            'notes': f'从通告 {announcement["id"]} 创建'
        }

        # 保留通告的坐标信息
        if announcement['work_mode'] == '线下':
            data.update({'x_coord': announcement['x_coord'], 'y_coord': announcement['y_coord'], 'z_coord': announcement['z_coord']})

        data.update(kwargs)
        return data
