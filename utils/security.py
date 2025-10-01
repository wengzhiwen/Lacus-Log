import logging

from flask import Flask
from flask_security import Security
from flask_security.datastore import MongoEngineUserDatastore
from flask_security.signals import user_authenticated

from models.user import Role, User


def create_user_datastore(db=None) -> MongoEngineUserDatastore:
    """创建MongoEngineUserDatastore。

    对于 Flask-Security-Too 的 MongoEngine 适配，构造函数签名为 (db, user_model, role_model)。
    在未使用 Flask-MongoEngine 的情况下，传入 db=None 即可。
    """
    return MongoEngineUserDatastore(db, User, Role)


def init_security(app: Flask,
                  user_datastore: MongoEngineUserDatastore) -> Security:
    """初始化 Flask-Security-Too，并接入登录相关日志。"""
    security = Security(app, user_datastore)

    logger = logging.getLogger('app')

    @user_authenticated.connect_via(app)
    def _on_user_authenticated(sender, user, **extra):  # pylint: disable=unused-argument
        logger.info('用户登录成功：%s', getattr(user, 'username', 'unknown'))

    @security.login_manager.user_loader
    def _load_user(user_id):  # pylint: disable=unused-argument
        user = User.objects(fs_uniquifier=user_id).first()
        if user:
            return user
        try:
            from bson import ObjectId  # 延迟导入，避免工具环境缺依赖报错
            return User.objects(id=ObjectId(user_id)).first()
        except Exception:  # pylint: disable=broad-except
            return None


    return security
