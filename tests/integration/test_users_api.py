"""
用户管理 REST API 集成测试

测试原则：
1. 不直接操作数据库
2. 所有操作通过REST API
3. 使用随机数据确保可重复执行
"""
import pytest
from tests.fixtures.factories import user_factory


@pytest.mark.integration
@pytest.mark.users
class TestUsersList:
    """测试用户列表API"""

    def test_get_users_list_success(self, admin_client):
        """测试获取用户列表 - 成功"""
        response = admin_client.get('/api/users')

        assert response['success'] is True
        assert 'data' in response
        assert isinstance(response['data'], list)
        # 至少应该有admin用户
        assert len(response['data']) >= 1
        # 检查分页信息
        assert 'meta' in response
        assert 'pagination' in response['meta']

    def test_get_users_list_with_filters(self, admin_client):
        """测试带过滤条件的用户列表"""
        # 测试按角色过滤
        response = admin_client.get('/api/users', params={'role': 'gicho'})

        assert response['success'] is True
        users = response['data']
        # 所有返回的用户应该都是gicho角色
        for user in users:
            assert 'gicho' in user['roles'] or user['roles'] == ['gicho']

    def test_get_users_list_unauthorized(self, api_client):
        """测试未登录访问用户列表 - 应失败"""
        response = api_client.get('/api/users')

        # Flask-Security会返回401或重定向，这里检查不是成功响应
        assert response.get('success') is not True


@pytest.mark.integration
@pytest.mark.users
class TestUserCreate:
    """测试创建用户API"""

    def test_create_user_success(self, admin_client):
        """测试创建用户 - 成功"""
        user_data = user_factory.create_user_data(role='kancho')

        response = admin_client.post('/api/users', json=user_data)

        assert response['success'] is True
        assert 'data' in response

        created_user = response['data']  # data直接是用户对象
        assert created_user['username'] == user_data['username']
        assert created_user['nickname'] == user_data['nickname']
        assert created_user['email'] == user_data['email']
        assert created_user['active'] is True
        assert 'id' in created_user

        # 清理：删除创建的用户
        admin_client.delete(f"/api/users/{created_user['id']}")

    def test_create_user_with_minimal_data(self, admin_client):
        """测试使用最小必需数据创建用户"""
        user_data = {'username': user_factory.generate_username(), 'password': user_factory.generate_password(), 'role': 'kancho'}

        response = admin_client.post('/api/users', json=user_data)

        assert response['success'] is True
        created_user = response['data']
        assert created_user['username'] == user_data['username']

        # 清理
        admin_client.delete(f"/api/users/{created_user['id']}")

    def test_create_user_without_role_defaults_to_kancho(self, admin_client):
        """测试不提供角色时默认为kancho"""
        user_data = {'username': user_factory.generate_username(), 'password': user_factory.generate_password()}

        response = admin_client.post('/api/users', json=user_data)

        assert response['success'] is True
        created_user = response['data']
        assert created_user['username'] == user_data['username']
        # 验证默认角色是kancho
        assert 'kancho' in created_user['roles']

        # 清理
        admin_client.delete(f"/api/users/{created_user['id']}")

    def test_create_user_duplicate_username(self, admin_client):
        """测试创建重复用户名 - 应失败"""
        user_data = user_factory.create_user_data()

        # 第一次创建
        response1 = admin_client.post('/api/users', json=user_data)
        assert response1['success'] is True
        user_id = response1['data']['id']

        # 第二次创建（相同用户名）
        response2 = admin_client.post('/api/users', json=user_data)
        assert response2['success'] is False
        assert 'error' in response2

        # 清理
        admin_client.delete(f"/api/users/{user_id}")

    def test_create_user_missing_required_fields(self, admin_client):
        """测试缺少必需字段 - 应失败"""
        # 缺少username
        response = admin_client.post('/api/users', json={'password': '123456', 'role': 'kancho'})
        assert response['success'] is False

        # 缺少password
        response = admin_client.post('/api/users', json={'username': user_factory.generate_username(), 'role': 'kancho'})
        assert response['success'] is False

        # 缺少role（现在应该成功，自动默认为kancho）
        response = admin_client.post('/api/users', json={'username': user_factory.generate_username(), 'password': '123456'})
        assert response['success'] is True
        created_user = response['data']
        # 验证默认角色是kancho
        assert 'kancho' in created_user['roles']

        # 清理
        admin_client.delete(f"/api/users/{created_user['id']}")

    def test_create_user_invalid_role(self, admin_client):
        """测试无效角色 - 应失败"""
        user_data = user_factory.create_user_data(role='invalid_role')

        response = admin_client.post('/api/users', json=user_data)
        assert response['success'] is False


@pytest.mark.integration
@pytest.mark.users
class TestUserDetail:
    """测试获取用户详情API"""

    def test_get_user_detail_success(self, admin_client):
        """测试获取用户详情 - 成功"""
        # 先创建一个用户
        user_data = user_factory.create_user_data()
        create_response = admin_client.post('/api/users', json=user_data)
        user_id = create_response['data']['id']

        # 获取详情
        response = admin_client.get(f'/api/users/{user_id}')

        assert response['success'] is True
        assert 'data' in response

        user = response['data']  # data直接是用户对象
        assert user['id'] == user_id
        assert user['username'] == user_data['username']
        assert user['nickname'] == user_data['nickname']

        # 清理
        admin_client.delete(f'/api/users/{user_id}')

    def test_get_user_detail_not_found(self, admin_client):
        """测试获取不存在的用户 - 应返回404"""
        response = admin_client.get('/api/users/nonexistent_id_123456')

        assert response['success'] is False


@pytest.mark.integration
@pytest.mark.users
class TestUserUpdate:
    """测试更新用户API"""

    def test_update_user_success(self, admin_client):
        """测试更新用户信息 - 成功"""
        # 创建用户
        user_data = user_factory.create_user_data()
        create_response = admin_client.post('/api/users', json=user_data)
        user_id = create_response['data']['id']

        # 更新信息
        new_nickname = user_factory.generate_nickname()
        new_email = user_factory.generate_email()

        update_data = {'nickname': new_nickname, 'email': new_email}

        response = admin_client.put(f'/api/users/{user_id}', json=update_data)

        assert response['success'] is True
        updated_user = response['data']
        assert updated_user['nickname'] == new_nickname
        assert updated_user['email'] == new_email
        # 用户名不应改变
        assert updated_user['username'] == user_data['username']

        # 清理
        admin_client.delete(f'/api/users/{user_id}')

    def test_update_user_not_found(self, admin_client):
        """测试更新不存在的用户 - 应失败"""
        response = admin_client.put('/api/users/nonexistent_id', json={'nickname': '新昵称'})

        assert response['success'] is False


@pytest.mark.integration
@pytest.mark.users
class TestUserActivation:
    """测试用户激活/停用API"""

    def test_toggle_user_activation_success(self, admin_client):
        """测试切换用户激活状态 - 成功"""
        # 创建用户（默认激活）
        user_data = user_factory.create_user_data()
        create_response = admin_client.post('/api/users', json=user_data)
        user_id = create_response['data']['id']

        # 停用用户
        response1 = admin_client.patch(f'/api/users/{user_id}/activation', json={'active': False})
        assert response1['success'] is True
        assert response1['data']['active'] is False

        # 再次激活
        response2 = admin_client.patch(f'/api/users/{user_id}/activation', json={'active': True})
        assert response2['success'] is True
        assert response2['data']['active'] is True

        # 清理
        admin_client.delete(f'/api/users/{user_id}')

    def test_deactivate_last_admin_should_fail(self, admin_client):
        """测试停用最后一个管理员 - 应失败"""
        # 获取所有管理员
        response = admin_client.get('/api/users', params={'role': 'gicho'})
        admins = [u for u in response['data'] if u['active']]

        if len(admins) == 1:
            # 只有一个激活的管理员，尝试停用应该失败
            admin_id = admins[0]['id']
            response = admin_client.patch(f'/api/users/{admin_id}/activation', json={'active': False})

            # 应该失败
            assert response['success'] is False
            assert 'CANNOT_DEACTIVATE_LAST_ADMIN' in str(response.get('error', {}))


@pytest.mark.integration
@pytest.mark.users
class TestUserPasswordReset:
    """测试重置用户密码API"""

    def test_reset_user_password_success(self, admin_client):
        """测试重置用户密码 - 成功"""
        # 创建用户
        user_data = user_factory.create_user_data()
        original_password = user_data['password']

        create_response = admin_client.post('/api/users', json=user_data)
        user_id = create_response['data']['id']
        username = user_data['username']

        # 重置密码
        reset_response = admin_client.post(f'/api/users/{user_id}/reset-password')
        assert reset_response['success'] is True

        # 验证旧密码无法登录
        from tests.fixtures.api_client import ApiClient
        test_client = ApiClient(admin_client.base_url, client=admin_client.client)
        login_old = test_client.login(username, original_password)
        assert login_old['success'] is False

        # 验证新密码（123456）可以登录
        login_new = test_client.login(username, '123456')
        assert login_new['success'] is True

        # 清理
        admin_client.delete(f'/api/users/{user_id}')


@pytest.mark.integration
@pytest.mark.users
class TestUserOperatorsList:
    """测试获取运营列表API"""

    def test_get_operators_list_success(self, admin_client):
        """测试获取运营列表 - 成功"""
        response = admin_client.get('/api/users/operators')

        assert response['success'] is True
        assert 'data' in response
        assert isinstance(response['data'], list)  # data直接是数组

    def test_get_operators_list_as_kancho(self, kancho_client):
        """测试运营身份获取运营列表 - 成功"""
        response = kancho_client.get('/api/users/operators')
        
        assert response['success'] is True
        assert 'data' in response
        assert isinstance(response['data'], list)


@pytest.mark.integration
@pytest.mark.users
class TestUserEmails:
    """测试获取用户邮箱列表API"""

    def test_get_user_emails_success(self, admin_client):
        """测试获取用户邮箱列表 - 成功"""
        response = admin_client.get('/api/users/emails')

        assert response['success'] is True
        assert 'emails' in response['data']
        assert isinstance(response['data']['emails'], list)

    def test_get_user_emails_with_role_filter(self, admin_client):
        """测试按角色过滤邮箱"""
        response = admin_client.get('/api/users/emails', params={'role': 'gicho'})

        assert response['success'] is True
        assert 'emails' in response['data']


@pytest.mark.integration
@pytest.mark.users
class TestUserWorkflow:
    """测试用户管理完整工作流"""

    def test_complete_user_lifecycle(self, admin_client):
        """测试完整的用户生命周期：创建->查询->更新->停用->激活->删除"""
        # 1. 创建用户
        user_data = user_factory.create_user_data()
        create_response = admin_client.post('/api/users', json=user_data)
        assert create_response['success'] is True
        user_id = create_response['data']['id']

        # 2. 查询用户详情
        detail_response = admin_client.get(f'/api/users/{user_id}')
        assert detail_response['success'] is True
        assert detail_response['data']['username'] == user_data['username']

        # 3. 更新用户信息
        new_nickname = user_factory.generate_nickname()
        update_response = admin_client.put(f'/api/users/{user_id}', json={'nickname': new_nickname})
        assert update_response['success'] is True
        assert update_response['data']['nickname'] == new_nickname

        # 4. 停用用户
        deactivate_response = admin_client.patch(f'/api/users/{user_id}/activation', json={'active': False})
        assert deactivate_response['success'] is True
        assert deactivate_response['data']['active'] is False

        # 5. 验证停用后用户无法登录
        from tests.fixtures.api_client import ApiClient
        from app import create_app
        app = create_app()
        with app.test_client() as fresh_client:
            test_client = ApiClient(admin_client.base_url, client=fresh_client)
            login_response = test_client.login(user_data['username'], user_data['password'])
            assert login_response['success'] is False

        # 6. 重新激活用户
        activate_response = admin_client.patch(f'/api/users/{user_id}/activation', json={'active': True})
        assert activate_response['success'] is True
        assert activate_response['data']['active'] is True

        # 7. 验证激活后可以登录
        with app.test_client() as another_fresh_client:
            activated_test_client = ApiClient(admin_client.base_url, client=another_fresh_client)
            login_response2 = activated_test_client.login(user_data['username'], user_data['password'])
            assert login_response2['success'] is True

        # 8. 删除用户
        delete_response = admin_client.delete(f'/api/users/{user_id}')
        assert delete_response['success'] is True

        # 9. 验证删除后无法查询
        detail_response2 = admin_client.get(f'/api/users/{user_id}')
        assert detail_response2['success'] is False
