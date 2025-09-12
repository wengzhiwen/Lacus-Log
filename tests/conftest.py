"""
测试配置和工具函数
"""
import logging
import os
import sys
import tempfile
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
        'SERVER_NAME': 'localhost:5000',
        'APPLICATION_ROOT': '/',
        'PREFERRED_URL_SCHEME': 'http',
    }


@pytest.fixture(scope='session', autouse=True)
def test_db():
    """测试数据库连接 - 自动使用，确保所有测试都有数据库连接"""
    # 先断开任何现有连接
    try:
        disconnect()
    except:
        pass
    
    # 连接测试数据库
    connect(host='mongodb://localhost:27017/test_lacus', uuidRepresentation='standard')
    yield
    # 测试结束后断开连接
    disconnect()


@pytest.fixture
def app(test_config) -> Generator[Flask, None, None]:
    """创建测试应用"""
    # 设置测试环境变量（在创建应用之前）
    for key, value in test_config.items():
        os.environ[key] = str(value)

    # 为避免别名冲突，先断开可能存在的默认连接，让 create_app 自行连接
    try:
        disconnect()
    except Exception:
        pass

    app = create_app()
    app.config.update(test_config)

    with app.app_context():
        yield app


@pytest.fixture(autouse=True)
def app_context(app):
    """为所有测试自动提供应用上下文。"""
    with app.app_context():
        yield


@pytest.fixture(autouse=True)
def request_context(app):
    """为所有测试自动提供请求上下文，确保 current_user 等可用。"""
    with app.test_request_context():
        yield

@pytest.fixture(autouse=True)
def clean_db_between_tests():
    """每个用例前清空 test_lacus 库并重建必要索引，避免唯一约束相互影响。"""
    from mongoengine.connection import get_db
    from models.user import User, Role
    try:
        db = get_db()
        for name in db.list_collection_names():
            db.drop_collection(name)
        Role.ensure_indexes()
        User.ensure_indexes()
    except Exception:
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
