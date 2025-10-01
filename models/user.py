# pylint: disable=R0903,no-member

import uuid

from flask_security.utils import verify_password
from mongoengine import (BooleanField, DateTimeField, Document, IntField, ListField, ReferenceField, StringField,
                         EmailField, DoesNotExist)
from utils.timezone_helper import get_current_utc_time


class Role(Document):
    """角色模型。"""

    name = StringField(required=True, unique=True)
    description = StringField()
    permissions = ListField(StringField(), default=list)

    meta = {
        'collection': 'roles',
        'indexes': [{
            'fields': ['name'],
            'unique': True
        }],
    }

    def get_permissions(self):  # pragma: no cover - 简单返回集合
        return set(self.permissions or [])

    def __str__(self):
        return self.name

    def __repr__(self):
        return f'<Role {self.name}>'


class User(Document):
    """用户模型，兼容 Flask-Security-Too MongoEngineUserDatastore。

    采用用户名作为登录标识。
    """

    username = StringField(required=True, unique=True)
    password = StringField(required=True)  # 密文
    nickname = StringField(default='')
    email = EmailField(required=False, null=True)
    active = BooleanField(default=True)
    created_at = DateTimeField(default=get_current_utc_time)
    fs_uniquifier = StringField(required=True, unique=True, default=lambda: uuid.uuid4().hex)

    last_login_at = DateTimeField()
    current_login_at = DateTimeField()
    last_login_ip = StringField()
    current_login_ip = StringField()
    login_count = IntField(default=0)

    roles = ListField(ReferenceField(Role), default=list)

    meta = {
        'collection': 'users',
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

    def verify_and_update_password(self, password: str) -> bool:  # pragma: no cover - 简单委托
        """校验明文密码与存储的哈希。

        由于采用稳定的哈希方案（pbkdf2_sha512），本方法不涉及升级更新，仅校验返回布尔值。
        """
        return verify_password(password, self.password)

    def has_role(self, role) -> bool:  # pragma: no cover - 简单逻辑
        """判断用户是否具备某角色（支持字符串或Role对象）。"""
        role_name = role if isinstance(role, str) else getattr(role, 'name', None)
        if not role_name:
            return False
        return any(r.name == role_name for r in self.roles)

    def get_roles(self):
        """Flask-Security-Too需要的角色获取方法"""
        return self.roles

    def has_permission(self, permission):  # pylint: disable=unused-argument
        """Flask-Security-Too需要的权限检查方法"""
        return False  # 暂时不实现权限系统

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
        return self.fs_uniquifier

    @classmethod
    def get_emails_by_role(cls, role_name: str | None = None, only_active: bool = True):
        """按角色名获取邮箱列表；不传角色名时返回全部用户邮箱。

        - role_name: 角色名，如 'gicho'（管理员）、'kancho'（运营）
        - only_active: 是否仅返回激活用户的邮箱

        返回去重后的邮箱字符串列表（忽略空值）。
        """
        if not role_name:
            query = cls.objects(email__ne=None)
        else:
            try:
                role_obj = Role.objects.get(name=role_name)
            except DoesNotExist:
                return []
            query = cls.objects(roles=role_obj, email__ne=None)
        if only_active:
            query = query.filter(active=True)

        emails = [u.email for u in query if getattr(u, 'email', None)]
        return sorted(set(emails))
