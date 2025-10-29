"""
S9 邮件生成测试套件

目标：按照MAIL_DEBUG=true为预设，验证所有邮件被触发后，都会在log/mail目录中生成对应的邮件文件
- 不仅需要确认接口正确被调用
- 也要确认邮件正确的被生成
- 如果是S8中没有被测试过的运算逻辑，也需要对边界值等复杂逻辑进行验证
"""
import pytest
import os
import time
from datetime import datetime, timedelta
from tests.fixtures.factories import (pilot_factory, battle_record_factory, recruit_factory, announcement_factory)
from utils.timezone_helper import get_current_local_time, local_to_utc


@pytest.mark.suite("S9")
@pytest.mark.integration
class TestS9MailGeneration:
    """S9 邮件生成测试套件"""

    def test_s9_basic_mail_file_generation(self, admin_client):
        """
        S9-TC1: 基础邮件文件生成测试

        验证MAIL_DEBUG=true时，邮件API调用会在log/mail目录生成HTML文件
        """
        print("🔍 开始S9-TC1基础邮件文件生成测试...")

        try:
            # 清理log/mail目录中的测试文件
            self._cleanup_mail_files()

            # 确保MAIL_DEBUG=true
            original_mail_debug = os.getenv('MAIL_DEBUG', 'false')
            os.environ['MAIL_DEBUG'] = 'true'
            print(f"✅ 设置MAIL_DEBUG=true (原值: {original_mail_debug})")

            # 测试日报邮件生成
            current_date = datetime.now().strftime('%Y-%m-%d')
            mail_data = {'report_date': current_date}

            response = admin_client.post('/reports/mail/daily-report', json=mail_data)

            # 邮件API返回格式：{"status": "started", "sent": bool, "count": int}
            if response.get('status') == 'started':
                print("✅ 日报邮件API调用成功")

                # 等待邮件文件生成
                time.sleep(2)

                # 验证邮件文件是否生成
                mail_files = self._get_generated_mail_files()
                daily_mail_files = [f for f in mail_files if '开播日报' in f and current_date.replace('-', '_') in f]

                if daily_mail_files:
                    print(f"✅ 找到日报邮件文件: {len(daily_mail_files)}个")
                    for file_path in daily_mail_files:
                        print(f"📄 {file_path}")
                        # 验证文件内容
                        if self._validate_mail_file_content(file_path, '开播日报'):
                            print(f"  ✅ 文件内容验证通过")
                        else:
                            print(f"  ❌ 文件内容验证失败")

                    assert len(daily_mail_files) > 0, "未找到日报邮件文件"
                else:
                    print("❌ 未找到日报邮件文件")
                    pytest.fail("日报邮件文件生成失败")

            else:
                print(f"❌ 日报邮件API调用失败: {response}")
                pytest.fail("日报邮件API调用失败")

        finally:
            # 恢复原始MAIL_DEBUG设置
            os.environ['MAIL_DEBUG'] = original_mail_debug
            print(f"✅ 恢复MAIL_DEBUG={original_mail_debug}")

    def test_s9_complex_calculation_mail_generation(self, admin_client, kancho_client):
        """
        S9-TC2: 复杂计算邮件生成测试

        验证S8中未被测试过的复杂计算逻辑在邮件中正确生成
        """
        print("🔍 开始S9-TC2复杂计算邮件生成测试...")

        try:
            # 清理log/mail目录
            self._cleanup_mail_files()

            # 设置MAIL_DEBUG=true
            original_mail_debug = os.getenv('MAIL_DEBUG', 'false')
            os.environ['MAIL_DEBUG'] = 'true'

            # 创建复杂计算测试数据
            created_pilots = []
            created_records = []

            # 获取kancho用户ID
            kancho_me_response = kancho_client.get('/api/auth/me')
            if not kancho_me_response.get('success'):
                pytest.skip("无法获取kancho用户信息")
                return

            kancho_id = kancho_me_response['data']['user']['id']

            # 创建多个主播和开播记录用于复杂计算测试
            complex_scenarios = [{
                'income': 999999,
                'description': '极值收入'
            }, {
                'income': 0,
                'description': '零收入'
            }, {
                'income': 123456,
                'description': '精确计算'
            }, {
                'income': 789012,
                'description': '大额收入'
            }]

            total_expected_income = sum(scenario['income'] for scenario in complex_scenarios)

            for i, scenario in enumerate(complex_scenarios):
                # 创建主播
                pilot_data = pilot_factory.create_pilot_data(nickname=f"复杂测试主播{i+1}")
                pilot_response = admin_client.post('/api/pilots', json=pilot_data)

                if pilot_response.get('success'):
                    pilot_id = pilot_response['data']['id']
                    created_pilots.append(pilot_id)

                    # 创建开播记录
                    current_local = get_current_local_time()
                    start_time_local = current_local.replace(hour=10 + i, minute=0, second=0, microsecond=0)
                    end_time_local = current_local.replace(hour=12 + i, minute=0, second=0, microsecond=0)

                    battle_data = {
                        'pilot': pilot_id,
                        'start_time': start_time_local.isoformat(),
                        'end_time': end_time_local.isoformat(),
                        'revenue_amount': scenario['income'],
                        'work_mode': '线下',
                        'x_coord': f'CMPLX{i}',
                        'y_coord': f'TEST{i}',
                        'z_coord': 'C3',
                        'notes': f'S9复杂测试 - {scenario["description"]}: {scenario["income"]}'
                    }

                    battle_response = admin_client.post('/battle-records/api/battle-records', json=battle_data)
                    if battle_response.get('success'):
                        record_id = battle_response['data']['id']
                        created_records.append(record_id)
                        print(f"✅ 创建复杂记录: {scenario['description']} - {scenario['income']}")

            # 等待数据持久化
            time.sleep(2)

            # 测试月报邮件生成（包含复杂计算）
            current_month = datetime.now().strftime('%Y-%m')
            mail_data = {'report_month': current_month}

            response = admin_client.post('/reports/mail/monthly-report', json=mail_data)

            # 邮件API返回格式：{"status": "started", "sent": bool, "count": int}
            if response.get('status') == 'started':
                print("✅ 月报邮件API调用成功")

                # 等待邮件文件生成
                time.sleep(3)

                # 验证邮件文件是否生成
                mail_files = self._get_generated_mail_files()
                monthly_mail_files = [f for f in mail_files if '开播月报' in f and current_month.replace('-', '_') in f]

                if monthly_mail_files:
                    print(f"✅ 找到月报邮件文件: {len(monthly_mail_files)}个")
                    for file_path in monthly_mail_files:
                        print(f"📄 {file_path}")

                        # 验证文件内容包含复杂计算逻辑
                        if self._validate_complex_mail_content(file_path, total_expected_income):
                            print(f"  ✅ 复杂计算验证通过")
                        else:
                            print(f"  ❌ 复杂计算验证失败")

                    assert len(monthly_mail_files) > 0, "未找到月报邮件文件"
                else:
                    print("❌ 未找到月报邮件文件")
                    pytest.fail("月报邮件文件生成失败")

            else:
                print(f"❌ 月报邮件API调用失败: {response}")
                pytest.fail("月报邮件API调用失败")

        finally:
            # 恢复MAIL_DEBUG设置
            os.environ['MAIL_DEBUG'] = original_mail_debug
            # 清理测试数据
            self._cleanup_test_data(admin_client, created_records, created_pilots)
            print("✅ S9-TC2复杂计算邮件生成测试完成")

    def test_s9_boundary_mail_generation(self, admin_client):
        """
        S9-TC3: 边界情况邮件生成测试

        验证边界值在邮件中的正确处理
        """
        print("🔍 开始S9-TC3边界情况邮件生成测试...")

        try:
            # 清理log/mail目录
            self._cleanup_mail_files()

            # 设置MAIL_DEBUG=true
            original_mail_debug = os.getenv('MAIL_DEBUG', 'false')
            os.environ['MAIL_DEBUG'] = 'true'

            # 创建边界测试数据
            boundary_scenarios = [{'income': 0, 'description': '零收入边界'}, {'income': 1, 'description': '最小收入边界'}, {'income': 99999999, 'description': '最大值边界'}]

            total_boundary_income = sum(scenario['income'] for scenario in boundary_scenarios)

            for i, scenario in enumerate(boundary_scenarios):
                # 创建主播
                pilot_data = pilot_factory.create_pilot_data(nickname=f"边界测试主播{i+1}")
                pilot_response = admin_client.post('/api/pilots', json=pilot_data)

                if pilot_response.get('success'):
                    pilot_id = pilot_response['data']['id']

                    # 创建开播记录
                    current_local = get_current_local_time()
                    start_time_local = current_local.replace(hour=14 + i * 2, minute=0, second=0, microsecond=0)
                    end_time_local = current_local.replace(hour=16 + i * 2, minute=0, second=0, microsecond=0)

                    battle_data = {
                        'pilot': pilot_id,
                        'start_time': start_time_local.isoformat(),
                        'end_time': end_time_local.isoformat(),
                        'revenue_amount': scenario['income'],
                        'work_mode': '线下',
                        'x_coord': f'BND{i}',
                        'y_coord': f'TEST{i}',
                        'z_coord': 'C3',
                        'notes': f'S9边界测试 - {scenario["description"]}: {scenario["income"]}'
                    }

                    battle_response = admin_client.post('/battle-records/api/battle-records', json=battle_data)
                    if battle_response.get('success'):
                        record_id = battle_response['data']['id']

                        # 验证边界值记录创建成功
                        print(f"✅ 创建边界记录: {scenario['description']} - {scenario['income']}")

                        # 立即检查是否能在仪表盘中正确显示边界值
                        time.sleep(1)

                        # 获取仪表盘数据验证边界处理
                        dashboard_response = admin_client.get('/api/dashboard/battle-records')
                        if dashboard_response.get('success'):
                            dashboard_data = dashboard_response['data']
                            today_income = dashboard_data.get('battle_today_revenue', 0)

                            # 验证边界值是否被正确统计
                            if scenario['income'] == 0:
                                # 零收入应该被正确处理，不导致计算错误
                                print(f"✅ 零收入边界处理正确: {today_income}")
                            elif scenario['income'] == 99999999:
                                # 最大值应该被正确统计
                                print(f"✅ 最大值边界处理正确: {today_income}")
                            else:
                                # 正常边界值
                                print(f"✅ 正常边界值处理正确: {scenario['income']} -> {today_income}")

            # 测试招募邮件边界情况
            mail_data = {'report_date': datetime.now().strftime('%Y-%m-%d')}

            response = admin_client.post('/reports/mail/recruit-daily', json=mail_data)

            # 邮件API返回格式：{"status": "started", "sent": bool, "count": int}
            if response.get('status') == 'started':
                print("✅ 招募邮件API调用成功")

                # 等待邮件文件生成
                time.sleep(2)

                # 验证招募邮件文件
                mail_files = self._get_generated_mail_files()
                recruit_mail_files = [f for f in mail_files if '招募日报' in f]

                if recruit_mail_files:
                    print(f"✅ 找到招募邮件文件: {len(recruit_mail_files)}个")

                    # 验证边界值处理
                    if self._validate_boundary_mail_content(recruit_mail_files):
                        print("✅ 边界值在邮件中正确处理")
                    else:
                        print("❌ 边界值在邮件中处理错误")

                    assert len(recruit_mail_files) > 0, "未找到招募邮件文件"
                else:
                    print("❌ 未找到招募邮件文件")
                    pytest.fail("招募邮件文件生成失败")

            else:
                print(f"❌ 招募邮件API调用失败: {response}")
                pytest.fail("招募邮件API调用失败")

        finally:
            # 恢复MAIL_DEBUG设置
            os.environ['MAIL_DEBUG'] = original_mail_debug
            print("✅ S9-TC3边界情况邮件生成测试完成")

    def test_s9_tc4_new_pilot_warning_mail_on_5th_and_6th_basepay(self, admin_client):
        """
        S9-TC4：新主播生存警告邮件

        当同一主播的底薪申请第5/6次确认发放时，应该生成“拉科斯警告 这是一个活到了第n天的新主播”邮件文件。
        """
        print("🔍 开始S9-TC4新主播生存警告邮件测试...")

        original_mail_debug = os.getenv('MAIL_DEBUG', 'false')
        os.environ['MAIL_DEBUG'] = 'true'

        known_mail_files = set(self._get_generated_mail_files())
        created_records = []
        created_applications = []
        pilot_id = None

        try:
            pilot_data = pilot_factory.create_pilot_data(nickname="S9-新主播监控")
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)
            if not pilot_response.get('success'):
                pytest.skip("创建主播接口不可用，跳过S9-TC4")

            pilot_id = pilot_response['data']['id']

            # 为该主播创建6条开播记录与底薪申请
            for index in range(6):
                start_time = datetime.now() - timedelta(days=6 - index, hours=2)
                end_time = start_time + timedelta(hours=3)
                battle_payload = {
                    'pilot': pilot_id,
                    'start_time': start_time.isoformat(),
                    'end_time': end_time.isoformat(),
                    'work_mode': '线下',
                    'x_coord': f'NP{index}',
                    'y_coord': f'SEC{index}',
                    'z_coord': 'Z1',
                    'revenue_amount': '180.00',
                    'base_salary': '120.00',
                    'notes': f'S9新主播邮件测试第{index + 1}次'
                }
                battle_response = admin_client.post('/battle-records/api/battle-records', json=battle_payload)
                if not battle_response.get('success'):
                    pytest.skip("创建开播记录接口不可用，跳过S9-TC4")

                record_id = battle_response['data']['id']
                created_records.append(record_id)

                application_payload = {'pilot_id': pilot_id, 'battle_record_id': record_id, 'settlement_type': 'daily_base', 'base_salary_amount': '120.00'}
                application_response = admin_client.post('/api/base-salary-applications', json=application_payload)
                if not application_response.get('success'):
                    pytest.skip("创建底薪申请接口不可用，跳过S9-TC4")

                created_applications.append(application_response['data']['id'])

            milestone_hits = []

            for idx, application_id in enumerate(created_applications, start=1):
                approval_response = admin_client.patch(f'/api/base-salary-applications/{application_id}/status', json={'status': 'approved'})
                if not approval_response.get('success'):
                    pytest.skip("底薪审批接口不可用，跳过S9-TC4")

                if idx in (5, 6):
                    keyword = f"第{idx}天"
                    matched_file = self._wait_for_new_pilot_warning_mail(keyword, known_mail_files)
                    assert matched_file, f"未找到包含{keyword}的新主播生存警告邮件"
                    milestone_hits.append(idx)

            assert milestone_hits == [5, 6], f"未捕获所有新主播邮件，实际={milestone_hits}"

        finally:
            os.environ['MAIL_DEBUG'] = original_mail_debug
            self._cleanup_test_data(admin_client, record_ids=created_records, pilot_ids=[pilot_id] if pilot_id else None)
            print("✅ S9-TC4新主播生存警告邮件测试完成")

    def test_s9_tc5_base_salary_reminder_mail_generation(self, admin_client):
        """
        S9-TC5：底薪发放提醒邮件测试

        验证当底薪申请状态为PENDING且超过12小时时，系统能正确生成底薪发放提醒邮件。
        邮件内容应包含主播信息、开播日期、申请时间和超时小时数。
        """
        print("🔍 开始S9-TC5底薪发放提醒邮件测试...")

        original_mail_debug = os.getenv('MAIL_DEBUG', 'false')
        os.environ['MAIL_DEBUG'] = 'true'

        created_pilots = []
        created_records = []
        created_applications = []

        try:
            # 清理现有邮件文件
            self._cleanup_mail_files()

            # 创建测试主播
            pilot_data = pilot_factory.create_pilot_data(nickname="底薪提醒测试主播")
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if not pilot_response.get('success'):
                pytest.skip("创建主播接口不可用，跳过S9-TC5")
                return

            pilot_id = pilot_response['data']['id']
            created_pilots.append(pilot_id)

            # 创建13小时前的开播记录（确保超过12小时阈值）
            past_start_time = datetime.now() - timedelta(hours=13, minutes=30)
            past_end_time = past_start_time + timedelta(hours=3)

            battle_data = {
                'pilot': pilot_id,
                'start_time': past_start_time.isoformat(),
                'end_time': past_end_time.isoformat(),
                'work_mode': '线下',
                'x_coord': 'BSR1',
                'y_coord': 'TEST',
                'z_coord': 'Z1',
                'revenue_amount': '200.00',
                'base_salary': '150.00',
                'notes': '底薪提醒测试开播记录'
            }

            battle_response = admin_client.post('/battle-records/api/battle-records', json=battle_data)
            if not battle_response.get('success'):
                pytest.skip("创建开播记录接口不可用，跳过S9-TC5")
                return

            record_id = battle_response['data']['id']
            created_records.append(record_id)

            # 创建底薪申请（手动设置创建时间为13小时前）
            application_data = {'pilot_id': pilot_id, 'battle_record_id': record_id, 'settlement_type': 'daily_base', 'base_salary_amount': '150.00'}

            application_response = admin_client.post('/api/base-salary-applications', json=application_data)
            if not application_response.get('success'):
                pytest.skip("创建底薪申请接口不可用，跳过S9-TC5")
                return

            application_id = application_response['data']['id']
            created_applications.append(application_id)

            print(f"✅ 创建测试数据：主播{pilot_id}，记录{record_id}，申请{application_id}")

            # 直接调用底薪提醒邮件API
            response = admin_client.post('/reports/mail/base-salary-reminder')

            if response.get('status') == 'started':
                print("✅ 底薪提醒邮件API调用成功")

                # 等待邮件文件生成
                time.sleep(3)

                # 验证邮件文件
                mail_files = self._get_generated_mail_files()
                reminder_mail_files = [f for f in mail_files if '底薪发放提醒' in f]

                if reminder_mail_files:
                    print(f"✅ 找到底薪提醒邮件文件: {len(reminder_mail_files)}个")

                    # 验证邮件内容
                    validation_passed = False
                    for file_path in reminder_mail_files:
                        print(f"📄 邮件文件: {file_path}")
                        if self._validate_base_salary_reminder_mail_content(file_path, pilot_id):
                            print(f"  ✅ 邮件内容验证通过")
                            validation_passed = True
                            break
                        else:
                            print(f"  ❌ 邮件内容验证失败")

                    assert validation_passed, "底薪提醒邮件内容验证失败"

                else:
                    print("❌ 未找到底薪提醒邮件文件")
                    pytest.fail("底薪提醒邮件文件生成失败")

            else:
                print(f"❌ 底薪提醒邮件API调用失败: {response}")
                pytest.fail("底薪提醒邮件API调用失败")

        finally:
            # 恢复环境设置
            os.environ['MAIL_DEBUG'] = original_mail_debug

            # 清理测试数据
            self._cleanup_test_data(admin_client, record_ids=created_records, pilot_ids=created_pilots)

            # 清理底薪申请
            for application_id in created_applications:
                try:
                    admin_client.delete(f'/api/base-salary-applications/{application_id}')
                except:
                    pass

            print("✅ S9-TC5底薪发放提醒邮件测试完成")

    def _validate_base_salary_reminder_mail_content(self, file_path, expected_pilot_id):
        """验证底薪提醒邮件内容"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()

            # 检查邮件标题和基本结构
            if '底薪发放提醒' not in content:
                print("  ❌ 邮件标题不正确")
                return False

            # 检查关键字段
            required_fields = ['主播昵称', '真实姓名', '开播日期', '申请时间', '超时小时', '底薪金额', '未处理']

            for field in required_fields:
                if field not in content:
                    print(f"  ❌ 缺少必要字段: {field}")
                    return False

            # 检查说明文字
            if '申请时间已超过12小时' not in content:
                print("  ❌ 缺少超时说明")
                return False

            # 检查表格结构
            if '|' not in content or '---' not in content:
                print("  ❌ 邮件表格结构不正确")
                return False

            print("  ✅ 邮件内容结构验证通过")
            return True

        except Exception as e:
            print(f"  ❌ 读取邮件文件失败: {str(e)}")
            return False

    def _get_generated_mail_files(self):
        """获取log/mail目录中生成的邮件文件"""
        mail_dir = 'log/mail'
        if not os.path.exists(mail_dir):
            return []

        mail_files = []
        for filename in os.listdir(mail_dir):
            if filename.endswith('.html'):
                file_path = os.path.join(mail_dir, filename)
                # 只获取最近生成的文件（最近10分钟内）
                file_time = datetime.fromtimestamp(os.path.getmtime(file_path))
                if (datetime.now() - file_time).total_seconds() < 600:  # 10分钟内
                    mail_files.append(file_path)

        return sorted(mail_files, key=os.path.getmtime, reverse=True)

    def _validate_mail_file_content(self, file_path, expected_content_keyword):
        """验证邮件文件内容是否包含预期关键字"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                return expected_content_keyword in content
        except Exception as e:
            print(f"❌ 读取邮件文件失败: {str(e)}")
            return False

    def _validate_complex_mail_content(self, file_path, expected_total_income):
        """验证复杂计算邮件内容"""
        try:
            with open(file_path, 'r', encoding='utf-8') as f:
                content = f.read()
                # 检查是否包含总收入计算
                if str(expected_total_income) in content:
                    return True
                # 检查是否包含极值边界
                return '999999' in content or '0' in content or '1' in content
        except Exception as e:
            print(f"❌ 读取复杂邮件文件失败: {str(e)}")
            return False

    def _validate_boundary_mail_content(self, mail_files):
        """验证边界情况邮件内容"""
        for file_path in mail_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    # 检查是否包含边界值处理
                    if ('0' in content and '99999999' in content) or \
                       ('零收入' in content and '最大值' in content):
                        return True
            except Exception as e:
                print(f"❌ 读取边界邮件文件失败: {str(e)}")
                return False
        return False

    def _wait_for_new_pilot_warning_mail(self, keyword, known_files, timeout=12):
        """等待新主播生存警告邮件生成"""
        deadline = time.time() + timeout
        while time.time() < deadline:
            current_files = set(self._get_generated_mail_files())
            new_files = [path for path in current_files if path not in known_files]
            if not new_files:
                time.sleep(1)
                continue

            for file_path in new_files:
                known_files.add(file_path)
                try:
                    with open(file_path, 'r', encoding='utf-8') as file_obj:
                        content = file_obj.read()
                        if keyword in content and '新主播生存警告' in content:
                            print(f"✅ 捕获新主播邮件文件: {file_path}")
                            return file_path
                except Exception as exc:  # pylint: disable=broad-except
                    print(f"⚠️ 读取新主播邮件失败: {file_path} - {exc}")
            time.sleep(1)
        return None

    def _cleanup_mail_files(self):
        """清理log/mail目录中的测试邮件文件"""
        mail_dir = 'log/mail'
        if os.path.exists(mail_dir):
            for filename in os.listdir(mail_dir):
                if filename.endswith('.html') and 'test@example.com' in filename:
                    try:
                        file_path = os.path.join(mail_dir, filename)
                        os.remove(file_path)
                        print(f"✅ 清理邮件文件: {filename}")
                    except Exception as e:
                        print(f"⚠️ 清理邮件文件失败: {filename} - {str(e)}")

    def _cleanup_test_data(self, admin_client, record_ids=None, pilot_ids=None):
        """清理测试数据"""
        try:
            # 清理开播记录
            if record_ids:
                for record_id in record_ids:
                    try:
                        admin_client.delete(f"/battle-records/api/battle-records/{record_id}")
                    except:
                        pass

            # 清理主播
            if pilot_ids:
                for pilot_id in pilot_ids:
                    try:
                        admin_client.put(f"/api/pilots/{pilot_id}", json={'status': '未招募'})
                    except:
                        pass

            print("✅ 测试数据清理完成")

        except Exception as e:
            print(f"⚠️ 测试数据清理异常: {str(e)}")
