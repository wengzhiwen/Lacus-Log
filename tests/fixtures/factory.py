"""测试数据工厂：创建角色、用户、机师、战斗区域、通告、作战记录等。

说明：
- 尽量不依赖外部状态，按需创建并返回对象；
- 对于需要角色/默认管理员的场景，可复用应用启动逻辑已创建的角色；
"""

# pylint: disable=import-error,no-member
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Tuple

from flask_security.utils import hash_password
from flask import current_app

from models.announcement import Announcement, RecurrenceType
from models.battle_area import Availability, BattleArea
from models.battle_record import BattleRecord
from models.pilot import Gender, Platform, Rank, Status, WorkMode, Pilot
from models.recruit import Recruit, RecruitChannel, RecruitStatus
from models.user import Role, User
from utils.timezone_helper import local_to_utc


def ensure_roles() -> Tuple[Role, Role]:
    """确保基础角色存在，返回 (gicho, kancho)。"""
    gicho = Role.objects(name='gicho').first()
    if not gicho:
        gicho = Role(name='gicho', description='议长')
        gicho.save()
    kancho = Role.objects(name='kancho').first()
    if not kancho:
        kancho = Role(name='kancho', description='舰长')
        kancho.save()
    return gicho, kancho


def create_user(username: str, role_name: str = 'kancho', active: bool = True) -> User:
    """创建用户，默认舰长角色。"""
    gicho, kancho = ensure_roles()
    role = gicho if role_name == 'gicho' else kancho
    existing = User.objects(username=username).first()
    if existing:
        return existing
    try:
        _ = current_app.config
        pwd = hash_password('test_password')
    except Exception:
        pwd = 'test_password'
    user = User(username=username, password=pwd, roles=[role], active=active)
    user.save()
    return user


def create_battle_area(x: str = 'X1', y: str = 'Y1', z: str = '1', availability: str = Availability.ENABLED.value) -> BattleArea:
    area = BattleArea(x_coord=x, y_coord=y, z_coord=z, availability=Availability(availability))
    area.save()
    return area


def create_pilot(nickname: str = '测试机师', owner: User | None = None, rank: Rank = Rank.CANDIDATE, platform: Platform = Platform.KUAISHOU,
                 work_mode: WorkMode = WorkMode.ONLINE, status: Status = Status.NOT_RECRUITED, gender: Gender = Gender.MALE,
                 birth_year: int | None = 1998, real_name: str | None = None) -> Pilot:
    if status in (Status.RECRUITED, Status.CONTRACTED):
        if not real_name:
            real_name = '测试姓名'
        if not birth_year:
            birth_year = 1995
    pilot = Pilot(nickname=nickname,
                  owner=owner,
                  rank=rank,
                  platform=platform,
                  work_mode=work_mode,
                  status=status,
                  gender=gender,
                  birth_year=birth_year,
                  real_name=real_name)
    pilot.save()
    return pilot


def create_announcement(pilot: Pilot, area: BattleArea, start_local: datetime, duration_hours: float = 2.0) -> Announcement:
    creator = pilot.owner or create_user('creator_user')
    ann = Announcement(pilot=pilot,
                       battle_area=area,
                       x_coord=area.x_coord,
                       y_coord=area.y_coord,
                       z_coord=area.z_coord,
                       start_time=local_to_utc(start_local),
                       duration_hours=duration_hours,
                       recurrence_type=RecurrenceType.NONE,
                       created_by=creator)
    ann.save()
    return ann


def create_battle_record(pilot: Pilot, start_local: datetime | None = None, end_local: datetime | None = None, x: str = 'X1', y: str = 'Y1', z: str = '1',
                         work_mode: WorkMode = WorkMode.OFFLINE, revenue: Decimal = Decimal('100.00'), base_salary: Decimal = Decimal('50.00'),
                         registrar: User | None = None, **kwargs) -> BattleRecord:
    if start_local is None and 'start_time' in kwargs:
        start_local = kwargs['start_time']
    if end_local is None and 'end_time' in kwargs:
        end_local = kwargs['end_time']
    if not registrar:
        registrar = create_user('registrar_user')
    
    record = BattleRecord(pilot=pilot,
                          start_time=local_to_utc(start_local),
                          end_time=local_to_utc(end_local),
                          x_coord=x,
                          y_coord=y,
                          z_coord=z,
                          work_mode=work_mode,
                          revenue_amount=revenue,
                          base_salary=base_salary,
                          owner_snapshot=pilot.owner,
                          registered_by=registrar)
    record.save()
    return record


def create_recruit(pilot: Pilot, recruiter: User, appointment_time: datetime | None = None, 
                   channel: RecruitChannel = RecruitChannel.BOSS, introduction_fee: Decimal = Decimal('0.00'),
                   remarks: str = '', status: RecruitStatus = RecruitStatus.STARTED) -> Recruit:
    """创建征召记录"""
    if not appointment_time:
        appointment_time = datetime.now() + timedelta(days=1)
    
    recruit = Recruit(pilot=pilot,
                      recruiter=recruiter,
                      appointment_time=local_to_utc(appointment_time),
                      channel=channel,
                      introduction_fee=introduction_fee,
                      remarks=remarks,
                      status=status)
    recruit.save()
    return recruit


def days_from_now_local(days: int) -> datetime:
    now = datetime.now()
    return now + timedelta(days=days)


