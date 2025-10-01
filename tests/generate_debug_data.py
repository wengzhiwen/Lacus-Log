"""测试数据生成脚本

生成包含完整测试数据的独立数据库，用于调试和测试。
使用项目中的业务逻辑函数而不是直接操作模型。
"""

import random
import string
from datetime import datetime, timedelta
from decimal import Decimal

import pytest
from flask import Flask
from mongoengine import connect, disconnect

from models.announcement import Announcement, RecurrenceType
from models.battle_area import Availability, BattleArea
from models.battle_record import BattleRecord
from models.pilot import Gender, Platform, Rank, Status, WorkMode, Pilot
from models.user import Role, User
from utils.bootstrap import ensure_initial_roles_and_admin
from utils.security import create_user_datastore
from utils.timezone_helper import local_to_utc


def generate_random_nickname(length=6):
    """生成随机昵称"""
    return ''.join(random.choices(string.ascii_letters + string.digits, k=length))


def generate_random_database_name():
    """生成随机数据库名"""
    return f"test_lacus_debug_{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}"


@pytest.fixture(scope='session')
def debug_database():
    """创建独立的调试数据库"""
    try:
        disconnect()
    except:
        pass

    db_name = generate_random_database_name()
    print(f"创建调试数据库: {db_name}")

    connect(db_name, host='mongodb://localhost:27017')

    yield db_name

    print(f"调试数据库 {db_name} 已创建，数据保留用于调试")
    disconnect()


@pytest.fixture(scope='session')
def debug_app(debug_database):
    """创建调试应用"""
    from flask import Flask

    app = Flask(__name__)
    app.config.update({
        'TESTING': True,
        'MONGODB_URI': f'mongodb://localhost:27017/{debug_database}',
        'SECRET_KEY': 'debug-secret-key',
        'SECURITY_PASSWORD_SALT': 'debug-password-salt',
    })

    with app.app_context():
        yield app


def test_generate_debug_data(debug_app, debug_database):
    """生成调试测试数据"""
    with debug_app.app_context():
        print(f"开始生成调试数据到数据库: {debug_database}")

        gicho_role = Role(name='gicho', description='议长')
        gicho_role.save()
        kancho_role = Role(name='kancho', description='舰长')
        kancho_role.save()

        captains = []
        for i in range(2):
            captain = User(username=f'captain_{i+1}', nickname=generate_random_nickname(), password='test_password', roles=[kancho_role], active=True)
            captain.save()
            captains.append(captain)
            print(f"创建舰长: {captain.nickname}")

        pilots = []
        for i in range(10):
            owner = random.choice(captains)

            rank = Rank.TRAINEE if i < 5 else Rank.OFFICIAL

            pilot = Pilot(nickname=generate_random_nickname(),
                          real_name=f"真实姓名{generate_random_nickname(4)}",
                          owner=owner,
                          rank=rank,
                          status=Status.RECRUITED,
                          platform=Platform.KUAISHOU,
                          work_mode=WorkMode.OFFLINE,
                          gender=Gender.MALE,
                          birth_year=1995 + random.randint(0, 10))
            pilot.save()
            pilots.append(pilot)
            print(f"创建机师: {pilot.nickname} (所属: {owner.nickname}, 阶级: {rank.value})")

        battle_areas = []
        for z in range(1, 11):
            area = BattleArea(x_coord='测试宙域', y_coord='测试房', z_coord=str(z), availability=Availability.ENABLED)
            area.save()
            battle_areas.append(area)
        print(f"创建作战区域: 测试宙域-测试房-1到10")

        announcements = []

        pilot1 = random.choice(pilots)
        for day in range(1, 31):  # 9月1日到30日
            date = datetime(2025, 9, day)
            if date.weekday() < 5:  # 周一到周五
                area = random.choice(battle_areas)
                ann = Announcement(pilot=pilot1,
                                   battle_area=area,
                                   x_coord=area.x_coord,
                                   y_coord=area.y_coord,
                                   z_coord=area.z_coord,
                                   start_time=local_to_utc(datetime(2025, 9, day, 16, 0, 0)),
                                   duration_hours=6.0,
                                   recurrence_type=RecurrenceType.NONE,
                                   created_by=captains[0])
                ann.save()
                announcements.append(ann)
        print(f"为 {pilot1.nickname} 创建工作日16点计划")

        pilot2 = random.choice([p for p in pilots if p != pilot1])
        for day in range(1, 31):  # 9月1日到30日
            area = random.choice(battle_areas)
            ann = Announcement(pilot=pilot2,
                               battle_area=area,
                               x_coord=area.x_coord,
                               y_coord=area.y_coord,
                               z_coord=area.z_coord,
                               start_time=local_to_utc(datetime(2025, 9, day, 12, 0, 0)),
                               duration_hours=6.0,
                               recurrence_type=RecurrenceType.NONE,
                               created_by=captains[0])
            ann.save()
            announcements.append(ann)
        print(f"为 {pilot2.nickname} 创建每日12点计划")

        pilot3 = random.choice([p for p in pilots if p not in [pilot1, pilot2]])
        for day in range(1, 31):  # 9月1日到30日
            date = datetime(2025, 9, day)
            if date.weekday() in [1, 3, 4, 5, 6]:  # 周二四五六日
                area = random.choice(battle_areas)
                ann = Announcement(pilot=pilot3,
                                   battle_area=area,
                                   x_coord=area.x_coord,
                                   y_coord=area.y_coord,
                                   z_coord=area.z_coord,
                                   start_time=local_to_utc(datetime(2025, 9, day, 14, 0, 0)),
                                   duration_hours=6.0,
                                   recurrence_type=RecurrenceType.NONE,
                                   created_by=captains[0])
                ann.save()
                announcements.append(ann)
        print(f"为 {pilot3.nickname} 创建二四五六日14点计划")

        pilot4 = random.choice([p for p in pilots if p not in [pilot1, pilot2, pilot3]])
        selected_days = random.sample(range(1, 16), 7)  # 9月1-15日选7天
        for day in selected_days:
            area = random.choice(battle_areas)
            ann = Announcement(pilot=pilot4,
                               battle_area=area,
                               x_coord=area.x_coord,
                               y_coord=area.y_coord,
                               z_coord=area.z_coord,
                               start_time=local_to_utc(datetime(2025, 9, day, 10, 0, 0)),
                               duration_hours=6.0,
                               recurrence_type=RecurrenceType.NONE,
                               created_by=captains[0])
            ann.save()
            announcements.append(ann)
        print(f"为 {pilot4.nickname} 创建9月1-15日随机7天10点计划")

        pilot5 = random.choice([p for p in pilots if p not in [pilot1, pilot2, pilot3, pilot4]])
        selected_days = random.sample(range(10, 21), 7)  # 9月10-20日选7天
        for day in selected_days:
            area = random.choice(battle_areas)
            ann = Announcement(pilot=pilot5,
                               battle_area=area,
                               x_coord=area.x_coord,
                               y_coord=area.y_coord,
                               z_coord=area.z_coord,
                               start_time=local_to_utc(datetime(2025, 9, day, 11, 0, 0)),
                               duration_hours=6.0,
                               recurrence_type=RecurrenceType.NONE,
                               created_by=captains[0])
            ann.save()
            announcements.append(ann)
        print(f"为 {pilot5.nickname} 创建9月10-20日随机7天11点计划")

        remaining_pilots = [p for p in pilots if p not in [pilot1, pilot2, pilot3, pilot4, pilot5]]
        for pilot in remaining_pilots:
            selected_days = random.sample(range(1, 31), 26)  # 9月1-30日选26天
            for day in selected_days:
                hour = random.choice([8, 10, 12, 14, 16, 18, 20, 22])  # 8-22点随机选5个整点
                area = random.choice(battle_areas)
                ann = Announcement(pilot=pilot,
                                   battle_area=area,
                                   x_coord=area.x_coord,
                                   y_coord=area.y_coord,
                                   z_coord=area.z_coord,
                                   start_time=local_to_utc(datetime(2025, 9, day, hour, 0, 0)),
                                   duration_hours=6.0,
                                   recurrence_type=RecurrenceType.NONE,
                                   created_by=captains[0])
                ann.save()
                announcements.append(ann)
        print(f"为剩余5名机师创建随机计划")

        print(f"总共创建了 {len(announcements)} 个作战计划")

        battle_records = []
        for ann in announcements:
            if random.random() < 0.85:  # 85%概率生成作战记录
                duration_hours = 6.0 if random.random() < 0.9 else 5.0

                base_salary = Decimal('150.00') if duration_hours == 6.0 else Decimal('0.00')

                hourly_revenue = random.randint(10, 200)
                revenue_amount = Decimal(str(hourly_revenue * duration_hours))

                record = BattleRecord(pilot=ann.pilot,
                                      related_announcement=ann,
                                      start_time=ann.start_time,
                                      end_time=ann.start_time + timedelta(hours=duration_hours),
                                      revenue_amount=revenue_amount,
                                      base_salary=base_salary,
                                      x_coord=ann.x_coord,
                                      y_coord=ann.y_coord,
                                      z_coord=ann.z_coord,
                                      work_mode=WorkMode.OFFLINE,
                                      owner_snapshot=ann.pilot.owner,
                                      registered_by=captains[0],
                                      notes=f"基于计划生成的记录")
                record.save()
                battle_records.append(record)

        print(f"基于计划生成了 {len(battle_records)} 个作战记录")

        extra_records = []
        for i in range(5):  # 循环5次
            pilot = random.choice(pilots)

            pilot_announcement_days = set()
            for ann in announcements:
                if ann.pilot == pilot:
                    local_start = ann.start_time.replace(tzinfo=None) - timedelta(hours=8)
                    pilot_announcement_days.add(local_start.day)

            available_days = [day for day in range(1, 31) if day not in pilot_announcement_days]

            if len(available_days) >= 2:
                selected_days = random.sample(available_days, 2)
                for day in selected_days:
                    hour = random.randint(8, 22)
                    area = random.choice(battle_areas)

                    duration_hours = random.choice([4.0, 5.0, 6.0, 7.0, 8.0])
                    base_salary = Decimal('150.00') if duration_hours >= 6.0 else Decimal('0.00')
                    hourly_revenue = random.randint(10, 200)
                    revenue_amount = Decimal(str(hourly_revenue * duration_hours))

                    record = BattleRecord(pilot=pilot,
                                          start_time=local_to_utc(datetime(2025, 9, day, hour, 0, 0)),
                                          end_time=local_to_utc(datetime(2025, 9, day, hour, 0, 0)) + timedelta(hours=duration_hours),
                                          revenue_amount=revenue_amount,
                                          base_salary=base_salary,
                                          x_coord=area.x_coord,
                                          y_coord=area.y_coord,
                                          z_coord=area.z_coord,
                                          work_mode=WorkMode.OFFLINE,
                                          owner_snapshot=pilot.owner,
                                          registered_by=captains[0],
                                          notes=f"无计划的随机记录")
                    record.save()
                    extra_records.append(record)

        print(f"生成了 {len(extra_records)} 个无计划的作战记录")

        print("\n=== 调试数据生成完成 ===")
        print(f"数据库名: {debug_database}")
        print(f"舰长数量: {len(captains)}")
        print(f"机师数量: {len(pilots)}")
        print(f"作战区域数量: {len(battle_areas)}")
        print(f"作战计划数量: {len(announcements)}")
        print(f"作战记录数量: {len(battle_records) + len(extra_records)}")
        print(f"  - 基于计划的记录: {len(battle_records)}")
        print(f"  - 无计划的记录: {len(extra_records)}")
        print("\n舰长列表:")
        for captain in captains:
            print(f"  - {captain.nickname} (用户名: {captain.username})")
        print("\n机师列表:")
        for pilot in pilots:
            print(f"  - {pilot.nickname} (所属: {pilot.owner.nickname}, 阶级: {pilot.rank.value})")
        print(f"\n数据库连接信息:")
        print(f"mongodb://localhost:27017/{debug_database}")
        print("=" * 50)
