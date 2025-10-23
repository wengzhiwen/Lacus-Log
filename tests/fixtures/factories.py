"""
测试数据工厂

使用Faker生成随机测试数据，确保测试可重复执行
"""
import random
import string

from faker import Faker

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
        """生成主播昵称（带时间戳确保唯一性）"""
        timestamp = str(int(fake.unix_time()))[-6:]
        name = fake.name()
        return f"{name}_{timestamp}"

    @staticmethod
    def generate_real_name() -> str:
        """生成真实姓名"""
        return fake.name()

    @staticmethod
    def generate_phone() -> str:
        """生成手机号"""
        return fake.phone_number()

    @staticmethod
    def generate_hometown() -> str:
        """生成籍贯"""
        return fake.city()

    @staticmethod
    def generate_birth_year() -> int:
        """生成出生年份（18-35岁之间）"""
        from datetime import datetime
        current_year = datetime.now().year
        return current_year - random.randint(18, 35)

    @staticmethod
    def create_pilot_data(owner_id: str = None, **kwargs) -> dict:
        """
        生成完整的主播数据
        
        Args:
            owner_id: 直属运营ID（可选）
            **kwargs: 覆盖默认值的字段
        
        Returns:
            主播数据字典
        
        注意：
        - 使用系统实际的枚举值（参考models/pilot.py）
        - gender: 0(男), 1(女), 2(不明确)
        - platform: "快手", "抖音", "其他", "未知"
        - work_mode: "线下", "线上", "未知"
        - rank: "候选人", "试播主播", "实习主播", "正式主播"
        - status: "未招募", "不招募", "已招募", "已签约", "流失"
        """
        data = {
            'nickname': PilotFactory.generate_nickname(),
            'real_name': PilotFactory.generate_real_name(),
            'gender': random.choice([0, 1, 2]),  # 0=男, 1=女, 2=不明确
            'birth_year': PilotFactory.generate_birth_year(),
            'hometown': PilotFactory.generate_hometown(),
            'platform': random.choice(['快手', '抖音', '其他', '未知']),
            'work_mode': random.choice(['线下', '线上', '未知']),
            'rank': '候选人',
            'status': '未招募',
        }

        if owner_id:
            data['owner_id'] = owner_id

        data.update(kwargs)
        return data


class BattleAreaFactory:
    """开播地点数据工厂"""

    # 预定义的基地和场地名称
    X_COORDS = ['基地A', '基地B', '基地C', '基地D', '基地E']
    Y_COORDS = ['场地1', '场地2', '场地3', '场地4', '场地5']

    @staticmethod
    def generate_x_coord() -> str:
        """生成基地名称"""
        return random.choice(BattleAreaFactory.X_COORDS)

    @staticmethod
    def generate_y_coord() -> str:
        """生成场地名称"""
        return random.choice(BattleAreaFactory.Y_COORDS)

    @staticmethod
    def generate_z_coord() -> str:
        """生成坐席编号（1-99）"""
        return str(random.randint(1, 99))

    @staticmethod
    def create_battle_area_data(**kwargs) -> dict:
        """
        生成完整的开播地点数据
        
        Args:
            **kwargs: 覆盖默认值的字段
        
        Returns:
            开播地点数据字典
        """
        data = {
            'x_coord': BattleAreaFactory.generate_x_coord(),
            'y_coord': BattleAreaFactory.generate_y_coord(),
            'z_coord': BattleAreaFactory.generate_z_coord(),
            'availability': '可用',
        }
        data.update(kwargs)
        return data

    @staticmethod
    def create_specific_battle_area(x: str, y: str, z: str, **kwargs) -> dict:
        """
        创建指定坐标的开播地点数据
        
        Args:
            x: 基地
            y: 场地
            z: 坐席
            **kwargs: 其他字段
        
        Returns:
            开播地点数据字典
        """
        data = {
            'x_coord': x,
            'y_coord': y,
            'z_coord': z,
            'availability': '可用',
        }
        data.update(kwargs)
        return data


class AnnouncementFactory:
    """通告数据工厂"""

    @staticmethod
    def create_announcement_data(pilot_id: str, battle_area_id: str, start_time_str: str = None, **kwargs) -> dict:
        """
        生成完整的通告数据
        
        Args:
            pilot_id: 主播ID
            battle_area_id: 开播地点ID
            start_time_str: 开始时间字符串（可选）
            **kwargs: 覆盖默认值的字段
        
        Returns:
            通告数据字典
        """
        from datetime import datetime, timedelta

        if start_time_str is None:
            start_time = datetime.now() + timedelta(days=random.randint(1, 7))
            start_time_str = start_time.strftime('%Y-%m-%d %H:%M:%S')

        data = {
            'pilot_id': pilot_id,
            'battle_area_id': battle_area_id,
            'start_time': start_time_str,
            'duration_hours': random.choice([2, 3, 4, 6, 8]),
            'recurrence_type': 'NONE',
        }

        data.update(kwargs)
        return data

    @staticmethod
    def create_daily_recurrence_data(pilot_id: str, battle_area_id: str, start_time_str: str, end_date_str: str, interval: int = 1, **kwargs) -> dict:
        """
        创建每日循环通告数据
        
        Args:
            pilot_id: 主播ID
            battle_area_id: 开播地点ID
            start_time_str: 开始时间
            end_date_str: 结束日期
            interval: 间隔天数（1=每天，2=隔天）
            **kwargs: 其他字段
        
        Returns:
            通告数据字典
        """
        data = {
            'pilot_id': pilot_id,
            'battle_area_id': battle_area_id,
            'start_time': start_time_str,
            'duration_hours': kwargs.get('duration_hours', 6),
            'recurrence_type': 'DAILY',
            'recurrence_pattern': {
                'type': '每日',
                'interval': interval
            },
            'recurrence_end_date': end_date_str,
        }
        data.update(kwargs)
        return data

    @staticmethod
    def create_weekly_recurrence_data(pilot_id: str,
                                      battle_area_id: str,
                                      start_time_str: str,
                                      end_date_str: str,
                                      days_of_week: list = None,
                                      interval: int = 1,
                                      **kwargs) -> dict:
        """
        创建每周循环通告数据
        
        Args:
            pilot_id: 主播ID
            battle_area_id: 开播地点ID
            start_time_str: 开始时间
            end_date_str: 结束日期
            days_of_week: 星期几列表（1-7，1=周一）
            interval: 间隔周数
            **kwargs: 其他字段
        
        Returns:
            通告数据字典
        """
        if days_of_week is None:
            days_of_week = [1, 3, 5]  # 默认周一、周三、周五

        data = {
            'pilot_id': pilot_id,
            'battle_area_id': battle_area_id,
            'start_time': start_time_str,
            'duration_hours': kwargs.get('duration_hours', 6),
            'recurrence_type': 'WEEKLY',
            'recurrence_pattern': {
                'type': '每周',
                'interval': interval,
                'days_of_week': days_of_week
            },
            'recurrence_end_date': end_date_str,
        }
        data.update(kwargs)
        return data


class RecruitFactory:
    """招募数据工厂"""

    @staticmethod
    def generate_appointment_time() -> str:
        """生成预约时间（未来24小时内）"""
        from datetime import datetime, timedelta
        future_time = datetime.now() + timedelta(hours=random.randint(1, 24))
        return future_time.strftime('%Y-%m-%d %H:%M:%S')

    @staticmethod
    def create_recruit_data(pilot_id: str = None, kancho_id: str = None, **kwargs) -> dict:
        """
        生成完整的招募数据

        Args:
            pilot_id: 主播ID
            kancho_id: 招募负责人ID
            **kwargs: 覆盖默认值的字段

        Returns:
            招募数据字典
        """
        data = {
            'pilot_id': pilot_id,
            'recruiter_id': kancho_id,
            'appointment_time': RecruitFactory.generate_appointment_time(),
            'channel': random.choice(['BOSS', '51', '介绍', '其他']),
            'introduction_fee': random.randint(0, 1000),
            'remarks': fake.sentence(),
        }
        data.update(kwargs)
        return data


class BattleRecordFactory:
    """开播记录数据工厂"""

    @staticmethod
    def create_battle_record_data(pilot_id: str = None, **kwargs) -> dict:
        """
        生成完整的开播记录数据

        Args:
            pilot_id: 主播ID
            **kwargs: 覆盖默认值的字段

        Returns:
            开播记录数据字典
        """
        from datetime import datetime, timedelta

        data = {
            'pilot_id': pilot_id,
            'battle_date': (datetime.now() - timedelta(days=random.randint(1, 30))).strftime('%Y-%m-%d'),
            'platform': random.choice(['快手', '抖音', '其他', '未知']),
            'work_mode': random.choice(['线下', '线上', '未知']),
            'duration_hours': random.randint(1, 8),
            'salary_amount': random.randint(0, 5000),
        }
        data.update(kwargs)
        return data


class BaseSalaryApplicationFactory:
    """底薪申请数据工厂"""

    @staticmethod
    def create_base_salary_application_data(pilot_id: str = None, **kwargs) -> dict:
        """
        生成完整的底薪申请数据

        Args:
            pilot_id: 主播ID
            **kwargs: 覆盖默认值的字段

        Returns:
            底薪申请数据字典
        """
        data = {
            'pilot_id': pilot_id,
            'base_salary': random.randint(2000, 8000),
            'reason': fake.sentence(),
            'start_date': fake.date_between(start_date='-30d', end_date='today').strftime('%Y-%m-%d'),
        }
        data.update(kwargs)
        return data


class BbsPostFactory:
    """BBS帖子数据工厂"""

    @staticmethod
    def create_bbs_post_data(user_id: str = None, **kwargs) -> dict:
        """
        生成完整的BBS帖子数据

        Args:
            user_id: 用户ID
            **kwargs: 覆盖默认值的字段

        Returns:
            BBS帖子数据字典
        """
        data = {
            'user_id': user_id,
            'title': fake.sentence(),
            'content': fake.text(max_nb_chars=200),
            'category': random.choice(['其他', '通知', '讨论']),
            'is_pinned': False,
        }
        data.update(kwargs)
        return data


class JamesAlertFactory:
    """警报通知数据工厂"""

    @staticmethod
    def create_alert_data(user_id: str = None, **kwargs) -> dict:
        """
        生成完整的警报通知数据

        Args:
            user_id: 用户ID
            **kwargs: 覆盖默认值的字段

        Returns:
            警报通知数据字典
        """
        data = {
            'user_id': user_id,
            'type': random.choice(['系统警报', '业务通知', '异常提醒']),
            'title': fake.sentence(),
            'message': fake.text(max_nb_chars=200),
            'is_read': False,
        }
        data.update(kwargs)
        return data


class SettlementFactory:
    """结算数据工厂"""

    @staticmethod
    def create_settlement_data(pilot_id: str = None, **kwargs) -> dict:
        """
        生成完整的结算数据

        Args:
            pilot_id: 主播ID
            **kwargs: 覆盖默认值的字段

        Returns:
            结算数据字典
        """
        from datetime import datetime, timedelta
        data = {
            'pilot_id': pilot_id,
            'settlement_date': (datetime.now() - timedelta(days=random.randint(1, 30))).strftime('%Y-%m-%d'),
            'total_days': random.randint(20, 31),
            'working_days': random.randint(15, 30),
            'total_salary': random.randint(2000, 10000),
            'base_salary': random.randint(2000, 5000),
            'commission': random.randint(0, 3000),
            'deduction': random.randint(0, 500),
            'net_salary': random.randint(1500, 8000),
        }
        data.update(kwargs)
        return data


# 创建便捷实例
user_factory = UserFactory()
pilot_factory = PilotFactory()
battle_area_factory = BattleAreaFactory()
announcement_factory = AnnouncementFactory()
recruit_factory = RecruitFactory()
battle_record_factory = BattleRecordFactory()
base_salary_application_factory = BaseSalaryApplicationFactory()
bbs_post_factory = BbsPostFactory()
james_alert_factory = JamesAlertFactory()
settlement_factory = SettlementFactory()
