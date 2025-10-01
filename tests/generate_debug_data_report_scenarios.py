"""复杂场景测试数据生成脚本

生成一套更复杂、覆盖边界条件的数据到一个新的Mongo数据库中：
- 覆盖分成比例在月中多次调整（默认/单次/多次/未来生效）
- 覆盖返点5档（至少有机师满足第1/3/5档）
- 覆盖3日平均（>=3天与<3天两种情况）
- 覆盖跨日作战记录（按开始时间归属当日）
- 覆盖“有效机师”（累计播时≥6小时）统计差异

运行方式：
  python tests/generate_debug_data_report_scenarios.py

输出：
- 新数据库名与连接串
- 必须要测的日期列表（用于验证日报日志）
"""
import random
import string
from datetime import datetime, timedelta
from decimal import Decimal

from flask import Flask
from mongoengine import connect, disconnect

from models.announcement import Announcement, RecurrenceType
from models.battle_area import Availability, BattleArea
from models.battle_record import BattleRecord
from models.pilot import (Gender, Platform, Rank, Status, WorkMode, Pilot, PilotCommission)
from models.user import Role
from utils.bootstrap import ensure_initial_roles_and_admin
from utils.security import create_user_datastore
from utils.timezone_helper import local_to_utc


def _rand_nick(n=6):
    return ''.join(random.choices(string.ascii_letters + string.digits, k=n))


def _rand_db_name():
    return f"test_lacus_report_{''.join(random.choices(string.ascii_lowercase + string.digits, k=8))}"


def _mk_captains(user_datastore, count=2):
    kancho_role = Role.objects(name='kancho').first()
    captains = []
    for i in range(count):
        captain = user_datastore.create_user(username=f'captain_ex_{i+1}', nickname=_rand_nick(), password='test_password', roles=[kancho_role], active=True)
        captains.append(captain)
    return captains


def _mk_pilots(captains, count=12):
    pilots = []
    for i in range(count):
        owner = random.choice(captains)
        rank = Rank.TRAINEE if i < 6 else Rank.OFFICIAL
        p = Pilot(nickname=_rand_nick())
        p.real_name = f"真实{_rand_nick(4)}"
        p.owner = owner
        p.rank = rank
        p.status = Status.RECRUITED
        p.platform = Platform.KUAISHOU
        p.work_mode = WorkMode.OFFLINE
        p.gender = Gender.MALE if i % 2 == 0 else Gender.FEMALE
        p.birth_year = 1992 + (i % 10)
        p.save()
        pilots.append(p)
    return pilots


def _mk_battle_areas():
    areas = []
    for z in range(1, 11):
        a = BattleArea(x_coord='复杂宙域', y_coord='复杂房', z_coord=str(z), availability=Availability.ENABLED)
        a.save()
        areas.append(a)
    return areas


def _add_commission_change(pilot, local_date_tuple, rate, remark):
    y, m, d = local_date_tuple
    utc_dt = local_to_utc(datetime(y, m, d, 0, 0, 0))
    PilotCommission(pilot_id=pilot, adjustment_date=utc_dt, commission_rate=rate, remark=remark, is_active=True).save()


def _mk_commissions(pilots):
    if len(pilots) < 4:
        return
    _add_commission_change(pilots[1], (2025, 9, 10), 30.0, '9/10起30%')
    _add_commission_change(pilots[2], (2025, 9, 5), 15.0, '9/05起15%')
    _add_commission_change(pilots[2], (2025, 9, 18), 40.0, '9/18起40%')
    _add_commission_change(pilots[3], (2025, 10, 1), 25.0, '10/01起25%（未来）')


def _mk_record(pilot, area, y, m, d, hour_local, duration_h, hourly_revenue, base_salary_by_hours=True, work_mode=WorkMode.OFFLINE):
    start_local = datetime(y, m, d, hour_local, 0, 0)
    start_utc = local_to_utc(start_local)
    end_utc = start_utc + timedelta(hours=duration_h)
    base_salary = Decimal('150.00') if (base_salary_by_hours and duration_h >= 6.0) else Decimal('0.00')
    revenue_amount = Decimal(str(hourly_revenue)) * Decimal(str(duration_h))
    BattleRecord(pilot=pilot,
                 start_time=start_utc,
                 end_time=end_utc,
                 revenue_amount=revenue_amount,
                 base_salary=base_salary,
                 x_coord=area.x_coord,
                 y_coord=area.y_coord,
                 z_coord=area.z_coord,
                 work_mode=work_mode,
                 owner_snapshot=pilot.owner,
                 registered_by=pilot.owner,
                 notes='复杂场景生成').save()


def _mk_record_minutes(pilot, area, y, m, d, hour_local, minute_local, duration_minutes, hourly_revenue, base_salary_by_hours=True, work_mode=WorkMode.OFFLINE):
    """分钟精度创建记录：用于本地日边界与时长边界验证"""
    start_local = datetime(y, m, d, hour_local, minute_local, 0)
    start_utc = local_to_utc(start_local)
    end_utc = start_utc + timedelta(minutes=duration_minutes)
    duration_h = duration_minutes / 60.0
    base_salary = Decimal('150.00') if (base_salary_by_hours and duration_h >= 6.0) else Decimal('0.00')
    revenue_amount = Decimal(str(hourly_revenue)) * Decimal(str(duration_h))
    BattleRecord(pilot=pilot,
                 start_time=start_utc,
                 end_time=end_utc,
                 revenue_amount=revenue_amount,
                 base_salary=base_salary,
                 x_coord=area.x_coord,
                 y_coord=area.y_coord,
                 z_coord=area.z_coord,
                 work_mode=work_mode,
                 owner_snapshot=pilot.owner,
                 registered_by=pilot.owner,
                 notes='复杂场景生成-分钟精度').save()


def _generate_data(app, db_name):  # pylint: disable=too-many-locals
    print(f"开始生成复杂场景测试数据到数据库: {db_name}")

    user_datastore = create_user_datastore()
    ensure_initial_roles_and_admin(user_datastore)
    captains = _mk_captains(user_datastore, count=2)
    pilots = _mk_pilots(captains, count=12)
    areas = _mk_battle_areas()
    _mk_commissions(pilots)

    P0, P1, P2, P3, P4, P5, P6, P7, P8, P9, P10, P11 = pilots

    for day in range(1, 31):
        area = random.choice(areas)
        rate = 150 if day <= 9 else 300
        _mk_record(P1, area, 2025, 9, day, 12, 6.0, rate)

    p2_days = sorted(random.sample(range(1, 31), 22))
    for day in p2_days:
        area = random.choice(areas)
        rate = 120 if day <= 17 else 400
        _mk_record(P2, area, 2025, 9, day, 14, 6.0, rate)

    p4_days = sorted(random.sample(range(1, 31), 22))
    for day in p4_days:
        area = random.choice(areas)
        _mk_record(P4, area, 2025, 9, day, 10, 8.0, 700)

    p5_days = sorted(random.sample(range(1, 31), 18))
    for day in p5_days:
        area = random.choice(areas)
        _mk_record(P5, area, 2025, 9, day, 16, 6.0, 100)

    p6_days_6h = sorted(random.sample(range(1, 31), 10))
    remaining_days = [d for d in range(1, 31) if d not in p6_days_6h]
    p6_days_3h = sorted(random.sample(remaining_days, 2))
    for day in p6_days_6h:
        area = random.choice(areas)
        _mk_record(P6, area, 2025, 9, day, 18, 6.0, 14)
    for day in p6_days_3h:
        area = random.choice(areas)
        _mk_record(P6, area, 2025, 9, day, 18, 3.0, 14)  # 3h 也计入有效天≥1h

    for day in [24, 30, 2, 3]:
        area = random.choice(areas)
        _mk_record(P7, area, 2025, 9, day, 12, 6.0, 80)

    area = random.choice(areas)
    start_local = datetime(2025, 9, 21, 23, 30, 0)
    start_utc = local_to_utc(start_local)
    end_utc = start_utc + timedelta(hours=8)
    BattleRecord(pilot=P8,
                 start_time=start_utc,
                 end_time=end_utc,
                 revenue_amount=Decimal('8') * Decimal('200'),
                 base_salary=Decimal('150.00'),
                 x_coord=area.x_coord,
                 y_coord=area.y_coord,
                 z_coord=area.z_coord,
                 work_mode=WorkMode.OFFLINE,
                 owner_snapshot=P8.owner,
                 registered_by=P8.owner,
                 notes='跨日记录-起于9/21 23:30').save()

    for day in random.sample(range(1, 31), 8):
        area = random.choice(areas)
        _mk_record(P9, area, 2025, 9, day, 9, 5.0, 120)

    for pilot in [P0, P3, P10, P11]:
        for day in random.sample(range(1, 31), 10):
            area = random.choice(areas)
            dur = random.choice([4.0, 5.0, 6.0, 7.0])
            hourly = random.choice([60, 80, 120, 180])
            _mk_record(pilot, area, 2025, 9, day, random.choice([10, 12, 14, 16, 18]), dur, hourly)

    tz_area = random.choice(areas)
    _mk_record_minutes(P0, tz_area, 2025, 9, 1, 0, 0, 360, 100)
    _mk_record_minutes(P0, tz_area, 2025, 9, 30, 23, 59, 60, 100)
    _mk_record_minutes(P0, tz_area, 2025, 8, 31, 23, 30, 360, 200)
    _mk_record_minutes(P0, tz_area, 2025, 10, 1, 0, 0, 360, 100)
    edge_area = random.choice(areas)
    _mk_record_minutes(P10, edge_area, 2025, 9, 16, 9, 0, 180, 90)
    _mk_record_minutes(P10, edge_area, 2025, 9, 16, 13, 0, 180, 110)
    _mk_record_minutes(P10, edge_area, 2025, 9, 17, 9, 0, 174, 90)
    _mk_record_minutes(P10, edge_area, 2025, 9, 17, 12, 0, 180, 110)
    _mk_record_minutes(P1, tz_area, 2025, 9, 9, 23, 30, 120, 180)
    _mk_record_minutes(P1, tz_area, 2025, 9, 10, 0, 0, 120, 220)

    anns = []
    for pilot in [P1, P2, P4, P5]:
        for day in random.sample(range(1, 31), 5):
            area = random.choice(areas)
            ann = Announcement(pilot=pilot,
                               battle_area=area,
                               x_coord=area.x_coord,
                               y_coord=area.y_coord,
                               z_coord=area.z_coord,
                               start_time=local_to_utc(datetime(2025, 9, day, 12, 0, 0)),
                               duration_hours=6.0,
                               recurrence_type=RecurrenceType.NONE,
                               created_by=captains[0])
            ann.save()
            anns.append(ann)

    print("\n=== 复杂场景数据已生成 ===")
    print(f"数据库名: {db_name}")
    print(f"连接串: mongodb://localhost:27017/{db_name}")
    print("\n建议必须测试的报表日期（GMT+8本地日）：")
    must_test_dates = [
        '2025-09-09',  # P1/P2 变更前
        '2025-09-10',  # P1 30% 生效日
        '2025-09-17',  # P2 变更前最后一天（15%）
        '2025-09-18',  # P2 40% 生效日
        '2025-09-22',  # P4 达到22天左右，检查5档
        '2025-09-19',  # P5 达到18天附近，检查3档
        '2025-09-12',  # P6 覆盖第1档（>=12天阈值附近）
        '2025-09-26',  # P7 最近7天不足3天开播（应为空）
        '2025-09-28',  # P7 若增加一天则仍不足或恰好不足
        '2025-09-21',  # P8 跨日记录：应归属9/21
        '2025-09-01',  # 月初：检查月范围起点
        '2025-09-30',  # 月末：检查月范围终点
        '2025-08-31',  # TE3：不应计入9月
        '2025-10-01',  # TE4：不应计入9月
        '2025-09-16',  # TE5：同日累积=6.0 有效
        '2025-09-17',  # TE6：同日累积=5.9 非有效
    ]
    for d in must_test_dates:
        print(f"  - {d}")


def main():
    try:
        disconnect()
    except:  # pylint: disable=bare-except
        pass

    db_name = _rand_db_name()
    connect(db_name, host='mongodb://localhost:27017')

    app = Flask(__name__)
    app.config.update({
        'TESTING': True,
        'MONGODB_URI': f'mongodb://localhost:27017/{db_name}',
        'SECRET_KEY': 'debug-secret-key',
        'SECURITY_PASSWORD_SALT': 'debug-password-salt',
    })

    with app.app_context():
        _generate_data(app, db_name)


if __name__ == '__main__':
    main()
