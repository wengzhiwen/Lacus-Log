import uuid
from datetime import datetime

from flask_security.utils import verify_password
from mongoengine import (BooleanField, DateTimeField, Document, IntField,
                         ListField, ReferenceField, StringField)

# pylint: disable=R0903


class Role(Document):
    """角色模型。"""

    name = StringField(required=True, unique=True)
    description = StringField()
    # Flask-Security-Too 可选：基于角色的权限集合
    permissions = ListField(StringField(), default=list)

    meta = {
        'collection': 'roles',
        'indexes': [{
            'fields': ['name'],
            'unique': True
        }],
    }

    # 供 Flask-Security-Too 的身份系统使用
    def get_permissions(self):  # pragma: no cover - 简单返回集合
        return set(self.permissions or [])


class User(Document):
    """用户模型，兼容 Flask-Security-Too MongoEngineUserDatastore。

    采用用户名作为登录标识。
    """

    username = StringField(required=True, unique=True)
    password = StringField(required=True)  # 密文
    nickname = StringField(default='')
    active = BooleanField(default=True)
    created_at = DateTimeField(default=datetime.utcnow)
    # Flask-Security-Too 要求：全局唯一标识
    fs_uniquifier = StringField(required=True,
                                unique=True,
                                default=lambda: uuid.uuid4().hex)

    # Trackable（开启 SECURITY_TRACKABLE=True 时建议具备）
    last_login_at = DateTimeField()
    current_login_at = DateTimeField()
    last_login_ip = StringField()
    current_login_ip = StringField()
    login_count = IntField(default=0)

    # 角色关联
    roles = ListField(ReferenceField(Role), default=list)

    meta = {
        'collection':
        'users',
        'indexes': [
            {
                'fields': ['username'],
                'unique': True
            },
            {
                'fields': ['fs_uniquifier'],
                'unique': True
            },
        ],
    }

    # ---- Flask-Security 期望的方法 ----
    def verify_and_update_password(
            self, password: str) -> bool:  # pragma: no cover - 简单委托
        """校验明文密码与存储的哈希。

        由于采用稳定的哈希方案（pbkdf2_sha512），本方法不涉及升级更新，仅校验返回布尔值。
        """
        return verify_password(password, self.password)

    def has_role(self, role) -> bool:  # pragma: no cover - 简单逻辑
        """判断用户是否具备某角色（支持字符串或Role对象）。"""
        role_name = role if isinstance(role, str) else getattr(
            role, 'name', None)
        if not role_name:
            return False
        return any(r.name == role_name for r in self.roles)

    # ---- Flask-Login 期望的属性/方法 ----
    @property
    def is_active(self) -> bool:  # pragma: no cover - 简单映射
        return bool(self.active)

    @property
    def is_authenticated(self) -> bool:  # pragma: no cover
        return True

    @property
    def is_anonymous(self) -> bool:  # pragma: no cover
        return False

    def get_id(self) -> str:  # pragma: no cover
        # 使用 fs_uniquifier 作为稳定的会话标识
        return self.fs_uniquifier
