"""
测试配置和工具函数
"""
import os
import sys
import tempfile
import logging
from typing import Generator

# 添加项目根目录到 Python 路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from flask import Flask
from mongoengine import connect, disconnect

from app import create_app


@pytest.fixture(scope='session')
def test_config():
    """测试配置"""
    return {
        'TESTING': True,
        'SECRET_KEY': 'test-secret-key',
        'SECURITY_PASSWORD_SALT': 'test-password-salt',
        'SECURITY_REMEMBER_SALT': 'test-remember-salt',
        'SECURITY_DEFAULT_REMEMBER_ME': False,
        'PERMANENT_SESSION_LIFETIME': 3600,
        'MONGODB_URI': 'mongodb://localhost:27017/test_lacus',
        'LOG_LEVEL': 'DEBUG',
        'PYMONGO_LOG_LEVEL': 'WARNING',
    }


@pytest.fixture(scope='session')
def test_db():
    """测试数据库连接"""
    # 连接测试数据库
    connect('test_lacus', host='mongodb://localhost:27017/test_lacus')
    yield
    # 测试结束后断开连接
    disconnect()


@pytest.fixture
def app(test_config) -> Generator[Flask, None, None]:
    """创建测试应用"""
    # 断开现有连接
    try:
        disconnect()
    except:
        pass
    
    # 设置测试环境变量
    for key, value in test_config.items():
        os.environ[key] = str(value)
    
    app = create_app()
    app.config.update(test_config)
    
    with app.app_context():
        yield app
    
    # 清理
    try:
        disconnect()
    except:
        pass


@pytest.fixture
def client(app):
    """测试客户端"""
    return app.test_client()


@pytest.fixture
def runner(app):
    """测试运行器"""
    return app.test_cli_runner()


@pytest.fixture
def temp_log_dir():
    """临时日志目录"""
    with tempfile.TemporaryDirectory() as temp_dir:
        yield temp_dir


@pytest.fixture
def mock_logger():
    """模拟日志记录器"""
    logger = logging.getLogger('test')
    logger.setLevel(logging.DEBUG)
    return logger
