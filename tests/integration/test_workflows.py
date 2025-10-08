"""
跨模块集成测试 - 工作流测试

测试完整的业务流程，验证多个模块间的协作
"""
from datetime import datetime, timedelta

import pytest

from tests.fixtures.factories import (AnnouncementFactory, BattleAreaFactory,
                                      PilotFactory)


@pytest.mark.integration
@pytest.mark.workflows
class TestRecruitmentWorkflow:
    """招募工作流集成测试"""

    def test_batch_recruitment_20_pilots(self, admin_client, kancho_client):
        """
        测试批量招募20个主播的综合场景
        
        场景分布：
        - 2个主播：面试阶段被拒（不招募）
        - 3个主播：试播阶段被拒（不招募）
        - 2个主播：开播阶段被拒（不招募）
        - 3个主播：停留在待面试阶段
        - 2个主播：停留在待预约试播阶段
        - 2个主播：停留在待试播阶段
        - 1个主播：停留在待预约开播阶段
        - 5个主播：完成招募（3个正式主播，2个实习主播）
        
        总计：20个主播，7个被拒，8个停留在中间阶段，5个完成招募
        """
        print("\n========== 开始批量招募20个主播综合测试 ==========")

        # 获取运营用户信息（作为招募负责人和直属运营）
        me_response = admin_client.get('/api/auth/me')
        assert me_response['success'] is True, f"获取当前用户失败：{me_response}"
        admin_user_id = me_response['data']['user']['id']
        admin_nickname = me_response['data']['user']['nickname']
        print(f"管理员用户：{admin_nickname} (ID: {admin_user_id})")

        # 存储所有创建的主播和招募记录ID
        created_pilots = []
        created_recruits = []
        pilot_factory = PilotFactory()

        try:
            # ========== 1. 创建20个主播 ==========
            print("\n===== 步骤1：创建20个主播 =====")
            for i in range(20):
                pilot_data = pilot_factory.create_pilot_data()
                pilot_response = admin_client.post('/api/pilots', json=pilot_data)
                assert pilot_response['success'] is True, f"创建主播{i+1}失败：{pilot_response}"

                pilot_id = pilot_response['data']['id']
                nickname = pilot_response['data']['nickname']
                created_pilots.append(pilot_id)
                print(f"  创建主播 {i+1}/20: {nickname} (ID: {pilot_id})")

            assert len(created_pilots) == 20, "应创建20个主播"

            # ========== 2. 为所有主播启动招募 ==========
            print("\n===== 步骤2：为20个主播启动招募 =====")
            appointment_base = datetime.now() + timedelta(days=1)

            for idx, pilot_id in enumerate(created_pilots):
                recruit_data = {
                    'pilot_id': pilot_id,
                    'recruiter_id': admin_user_id,
                    'appointment_time': (appointment_base + timedelta(hours=idx)).strftime('%Y-%m-%d %H:%M:%S'),
                    'channel': 'BOSS',
                    'introduction_fee': 0,
                    'remarks': f'批量测试主播{idx+1}'
                }

                recruit_response = admin_client.post('/api/recruits', json=recruit_data)
                assert recruit_response['success'] is True, f"启动招募失败（主播{idx+1}）：{recruit_response}"

                recruit_id = recruit_response['data']['id']
                created_recruits.append(recruit_id)
                print(f"  启动招募 {idx+1}/20: 招募ID {recruit_id}")

            assert len(created_recruits) == 20, "应创建20条招募记录"

            # ========== 3. 场景1：面试阶段被拒（2个主播，索引0-1） ==========
            print("\n===== 步骤3：面试阶段被拒（2个主播） =====")
            for idx in range(2):
                recruit_id = created_recruits[idx]
                decision_data = {'interview_decision': '不招募', 'real_name': '测试姓名', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试表现不佳'}

                decision_response = admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=decision_data)
                assert decision_response['success'] is True, f"面试决策失败：{decision_response}"
                print(f"  主播{idx+1}：面试阶段被拒")

            # ========== 4. 场景2：通过面试，停留在待预约试播（2个主播，索引2-3） ==========
            print("\n===== 步骤4：通过面试，停留在待预约试播（2个主播） =====")
            for idx in range(2, 4):
                recruit_id = created_recruits[idx]
                decision_data = {'interview_decision': '预约试播', 'real_name': f'测试姓名{idx+1}', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试通过'}

                decision_response = admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=decision_data)
                assert decision_response['success'] is True, f"面试决策失败：{decision_response}"
                print(f"  主播{idx+1}：通过面试，停留在待预约试播阶段")

            # ========== 5. 场景3：通过面试并预约试播，停留在待试播（2个主播，索引4-5） ==========
            print("\n===== 步骤5：通过面试并预约试播，停留在待试播（2个主播） =====")
            training_time_base = datetime.now() + timedelta(days=2)

            for idx in range(4, 6):
                recruit_id = created_recruits[idx]

                # 面试通过
                decision_data = {'interview_decision': '预约试播', 'real_name': f'测试姓名{idx+1}', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试通过'}
                admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=decision_data)

                # 预约试播
                schedule_data = {
                    'scheduled_training_time': (training_time_base + timedelta(hours=idx)).strftime('%Y-%m-%d %H:%M:%S'),
                    'work_mode': '线下',
                    'introduction_fee': 0,
                    'remarks': '预约试播时间'
                }
                schedule_response = admin_client.post(f'/api/recruits/{recruit_id}/schedule-training', json=schedule_data)
                assert schedule_response['success'] is True, f"预约试播失败：{schedule_response}"
                print(f"  主播{idx+1}：预约试播完成，停留在待试播阶段")

            # ========== 6. 场景4：试播阶段被拒（3个主播，索引6-8） ==========
            print("\n===== 步骤6：试播阶段被拒（3个主播） =====")

            for idx in range(6, 9):
                recruit_id = created_recruits[idx]

                # 面试通过
                decision_data = {'interview_decision': '预约试播', 'real_name': f'测试姓名{idx+1}', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试通过'}
                admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=decision_data)

                # 预约试播
                schedule_data = {
                    'scheduled_training_time': (training_time_base + timedelta(hours=idx)).strftime('%Y-%m-%d %H:%M:%S'),
                    'work_mode': '线下',
                    'introduction_fee': 0,
                    'remarks': '预约试播时间'
                }
                admin_client.post(f'/api/recruits/{recruit_id}/schedule-training', json=schedule_data)

                # 试播被拒
                training_decision_data = {'training_decision': '不招募', 'introduction_fee': 0, 'remarks': '试播表现不佳'}
                training_response = admin_client.post(f'/api/recruits/{recruit_id}/training-decision', json=training_decision_data)
                assert training_response['success'] is True, f"试播决策失败：{training_response}"
                print(f"  主播{idx+1}：试播阶段被拒")

            # ========== 7. 场景5：通过试播，停留在待预约开播（1个主播，索引9） ==========
            print("\n===== 步骤7：通过试播，停留在待预约开播（1个主播） =====")
            idx = 9
            recruit_id = created_recruits[idx]

            # 面试通过
            decision_data = {'interview_decision': '预约试播', 'real_name': f'测试姓名{idx+1}', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试通过'}
            admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=decision_data)

            # 预约试播
            schedule_data = {
                'scheduled_training_time': (training_time_base + timedelta(hours=idx)).strftime('%Y-%m-%d %H:%M:%S'),
                'work_mode': '线下',
                'introduction_fee': 0,
                'remarks': '预约试播时间'
            }
            admin_client.post(f'/api/recruits/{recruit_id}/schedule-training', json=schedule_data)

            # 试播通过
            training_decision_data = {'training_decision': '预约开播', 'introduction_fee': 0, 'remarks': '试播通过'}
            training_response = admin_client.post(f'/api/recruits/{recruit_id}/training-decision', json=training_decision_data)
            assert training_response['success'] is True, f"试播决策失败：{training_response}"
            print(f"  主播{idx+1}：通过试播，停留在待预约开播阶段")

            # ========== 8. 场景6：开播阶段被拒（2个主播，索引10-11） ==========
            print("\n===== 步骤8：开播阶段被拒（2个主播） =====")
            broadcast_time_base = datetime.now() + timedelta(days=3)

            for idx in range(10, 12):
                recruit_id = created_recruits[idx]

                # 面试通过
                decision_data = {'interview_decision': '预约试播', 'real_name': f'测试姓名{idx+1}', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试通过'}
                admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=decision_data)

                # 预约试播
                schedule_data = {
                    'scheduled_training_time': (training_time_base + timedelta(hours=idx)).strftime('%Y-%m-%d %H:%M:%S'),
                    'work_mode': '线下',
                    'introduction_fee': 0,
                    'remarks': '预约试播时间'
                }
                admin_client.post(f'/api/recruits/{recruit_id}/schedule-training', json=schedule_data)

                # 试播通过
                training_decision_data = {'training_decision': '预约开播', 'introduction_fee': 0, 'remarks': '试播通过'}
                admin_client.post(f'/api/recruits/{recruit_id}/training-decision', json=training_decision_data)

                # 预约开播
                broadcast_schedule_data = {
                    'scheduled_broadcast_time': (broadcast_time_base + timedelta(hours=idx)).strftime('%Y-%m-%d %H:%M:%S'),
                    'introduction_fee': 0,
                    'remarks': '预约开播时间'
                }
                admin_client.post(f'/api/recruits/{recruit_id}/schedule-broadcast', json=broadcast_schedule_data)

                # 开播被拒
                broadcast_decision_data = {'broadcast_decision': '不招募', 'introduction_fee': 0, 'remarks': '开播表现不佳'}
                broadcast_response = admin_client.post(f'/api/recruits/{recruit_id}/broadcast-decision', json=broadcast_decision_data)
                assert broadcast_response['success'] is True, f"开播决策失败：{broadcast_response}"
                print(f"  主播{idx+1}：开播阶段被拒")

            # ========== 9. 场景7：完成招募（5个主播，索引12-16，3个正式+2个实习） ==========
            print("\n===== 步骤9：完成招募（5个主播：3个正式主播，2个实习主播） =====")

            # 3个正式主播（索引12-14）
            for idx in range(12, 15):
                recruit_id = created_recruits[idx]

                # 面试通过
                decision_data = {'interview_decision': '预约试播', 'real_name': f'测试姓名{idx+1}', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试通过'}
                admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=decision_data)

                # 预约试播
                schedule_data = {
                    'scheduled_training_time': (training_time_base + timedelta(hours=idx)).strftime('%Y-%m-%d %H:%M:%S'),
                    'work_mode': '线下',
                    'introduction_fee': 0,
                    'remarks': '预约试播时间'
                }
                admin_client.post(f'/api/recruits/{recruit_id}/schedule-training', json=schedule_data)

                # 试播通过
                training_decision_data = {'training_decision': '预约开播', 'introduction_fee': 0, 'remarks': '试播通过'}
                admin_client.post(f'/api/recruits/{recruit_id}/training-decision', json=training_decision_data)

                # 预约开播
                broadcast_schedule_data = {
                    'scheduled_broadcast_time': (broadcast_time_base + timedelta(hours=idx)).strftime('%Y-%m-%d %H:%M:%S'),
                    'introduction_fee': 0,
                    'remarks': '预约开播时间'
                }
                admin_client.post(f'/api/recruits/{recruit_id}/schedule-broadcast', json=broadcast_schedule_data)

                # 招募为正式主播
                broadcast_decision_data = {'broadcast_decision': '正式主播', 'owner_id': admin_user_id, 'platform': '快手', 'introduction_fee': 0, 'remarks': '招募成功'}
                broadcast_response = admin_client.post(f'/api/recruits/{recruit_id}/broadcast-decision', json=broadcast_decision_data)
                assert broadcast_response['success'] is True, f"招募为正式主播失败：{broadcast_response}"
                print(f"  主播{idx+1}：招募成功，成为正式主播")

            # 2个实习主播（索引15-16）
            for idx in range(15, 17):
                recruit_id = created_recruits[idx]

                # 面试通过
                decision_data = {'interview_decision': '预约试播', 'real_name': f'测试姓名{idx+1}', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试通过'}
                admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=decision_data)

                # 预约试播
                schedule_data = {
                    'scheduled_training_time': (training_time_base + timedelta(hours=idx)).strftime('%Y-%m-%d %H:%M:%S'),
                    'work_mode': '线下',
                    'introduction_fee': 0,
                    'remarks': '预约试播时间'
                }
                admin_client.post(f'/api/recruits/{recruit_id}/schedule-training', json=schedule_data)

                # 试播通过
                training_decision_data = {'training_decision': '预约开播', 'introduction_fee': 0, 'remarks': '试播通过'}
                admin_client.post(f'/api/recruits/{recruit_id}/training-decision', json=training_decision_data)

                # 预约开播
                broadcast_schedule_data = {
                    'scheduled_broadcast_time': (broadcast_time_base + timedelta(hours=idx)).strftime('%Y-%m-%d %H:%M:%S'),
                    'introduction_fee': 0,
                    'remarks': '预约开播时间'
                }
                admin_client.post(f'/api/recruits/{recruit_id}/schedule-broadcast', json=broadcast_schedule_data)

                # 招募为实习主播
                broadcast_decision_data = {'broadcast_decision': '实习主播', 'owner_id': admin_user_id, 'platform': '抖音', 'introduction_fee': 0, 'remarks': '招募成功'}
                broadcast_response = admin_client.post(f'/api/recruits/{recruit_id}/broadcast-decision', json=broadcast_decision_data)
                assert broadcast_response['success'] is True, f"招募为实习主播失败：{broadcast_response}"
                print(f"  主播{idx+1}：招募成功，成为实习主播")

            # ========== 10. 场景8：停留在待面试阶段（3个主播，索引17-19） ==========
            print("\n===== 步骤10：停留在待面试阶段（3个主播） =====")
            for idx in range(17, 20):
                print(f"  主播{idx+1}：停留在待面试阶段（未做任何决策）")

            # ========== 11. 验证最终结果 ==========
            print("\n===== 步骤11：验证最终结果 =====")

            # 统计各阶段主播数量
            stats = {
                'interview_rejected': 0,  # 面试被拒
                'pending_training_schedule': 0,  # 待预约试播
                'pending_training': 0,  # 待试播
                'training_rejected': 0,  # 试播被拒
                'pending_broadcast_schedule': 0,  # 待预约开播
                'broadcast_rejected': 0,  # 开播被拒
                'official_pilot': 0,  # 正式主播
                'intern_pilot': 0,  # 实习主播
                'pending_interview': 0  # 待面试
            }

            # 检查每个招募记录的状态
            for idx, recruit_id in enumerate(created_recruits):
                recruit_detail = admin_client.get(f'/api/recruits/{recruit_id}')
                assert recruit_detail['success'] is True, f"获取招募详情失败：{recruit_detail}"

                recruit = recruit_detail['data']
                status = recruit['status']

                # 索引0-1：面试被拒
                if idx < 2:
                    assert status == '已结束', f"主播{idx+1}应处于已结束状态"
                    assert recruit['interview_decision'] == '不招募', f"主播{idx+1}面试决策应为不招募"
                    stats['interview_rejected'] += 1

                # 索引2-3：待预约试播
                elif idx < 4:
                    assert status == '待预约试播', f"主播{idx+1}应处于待预约试播状态"
                    stats['pending_training_schedule'] += 1

                # 索引4-5：待试播
                elif idx < 6:
                    assert status == '待试播', f"主播{idx+1}应处于待试播状态"
                    stats['pending_training'] += 1

                # 索引6-8：试播被拒
                elif idx < 9:
                    assert status == '已结束', f"主播{idx+1}应处于已结束状态"
                    assert recruit['training_decision'] == '不招募', f"主播{idx+1}试播决策应为不招募"
                    stats['training_rejected'] += 1

                # 索引9：待预约开播
                elif idx == 9:
                    assert status == '待预约开播', f"主播{idx+1}应处于待预约开播状态"
                    stats['pending_broadcast_schedule'] += 1

                # 索引10-11：开播被拒
                elif idx < 12:
                    assert status == '已结束', f"主播{idx+1}应处于已结束状态"
                    assert recruit['broadcast_decision'] == '不招募', f"主播{idx+1}开播决策应为不招募"
                    stats['broadcast_rejected'] += 1

                # 索引12-14：正式主播
                elif idx < 15:
                    assert status == '已结束', f"主播{idx+1}应处于已结束状态"
                    assert recruit['broadcast_decision'] == '正式主播', f"主播{idx+1}应招募为正式主播"
                    stats['official_pilot'] += 1

                # 索引15-16：实习主播
                elif idx < 17:
                    assert status == '已结束', f"主播{idx+1}应处于已结束状态"
                    assert recruit['broadcast_decision'] == '实习主播', f"主播{idx+1}应招募为实习主播"
                    stats['intern_pilot'] += 1

                # 索引17-19：待面试
                else:
                    assert status == '待面试', f"主播{idx+1}应处于待面试状态"
                    stats['pending_interview'] += 1

            # 验证统计数据
            print("\n招募结果统计：")
            print(f"  待面试：{stats['pending_interview']} 个")
            print(f"  面试被拒：{stats['interview_rejected']} 个")
            print(f"  待预约试播：{stats['pending_training_schedule']} 个")
            print(f"  待试播：{stats['pending_training']} 个")
            print(f"  试播被拒：{stats['training_rejected']} 个")
            print(f"  待预约开播：{stats['pending_broadcast_schedule']} 个")
            print(f"  开播被拒：{stats['broadcast_rejected']} 个")
            print(f"  正式主播：{stats['official_pilot']} 个")
            print(f"  实习主播：{stats['intern_pilot']} 个")

            assert stats['pending_interview'] == 3, "应有3个主播停留在待面试"
            assert stats['interview_rejected'] == 2, "应有2个主播在面试阶段被拒"
            assert stats['pending_training_schedule'] == 2, "应有2个主播停留在待预约试播"
            assert stats['pending_training'] == 2, "应有2个主播停留在待试播"
            assert stats['training_rejected'] == 3, "应有3个主播在试播阶段被拒"
            assert stats['pending_broadcast_schedule'] == 1, "应有1个主播停留在待预约开播"
            assert stats['broadcast_rejected'] == 2, "应有2个主播在开播阶段被拒"
            assert stats['official_pilot'] == 3, "应有3个正式主播"
            assert stats['intern_pilot'] == 2, "应有2个实习主播"

            total_rejected = stats['interview_rejected'] + stats['training_rejected'] + stats['broadcast_rejected']
            total_in_progress = (stats['pending_interview'] + stats['pending_training_schedule'] + stats['pending_training'] +
                                 stats['pending_broadcast_schedule'])
            total_success = stats['official_pilot'] + stats['intern_pilot']

            assert total_rejected == 7, "应有7个主播被拒"
            assert total_in_progress == 8, "应有8个主播停留在中间阶段"
            assert total_success == 5, "应有5个主播完成招募"

            print("\n✅ 批量招募20个主播测试完成！")
            print(f"   总计：20个主播")
            print(f"   - 被拒绝：{total_rejected}个（面试2个 + 试播3个 + 开播2个）")
            print(f"   - 进行中：{total_in_progress}个（待面试3个 + 待预约试播2个 + 待试播2个 + 待预约开播1个）")
            print(f"   - 已完成：{total_success}个（正式主播3个 + 实习主播2个）")

        finally:
            # ========== 清理测试数据 ==========
            print("\n===== 清理测试数据 =====")

            # 清理招募记录（MongoDB会自动软删除，这里主要是验证）
            for recruit_id in created_recruits:
                try:
                    recruit_detail = admin_client.get(f'/api/recruits/{recruit_id}')
                    if recruit_detail.get('success'):
                        print(f"  招募记录 {recruit_id} 存在（保留）")
                except Exception:  # pylint: disable=broad-except
                    pass

            # 清理主播（设置为流失状态）
            for pilot_id in created_pilots:
                try:
                    # 将主播状态设置为流失（软删除）
                    admin_client.patch(f'/api/pilots/{pilot_id}/status', json={'status': '流失'})
                    print(f"  主播 {pilot_id} 已设置为流失状态")
                except Exception:  # pylint: disable=broad-except
                    pass

            print("清理完成")


@pytest.mark.integration
@pytest.mark.workflows
class TestAnnouncementConflicts:
    """通告冲突检测和处理测试"""

    def test_announcement_conflicts_and_resolution(self, admin_client):
        """
        测试通告冲突场景和解决方案
        
        场景：
        1. 创建一个通告占用某个地点
        2. 尝试在同一时段为另一主播创建通告使用同一地点（预期失败：地点冲突）
        3. 换一个地点重新创建（预期成功）
        4. 尝试为同一主播在重叠时段创建通告（预期失败：主播冲突）
        5. 调整时间后重新创建（预期成功）
        """
        print("\n========== 开始通告冲突检测和处理测试 ==========")

        from datetime import datetime, timedelta
        battle_area_factory = BattleAreaFactory()
        announcement_factory = AnnouncementFactory()

        created_announcements = []
        created_areas = []

        try:
            # 准备测试数据
            print("\n===== 准备测试数据 =====")

            # 获取两个已招募的主播
            pilots_response = admin_client.get('/api/pilots?status=已招募&rank=正式主播,实习主播')
            assert pilots_response['success'] is True

            pilots = pilots_response['data']['items'][:2]
            if len(pilots) < 2:
                print("  ⚠️ 需要至少2个已招募主播，跳过测试")
                return

            pilot_1_id = pilots[0]['id']
            pilot_2_id = pilots[1]['id']
            print(f"  主播1: {pilots[0]['nickname']} (ID: {pilot_1_id})")
            print(f"  主播2: {pilots[1]['nickname']} (ID: {pilot_2_id})")

            # 创建或获取2个测试地点
            print("\n  准备开播地点...")
            test_coords = [
                ('测试基地X', '测试场地X', '88'),
                ('测试基地Y', '测试场地Y', '99'),
            ]

            test_areas = []
            for x, y, z in test_coords:
                # 先查询
                areas_response = admin_client.get('/api/battle-areas')
                area_id = None

                if areas_response.get('success'):
                    for area in areas_response['data']['items']:
                        if area['x_coord'] == x and area['y_coord'] == y and area['z_coord'] == z:
                            area_id = area['id']
                            break

                if not area_id:
                    # 不存在则创建
                    area_data = battle_area_factory.create_specific_battle_area(x, y, z)
                    area_response = admin_client.post('/api/battle-areas', json=area_data)
                    if area_response.get('success'):
                        area_id = area_response['data']['id']
                        created_areas.append(area_id)

                if area_id:
                    test_areas.append(area_id)
                    print(f"    地点: {x}-{y}-{z} (ID: {area_id})")

            assert len(test_areas) >= 2, "需要至少2个测试地点"

            # ========== 场景1：创建第一个通告 ==========
            print("\n===== 场景1：创建第一个通告（占用地点A，时间段：明天10:00-16:00） =====")
            tomorrow = datetime.now() + timedelta(days=1)
            start_time_1 = tomorrow.replace(hour=10, minute=0, second=0, microsecond=0)

            announcement_1_data = announcement_factory.create_announcement_data(pilot_id=pilot_1_id,
                                                                                battle_area_id=test_areas[0],
                                                                                start_time_str=start_time_1.strftime('%Y-%m-%d %H:%M:%S'),
                                                                                duration_hours=6)

            ann_1_response = admin_client.post('/announcements/api/announcements', json=announcement_1_data)
            assert ann_1_response['success'] is True, f"创建第一个通告失败：{ann_1_response}"

            ann_1_id = ann_1_response['data']['id']
            created_announcements.append(ann_1_id)
            print(f"  ✅ 通告1创建成功 (ID: {ann_1_id})")
            print(f"     主播: {pilots[0]['nickname']}, 时间: {start_time_1.strftime('%Y-%m-%d %H:%M')}, 时长: 6小时")

            # ========== 场景2：地点冲突测试 ==========
            print("\n===== 场景2：测试地点冲突（主播2尝试使用同一地点同一时段） =====")

            # 尝试为主播2在完全相同的时间和地点创建通告
            announcement_2_conflict_data = announcement_factory.create_announcement_data(
                pilot_id=pilot_2_id,
                battle_area_id=test_areas[0],  # 同一地点
                start_time_str=start_time_1.strftime('%Y-%m-%d %H:%M:%S'),  # 同一时间
                duration_hours=6)

            ann_2_conflict_response = admin_client.post('/announcements/api/announcements', json=announcement_2_conflict_data)

            # 应该失败（地点冲突）
            if not ann_2_conflict_response.get('success'):
                error_code = ann_2_conflict_response.get('error', {}).get('code', '')
                print(f"  ✅ 预期的冲突检测成功：{error_code}")
                print(f"     错误信息: {ann_2_conflict_response.get('error', {}).get('message', '')}")

                # 检查是否有冲突详情
                conflicts = ann_2_conflict_response.get('meta', {}).get('conflicts', [])
                if conflicts:
                    print(f"     检测到 {len(conflicts)} 个冲突:")
                    for conflict in conflicts[:3]:  # 只显示前3个
                        print(f"       - {conflict.get('type')}: {conflict.get('pilot_name')} "
                              f"@ {conflict.get('start_time')}")
            else:
                print(f"  ❌ 错误：应该检测到地点冲突，但创建成功了")
                created_announcements.append(ann_2_conflict_response['data']['id'])

            # ========== 场景3：换地点成功创建 ==========
            print("\n===== 场景3：换地点重新创建通告（使用地点B） =====")

            announcement_2_ok_data = announcement_factory.create_announcement_data(
                pilot_id=pilot_2_id,
                battle_area_id=test_areas[1],  # 换一个地点
                start_time_str=start_time_1.strftime('%Y-%m-%d %H:%M:%S'),
                duration_hours=6)

            ann_2_ok_response = admin_client.post('/announcements/api/announcements', json=announcement_2_ok_data)

            if ann_2_ok_response.get('success'):
                ann_2_id = ann_2_ok_response['data']['id']
                created_announcements.append(ann_2_id)
                print(f"  ✅ 通告2创建成功 (ID: {ann_2_id})")
                print(f"     主播: {pilots[1]['nickname']}, 使用不同地点，成功避开冲突")
            else:
                print(f"  ❌ 错误：换地点后创建仍失败：{ann_2_ok_response}")

            # ========== 场景4：主播时段冲突测试 ==========
            print("\n===== 场景4：测试主播时段冲突（主播1在重叠时段再次安排） =====")

            # 尝试为主播1在重叠时段创建另一个通告（不同地点）
            start_time_overlap = start_time_1 + timedelta(hours=3)  # 13:00，与10:00-16:00重叠

            announcement_3_conflict_data = announcement_factory.create_announcement_data(
                pilot_id=pilot_1_id,  # 同一主播
                battle_area_id=test_areas[1],  # 不同地点
                start_time_str=start_time_overlap.strftime('%Y-%m-%d %H:%M:%S'),
                duration_hours=4)

            ann_3_conflict_response = admin_client.post('/announcements/api/announcements', json=announcement_3_conflict_data)

            # 应该失败（主播冲突）
            if not ann_3_conflict_response.get('success'):
                error_code = ann_3_conflict_response.get('error', {}).get('code', '')
                print(f"  ✅ 预期的主播冲突检测成功：{error_code}")
                print(f"     错误信息: {ann_3_conflict_response.get('error', {}).get('message', '')}")
            else:
                print(f"  ❌ 错误：应该检测到主播时段冲突，但创建成功了")
                created_announcements.append(ann_3_conflict_response['data']['id'])

            # ========== 场景5：调整时间后成功创建 ==========
            print("\n===== 场景5：调整时间后重新创建（使用不重叠的时段） =====")

            # 安排在第一个通告之后
            start_time_after = start_time_1 + timedelta(hours=7)  # 17:00，不重叠

            announcement_3_ok_data = announcement_factory.create_announcement_data(pilot_id=pilot_1_id,
                                                                                   battle_area_id=test_areas[1],
                                                                                   start_time_str=start_time_after.strftime('%Y-%m-%d %H:%M:%S'),
                                                                                   duration_hours=4)

            ann_3_ok_response = admin_client.post('/announcements/api/announcements', json=announcement_3_ok_data)

            if ann_3_ok_response.get('success'):
                ann_3_id = ann_3_ok_response['data']['id']
                created_announcements.append(ann_3_id)
                print(f"  ✅ 通告3创建成功 (ID: {ann_3_id})")
                print(f"     主播: {pilots[0]['nickname']}, 时间调整后成功避开冲突")
            else:
                print(f"  ❌ 错误：调整时间后创建仍失败：{ann_3_ok_response}")

            # ========== 统计验证 ==========
            print("\n===== 测试结果统计 =====")
            print(f"  成功创建的通告数: {len(created_announcements)}")
            print(f"  预期成功数: 3 (通告1 + 通告2换地点 + 通告3调整时间)")
            print(f"  预期冲突检测: 2 (地点冲突 + 主播时段冲突)")

            print("\n✅ 通告冲突检测和处理测试完成！")

        finally:
            # ========== 清理测试数据 ==========
            print("\n===== 清理测试数据 =====")

            # 清理通告
            for ann_id in created_announcements:
                try:
                    admin_client.delete(f'/announcements/api/announcements/{ann_id}')
                except Exception:  # pylint: disable=broad-except
                    pass
            print(f"  已删除 {len(created_announcements)} 个测试通告")

            # 清理开播地点（设置为不可用）
            for area_id in created_areas:
                try:
                    admin_client.put(f'/api/battle-areas/{area_id}', json={'availability': '不可用'})
                except Exception:  # pylint: disable=broad-except
                    pass
            print(f"  已禁用 {len(created_areas)} 个测试地点")

            print("清理完成")
