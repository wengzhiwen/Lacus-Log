"""
工具函数测试
"""
import pytest
from unittest.mock import patch, MagicMock

from utils.security import create_user_datastore, init_security
from utils.bootstrap import ensure_initial_roles_and_admin


@pytest.mark.unit
class TestSecurityUtils:
    """测试安全工具函数"""

    def test_create_user_datastore(self):
        """测试用户数据存储创建"""
        from models.user import User, Role

        datastore = create_user_datastore()
        assert datastore is not None
        assert datastore.user_model == User
        assert datastore.role_model == Role

    def test_init_security(self, app):
        """测试安全组件初始化"""
        from flask_security.datastore import MongoEngineUserDatastore

        # 创建模拟数据存储
        mock_datastore = MagicMock(spec=MongoEngineUserDatastore)

        security = init_security(app, mock_datastore)
        assert security is not None
        assert hasattr(app, 'security')


@pytest.mark.unit
class TestBootstrapUtils:
    """测试引导工具函数"""

    def test_ensure_initial_roles_and_admin(self):
        """测试初始角色和管理员创建"""
        # 创建模拟数据存储
        mock_datastore = MagicMock()
        mock_datastore.create_role.return_value = MagicMock()
        mock_datastore.create_user.return_value = MagicMock()

        # 模拟 Role.objects
        with patch('utils.bootstrap.Role') as mock_role_class:
            mock_role_objects = MagicMock()
            mock_role_class.objects = mock_role_objects

            # 模拟角色查询
            mock_gicho_role = MagicMock()
            mock_gicho_role.name = 'gicho'
            mock_role_objects.get.return_value = mock_gicho_role

            # 模拟用户查询
            with patch('utils.bootstrap.User') as mock_user_class:
                mock_user_objects = MagicMock()
                mock_user_class.objects = mock_user_objects
                mock_user_objects.filter.return_value.first.return_value = None  # 没有议长

                # 执行函数
                ensure_initial_roles_and_admin(mock_datastore)

                # 验证角色创建
                assert mock_datastore.create_role.call_count >= 2  # gicho 和 kancho

                # 验证用户创建
                mock_datastore.create_user.assert_called_once()


@pytest.mark.unit
class TestLoggingUtils:
    """测试日志工具函数"""

    def test_get_logger(self):
        """测试获取日志记录器"""
        from utils.logging_setup import get_logger

        logger = get_logger('test_module')
        assert logger is not None
        assert logger.name == 'test_module'

    def test_init_logging(self):
        """测试日志初始化"""
        from utils.logging_setup import init_logging

        # 这个测试主要确保函数不抛出异常
        init_logging()

        # 验证日志记录器存在
        import logging
        app_logger = logging.getLogger('app')
        flask_logger = logging.getLogger('flask.app')

        assert app_logger is not None
        assert flask_logger is not None


@pytest.mark.unit
class TestPasswordUtils:
    """测试密码工具函数"""

    def test_password_hashing(self, app):
        """测试密码哈希"""
        from flask_security.utils import hash_password, verify_password

        with app.app_context():
            password = 'test_password'
            hashed = hash_password(password)

            # 验证哈希结果
            assert hashed != password
            assert len(hashed) > 0

            # 验证密码验证
            assert verify_password(password, hashed) is True
            assert verify_password('wrong_password', hashed) is False

    def test_password_hash_consistency(self, app):
        """测试密码哈希一致性"""
        from flask_security.utils import hash_password, verify_password

        with app.app_context():
            password = 'test_password'

            # 多次哈希同一密码应该得到不同结果（盐值不同）
            hash1 = hash_password(password)
            hash2 = hash_password(password)

            assert hash1 != hash2

            # 但都应该能验证原始密码
            assert verify_password(password, hash1) is True
            assert verify_password(password, hash2) is True
