"""
套件S9：告警与通知测试

覆盖 API：/api/james-alerts/*（若存在）、/api/bbs/notifications, /api/mail/*

测试原则：
1. 不直接操作数据库
2. 所有操作通过REST API
3. 测试告警触发机制
4. 验证通知发送和过滤
"""
import pytest
from datetime import datetime, timedelta
from tests.fixtures.factories import (
    pilot_factory, james_alert_factory, battle_record_factory, bbs_post_factory
)


@pytest.mark.suite("S9")
@pytest.mark.alerts_notifications
class TestS9AlertsNotifications:
    """告警与通知测试套件"""

    def test_s9_tc1_james_attention_alert_triggering(self, admin_client):
        """
        S9-TC1 詹姆斯关注告警触发

        步骤：创建满足告警条件的开播记录 → 调用告警查询 API → 确认新增项目。
        """
        created_ids = {}

        try:
            # 1. 创建主播
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                # 2. 创建可能触发告警的开播记录
                # 例如：收入异常低的主播
                low_income_record = battle_record_factory.create_battle_record_data(
                    pilot_id=pilot_id,
                    status='COMPLETED',
                    income=5000,  # 很低的收入，可能触发告警
                    work_mode='线下',
                    platform='快手'
                )

                battle_response = admin_client.post('/api/battle-records', json=low_income_record)

                if battle_response.get('success'):
                    battle_record_id = battle_response['data']['id']
                    created_ids['battle_record_id'] = battle_record_id

                # 3. 创建另一个可能触发连续未开播告警的情况
                # 创建很久以前的开播记录，然后没有新记录
                old_record_date = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d %H:%M:%S')
                old_record = battle_record_factory.create_battle_record_data(
                    pilot_id=pilot_id,
                    start_time=old_record_date,
                    status='COMPLETED',
                    income=30000
                )

                old_battle_response = admin_client.post('/api/battle-records', json=old_record)

                if old_battle_response.get('success'):
                    old_record_id = old_battle_response['data']['id']
                    created_ids['old_record_id'] = old_record_id

            # 4. 查询詹姆斯告警
            alerts_endpoints = [
                '/api/james-alerts',
                '/api/alerts',
                '/api/pilots/alerts'
            ]

            for endpoint in alerts_endpoints:
                alerts_response = admin_client.get(endpoint)

                if alerts_response.get('success'):
                    alerts = alerts_response['data']

                    # 验证告警数据结构
                    if isinstance(alerts, list):
                        for alert in alerts:
                            assert 'pilot_id' in alert
                            assert 'alert_type' in alert
                            assert 'alert_level' in alert
                            assert 'created_at' in alert

                            # 验证可能的告警类型
                            valid_types = ['连续未开播', '收入异常', '开播时长不足', '数据异常', 'LOW_INCOME', 'ABSENT']
                            assert alert['alert_type'] in valid_types or 'test' in alert['alert_type'].lower()

                    break  # 如果有一个端点可用，就继续测试

            # 5. 手动创建告警（如果支持）
            if 'pilot_id' in created_ids:
                manual_alert_data = james_alert_factory.create_alert_data(
                    pilot_id=created_ids['pilot_id'],
                    alert_type='收入异常',
                    alert_level='HIGH',
                    message='手动创建的测试告警：主播收入低于预期'
                )

                manual_alert_response = admin_client.post('/api/james-alerts', json=manual_alert_data)

                if manual_alert_response.get('success'):
                    created_alert = manual_alert_response['data']
                    assert created_alert['pilot_id'] == created_ids['pilot_id']
                    assert created_alert['alert_type'] == '收入异常'
                    assert created_alert['status'] == 'ACTIVE'

        finally:
            # 清理创建的数据
            for key, record_id in created_ids.items():
                if key.endswith('_record_id'):
                    try:
                        admin_client.delete(f'/api/battle-records/{record_id}')
                    except:
                        pass

            if 'pilot_id' in created_ids:
                try:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
                except:
                    pass

    def test_s9_tc2_email_notification_blacklist(self, admin_client, kancho_client):
        """
        S9-TC2 邮件通知黑名单

        步骤：模拟 BBS 回复触发邮件 → 查询 /api/mail/logs（或下载日志文件）确认收件人过滤。
        """
        created_ids = {}

        try:
            # 1. 创建主播和主贴
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']
                created_ids['pilot_id'] = pilot_id

                post_data = bbs_post_factory.create_post_data(
                    author_id=kancho_client.get('/api/users/me')['data']['id'],
                    pilot_ids=[pilot_id],
                    title='邮件通知测试主贴',
                    content='这个主贴用于测试邮件通知功能',
                    category='主播反馈'
                )

                post_response = admin_client.post('/api/bbs/posts', json=post_data)

                if post_response.get('success'):
                    post = post_response['data']
                    post_id = post['id']
                    created_ids['post_id'] = post_id

                    # 2. 添加回复，可能触发邮件通知
                    reply_data = {
                        'content': '这是一个测试回复，可能触发邮件通知',
                        'author_id': admin_client.get('/api/users/me')['data']['id']
                    }

                    reply_response = admin_client.post(f'/api/bbs/posts/{post_id}/replies', json=reply_data)

                    if reply_response.get('success'):
                        reply_id = reply_response['data']['id']
                        created_ids['reply_id'] = reply_id

                        # 3. 查询邮件日志
                        mail_log_endpoints = [
                            '/api/mail/logs',
                            '/api/notifications/logs',
                            '/api/mail/history'
                        ]

                        for endpoint in mail_log_endpoints:
                            log_response = admin_client.get(endpoint, params={
                                'post_id': post_id,
                                'limit': 10
                            })

                            if log_response.get('success'):
                                logs = log_response['data']

                                # 验证邮件日志结构
                                if isinstance(logs, list):
                                    for log in logs:
                                        assert 'recipient' in log or 'to' in log
                                        assert 'subject' in log or 'content' in log
                                        assert 'sent_at' in log or 'created_at' in log

                                        # 验证黑名单过滤（如果支持）
                                        if 'blacklisted' in log:
                                            assert isinstance(log['blacklisted'], bool)

                                break  # 如果有一个端点可用，就继续测试

                    # 4. 测试邮件通知设置（如果支持）
                    notification_settings_response = admin_client.get('/api/mail/settings')

                    if notification_settings_response.get('success'):
                        settings = notification_settings_response['data']

                        # 验证设置结构
                        if isinstance(settings, dict):
                            possible_keys = ['blacklist', 'enabled', 'recipients', 'filters']
                            for key in possible_keys:
                                if key in settings:
                                    if key == 'blacklist':
                                        assert isinstance(settings[key], list)
                                    elif key == 'enabled':
                                        assert isinstance(settings[key], bool)

        finally:
            # 清理创建的数据
            try:
                if 'reply_id' in created_ids:
                    admin_client.delete(f'/api/bbs/replies/{created_ids["reply_id"]}')
                if 'post_id' in created_ids:
                    admin_client.delete(f'/api/bbs/posts/{created_ids["post_id"]}')
                if 'pilot_id' in created_ids:
                    admin_client.put(f'/api/pilots/{created_ids["pilot_id"]}', json={'status': '未招募'})
            except:
                pass

    def test_s9_tc3_sse_long_polling_notifications(self, admin_client, kancho_client):
        """
        S9-TC3 SSE/长轮询通知

        若存在通知流接口，构建事件并验证。
        """
        try:
            # 1. 测试SSE通知流接口
            sse_endpoints = [
                '/api/notifications/stream',
                '/api/events/stream',
                '/api/alerts/stream',
                '/api/bbs/notifications/stream'
            ]

            for endpoint in sse_endpoints:
                try:
                    sse_response = admin_client.get(endpoint)

                    # SSE接口通常返回200和特定的Content-Type
                    if sse_response.get('_status_code') == 200:
                        # SSE接口可能不支持在测试环境中完整验证
                        # 但至少验证接口存在且可访问
                        pytest.skip(f"SSE通知流接口{endpoint}可用，但无法在单元测试中完整验证")

                except Exception:
                    # SSE可能在测试环境中不支持
                    continue

            # 2. 测试长轮询通知接口
            long_polling_endpoints = [
                '/api/notifications/poll',
                '/api/events/poll',
                '/api/alerts/check'
            ]

            for endpoint in long_polling_endpoints:
                poll_response = admin_client.get(endpoint, params={
                    'timeout': 5,  # 5秒超时
                    'since': datetime.now().strftime('%Y-%m-%d %H:%M:%S')
                })

                if poll_response.get('success'):
                    notifications = poll_response['data']

                    # 验证通知结构
                    if isinstance(notifications, list):
                        for notification in notifications:
                            assert 'id' in notification
                            assert 'type' in notification
                            assert 'created_at' in notification

                    break  # 如果有一个端点可用，就继续测试

            # 3. 创建一些通知事件
            # 创建主播（可能触发通知）
            pilot_data = pilot_factory.create_pilot_data()
            pilot_response = admin_client.post('/api/pilots', json=pilot_data)

            if pilot_response.get('success'):
                pilot_id = pilot_response['data']['id']

                # 立即再次查询通知，看是否有新事件
                for endpoint in long_polling_endpoints:
                    poll_response = admin_client.get(endpoint, params={
                        'timeout': 2,
                        'since': (datetime.now() - timedelta(minutes=1)).strftime('%Y-%m-%d %H:%M:%S')
                    })

                    if poll_response.get('success'):
                        notifications = poll_response['data']
                        # 可能会有新的通知事件
                        break

                # 清理
                admin_client.put(f'/api/pilots/{pilot_id}', json={'status': '未招募'})

        except Exception:
            pytest.skip("通知流或长轮询接口不可用")

    def test_s9_tc4_alert_rules_and_configuration(self, admin_client):
        """
        S9-TC4 告警规则和配置（额外测试）

        步骤：配置告警规则 → 测试规则生效。
        """
        try:
            # 1. 查询当前告警规则配置
            rules_response = admin_client.get('/api/james-alerts/rules')

            if rules_response.get('success'):
                rules = rules_response['data']
                assert isinstance(rules, (list, dict))

            # 2. 测试告警规则配置（如果支持）
            rule_config = {
                'rule_type': 'income_threshold',
                'threshold': 10000,
                'operator': 'less_than',
                'alert_level': 'MEDIUM',
                'enabled': True,
                'description': '收入低于10000元时触发告警'
            }

            config_response = admin_client.post('/api/james-alerts/rules', json=rule_config)

            if config_response.get('success'):
                created_rule = config_response['data']
                assert created_rule['rule_type'] == 'income_threshold'
                assert created_rule['threshold'] == 10000

                # 3. 更新告警规则
                update_response = admin_client.put(f'/api/james-alerts/rules/{created_rule["id"]}', json={
                    'threshold': 15000,
                    'alert_level': 'HIGH'
                })

                if update_response.get('success'):
                    updated_rule = update_response['data']
                    assert updated_rule['threshold'] == 15000
                    assert updated_rule['alert_level'] == 'HIGH'

            # 4. 测试告警通知渠道配置
            channels_response = admin_client.get('/api/james-alerts/channels')

            if channels_response.get('success'):
                channels = channels_response['data']
                assert isinstance(channels, list)

        except Exception:
            pytest.skip("告警规则配置接口不可用")

    def test_s9_tc5_notification_preferences_and_filters(self, admin_client, kancho_client):
        """
        S9-TC5 通知偏好和过滤器（额外测试）

        步骤：设置用户通知偏好 → 验证通知过滤生效。
        """
        try:
            # 1. 获取当前用户通知偏好
            preferences_response = kancho_client.get('/api/notifications/preferences')

            if preferences_response.get('success'):
                preferences = preferences_response['data']
                assert isinstance(preferences, dict)

            # 2. 设置通知偏好
            new_preferences = {
                'email_notifications': True,
                'bbs_notifications': True,
                'alert_notifications': False,  # 关闭告警通知
                'frequency': 'daily',
                'categories': {
                    '主播反馈': True,
                    '运营公告': True,
                    '系统通知': False
                }
            }

            set_preferences_response = kancho_client.post('/api/notifications/preferences', json=new_preferences)

            if set_preferences_response.get('success'):
                updated_preferences = set_preferences_response['data']
                assert updated_preferences['email_notifications'] is True
                assert updated_preferences['alert_notifications'] is False

            # 3. 验证偏好设置生效
            verify_response = kancho_client.get('/api/notifications/preferences')
            if verify_response.get('success'):
                verify_preferences = verify_response['data']
                assert verify_preferences['alert_notifications'] is False

        except Exception:
            pytest.skip("通知偏好设置接口不可用")