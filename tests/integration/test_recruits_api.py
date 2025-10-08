"""
招募记录 REST API 集成测试

测试招募记录的完整生命周期管理，包括创建、查询、更新、面试决策、
试播安排、试播决策、开播安排、开播决策等所有招募阶段的功能。
"""
from datetime import datetime, timedelta

import pytest

from tests.fixtures.factories import PilotFactory


@pytest.mark.integration
@pytest.mark.recruits
class TestRecruitsList:
    """测试招募记录列表相关功能"""

    def test_get_recruits_list_success(self, admin_client):
        """测试获取招募记录列表 - 成功"""
        print("\n========== 测试获取招募记录列表 ==========")

        response = admin_client.get('/api/recruits')

        assert response['success'] is True
        assert 'data' in response
        assert 'items' in response['data']
        assert 'meta' in response

        # 验证列表结构
        items = response['data']['items']
        if items:  # 如果有数据，验证数据结构
            recruit = items[0]
            assert 'id' in recruit
            assert 'pilot' in recruit
            assert 'status' in recruit
            assert 'created_at' in recruit

    def test_get_recruits_with_filters(self, admin_client):
        """测试带过滤条件的招募记录列表"""
        print("\n========== 测试招募记录过滤功能 ==========")

        # 测试按状态过滤
        response = admin_client.get('/api/recruits?status=待面试')
        assert response['success'] is True

        # 测试按招募负责人过滤
        response = admin_client.get('/api/recruits?recruiter=test_recruiter_id')
        assert response['success'] is True

        # 测试按日期过滤
        today = datetime.now().date().isoformat()
        response = admin_client.get(f'/api/recruits?date={today}')
        assert response['success'] is True

    def test_get_recruits_unauthorized(self, api_client):
        """测试未授权访问招募记录列表 - 应失败"""
        print("\n========== 测试招募记录列表权限控制 ==========")

        response = api_client.get('/api/recruits')

        assert response.get('success') is not True


@pytest.mark.integration
@pytest.mark.recruits
class TestRecruitsCreate:
    """测试招募记录创建功能"""

    def test_create_recruit_success(self, admin_client):
        """测试创建招募记录 - 成功"""
        print("\n========== 测试创建招募记录基础功能 ==========")

        # 先创建一个主播
        pilot_data = PilotFactory.create_pilot_data()
        pilot_response = admin_client.post('/api/pilots', json=pilot_data)
        assert pilot_response['success'] is True

        pilot_id = pilot_response['data']['id']

        # 获取管理员用户ID
        me_response = admin_client.get('/api/auth/me')
        assert me_response['success'] is True
        admin_user_id = me_response['data']['user']['id']

        # 创建招募记录数据
        appointment_time = datetime.now() + timedelta(days=1)

        recruit_data = {
            'pilot_id': pilot_id,
            'recruiter_id': admin_user_id,
            'appointment_time': appointment_time.strftime('%Y-%m-%d %H:%M:%S'),
            'channel': 'BOSS',
            'introduction_fee': 0,
            'remarks': '测试招募记录'
        }

        # 创建记录
        response = admin_client.post('/api/recruits', json=recruit_data)

        assert response['success'] is True
        assert 'data' in response

        recruit = response['data']
        assert recruit['pilot']['id'] == pilot_id
        assert recruit['status'] == '待面试'
        assert recruit['channel'] == 'BOSS'

        recruit_id = recruit['id']

        # 清理：删除创建的记录和主播
        admin_client.delete(f'/api/recruits/{recruit_id}')
        admin_client.delete(f'/api/pilots/{pilot_id}')

    def test_create_recruit_missing_required_fields(self, admin_client):
        """测试创建招募记录缺少必需字段 - 应失败"""
        print("\n========== 测试招募记录字段验证 ==========")

        # 缺少必需字段
        incomplete_data = {
            'pilot_id': 'test_pilot_id',
            # 缺少 recruiter_id, appointment_time
        }

        response = admin_client.post('/api/recruits', json=incomplete_data)

        assert response['success'] is False
        assert 'error' in response


@pytest.mark.integration
@pytest.mark.recruits
class TestRecruitsDetail:
    """测试招募记录详情功能"""

    def test_get_recruit_detail_success(self, admin_client):
        """测试获取招募记录详情 - 成功"""
        print("\n========== 测试获取招募记录详情 ==========")

        # 先创建主播和招募记录
        pilot_data = PilotFactory.create_pilot_data()
        pilot_response = admin_client.post('/api/pilots', json=pilot_data)
        assert pilot_response['success'] is True

        pilot_id = pilot_response['data']['id']

        me_response = admin_client.get('/api/auth/me')
        admin_user_id = me_response['data']['user']['id']

        appointment_time = datetime.now() + timedelta(days=1)
        recruit_data = {
            'pilot_id': pilot_id,
            'recruiter_id': admin_user_id,
            'appointment_time': appointment_time.strftime('%Y-%m-%d %H:%M:%S'),
            'channel': 'BOSS',
            'introduction_fee': 0
        }

        create_response = admin_client.post('/api/recruits', json=recruit_data)
        assert create_response['success'] is True

        recruit_id = create_response['data']['id']

        try:
            # 获取详情
            detail_response = admin_client.get(f'/api/recruits/{recruit_id}')

            assert detail_response['success'] is True
            assert 'data' in detail_response

            recruit = detail_response['data']
            assert recruit['id'] == recruit_id
            assert recruit['pilot']['id'] == pilot_id
            assert recruit['status'] == '待面试'
            assert 'created_at' in recruit

        finally:
            # 清理
            admin_client.delete(f'/api/recruits/{recruit_id}')
            admin_client.delete(f'/api/pilots/{pilot_id}')

    def test_get_recruit_detail_not_found(self, admin_client):
        """测试获取不存在的招募记录详情 - 应失败"""
        print("\n========== 测试获取不存在招募记录 ==========")

        fake_id = 'ffffffffffffffffffffffff'
        response = admin_client.get(f'/api/recruits/{fake_id}')

        assert response['success'] is False


@pytest.mark.integration
@pytest.mark.recruits
class TestRecruitsInterviewDecision:
    """测试招募面试决策功能"""

    def test_interview_decision_success(self, admin_client):
        """测试面试决策 - 成功"""
        print("\n========== 测试面试决策功能 ==========")

        # 创建测试数据
        pilot_data = PilotFactory.create_pilot_data()
        pilot_response = admin_client.post('/api/pilots', json=pilot_data)
        pilot_id = pilot_response['data']['id']

        me_response = admin_client.get('/api/auth/me')
        admin_user_id = me_response['data']['user']['id']

        appointment_time = datetime.now() + timedelta(days=1)
        recruit_data = {
            'pilot_id': pilot_id,
            'recruiter_id': admin_user_id,
            'appointment_time': appointment_time.strftime('%Y-%m-%d %H:%M:%S'),
            'channel': 'BOSS',
            'introduction_fee': 0
        }

        create_response = admin_client.post('/api/recruits', json=recruit_data)
        recruit_id = create_response['data']['id']

        try:
            # 面试通过
            decision_data = {'interview_decision': '预约试播', 'real_name': '测试姓名', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试表现良好'}

            decision_response = admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=decision_data)

            assert decision_response['success'] is True

            # 验证状态更新
            detail_response = admin_client.get(f'/api/recruits/{recruit_id}')
            recruit = detail_response['data']
            assert recruit['status'] == '待预约试播'
            assert recruit['interview_decision'] == '预约试播'

        finally:
            # 清理
            admin_client.delete(f'/api/recruits/{recruit_id}')
            admin_client.delete(f'/api/pilots/{pilot_id}')

    def test_interview_decision_reject(self, admin_client):
        """测试面试决策 - 拒绝"""
        print("\n========== 测试面试拒绝功能 ==========")

        # 创建测试数据
        pilot_data = PilotFactory.create_pilot_data()
        pilot_response = admin_client.post('/api/pilots', json=pilot_data)
        pilot_id = pilot_response['data']['id']

        me_response = admin_client.get('/api/auth/me')
        admin_user_id = me_response['data']['user']['id']

        appointment_time = datetime.now() + timedelta(days=1)
        recruit_data = {
            'pilot_id': pilot_id,
            'recruiter_id': admin_user_id,
            'appointment_time': appointment_time.strftime('%Y-%m-%d %H:%M:%S'),
            'channel': 'BOSS',
            'introduction_fee': 0
        }

        create_response = admin_client.post('/api/recruits', json=recruit_data)
        recruit_id = create_response['data']['id']

        try:
            # 面试拒绝
            decision_data = {'interview_decision': '不招募', 'real_name': '测试姓名', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试表现不佳'}

            decision_response = admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=decision_data)

            assert decision_response['success'] is True

            # 验证状态更新
            detail_response = admin_client.get(f'/api/recruits/{recruit_id}')
            recruit = detail_response['data']
            assert recruit['status'] == '已结束'
            assert recruit['interview_decision'] == '不招募'

        finally:
            # 清理
            admin_client.delete(f'/api/recruits/{recruit_id}')
            admin_client.delete(f'/api/pilots/{pilot_id}')


@pytest.mark.integration
@pytest.mark.recruits
class TestRecruitsTrainingSchedule:
    """测试招募试播安排功能"""

    def test_schedule_training_success(self, admin_client):
        """测试预约试播 - 成功"""
        print("\n========== 测试预约试播功能 ==========")

        # 创建测试数据
        pilot_data = PilotFactory.create_pilot_data()
        pilot_response = admin_client.post('/api/pilots', json=pilot_data)
        pilot_id = pilot_response['data']['id']

        me_response = admin_client.get('/api/auth/me')
        admin_user_id = me_response['data']['user']['id']

        appointment_time = datetime.now() + timedelta(days=1)
        recruit_data = {
            'pilot_id': pilot_id,
            'recruiter_id': admin_user_id,
            'appointment_time': appointment_time.strftime('%Y-%m-%d %H:%M:%S'),
            'channel': 'BOSS',
            'introduction_fee': 0
        }

        create_response = admin_client.post('/api/recruits', json=recruit_data)
        recruit_id = create_response['data']['id']

        try:
            # 面试通过
            interview_data = {'interview_decision': '预约试播', 'real_name': '测试姓名', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试通过'}
            admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=interview_data)

            # 预约试播
            training_time = datetime.now() + timedelta(days=2)
            schedule_data = {
                'scheduled_training_time': training_time.strftime('%Y-%m-%d %H:%M:%S'),
                'work_mode': '线下',
                'introduction_fee': 0,
                'remarks': '预约试播时间'
            }

            schedule_response = admin_client.post(f'/api/recruits/{recruit_id}/schedule-training', json=schedule_data)

            assert schedule_response['success'] is True

            # 验证状态更新
            detail_response = admin_client.get(f'/api/recruits/{recruit_id}')
            recruit = detail_response['data']
            assert recruit['status'] == '待试播'

        finally:
            # 清理
            admin_client.delete(f'/api/recruits/{recruit_id}')
            admin_client.delete(f'/api/pilots/{pilot_id}')


@pytest.mark.integration
@pytest.mark.recruits
class TestRecruitsWorkflow:
    """招募记录工作流测试"""

    def test_complete_recruitment_workflow_success(self, admin_client):
        """
        测试完整的招募成功流程

        流程：创建招募 -> 面试通过 -> 预约试播 -> 试播通过 -> 预约开播 -> 招募成功
        """
        print("\n========== 开始完整招募成功流程测试 ==========")

        # 1. 创建主播
        print("\n===== 步骤1：创建主播 =====")
        pilot_data = PilotFactory.create_pilot_data()
        pilot_response = admin_client.post('/api/pilots', json=pilot_data)
        assert pilot_response['success'] is True

        pilot_id = pilot_response['data']['id']
        pilot_nickname = pilot_response['data']['nickname']
        print(f"  创建主播: {pilot_nickname} (ID: {pilot_id})")

        # 2. 创建招募记录
        print("\n===== 步骤2：创建招募记录 =====")
        me_response = admin_client.get('/api/auth/me')
        admin_user_id = me_response['data']['user']['id']

        appointment_time = datetime.now() + timedelta(days=1)
        recruit_data = {
            'pilot_id': pilot_id,
            'recruiter_id': admin_user_id,
            'appointment_time': appointment_time.strftime('%Y-%m-%d %H:%M:%S'),
            'channel': 'BOSS',
            'introduction_fee': 0,
            'remarks': '完整流程测试'
        }

        recruit_response = admin_client.post('/api/recruits', json=recruit_data)
        assert recruit_response['success'] is True

        recruit_id = recruit_response['data']['id']
        print(f"  创建招募记录: {recruit_id}")

        try:
            # 3. 面试通过
            print("\n===== 步骤3：面试通过 =====")
            interview_data = {'interview_decision': '预约试播', 'real_name': '测试真实姓名', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试表现优秀'}

            interview_response = admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=interview_data)
            assert interview_response['success'] is True
            print("  面试通过，进入试播阶段")

            # 4. 预约试播
            print("\n===== 步骤4：预约试播 =====")
            training_time = datetime.now() + timedelta(days=2)
            training_schedule_data = {
                'scheduled_training_time': training_time.strftime('%Y-%m-%d %H:%M:%S'),
                'work_mode': '线下',
                'introduction_fee': 0,
                'remarks': '预约试播时间'
            }

            training_schedule_response = admin_client.post(f'/api/recruits/{recruit_id}/schedule-training', json=training_schedule_data)
            assert training_schedule_response['success'] is True
            print("  试播预约成功")

            # 5. 试播通过
            print("\n===== 步骤5：试播通过 =====")
            training_decision_data = {'training_decision': '预约开播', 'introduction_fee': 0, 'remarks': '试播表现良好'}

            training_response = admin_client.post(f'/api/recruits/{recruit_id}/training-decision', json=training_decision_data)
            assert training_response['success'] is True
            print("  试播通过，进入开播阶段")

            # 6. 预约开播
            print("\n===== 步骤6：预约开播 =====")
            from utils.timezone_helper import get_current_utc_time, utc_to_local
            now_utc = get_current_utc_time()
            now_local = utc_to_local(now_utc)
            broadcast_time = now_local.replace(hour=16, minute=0, second=0, microsecond=0) + timedelta(days=3)
            broadcast_schedule_data = {'scheduled_broadcast_time': broadcast_time.strftime('%Y-%m-%d %H:%M:%S'), 'introduction_fee': 0, 'remarks': '预约开播时间'}

            broadcast_schedule_response = admin_client.post(f'/api/recruits/{recruit_id}/schedule-broadcast', json=broadcast_schedule_data)
            assert broadcast_schedule_response['success'] is True
            print("  开播预约成功")

            # 7. 招募成功
            print("\n===== 步骤7：招募成功 =====")
            broadcast_decision_data = {
                'broadcast_decision': '正式主播',
                'owner_id': admin_user_id,
                'platform': '快手',
                'introduction_fee': 0,
                'remarks': '招募成功，成为正式主播'
            }

            broadcast_response = admin_client.post(f'/api/recruits/{recruit_id}/broadcast-decision', json=broadcast_decision_data)
            assert broadcast_response['success'] is True
            print("  招募成功！")

            # 8. 验证最终结果
            print("\n===== 步骤8：验证最终结果 =====")
            detail_response = admin_client.get(f'/api/recruits/{recruit_id}')
            final_recruit = detail_response['data']

            assert final_recruit['status'] == '已结束'
            assert final_recruit['broadcast_decision'] == '正式主播'
            print(f"  最终状态: {final_recruit['status']}")
            print(f"  招募结果: {final_recruit['broadcast_decision']}")

            # 验证主播状态更新
            pilot_detail_response = admin_client.get(f'/api/pilots/{pilot_id}')
            pilot_detail = pilot_detail_response['data']
            assert pilot_detail['status'] == '已招募'
            assert pilot_detail['owner']['id'] == admin_user_id
            print(f"  主播状态: {pilot_detail['status']}")
            print(f"  归属运营: {pilot_detail['owner']['nickname']}")

            print("\n✅ 完整招募流程测试成功！")

        finally:
            # 清理
            print("\n===== 清理测试数据 =====")
            admin_client.delete(f'/api/recruits/{recruit_id}')
            admin_client.delete(f'/api/pilots/{pilot_id}')
            print("  清理完成")

    def test_daily_recruitment_report_validation(self, admin_client):
        """
        生成招募日报并验证数据结构的正确性

        测试目标：
        1. 验证招募日报API能够正常响应
        2. 验证日报数据结构的完整性
        3. 验证统计逻辑的合理性（不追求精确数据匹配）
        4. 验证时间趋势数据和平均值计算的正确性
        """
        print("\n========== 开始招募日报功能验证测试 ==========")

        # 步骤1：生成今日的招募日报
        print("\n===== 步骤1：生成招募日报 =====")
        from utils.timezone_helper import get_current_utc_time, utc_to_local
        now_utc = get_current_utc_time()
        now_local = utc_to_local(now_utc)
        today = now_local.strftime('%Y-%m-%d')
        print(f"  当前本地时间: {now_local.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"  查询日期: {today}")

        report_response = admin_client.get(f'/api/recruit-reports/daily?date={today}')
        assert report_response['success'], f"无法生成招募日报: {report_response.get('error', {}).get('message', '未知错误')}"
        report_data = report_response['data']
        print(f"  招募日报生成成功，日期: {today}")

        # 步骤2：验证数据结构完整性
        print("\n===== 步骤2：验证数据结构完整性 =====")
        required_fields = ['date', 'summary', 'averages', 'pagination']
        for field in required_fields:
            assert field in report_data, f"日报缺少必需字段: {field}"
        print("  ✅ 数据结构验证通过")

        # 步骤3：验证报告日期正确性
        print("\n===== 步骤3：验证报告日期正确性 =====")
        assert report_data['date'] == today, f"报告日期错误: 期望{today}, 实际{report_data['date']}"
        print(f"  ✅ 报告日期正确: {report_data['date']}")

        # 步骤4：验证汇总数据结构
        print("\n===== 步骤4：验证汇总数据结构 =====")
        summary = report_data['summary']
        required_summary_sections = ['report_day', 'last_7_days', 'last_14_days']
        for section in required_summary_sections:
            assert section in summary, f"汇总数据缺少{section}部分"
        print("  ✅ 汇总数据结构验证通过")

        # 步骤5：验证当日数据字段
        print("\n===== 步骤5：验证当日数据字段 =====")
        today_data = summary.get('report_day', {})
        required_today_fields = ['appointments', 'interviews', 'trials', 'new_recruits']
        for field in required_today_fields:
            assert field in today_data, f"当日数据缺少{field}字段"
            assert isinstance(today_data[field], int), f"{field}应该是整数类型"
            assert today_data[field] >= 0, f"{field}应该非负数"

        print(f"  当日数据:")
        print(f"    预约人数: {today_data.get('appointments', 0)}")
        print(f"    面试人数: {today_data.get('interviews', 0)}")
        print(f"    试播人数: {today_data.get('trials', 0)}")
        print(f"    招募成功: {today_data.get('new_recruits', 0)}")
        print("  ✅ 当日数据字段验证通过")

        # 步骤6：验证时间趋势数据的逻辑性
        print("\n===== 步骤6：验证时间趋势数据逻辑性 =====")
        last_7_days = summary.get('last_7_days', {})
        last_14_days = summary.get('last_14_days', {})

        # 验证时间逻辑：14天数据应该 >= 7天数据
        for metric in ['appointments', 'interviews', 'trials', 'new_recruits']:
            val_7 = last_7_days.get(metric, 0)
            val_14 = last_14_days.get(metric, 0)
            assert val_14 >= val_7, f"{metric}统计错误: 14天数据({val_14})应该 >= 7天数据({val_7})"
            assert val_7 >= 0, f"{metric}应该非负数"
            assert val_14 >= 0, f"{metric}应该非负数"

        print("  ✅ 时间趋势数据逻辑验证通过")

        # 步骤7：验证平均值计算的正确性
        print("\n===== 步骤7：验证平均值计算正确性 =====")
        averages = report_data['averages']
        last_7_days_avg = averages.get('last_7_days', {})
        last_14_days_avg = averages.get('last_14_days', {})

        # 验证7天平均值
        for metric in ['appointments', 'interviews', 'trials', 'new_recruits']:
            total_7 = last_7_days.get(metric, 0)
            avg_7 = last_7_days_avg.get(metric, 0)
            expected_avg_7 = round(total_7 / 7, 1)
            assert abs(avg_7 - expected_avg_7) < 0.01, f"{metric}的7天平均值计算错误: 期望{expected_avg_7}, 实际{avg_7}"

        # 验证14天平均值
        for metric in ['appointments', 'interviews', 'trials', 'new_recruits']:
            total_14 = last_14_days.get(metric, 0)
            avg_14 = last_14_days_avg.get(metric, 0)
            expected_avg_14 = round(total_14 / 14, 1)
            assert abs(avg_14 - expected_avg_14) < 0.01, f"{metric}的14天平均值计算错误: 期望{expected_avg_14}, 实际{avg_14}"

        print("  ✅ 平均值计算验证通过")

        # 步骤8：验证分页信息
        print("\n===== 步骤8：验证分页信息 =====")
        pagination = report_data['pagination']
        required_pagination_fields = ['date', 'prev_date', 'next_date']
        for field in required_pagination_fields:
            assert field in pagination, f"分页信息缺少{field}字段"

        # 验证日期格式
        assert pagination['date'] == today, f"分页日期错误: 期望{today}, 实际{pagination['date']}"
        assert len(pagination['prev_date']) == 10, f"前一天的日期格式错误: {pagination['prev_date']}"
        assert len(pagination['next_date']) == 10, f"后一天的日期格式错误: {pagination['next_date']}"

        print(f"  当前日期: {pagination.get('date', 'N/A')}")
        print(f"  前一天: {pagination.get('prev_date', 'N/A')}")
        print(f"  后一天: {pagination.get('next_date', 'N/A')}")
        print("  ✅ 分页信息验证通过")

        # 步骤9：验证转化率的合理性（如果有数据的话）
        print("\n===== 步骤9：验证转化率合理性 =====")
        appointments = today_data.get('appointments', 0)
        interviews = today_data.get('interviews', 0)
        trials = today_data.get('trials', 0)
        new_recruits = today_data.get('new_recruits', 0)

        if appointments > 0:
            # 验证各项数值的合理性
            assert interviews <= appointments, f"面试人数({interviews})不应超过预约人数({appointments})"
            assert trials <= appointments, f"试播人数({trials})不应超过预约人数({appointments})"
            assert new_recruits <= appointments, f"招募成功数({new_recruits})不应超过预约人数({appointments})"
            assert new_recruits <= trials, f"招募成功数({new_recruits})不应超过试播人数({trials})"

            print(f"  面试转化率: {(interviews/appointments*100):.1f}% ({interviews}/{appointments})")
            if interviews > 0:
                print(f"  试播转化率: {(trials/interviews*100):.1f}% ({trials}/{interviews})")
            if trials > 0:
                print(f"  最终成功率: {(new_recruits/trials*100):.1f}% ({new_recruits}/{trials})")
        else:
            print("  当日无预约数据，跳过转化率验证")

        print("  ✅ 转化率合理性验证通过")

        print("\n✅ 招募日报功能验证完成！")
        print("✅ 所有功能验证项均已通过！")

    def _create_sample_recruitment_data(self, admin_client):
        """创建示例招募数据"""
        """为日报测试创建不同状态的招募数据"""
        from tests.fixtures.factories import PilotFactory

        print("  创建示例招募数据...")

        # 获取管理员用户ID
        me_response = admin_client.get('/api/auth/me')
        admin_user_id = me_response['data']['user']['id']
        admin_nickname = me_response['data']['user']['nickname']

        created_data = []

        # 创建不同状态的招募记录
        scenarios = [
            {
                'status': '待面试',
                'decision': None,
                'count': 2
            },
            {
                'status': '面试拒绝',
                'decision': '不招募',
                'count': 1
            },
            {
                'status': '试播拒绝',
                'decision': '不招募',
                'count': 1
            },
            {
                'status': '招募成功',
                'decision': '正式主播',
                'count': 2
            },
        ]

        for scenario in scenarios:
            for i in range(scenario['count']):
                # 创建主播
                pilot_data = PilotFactory.create_pilot_data()
                pilot_response = admin_client.post('/api/pilots', json=pilot_data)
                pilot_id = pilot_response['data']['id']

                # 创建招募记录 - 使用当前时间，确保created_at在查询范围内
                from utils.timezone_helper import get_current_utc_time, utc_to_local
                now_utc = get_current_utc_time()
                now_local = utc_to_local(now_utc)
                appointment_time = now_local.replace(hour=now_local.hour, minute=now_local.minute, second=0, microsecond=0)
                recruit_data = {
                    'pilot_id': pilot_id,
                    'recruiter_id': admin_user_id,
                    'appointment_time': appointment_time.strftime('%Y-%m-%d %H:%M:%S'),
                    'channel': 'BOSS',
                    'introduction_fee': 0,
                    'remarks': f'日报测试数据 {scenario["status"]} {i+1}'
                }

                recruit_response = admin_client.post('/api/recruits', json=recruit_data)
                recruit_id = recruit_response['data']['id']

                created_data.append({'recruit_id': recruit_id, 'pilot_id': pilot_id, 'scenario': scenario['status']})

                # 根据场景推进招募流程
                if scenario['status'] == '面试拒绝':
                    # 面试拒绝
                    decision_data = {
                        'interview_decision': scenario['decision'],
                        'real_name': f'测试姓名{i+1}',
                        'birth_year': 1995,
                        'introduction_fee': 0,
                        'remarks': '面试测试拒绝'
                    }
                    admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=decision_data)

                elif scenario['status'] == '试播拒绝':
                    # 面试通过 -> 试播拒绝
                    interview_data = {'interview_decision': '预约试播', 'real_name': f'测试姓名{i+1}', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试测试通过'}
                    admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=interview_data)

                    training_time = now_local.replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=1, hours=i)
                    schedule_data = {
                        'scheduled_training_time': training_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'work_mode': '线下',
                        'introduction_fee': 0,
                        'remarks': '试播测试预约'
                    }
                    admin_client.post(f'/api/recruits/{recruit_id}/schedule-training', json=schedule_data)

                    training_decision_data = {'training_decision': scenario['decision'], 'introduction_fee': 0, 'remarks': '试播测试拒绝'}
                    admin_client.post(f'/api/recruits/{recruit_id}/training-decision', json=training_decision_data)

                elif scenario['status'] == '招募成功':
                    # 完整招募流程
                    interview_data = {'interview_decision': '预约试播', 'real_name': f'测试姓名{i+1}', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试测试通过'}
                    admin_client.post(f'/api/recruits/{recruit_id}/interview-decision', json=interview_data)

                    training_time = now_local.replace(hour=14, minute=0, second=0, microsecond=0) + timedelta(days=1, hours=i)
                    schedule_data = {
                        'scheduled_training_time': training_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'work_mode': '线下',
                        'introduction_fee': 0,
                        'remarks': '试播测试预约'
                    }
                    admin_client.post(f'/api/recruits/{recruit_id}/schedule-training', json=schedule_data)

                    training_decision_data = {'training_decision': '预约开播', 'introduction_fee': 0, 'remarks': '试播测试通过'}
                    admin_client.post(f'/api/recruits/{recruit_id}/training-decision', json=training_decision_data)

                    broadcast_time = now_local.replace(hour=16, minute=0, second=0, microsecond=0) + timedelta(days=2, hours=i)
                    broadcast_schedule_data = {
                        'scheduled_broadcast_time': broadcast_time.strftime('%Y-%m-%d %H:%M:%S'),
                        'introduction_fee': 0,
                        'remarks': '开播测试预约'
                    }
                    admin_client.post(f'/api/recruits/{recruit_id}/schedule-broadcast', json=broadcast_schedule_data)

                    broadcast_decision_data = {
                        'broadcast_decision': scenario['decision'],
                        'owner_id': admin_user_id,
                        'platform': '快手',
                        'introduction_fee': 0,
                        'remarks': '招募测试成功'
                    }
                    admin_client.post(f'/api/recruits/{recruit_id}/broadcast-decision', json=broadcast_decision_data)

        print(f"  创建了 {len(created_data)} 条招募记录")
        return created_data


# 数据工厂扩展
class RecruitFactory:
    """招募记录数据工厂"""

    @staticmethod
    def create_recruit_data(pilot_id: str, recruiter_id: str, **kwargs) -> dict:
        """生成招募记录数据"""
        from datetime import datetime, timedelta

        data = {
            'pilot_id': pilot_id,
            'recruiter_id': recruiter_id,
            'appointment_time': (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d %H:%M:%S'),
            'channel': 'BOSS',
            'introduction_fee': 0,
            'remarks': '测试招募记录'
        }

        data.update(kwargs)
        return data

    @staticmethod
    def create_interview_decision_data(**kwargs) -> dict:
        """生成面试决策数据"""
        data = {'interview_decision': '预约试播', 'real_name': '测试姓名', 'birth_year': 1995, 'introduction_fee': 0, 'remarks': '面试通过'}

        data.update(kwargs)
        return data

    @staticmethod
    def create_training_schedule_data(**kwargs) -> dict:
        """生成试播预约数据"""
        from datetime import datetime, timedelta

        data = {
            'scheduled_training_time': (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d %H:%M:%S'),
            'work_mode': '线下',
            'introduction_fee': 0,
            'remarks': '预约试播'
        }

        data.update(kwargs)
        return data

    @staticmethod
    def create_training_decision_data(**kwargs) -> dict:
        """生成试播决策数据"""
        data = {'training_decision': '预约开播', 'introduction_fee': 0, 'remarks': '试播通过'}

        data.update(kwargs)
        return data

    @staticmethod
    def create_broadcast_decision_data(**kwargs) -> dict:
        """生成开播决策数据"""
        data = {'broadcast_decision': '正式主播', 'platform': '快手', 'introduction_fee': 0, 'remarks': '招募成功'}

        data.update(kwargs)
        return data
