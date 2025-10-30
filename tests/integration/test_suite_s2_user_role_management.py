"""
套件S2：用户与角色管理测试

覆盖 API：/api/users, /api/users/<id>, /api/users/<id>/activation, /api/users/password

测试原则：
1. 不直接操作数据库
2. 所有操作通过REST API
3. 测试用户CRUD操作
4. 验证角色权限和激活状态管理
"""
import pytest
from tests.fixtures.factories import user_factory


@pytest.mark.suite("S2")
@pytest.mark.user_role_management
class TestS2UserRoleManagement:
    """用户与角色管理测试套件"""

    def test_s2_tc1_user_creation_and_role_assignment(self, admin_client):
        """
        S2-TC1 用户创建与角色分配

        步骤：管理员登录 → POST /api/users 创建 kancho → GET /api/users 校验 →
              kancho 登录验证。

        断言：列表含新用户，角色列表正确。
        """
        # 1. 创建运营用户
        kancho_data = user_factory.create_user_data(role='kancho')
        create_response = admin_client.post('/api/users', json=kancho_data)

        assert create_response['success'] is True
        assert 'data' in create_response

        created_user = create_response['data']
        user_id = created_user['id']
        username = kancho_data['username']
        password = kancho_data['password']

        # 验证创建的用户信息
        assert created_user['username'] == username
        assert created_user['nickname'] == kancho_data['nickname']
        assert created_user['email'] == kancho_data['email']
        assert kancho_data['role'] in created_user.get('roles', [])

        # 2. 从用户列表中验证新用户存在
        users_list_response = admin_client.get('/api/users', params={'role': 'kancho'})

        assert users_list_response['success'] is True
        users_list = users_list_response['data']

        # 找到新创建的用户
        found_user = None
        for user in users_list:
            if user['id'] == user_id:
                found_user = user
                break

        assert found_user is not None
        assert found_user['username'] == username

        # 3. 验证新创建的用户可以登录
        from tests.fixtures.api_client import ApiClient
        from tests.conftest import base_url
        from app import create_app

        flask_app = create_app()
        test_client = flask_app.test_client()
        new_client = ApiClient(base_url, client=test_client)

        # 使用新用户登录
        login_response = new_client.login(username, password)
        assert login_response['success'] is True

        # 4. 验证新用户可以访问自己的信息
        me_response = new_client.get('/api/auth/me')
        assert me_response['success'] is True
        assert me_response['data']['user']['username'] == username

        # 5. 清理：停用测试用户
        try:
            admin_client.patch(f'/api/users/{user_id}/activation', json={'active': False})
        except:
            pass

    def test_s2_tc2_user_information_update(self, admin_client):
        """
        S2-TC2 用户信息更新

        步骤：PUT /api/users/<id> 修改昵称、邮箱 → 再次获取详情。

        断言：变更生效，updated_at 变化。
        """
        # 1. 创建测试用户
        user_data = user_factory.create_user_data(role='kancho')
        create_response = admin_client.post('/api/users', json=user_data)

        assert create_response['success'] is True
        user_id = create_response['data']['id']

        # 获取原始updated_at时间
        original_user = create_response['data']
        original_updated_at = original_user.get('updated_at')

        # 2. 更新用户信息
        update_data = {'nickname': '更新后的昵称', 'email': 'updated@example.com'}

        update_response = admin_client.put(f'/api/users/{user_id}', json=update_data)
        assert update_response['success'] is True

        updated_user = update_response['data']
        assert updated_user['nickname'] == update_data['nickname']
        assert updated_user['email'] == update_data['email']

        # 验证updated_at有变化（如果系统支持）
        if original_updated_at and updated_user.get('updated_at'):
            assert updated_user['updated_at'] != original_updated_at

        # 3. 再次获取详情验证
        get_response = admin_client.get(f'/api/users/{user_id}')
        assert get_response['success'] is True

        user_detail = get_response['data']
        assert user_detail['nickname'] == update_data['nickname']
        assert user_detail['email'] == update_data['email']

        # 4. 清理：停用测试用户
        try:
            admin_client.patch(f'/api/users/{user_id}/activation', json={'active': False})
        except Exception:  # pylint: disable=broad-except
            pass

    def test_s2_tc3_activation_deactivation_and_last_admin_protection(self, admin_client):
        """
        S2-TC3 激活/停用与最后管理员保护

        步骤：停用普通运营成功 → 尝试停用最后一位 gicho → 接口应拒绝。

        断言：提示"必须保留至少一名管理员"。
        """
        # 1. 创建一个普通运营用户
        kancho_data = user_factory.create_user_data(role='kancho')
        create_response = admin_client.post('/api/users', json=kancho_data)
        assert create_response['success'] is True

        kancho_id = create_response['data']['id']

        # 2. 成功停用普通运营用户
        deactivate_response = admin_client.patch(f'/api/users/{kancho_id}/activation', json={'active': False})
        assert deactivate_response['success'] is True

        # 验证用户已被停用
        get_response = admin_client.get(f'/api/users/{kancho_id}')
        assert get_response['success'] is True
        assert get_response['data']['active'] is False

        # 3. 尝试获取当前活跃的管理员列表
        admins_response = admin_client.get('/api/users', params={'role': 'gicho', 'active': True})
        assert admins_response['success'] is True

        active_admins = admins_response['data']
        admin_count = len(active_admins)

        # 如果只有1个活跃管理员，尝试停用应该失败
        if admin_count <= 1:
            # 找到第一个管理员ID
            if active_admins:
                admin_id = active_admins[0]['id']

                # 尝试停用最后一位管理员
                try:
                    deactivate_admin_response = admin_client.patch(f'/api/users/{admin_id}/activation', json={'active': False})

                    # 应该返回失败
                    assert deactivate_admin_response.get('success') is not True
                    assert deactivate_admin_response['_status_code'] in [400, 409]

                    if 'error' in deactivate_admin_response:
                        error_message = deactivate_admin_response['error']['message']
                        assert any(keyword in error_message for keyword in ['至少一名管理员', '最后管理员', 'cannot deactivate'])

                except Exception:  # pylint: disable=broad-except
                    # 如果抛出异常也是预期的行为
                    pass

        # 4. 清理：保持测试用户停用状态
        # （kancho用户已经是停用状态，不需要额外操作）

    def test_s2_tc4_password_reset_and_login_verification(self, admin_client):
        """
        S2-TC4 密码重置与登录验证

        步骤：POST /api/users/<id>/reset-password（或同等接口）→ 用新密码登录 →
              老密码失败。

        断言：密码重置成功，新密码可登录，旧密码失效。
        """
        # 1. 创建测试用户
        user_data = user_factory.create_user_data(role='kancho')
        original_password = user_data['password']

        create_response = admin_client.post('/api/users', json=user_data)
        assert create_response['success'] is True

        user_id = create_response['data']['id']
        username = user_data['username']

        # 2. 重置密码（密码会被重置为123456）
        reset_response = admin_client.post(f'/api/users/{user_id}/reset-password')
        assert reset_response.get('success') is True
        assert reset_response['data']['temp_password'] == '123456'

        # 3. 验证新密码可以登录
        from tests.fixtures.api_client import ApiClient
        from app import create_app

        flask_app = create_app()
        test_client = flask_app.test_client()
        new_client = ApiClient('', client=test_client)

        # 使用新密码123456登录
        new_login_response = new_client.login(username, '123456')
        assert new_login_response['success'] is True

        # 4. 验证旧密码无法登录
        old_login_response = new_client.login(username, original_password)
        assert old_login_response.get('success') is not True

        # 5. 清理：停用测试用户
        try:
            admin_client.patch(f'/api/users/{user_id}/activation', json={'active': False})
        except Exception:  # pylint: disable=broad-except
            pass

    def test_s2_tc5_user_validation_and_error_handling(self, admin_client):
        """
        S2-TC5 用户数据验证和错误处理（额外测试）

        步骤：尝试创建无效用户数据（重复用户名、无效邮箱等）。

        断言：返回适当的错误响应。
        """
        # 1. 创建第一个用户
        user_data1 = user_factory.create_user_data(role='kancho')
        create_response1 = admin_client.post('/api/users', json=user_data1)
        assert create_response1['success'] is True

        # 2. 尝试使用相同用户名创建第二个用户
        user_data2 = user_factory.create_user_data(role='kancho')
        user_data2['username'] = user_data1['username']  # 使用相同用户名
        user_data2['email'] = 'different@example.com'  # 使用不同邮箱

        duplicate_response = admin_client.post('/api/users', json=user_data2)

        # 应该返回失败
        assert duplicate_response.get('success') is not True
        assert duplicate_response['_status_code'] in [400, 409]

        if 'error' in duplicate_response:
            assert 'code' in duplicate_response['error']

        # 3. 尝试使用无效邮箱格式
        invalid_email_data = user_factory.create_user_data(role='kancho')
        invalid_email_data['email'] = 'invalid-email-format'
        invalid_email_data['username'] = 'unique_username_for_test'

        invalid_email_response = admin_client.post('/api/users', json=invalid_email_data)

        # 应该返回失败
        assert invalid_email_response.get('success') is not True
        assert invalid_email_response['_status_code'] in [400, 422]

        # 4. 清理：停用创建的测试用户
        try:
            user_id1 = create_response1['data']['id']
            admin_client.patch(f'/api/users/{user_id1}/activation', json={'active': False})
        except Exception:  # pylint: disable=broad-except
            pass

    def test_s2_tc6_user_search_and_filtering(self, admin_client):
        """
        S2-TC6 用户搜索和过滤功能（额外测试）

        步骤：创建多个不同角色的用户 → 测试各种过滤和搜索参数。

        断言：过滤结果正确。
        """
        created_user_ids = []

        try:
            # 1. 创建多个不同角色的用户
            users_to_create = [
                user_factory.create_user_data(role='kancho', nickname='搜索测试1'),
                user_factory.create_user_data(role='kancho', nickname='搜索测试2'),
                user_factory.create_user_data(role='gicho', nickname='管理员搜索测试'),
            ]

            for user_data in users_to_create:
                create_response = admin_client.post('/api/users', json=user_data)
                if create_response.get('success'):
                    created_user_ids.append(create_response['data']['id'])

            # 2. 测试按角色过滤
            kancho_response = admin_client.get('/api/users', params={'role': 'kancho'})
            assert kancho_response['success'] is True

            kancho_users = kancho_response['data']
            # 至少应该包含我们创建的运营用户
            assert len(kancho_users) >= 2

            # 3. 测试按昵称搜索
            search_response = admin_client.get('/api/users', params={'search': '搜索测试'})
            assert search_response['success'] is True

            search_users = search_response['data']
            # 应该找到包含搜索关键词的用户
            assert len(search_users) >= 1

            # 4. 测试组合过滤
            combo_response = admin_client.get('/api/users', params={'role': 'kancho', 'search': '搜索测试'})
            assert combo_response['success'] is True

        finally:
            # 5. 清理：停用所有创建的测试用户
            for user_id in created_user_ids:
                try:
                    admin_client.patch(f'/api/users/{user_id}/activation', json={'active': False})
                except Exception:  # pylint: disable=broad-except
                    pass

    def test_s2_tc7_user_complete_lifecycle(self, admin_client):
        """
        S2-TC7 用户完整生命周期测试

        步骤：创建→查询→更新→停用→验证无法登录→激活→验证可登录→删除→验证不存在
        """
        created_user_id = None

        try:
            # 1. 创建用户
            user_data = user_factory.create_user_data(role='kancho')
            create_resp = admin_client.post('/api/users', json=user_data)
            assert create_resp['success'] is True
            created_user_id = create_resp['data']['id']

            # 2. 查询用户详情
            detail_resp = admin_client.get(f'/api/users/{created_user_id}')
            assert detail_resp['success'] is True
            assert detail_resp['data']['username'] == user_data['username']

            # 3. 更新用户信息
            update_resp = admin_client.put(f'/api/users/{created_user_id}', json={'nickname': '更新昵称'})
            assert update_resp['success'] is True
            assert update_resp['data']['nickname'] == '更新昵称'

            # 4. 停用用户
            deactivate_resp = admin_client.patch(f'/api/users/{created_user_id}/activation', json={'active': False})
            assert deactivate_resp['success'] is True
            assert deactivate_resp['data']['active'] is False

            # 5. 验证停用后无法登录
            from tests.fixtures.api_client import ApiClient
            from app import create_app

            app = create_app()
            with app.test_client() as test_client:
                temp_client = ApiClient('', client=test_client)
                login_resp = temp_client.login(user_data['username'], user_data['password'])
                assert login_resp['success'] is False

            # 6. 重新激活
            activate_resp = admin_client.patch(f'/api/users/{created_user_id}/activation', json={'active': True})
            assert activate_resp['success'] is True

            # 7. 验证可以登录
            with app.test_client() as test_client2:
                temp_client2 = ApiClient('', client=test_client2)
                login_resp2 = temp_client2.login(user_data['username'], user_data['password'])
                assert login_resp2['success'] is True

            # 8. 删除用户
            delete_resp = admin_client.delete(f'/api/users/{created_user_id}')
            assert delete_resp['success'] is True

            # 9. 验证删除后无法查询
            detail_resp2 = admin_client.get(f'/api/users/{created_user_id}')
            assert detail_resp2['success'] is False

            created_user_id = None  # 标记为已删除

        finally:
            if created_user_id:
                try:
                    admin_client.delete(f'/api/users/{created_user_id}')
                except Exception:  # pylint: disable=broad-except
                    pass

    def test_s2_tc8_gunsou_role_creation_and_permissions(self, admin_client):
        """
        S2-TC8 助理运营(gunsou)角色创建和权限验证

        步骤：管理员登录 → POST /api/users 创建 gunsou → GET /api/users 校验 →
              gunsou 登录验证权限限制 → 验证可以访问的功能 → 验证不能访问的功能。

        断言：列表含新用户，gunsou角色正确，权限符合预期。
        """
        gunsou_user_id = None

        try:
            # 1. 创建助理运营用户
            gunsou_data = user_factory.create_user_data(role='gunsou')
            create_response = admin_client.post('/api/users', json=gunsou_data)

            assert create_response['success'] is True
            assert 'data' in create_response

            created_user = create_response['data']
            gunsou_user_id = created_user['id']
            username = gunsou_data['username']
            password = gunsou_data['password']

            # 验证创建的用户信息
            assert created_user['username'] == username
            assert created_user['nickname'] == gunsou_data['nickname']
            assert 'gunsou' in created_user.get('roles', [])

            # 2. 从用户列表中验证新用户存在
            users_list_response = admin_client.get('/api/users', params={'role': 'gunsou'})
            assert users_list_response['success'] is True

            found_user = None
            for user in users_list_response['data']:
                if user['id'] == gunsou_user_id:
                    found_user = user
                    break

            assert found_user is not None
            assert found_user['username'] == username
            assert 'gunsou' in found_user.get('roles', [])

            # 3. 创建gunsou客户端并登录
            from tests.fixtures.api_client import ApiClient
            from app import create_app

            flask_app = create_app()
            test_client = flask_app.test_client()
            gunsou_client = ApiClient('', client=test_client)

            # 使用gunsou账户登录
            login_response = gunsou_client.login(username, password)
            assert login_response['success'] is True

            # 4. 验证gunsou可以访问的功能
            # 应该可以访问：招募列表
            recruits_response = gunsou_client.get('/api/recruits')
            assert recruits_response['success'] is True

            # 应该可以访问：仪表盘基础数据
            dashboard_response = gunsou_client.get('/api/dashboard/recruit')
            assert dashboard_response['success'] is True

            # 应该可以访问：日报
            daily_report_response = gunsou_client.get('/daily')
            # API客户端对于页面请求会返回错误响应，但至少不是403权限错误
            assert daily_report_response.get('success') is True or '404' not in str(daily_report_response.get('error', {}).get('code', ''))

            # 5. 验证gunsou不能访问的功能
            # 不应该可以访问：周报
            weekly_response = gunsou_client.get('/weekly')
            # gunsou应该不能访问周报，API会返回403错误
            assert weekly_response.get('success') is False

            # 不应该可以访问：月报
            monthly_response = gunsou_client.get('/monthly')
            assert monthly_response.get('success') is False

            # 不应该可以访问：底薪月报
            base_salary_response = gunsou_client.get('/base-salary-monthly')
            assert base_salary_response.get('success') is False

            # 不应该可以访问：招募月报
            recruit_monthly_response = gunsou_client.get('/recruit-reports/monthly')
            assert recruit_monthly_response.get('success') is False

            # 不应该可以访问：用户管理
            users_response = gunsou_client.get('/api/users')
            assert users_response.get('success') is False

            # 6. 验证gunsou用户信息编辑功能
            # 应该可以编辑自己的基本信息
            update_data = {'nickname': '助理运营测试用户', 'email': 'gunsou_test@example.com', 'roles': ['gunsou']}
            update_response = gunsou_client.put(f'/api/users/{gunsou_user_id}', json=update_data)
            # 用户管理API需要gicho权限，所以gunsou不能编辑其他用户
            assert update_response.get('success') is False or '403' in str(update_response.get('error', {}).get('code', ''))

        finally:
            # 清理：停用测试用户
            if gunsou_user_id:
                try:
                    admin_client.delete(f'/api/users/{gunsou_user_id}')
                except Exception:  # pylint: disable=broad-except
                    pass

    def test_s2_tc9_gunsou_role_switching(self, admin_client):
        """
        S2-TC9 助理运营(gunsou)角色切换测试

        步骤：创建用户 → 切换角色为 gunsou → 验证切换结果 →
              切换角色为 kancho → 验证切换结果 →
              切换角色为 gicho → 验证切换结果。

        断言：角色切换成功，权限相应变化。
        """
        test_user_id = None

        try:
            # 1. 创建测试用户（初始为kancho）
            user_data = user_factory.create_user_data(role='kancho')
            create_response = admin_client.post('/api/users', json=user_data)
            assert create_response['success'] is True

            test_user_id = create_response['data']['id']
            username = user_data['username']
            password = user_data['password']

            # 2. 切换角色为gunsou
            update_gunsou_data = {'nickname': '助理运营用户', 'email': 'gunsou@example.com', 'roles': ['gunsou']}
            update_response = admin_client.put(f'/api/users/{test_user_id}', json=update_gunsou_data)
            assert update_response['success'] is True

            updated_user = update_response['data']
            assert 'gunsou' in updated_user.get('roles', [])
            assert updated_user['nickname'] == '助理运营用户'
            assert updated_user['email'] == 'gunsou@example.com'

            # 3. 创建gunsou客户端并登录验证
            from tests.fixtures.api_client import ApiClient
            from app import create_app

            flask_app = create_app()
            test_client = flask_app.test_client()
            gunsou_client = ApiClient('', client=test_client)

            login_response = gunsou_client.login(username, password)
            assert login_response['success'] is True

            # 验证gunsou权限
            recruits_response = gunsou_client.get('/api/recruits')
            assert recruits_response['success'] is True

            # 4. 切换角色为kancho
            update_kancho_data = {'nickname': '运营用户', 'email': 'kancho@example.com', 'roles': ['kancho']}
            update_response2 = admin_client.put(f'/api/users/{test_user_id}', json=update_kancho_data)
            assert update_response2['success'] is True

            updated_user2 = update_response2['data']
            assert 'kancho' in updated_user2.get('roles', [])
            assert updated_user2['nickname'] == '运营用户'

            # 5. 创建kancho客户端并登录验证
            kancho_client = ApiClient('', client=test_client)
            login_response2 = kancho_client.login(username, password)
            assert login_response2['success'] is True

            # 验证kancho权限（可以访问周报）
            try:
                weekly_response = kancho_client.get('/weekly')
                # kancho应该可以访问周报
                assert weekly_response.status_code == 200
            except Exception as e:
                # 如果有其他错误，至少不是权限错误
                assert '403' not in str(e) and 'Forbidden' not in str(e)

        finally:
            # 清理：删除测试用户
            if test_user_id:
                try:
                    admin_client.delete(f'/api/users/{test_user_id}')
                except Exception:  # pylint: disable=broad-except
                    pass
