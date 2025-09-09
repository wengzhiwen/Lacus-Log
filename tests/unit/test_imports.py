"""
核心模块导入测试
"""
import pytest


@pytest.mark.unit
class TestImports:
    """测试核心模块导入"""
    
    def test_app_import(self):
        """测试应用模块导入"""
        from app import create_app, app
        assert create_app is not None
        assert app is not None
    
    def test_models_import(self):
        """测试模型模块导入"""
        from models.user import User, Role
        assert User is not None
        assert Role is not None
    
    def test_utils_import(self):
        """测试工具模块导入"""
        from utils.logging_setup import init_logging, get_logger
        from utils.security import create_user_datastore, init_security
        from utils.bootstrap import ensure_initial_roles_and_admin
        
        assert init_logging is not None
        assert get_logger is not None
        assert create_user_datastore is not None
        assert init_security is not None
        assert ensure_initial_roles_and_admin is not None
    
    def test_routes_import(self):
        """测试路由模块导入"""
        from routes.main import main_bp
        from routes.admin import admin_bp
        
        assert main_bp is not None
        assert admin_bp is not None
    
    def test_flask_security_import(self):
        """测试 Flask-Security-Too 导入"""
        from flask_security import Security
        from flask_security.utils import hash_password, verify_password
        from flask_security.datastore import MongoEngineUserDatastore
        
        assert Security is not None
        assert hash_password is not None
        assert verify_password is not None
        assert MongoEngineUserDatastore is not None
