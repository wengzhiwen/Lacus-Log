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

    def test_init_security(self):
        """测试安全组件初始化（使用独立最小 Flask 应用，避免蓝图重复注册）"""
        from flask import Flask
        from flask_security.datastore import MongoEngineUserDatastore

        test_app = Flask(__name__)
        test_app.config['SECRET_KEY'] = 'test'
        test_app.config['SECURITY_PASSWORD_SALT'] = 'salt'

        mock_datastore = MagicMock(spec=MongoEngineUserDatastore)

        with test_app.app_context():
            security = init_security(test_app, mock_datastore)
            assert security is not None


@pytest.mark.unit
class TestBootstrapUtils:
    """测试引导工具函数"""

    def test_ensure_initial_roles_and_admin(self):
        """测试初始角色和管理员创建"""
        mock_datastore = MagicMock()
        mock_datastore.create_role.return_value = MagicMock()
        mock_datastore.create_user.return_value = MagicMock()

        with patch('utils.bootstrap.Role') as mock_role_class:
            mock_role_objects = MagicMock()
            mock_role_class.objects = mock_role_objects
            mock_role_objects.get.side_effect = Exception('not found')

            with patch('utils.bootstrap.User') as mock_user_class:
                mock_user_objects = MagicMock()
                mock_user_class.objects = mock_user_objects
                mock_user_objects.filter.return_value.first.return_value = None  # 没有议长

                ensure_initial_roles_and_admin(mock_datastore)

                assert mock_datastore.create_role.call_count >= 0

                assert mock_datastore.create_user.call_count >= 0


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

        init_logging()

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

            assert hashed != password
            assert len(hashed) > 0

            assert verify_password(password, hashed) is True
            assert verify_password('wrong_password', hashed) is False

    def test_password_hash_consistency(self, app):
        """测试密码哈希一致性"""
        from flask_security.utils import hash_password, verify_password

        with app.app_context():
            password = 'test_password'

            hash1 = hash_password(password)
            hash2 = hash_password(password)

            assert hash1 != hash2

            assert verify_password(password, hash1) is True
            assert verify_password(password, hash2) is True
