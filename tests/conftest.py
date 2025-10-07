"""
Pytest 配置和共享 fixtures
"""
import os
import pytest
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

# 设置测试环境变量
os.environ['FLASK_ENV'] = 'testing'
os.environ['TESTING'] = 'True'

# 使用独立的测试数据库（如果需要）
if not os.getenv('MONGODB_URI_TEST'):
    # 默认使用测试数据库
    os.environ['MONGODB_URI'] = os.getenv('MONGODB_URI', 'mongodb://127.0.0.1:27017/lacus') + '_test'
else:
    os.environ['MONGODB_URI'] = os.getenv('MONGODB_URI_TEST')


@pytest.fixture(scope='session')
def app():
    """创建Flask应用实例（会话级别，整个测试会话共享一个实例）"""
    from app import create_app

    flask_app = create_app()
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False  # 测试时禁用CSRF（通过API的CSRF单独测试）
    flask_app.config['JWT_COOKIE_SECURE'] = False  # 测试环境不需要HTTPS
    flask_app.config['SESSION_COOKIE_SECURE'] = False  # 测试环境不需要HTTPS

    yield flask_app


@pytest.fixture(scope='session')
def base_url():
    """API基础URL"""
    return os.getenv('TEST_BASE_URL', 'http://localhost:5080')


@pytest.fixture(scope='function')
def client(app):
    """Flask测试客户端"""
    return app.test_client()
