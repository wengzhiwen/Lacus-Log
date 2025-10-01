"""
用户模型测试
"""
# pylint: disable=import-error,no-member
import pytest
from mongoengine import connect, disconnect

from models.user import User, Role
from models.pilot import Pilot, Gender


@pytest.mark.unit
class TestUserModel:
    """测试用户模型"""

    def test_role_creation(self):
        """测试角色创建"""
        role = Role(name='test_role', description='测试角色')
        assert role.name == 'test_role'
        assert role.description == '测试角色'
        assert role.permissions == []

    def test_role_get_permissions(self):
        """测试角色权限获取"""
        role = Role(name='test_role', permissions=['read', 'write'])
        permissions = role.get_permissions()
        assert permissions == {'read', 'write'}

    def test_user_creation(self):
        """测试用户创建"""
        user = User(username='test_user', password='hashed_password', nickname='测试用户')
        assert user.username == 'test_user'
        assert user.password == 'hashed_password'
        assert user.nickname == '测试用户'
        assert user.active is True
        assert user.created_at is not None
        assert user.fs_uniquifier is not None
        assert user.login_count == 0

    def test_user_properties(self):
        """测试用户属性"""
        user = User(username='test_user', password='password')

        assert user.is_active is True
        assert user.is_authenticated is True
        assert user.is_anonymous is False

        user.active = False
        assert user.is_active is False

    def test_user_get_id(self):
        """测试用户 ID 获取"""
        user = User(username='test_user', password='password')
        user_id = user.get_id()
        assert user_id == user.fs_uniquifier
        assert isinstance(user_id, str)

    def test_user_has_role(self):
        """测试用户角色检查"""
        role = Role(name='admin', description='管理员')
        user = User(username='test_user', password='password', roles=[role])

        assert user.has_role('admin') is True
        assert user.has_role('user') is False

        assert user.has_role(role) is True

        assert user.has_role(None) is False
        assert user.has_role('') is False

    def test_user_verify_password(self, app):
        """测试密码验证"""
        from flask_security.utils import hash_password

        with app.app_context():
            password = 'test_password'
            hashed = hash_password(password)

            user = User(username='test_user', password=hashed)

            assert user.verify_and_update_password(password) is True

            assert user.verify_and_update_password('wrong_password') is False


@pytest.mark.integration
@pytest.mark.requires_db
class TestUserModelIntegration:
    """用户模型集成测试"""

    @pytest.fixture(autouse=True)
    def setup_db(self):
        """设置测试数据库（连接由 conftest 提供）"""
        yield

    def test_role_save_and_load(self):
        """测试角色保存和加载"""
        role = Role(name='test_role', description='测试角色')
        role.save()

        loaded_role = Role.objects(name='test_role').first()
        assert loaded_role is not None
        assert loaded_role.name == 'test_role'
        assert loaded_role.description == '测试角色'

    def test_user_save_and_load(self):
        """测试用户保存和加载"""
        role = Role(name='test_role', description='测试角色')
        role.save()

        user = User(username='test_user', password='hashed_password', nickname='测试用户', roles=[role])
        user.save()

        loaded_user = User.objects(username='test_user').first()
        assert loaded_user is not None
        assert loaded_user.username == 'test_user'
        assert loaded_user.nickname == '测试用户'
        assert len(loaded_user.roles) == 1
        assert loaded_user.roles[0].name == 'test_role'

    def test_user_unique_constraints(self):
        """测试用户唯一约束"""
        user1 = User(username='unique_user', password='password1')
        user1.save()

        user2 = User(username='unique_user', password='password2')
        with pytest.raises(Exception):  # 应该是 NotUniqueError
            user2.save()

    def test_role_unique_constraints(self):
        """测试角色唯一约束"""
        role1 = Role(name='unique_role', description='角色1')
        role1.save()

        role2 = Role(name='unique_role', description='角色2')
        with pytest.raises(Exception):  # 应该是 NotUniqueError
            role2.save()


@pytest.mark.unit
class TestModelImports:
    """测试模型导入"""

    def test_pilot_model_import(self):
        """测试机师模型导入"""
        pilot = Pilot(nickname="测试机师", gender=Gender.FEMALE)
        assert pilot.nickname == "测试机师"
        assert pilot.gender == Gender.FEMALE
        assert pilot.gender_display == "女"

    def test_model_relationships(self):
        """测试模型关联关系"""
        user = User(username="test_user", password="password")
        pilot = Pilot(nickname="test_pilot", owner=user)
        assert pilot.owner == user
