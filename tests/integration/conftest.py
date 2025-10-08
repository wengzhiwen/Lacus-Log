"""
集成测试专用 fixtures
"""
import pytest
import os
from tests.fixtures.api_client import ApiClient


@pytest.fixture(scope='function')
def api_client(base_url, client):
    """
    API客户端fixture
    
    使用Flask test_client，不需要启动真实服务器
    """
    return ApiClient(base_url, client=client)


@pytest.fixture(scope='function')
def admin_client(api_client):
    """
    管理员身份的API客户端
    
    自动登录为管理员（使用传统session认证）
    """
    # 获取管理员账号
    admin_username = os.getenv('TEST_ADMIN_USERNAME', 'zala')
    admin_password = os.getenv('TEST_ADMIN_PASSWORD', 'plant4ever')

    # 使用传统的Flask-Security登录表单（维护session）
    # Flask test_client会自动管理session cookies
    login_response = api_client.client.post('/login', data={'username': admin_username, 'password': admin_password}, follow_redirects=True)

    if login_response.status_code != 200:
        pytest.fail(f"管理员登录失败: HTTP {login_response.status_code}")

    # 同时也获取JWT token和CSRF token（通过REST API）
    jwt_response = api_client.login(admin_username, admin_password)
    if not jwt_response.get('success'):
        pytest.fail(f"获取JWT token失败: {jwt_response.get('error', {}).get('message', '未知错误')}")

    yield api_client

    # 测试结束后登出
    try:
        api_client.client.post('/logout')
    except:
        pass


@pytest.fixture(scope='function')
def kancho_client(base_url, client, admin_client):
    """
    运营身份的API客户端
    
    自动创建一个临时运营账号并登录
    注意：使用独立的test_client以避免session冲突
    """
    from tests.fixtures.factories import user_factory

    # 生成运营账号数据
    user_data = user_factory.create_user_data(role='kancho')

    # 使用管理员权限创建运营账号
    response = admin_client.post('/api/users', json=user_data)

    if not response.get('success'):
        pytest.fail(f"创建运营账号失败: {response.get('error', {}).get('message', '未知错误')}")

    # API返回的data直接是用户对象
    user_id = response['data']['id']
    username = user_data['username']
    password = user_data['password']

    # ⚠️ 重要：为kancho创建独立的test_client，避免与admin_client的session冲突
    # 获取Flask app并创建新的test_client
    flask_app = client.application
    independent_test_client = flask_app.test_client()
    
    # 创建新的ApiClient（使用独立的test_client）
    new_client = ApiClient(base_url, client=independent_test_client)

    # 使用传统登录（维护session）
    login_resp = new_client.client.post('/login', data={'username': username, 'password': password}, follow_redirects=True)

    if login_resp.status_code != 200:
        pytest.fail(f"运营登录失败: HTTP {login_resp.status_code}")

    # 同时获取JWT token
    jwt_response = new_client.login(username, password)
    if not jwt_response.get('success'):
        pytest.fail(f"获取JWT token失败: {jwt_response.get('error', {}).get('message', '未知错误')}")

    yield new_client

    # 测试结束后清理
    try:
        new_client.client.post('/logout')
        # 使用管理员停用该运营账号（系统不支持删除用户，只能停用）
        admin_client.patch(f'/api/users/{user_id}/activation', json={'active': False})
    except:
        pass
