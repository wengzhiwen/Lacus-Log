"""
套件S1：认证与安全基线测试

覆盖 API：/api/auth/*, /api/users/me, 任意需要鉴权的 GET

测试原则：
1. 不直接操作数据库
2. 所有操作通过REST API
3. 验证JWT和CSRF机制
4. 测试角色权限控制
"""
import time

import pytest


@pytest.mark.suite("S1")
@pytest.mark.auth_security
class TestS1AuthSecurity:
    """认证与安全基线测试套件"""

    def test_s1_tc1_login_and_token_lifecycle(self, api_client):
        """
        S1-TC1 登录与Token生命周期

        步骤：使用默认管理员账号登录 → 获取 access token → 调用受保护接口成功 →
              验证token持续有效 → 登出。

        断言：响应 success=true，token认证正常工作，登出成功。
        """
        # 使用已知的管理员账号登录
        admin_username = 'zala'
        admin_password = 'plant4ever'

        # 1. 登录获取tokens
        login_response = api_client.login(admin_username, admin_password)

        assert login_response['success'] is True
        assert 'access_token' in login_response['data']
        # refresh_token 可能不直接返回，而是通过cookie设置

        # 2. 使用获得的token调用受保护接口
        me_response = api_client.get('/api/auth/me')

        assert me_response['success'] is True
        assert 'data' in me_response
        assert me_response['data']['user']['username'] == admin_username

        # 3. 测试当前token持续有效
        me_response_again = api_client.get('/api/auth/me')
        assert me_response_again['success'] is True
        assert me_response_again['data']['user']['username'] == admin_username

        # 4. 登出
        logout_response = api_client.post('/api/auth/logout')
        assert logout_response['success'] is True

    def test_s1_tc2_unauthorized_access_control(self, api_client):
        """
        S1-TC2 未认证访问控制

        步骤：不带 token 访问 /api/users、/api/bbs/posts。

        断言：返回 401/403，错误码符合规范。
        """
        # 1. 访问需要认证的接口
        users_response = api_client.get('/api/users')

        # 应该返回未认证错误
        assert users_response.get('success') is not True
        assert users_response['_status_code'] in [401, 403]

        if 'error' in users_response:
            assert 'code' in users_response['error']
            assert 'message' in users_response['error']

        # 2. 访问BBS帖子列表（应该需要认证）
        bbs_response = api_client.get('/api/bbs/posts')

        assert bbs_response.get('success') is not True
        assert bbs_response['_status_code'] in [401, 403]

    def test_s1_tc3_csrf_validation(self, api_client):
        """
        S1-TC3 CSRF校验

        步骤：缺失 X-CSRF-Token 直接 POST /api/bbs/posts。

        断言：返回 401，错误码等于 CSRF_INVALID。
        """
        # 先获取有效的JWT token但不获取CSRF token
        admin_username = 'zala'
        admin_password = 'plant4ever'

        login_response = api_client.login(admin_username, admin_password)
        assert login_response['success'] is True

        # 清除CSRF token以模拟缺失情况
        original_csrf_token = api_client.csrf_token
        api_client.csrf_token = None

        # 尝试进行需要CSRF保护的POST请求
        post_data = {'title': '测试帖子', 'content': '这是一个测试帖子', 'category': '其他'}

        response = api_client.post('/api/bbs/posts', json=post_data)

        # 应该返回CSRF错误
        assert response.get('success') is not True
        assert response['_status_code'] == 401

        if 'error' in response:
            assert response['error']['code'] in ['CSRF_INVALID', 'CSRF_MISSING', 'CSRF_SESSION_MISSING']

        # 恢复CSRF token
        api_client.csrf_token = original_csrf_token

    def test_s1_tc4_role_based_authorization(self, admin_client, kancho_client):
        """
        S1-TC4 角色鉴权

        步骤：使用 kancho 账号访问管理员专属接口（如 POST /api/users）。

        断言：返回 403，错误信息提示权限不足。
        """
        from tests.fixtures.factories import user_factory

        # 使用kancho账号尝试访问管理员专属接口
        # 1. 尝试创建用户（需要管理员权限）
        new_user_data = user_factory.create_user_data(role='kancho')

        create_user_response = kancho_client.post('/api/users', json=new_user_data)

        # 应该返回权限不足错误
        assert create_user_response.get('success') is not True
        assert create_user_response['_status_code'] in [403, 401]

        if 'error' in create_user_response:
            error_code = create_user_response['error']['code']
            assert error_code in ['INSUFFICIENT_PERMISSIONS', 'ACCESS_DENIED', 'FORBIDDEN']

        # 2. 验证管理员可以正常创建用户
        admin_user_data = user_factory.create_user_data(role='kancho')

        admin_create_response = admin_client.post('/api/users', json=admin_user_data)

        assert admin_create_response['success'] is True
        assert 'data' in admin_create_response
        created_user_id = admin_create_response['data']['id']

        # 3. 清理创建的测试用户
        try:
            # 停用用户而不是删除
            admin_client.patch(f'/api/users/{created_user_id}/activation', json={'active': False})
        except Exception:  # pylint: disable=broad-except
            pass

    def test_s1_tc5_jwt_token_validation(self, admin_client):
        """
        S1-TC5 JWT Token验证（额外测试）

        步骤：验证当前token有效性，测试不同受保护接口的访问。

        断言：有效token可以正常访问所有受保护接口。
        """
        # 1. 验证当前token有效
        me_response = admin_client.get('/api/auth/me')
        assert me_response['success'] is True
        assert me_response['data']['user']['username'] == 'zala'

        # 2. 测试访问其他受保护接口
        users_response = admin_client.get('/api/users')
        assert users_response['success'] is True

        # 3. 验证token一致性
        current_token = admin_client.access_token
        assert current_token is not None

        # 4. 再次验证用户信息接口
        me_again = admin_client.get('/api/auth/me')
        assert me_again['success'] is True
        assert me_again['data']['user']['username'] == 'zala'

    def test_s1_tc6_session_isolation(self, admin_client, kancho_client):
        """
        S1-TC6 会话隔离（额外测试）

        步骤：使用不同角色的客户端进行操作，验证会话隔离。

        断言：不同客户端的会话互不影响。
        """
        # 管理员访问自己的信息
        admin_me_response = admin_client.get('/api/auth/me')
        assert admin_me_response['success'] is True

        # 运营访问自己的信息
        kancho_me_response = kancho_client.get('/api/auth/me')
        assert kancho_me_response['success'] is True

        # 验证返回的是不同用户的信息
        admin_user = admin_me_response['data']['user']
        kancho_user = kancho_me_response['data']['user']

        assert admin_user['username'] != kancho_user['username']
        assert 'gicho' in admin_user.get('roles', [])
        assert 'kancho' in kancho_user.get('roles', [])

    def test_s1_tc7_refresh_token_lifecycle(self, api_client):
        """
        S1-TC7 Refresh Token 生命周期测试

        步骤：登录获取 tokens → 使用 refresh_token() 刷新 access token → 
              验证新 token 有效 → 验证旧 token 和新 token 不同。

        断言：刷新成功，新 token 可正常使用，token 内容已更新。
        
        注意：此测试使用特殊的 refresh_token() 方法，该方法模拟真实浏览器行为，
              不在 header 中发送 access token，仅依赖 cookie 中的 refresh token。
        """
        admin_username = 'zala'
        admin_password = 'plant4ever'

        # 1. 登录获取初始 tokens
        login_response = api_client.login(admin_username, admin_password)
        assert login_response['success'] is True
        assert 'access_token' in login_response['data']

        original_access_token = api_client.access_token
        assert original_access_token is not None

        # 2. 等待短暂时间（确保token时间戳不同）
        time.sleep(1)

        # 3. 使用 refresh_token() 方法刷新 access token
        refresh_response = api_client.refresh_token()

        # 4. 验证刷新成功
        assert refresh_response['success'] is True, f"刷新失败: {refresh_response.get('error', {})}"
        assert 'access_token' in refresh_response['data']

        # 5. 验证获得新的 access token
        new_access_token = api_client.access_token
        assert new_access_token is not None
        assert new_access_token != original_access_token, "新 token 应该与旧 token 不同"

        # 6. 验证新 token 可以正常工作
        me_response = api_client.get('/api/auth/me')
        assert me_response['success'] is True
        assert me_response['data']['user']['username'] == admin_username

        # 7. 验证可以继续使用新 token 访问其他接口
        me_response_again = api_client.get('/api/auth/me')
        assert me_response_again['success'] is True
