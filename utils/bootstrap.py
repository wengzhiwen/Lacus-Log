import logging

from flask_security.utils import hash_password
from mongoengine.errors import NotUniqueError

from models.user import Role, User
from utils.logging_setup import get_logger

logger = get_logger('bootstrap')


def ensure_initial_roles_and_admin(user_datastore) -> None:
    """确保系统初始角色与默认议长存在。

    - 角色：gicho（议长）、kancho（舰长）
    - 默认议长：用户名 zala / 密码 plant4ever
    """
    # 确保角色存在
    for role_name, desc in [('gicho', '议长'), ('kancho', '舰长')]:
        try:
            if not Role.objects(name=role_name).first():
                user_datastore.create_role(name=role_name, description=desc)
                logger.info('创建角色：%s', role_name)
        except NotUniqueError:
            pass

    # 如果没有任何议长，则创建默认议长
    gicho_role = Role.objects(name='gicho').first()
    if gicho_role is None:
        logger.error('未找到角色 gicho，无法创建默认议长')
        return

    has_gicho = User.objects(roles=gicho_role).first() is not None
    if not has_gicho:
        try:
            user = user_datastore.create_user(
                username='zala',
                password=hash_password('plant4ever'),
                nickname='ZAFT 议长',
                roles=[gicho_role],
                active=True,
            )
            logger.info('创建默认议长：%s', user.username)
        except Exception as exc:  # pylint: disable=broad-except
            logging.getLogger('app').exception('创建默认议长失败：%s', exc)
