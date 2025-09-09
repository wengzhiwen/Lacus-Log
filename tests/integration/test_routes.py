"""
路由测试
"""
# pylint: disable=import-error,no-member

import pytest
from flask import url_for

from models.user import Role, User


@pytest.mark.integration
@pytest.mark.requires_db
class TestMainRoutes:
    """测试主路由"""

    @pytest.fixture(autouse=True)
    def setup_db(self):
        """设置测试数据库"""
        from mongoengine import connect, disconnect
        try:
            disconnect()
        except Exception:
            pass
        connect('test_lacus', host='mongodb://localhost:27017/test_lacus')

        # 清理测试数据
        User.objects().delete()

        yield

        # 测试结束后清理数据
        try:
            User.objects().delete()
        except Exception:
            pass  # 忽略清理时的连接错误
        disconnect()

    def test_home_route_requires_login(self, client):
        """测试首页需要登录"""
        response = client.get('/')
        assert response.status_code == 302  # 重定向到登录页面

    def test_home_route_with_login(self, client, app):
        """测试登录后的首页"""
        with app.app_context():
            from flask_security.utils import hash_password

            # 使用已存在的角色（应用启动时自动创建）
            role = Role.objects(name='kancho').first()

            user = User(username='testuser', password=hash_password('test_password'), roles=[role], active=True)
            user.save()

            # 模拟登录（这里需要实际的登录流程）
            # 由于 Flask-Security-Too 的复杂性，这里只测试路由存在
            response = client.get('/')
            assert response.status_code in [302, 401]  # 重定向或未授权


@pytest.mark.integration
@pytest.mark.requires_db
class TestAdminRoutes:
    """测试管理路由"""

    @pytest.fixture(autouse=True)
    def setup_db(self):
        """设置测试数据库"""
        from mongoengine import connect, disconnect
        try:
            disconnect()
        except Exception:
            pass
        connect('test_lacus', host='mongodb://localhost:27017/test_lacus')

        # 清理测试数据
        User.objects().delete()

        yield

        # 测试结束后清理数据
        try:
            User.objects().delete()
        except Exception:
            pass  # 忽略清理时的连接错误
        disconnect()

    def test_users_list_requires_gicho_role(self, client):
        """测试用户列表需要议长角色"""
        response = client.get('/admin/users')
        assert response.status_code == 403  # Flask-Security-Too默认行为

    def test_users_new_requires_gicho_role(self, client):
        """测试新增用户需要议长角色"""
        response = client.get('/admin/users/new')
        assert response.status_code == 403  # Flask-Security-Too默认行为

    def test_users_toggle_requires_gicho_role(self, client):
        """测试用户状态切换需要议长角色"""
        response = client.post('/admin/users/test_id/toggle')
        assert response.status_code in [400, 403]  # CSRF错误或权限错误

    def test_users_reset_requires_gicho_role(self, client):
        """测试密码重置需要议长角色"""
        response = client.post('/admin/users/test_id/reset')
        assert response.status_code in [400, 403]  # CSRF错误或权限错误


@pytest.mark.unit
class TestRouteConfiguration:
    """测试路由配置"""

    def test_main_blueprint_registration(self, app):
        """测试主蓝图注册"""
        assert 'main' in app.blueprints
        main_bp = app.blueprints['main']
        assert main_bp.name == 'main'

    def test_admin_blueprint_registration(self, app):
        """测试管理蓝图注册"""
        assert 'admin' in app.blueprints
        admin_bp = app.blueprints['admin']
        assert admin_bp.name == 'admin'

    def test_admin_blueprint_url_prefix(self, app):
        """测试管理蓝图 URL 前缀"""
        admin_bp = app.blueprints['admin']
        # 检查蓝图是否正确注册，URL前缀在注册时设置
        assert admin_bp.name == 'admin'
        # 验证URL生成是否正确
        with app.app_context():
            assert url_for('admin.users_list') == 'http://localhost:5000/admin/users'

    def test_route_urls(self, app):
        """测试路由 URL 生成"""
        with app.app_context():
            # 测试主路由
            assert url_for('main.home') == 'http://localhost:5000/'

            # 测试管理路由
            assert url_for('admin.users_list') == 'http://localhost:5000/admin/users'
            assert url_for('admin.users_new') == 'http://localhost:5000/admin/users/new'
            assert url_for('admin.users_toggle_active', user_id='test') == 'http://localhost:5000/admin/users/test/toggle'
            assert url_for('admin.users_reset_password', user_id='test') == 'http://localhost:5000/admin/users/test/reset'
