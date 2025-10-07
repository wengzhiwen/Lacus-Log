"""
测试数据工厂

使用Faker生成随机测试数据，确保测试可重复执行
"""
from faker import Faker
import random
import string

# 创建中文Faker实例
fake = Faker('zh_CN')
# 也需要英文Faker用于生成用户名等
fake_en = Faker('en_US')


class UserFactory:
    """用户数据工厂"""

    @staticmethod
    def generate_username() -> str:
        """生成随机用户名"""
        # 使用时间戳+随机字符确保唯一性
        timestamp = str(int(fake.unix_time()))[-6:]
        random_str = ''.join(random.choices(string.ascii_lowercase, k=4))
        return f"test_{random_str}_{timestamp}"

    @staticmethod
    def generate_password() -> str:
        """生成随机密码（至少6位）"""
        return fake_en.password(length=10, special_chars=False)

    @staticmethod
    def generate_nickname() -> str:
        """生成随机昵称"""
        return fake.name()

    @staticmethod
    def generate_email() -> str:
        """生成随机邮箱"""
        return fake.email()

    @staticmethod
    def create_user_data(role: str = 'kancho', **kwargs) -> dict:
        """
        生成完整的用户数据
        
        Args:
            role: 用户角色（gicho管理员 / kancho运营）
            **kwargs: 覆盖默认值的字段
        
        Returns:
            用户数据字典
        """
        data = {
            'username': UserFactory.generate_username(),
            'password': UserFactory.generate_password(),
            'nickname': UserFactory.generate_nickname(),
            'email': UserFactory.generate_email(),
            'role': role,
            'active': True,
        }
        data.update(kwargs)
        return data


class PilotFactory:
    """主播数据工厂"""

    @staticmethod
    def generate_nickname() -> str:
        """生成主播昵称"""
        return fake.name()

    @staticmethod
    def generate_real_name() -> str:
        """生成真实姓名"""
        return fake.name()

    @staticmethod
    def generate_phone() -> str:
        """生成手机号"""
        return fake.phone_number()

    @staticmethod
    def create_pilot_data(owner_id: str = None, **kwargs) -> dict:
        """
        生成完整的主播数据
        
        Args:
            owner_id: 直属运营ID
            **kwargs: 覆盖默认值的字段
        
        Returns:
            主播数据字典
        """
        data = {
            'nickname': PilotFactory.generate_nickname(),
            'real_name': PilotFactory.generate_real_name(),
            'gender': random.choice(['男', '女']),
            'age': random.randint(18, 35),
            'phone': PilotFactory.generate_phone(),
            'platform': random.choice(['Twitch', 'YouTube', 'Bilibili', 'Douyu', 'Huya']),
            'rank': '候选人',
            'status': '未招募',
            'work_mode': '线下',
        }

        if owner_id:
            data['owner'] = owner_id

        data.update(kwargs)
        return data


class AnnouncementFactory:
    """通告数据工厂"""

    @staticmethod
    def create_announcement_data(pilot_id: str, **kwargs) -> dict:
        """
        生成完整的通告数据
        
        Args:
            pilot_id: 主播ID
            **kwargs: 覆盖默认值的字段
        
        Returns:
            通告数据字典
        """
        from datetime import datetime, timedelta

        start_time = datetime.now() + timedelta(days=random.randint(1, 7))

        data = {
            'pilot_id': pilot_id,
            'x_coord': str(random.randint(100, 999)),
            'y_coord': str(random.randint(100, 999)),
            'z_coord': str(random.randint(1, 99)),
            'start_time': start_time.isoformat(),
            'duration_hours': random.choice([2, 3, 4, 6, 8]),
            'recurrence_type': '无重复',
        }

        data.update(kwargs)
        return data


# 创建便捷实例
user_factory = UserFactory()
pilot_factory = PilotFactory()
announcement_factory = AnnouncementFactory()
