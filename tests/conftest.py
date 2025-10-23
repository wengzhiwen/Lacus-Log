"""
Pytest 配置和共享 fixtures
"""
import os
import uuid

import pytest
from dotenv import load_dotenv
from pymongo import MongoClient

# 加载环境变量
load_dotenv()

# 设置测试环境变量
os.environ['FLASK_ENV'] = 'testing'
os.environ['TESTING'] = 'True'


@pytest.fixture(scope='session')
def test_db_name():
    """生成随机的测试数据库名称"""
    # 使用UUID生成唯一的数据库名
    random_suffix = str(uuid.uuid4().hex)[:8]
    db_name = f"lacus_test_{random_suffix}"
    return db_name


@pytest.fixture(scope='session')
def mongodb_uri(test_db_name):
    """构建测试数据库URI"""
    # 获取基础MongoDB URI（去除数据库名）
    base_uri = os.getenv('MONGODB_URI', 'mongodb://127.0.0.1:27017/lacus')

    # 如果URI包含数据库名，去除它
    if '/' in base_uri:
        parts = base_uri.rsplit('/', 1)
        base_uri = parts[0]

    # 构建测试数据库URI
    test_uri = f"{base_uri}/{test_db_name}"

    # 设置环境变量，让Flask应用使用这个数据库
    os.environ['MONGODB_URI'] = test_uri

    return test_uri


@pytest.fixture(scope='session')
def app(mongodb_uri, test_db_name):
    """创建Flask应用实例（会话级别，整个测试会话共享一个实例）
    
    每次运行时使用随机生成的数据库，会自动创建：
    - 默认角色：gicho（管理员）、kancho（运营）
    - 默认管理员：zala / plant4ever
    """
    from app import create_app

    flask_app = create_app()
    flask_app.config['TESTING'] = True
    flask_app.config['WTF_CSRF_ENABLED'] = False  # 测试时禁用CSRF（通过API的CSRF单独测试）
    flask_app.config['JWT_COOKIE_SECURE'] = False  # 测试环境不需要HTTPS
    flask_app.config['SESSION_COOKIE_SECURE'] = False  # 测试环境不需要HTTPS

    # 记录使用的数据库名
    flask_app.logger.info('测试使用数据库: %s', test_db_name)

    yield flask_app

    # 测试会话结束后，清理测试数据库
    try:
        # 从MongoDB URI中提取连接信息
        if '://' in mongodb_uri:
            # 解析URI获取主机和数据库名
            parts = mongodb_uri.split('/')
            host_part = '/'.join(parts[:-1])  # mongodb://host:port

            # 连接到MongoDB并删除测试数据库
            client = MongoClient(host_part)
            client.drop_database(test_db_name)
            client.close()

            flask_app.logger.info('已清理测试数据库: %s', test_db_name)
    except Exception as e:
        flask_app.logger.warning('清理测试数据库失败: %s', str(e))


@pytest.fixture(scope='session')
def base_url():
    """API基础URL"""
    return os.getenv('TEST_BASE_URL', 'http://localhost:5080')


@pytest.fixture(scope='function')
def client(app):
    """Flask测试客户端"""
    return app.test_client()
