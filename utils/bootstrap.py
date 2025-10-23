# pylint: disable=no-member
import logging

from flask_security.utils import hash_password
from mongoengine.errors import NotUniqueError

from models.user import Role, User
from utils.logging_setup import get_logger

logger = get_logger('bootstrap')


def ensure_database_indexes() -> None:
    """确保所有模型的数据库索引被正确创建。
    
    根据项目约定，索引由各模块代码自行管理，在应用启动时统一确保创建。
    """
    logger.info('开始确保数据库索引创建...')

    try:
        from models.announcement import Announcement
        from models.battle_area import BattleArea
        from models.battle_record import BattleRecord
        from models.pilot import Pilot
        from models.recruit import Recruit

        models_to_index = [
            (Role, 'Role'),
            (User, 'User'),
            (Pilot, 'Pilot'),
            (BattleArea, 'BattleArea'),
            (Announcement, 'Announcement'),
            (BattleRecord, 'BattleRecord'),
            (Recruit, 'Recruit'),
        ]

        for model_class, model_name in models_to_index:
            try:
                model_class.ensure_indexes()
                logger.info('已确保 %s 模型索引创建', model_name)
            except Exception as exc:
                logger.error('确保 %s 模型索引失败：%s', model_name, exc)

        logger.info('数据库索引确保完成')

    except Exception as exc:
        logger.error('确保数据库索引失败：%s', exc)


def ensure_initial_roles_and_admin(user_datastore) -> None:
    """确保系统初始角色与默认议长存在。

    - 角色：gicho（议长）、kancho（舰长）
    - 默认议长：用户名 zala / 密码 plant4ever
    """
    for role_name, desc in [('gicho', '议长'), ('kancho', '舰长')]:
        try:
            if not Role.objects(name=role_name).first():
                user_datastore.create_role(name=role_name, description=desc)
                logger.info('创建角色：%s', role_name)
        except NotUniqueError:
            pass

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
                email='james@wengs.net',
                roles=[gicho_role],
                active=True,
            )
            logger.info('创建默认议长：%s', user.username)
        except Exception as exc:  # pylint: disable=broad-except
            logging.getLogger('app').exception('创建默认议长失败：%s', exc)
