"""
应用创建和配置测试
"""
import os
import tempfile
from unittest.mock import patch

import pytest
from flask import Flask

from app import create_app


@pytest.mark.unit
class TestAppCreation:
    """测试应用创建"""
    
    def test_create_app_basic(self, test_config):
        """测试基本应用创建"""
        # 设置环境变量
        for key, value in test_config.items():
            os.environ[key] = str(value)
        
        # 模拟 MongoDB 连接
        with patch('mongoengine.connect'):
            app = create_app()
            
            assert isinstance(app, Flask)
            assert app.config['TESTING'] is True
            assert app.config['SECRET_KEY'] == 'test-secret-key'
            assert app.config['SECURITY_PASSWORD_SALT'] == 'test-password-salt'
    
    def test_app_configuration(self, test_config):
        """测试应用配置"""
        # 设置环境变量
        for key, value in test_config.items():
            os.environ[key] = str(value)
        
        with patch('mongoengine.connect'):
            app = create_app()
            
            # 测试 Flask-Security-Too 配置
            assert app.config['SECURITY_REGISTERABLE'] is False
            assert app.config['SECURITY_RECOVERABLE'] is False
            assert app.config['SECURITY_CHANGEABLE'] is True
            assert app.config['SECURITY_TRACKABLE'] is True
            assert app.config['SECURITY_CONFIRMABLE'] is False
            assert app.config['SECURITY_USERNAME_ENABLE'] is True
            assert app.config['SECURITY_EMAIL_REQUIRED'] is False
            assert app.config['SECURITY_PASSWORD_HASH'] == 'pbkdf2_sha512'
            assert app.config['WTF_CSRF_ENABLED'] is True
            assert app.config['SECURITY_FLASH_MESSAGES'] is True
    
    def test_app_blueprints(self, test_config):
        """测试蓝图注册"""
        # 设置环境变量
        for key, value in test_config.items():
            os.environ[key] = str(value)
        
        with patch('mongoengine.connect'):
            app = create_app()
            
            # 检查蓝图是否注册
            blueprint_names = [bp.name for bp in app.blueprints.values()]
            assert 'main' in blueprint_names
            assert 'admin' in blueprint_names
    
    def test_app_security_initialization(self, test_config):
        """测试安全组件初始化"""
        # 设置环境变量
        for key, value in test_config.items():
            os.environ[key] = str(value)
        
        with patch('mongoengine.connect'):
            app = create_app()
            
            # 检查 Flask-Security-Too 是否初始化
            assert hasattr(app, 'security')
            assert app.security is not None
    
    def test_app_logging_initialization(self, test_config):
        """测试日志初始化"""
        # 设置环境变量
        for key, value in test_config.items():
            os.environ[key] = str(value)
        
        with patch('mongoengine.connect'):
            app = create_app()
            
            # 检查日志记录器
            assert app.logger is not None
            assert app.logger.name == 'flask.app'


@pytest.mark.integration
class TestAppIntegration:
    """应用集成测试"""
    
    def test_app_context(self, app):
        """测试应用上下文"""
        with app.app_context():
            # 在应用上下文中执行操作
            from flask import current_app
            assert current_app is not None
            assert current_app.config['TESTING'] is True
    
    def test_app_client(self, client):
        """测试应用客户端"""
        # 测试基本响应
        response = client.get('/')
        # 由于需要登录，应该重定向到登录页面
        assert response.status_code in [302, 401]  # 重定向或未授权
    
    def test_app_cli_runner(self, runner):
        """测试 CLI 运行器"""
        result = runner.invoke(args=['--help'])
        # CLI 命令可能不存在，但运行器应该工作
        assert result is not None


@pytest.mark.unit
class TestEnvironmentVariables:
    """测试环境变量处理"""
    
    def test_secret_key_fallback(self):
        """测试密钥回退"""
        # 清除环境变量
        if 'SECRET_KEY' in os.environ:
            del os.environ['SECRET_KEY']
        if 'FLASK_SECRET_KEY' in os.environ:
            del os.environ['FLASK_SECRET_KEY']
        
        with patch('mongoengine.connect'):
            app = create_app()
            assert app.config['SECRET_KEY'] == 'dev-secret-key'
    
    def test_secret_key_priority(self):
        """测试密钥优先级"""
        # 设置两个密钥
        os.environ['SECRET_KEY'] = 'primary_key'
        os.environ['FLASK_SECRET_KEY'] = 'fallback_key'
        
        with patch('mongoengine.connect'):
            app = create_app()
            assert app.config['SECRET_KEY'] == 'primary_key'
    
    def test_session_lifetime(self):
        """测试会话超时配置"""
        os.environ['PERMANENT_SESSION_LIFETIME'] = '7200'  # 2小时
        
        with patch('mongoengine.connect'):
            app = create_app()
            assert app.permanent_session_lifetime.total_seconds() == 7200
