"""
机师模型测试
"""
# pylint: disable=import-error,no-member
import pytest
from datetime import datetime
from mongoengine import connect, disconnect

from models.pilot import (Pilot, PilotChangeLog, Gender, Platform, WorkMode, Rank, Status)
from models.user import User, Role


@pytest.mark.unit
class TestPilotEnums:
    """测试机师枚举类型"""

    def test_gender_enum(self):
        """测试性别枚举"""
        assert Gender.MALE.value == 0
        assert Gender.FEMALE.value == 1
        assert Gender.UNKNOWN.value == 2

    def test_platform_enum(self):
        """测试平台枚举"""
        assert Platform.KUAISHOU.value == "快手"
        assert Platform.DOUYIN.value == "抖音"
        assert Platform.OTHER.value == "其他"
        assert Platform.UNKNOWN.value == "未知"

    def test_work_mode_enum(self):
        """测试参战形式枚举"""
        assert WorkMode.OFFLINE.value == "线下"
        assert WorkMode.ONLINE.value == "线上"
        assert WorkMode.UNKNOWN.value == "未知"

    def test_rank_enum(self):
        """测试阶级枚举"""
        assert Rank.CANDIDATE.value == "候补机师"
        assert Rank.TRAINEE.value == "训练机师"
        assert Rank.INTERN.value == "实习机师"
        assert Rank.OFFICIAL.value == "正式机师"

    def test_status_enum(self):
        """测试状态枚举"""
        assert Status.NOT_RECRUITED.value == "未征召"
        assert Status.NOT_RECRUITING.value == "不征召"
        assert Status.RECRUITED.value == "已征召"
        assert Status.CONTRACTED.value == "已签约"
        assert Status.FALLEN.value == "已阵亡"


@pytest.mark.unit
class TestPilotModel:
    """测试机师模型"""

    def test_pilot_creation(self):
        """测试机师创建"""
        pilot = Pilot(nickname="测试机师", real_name="张三", gender=Gender.FEMALE, birth_year=1995)

        assert pilot.nickname == "测试机师"
        assert pilot.real_name == "张三"
        assert pilot.gender == Gender.FEMALE
        assert pilot.birth_year == 1995
        assert pilot.platform == Platform.UNKNOWN  # 默认值
        assert pilot.work_mode == WorkMode.UNKNOWN  # 默认值
        assert pilot.rank == Rank.CANDIDATE  # 默认值
        assert pilot.status == Status.NOT_RECRUITED  # 默认值
        assert pilot.created_at is not None
        assert pilot.updated_at is not None

    def test_pilot_age_calculation(self):
        """测试年龄计算"""
        current_year = datetime.now().year

        pilot = Pilot(nickname="测试机师", birth_year=1995)
        expected_age = current_year - 1995
        assert pilot.age == expected_age

        pilot_no_birth = Pilot(nickname="测试机师2")
        assert pilot_no_birth.age is None

    def test_pilot_gender_display(self):
        """测试性别显示"""
        pilot_female = Pilot(nickname="女机师", gender=Gender.FEMALE)
        assert pilot_female.gender_display == "女"

        pilot_male = Pilot(nickname="男机师", gender=Gender.MALE)
        assert pilot_male.gender_display == "男"

        pilot_unknown = Pilot(nickname="未知机师", gender=Gender.UNKNOWN)
        assert pilot_unknown.gender_display == "不明确"


@pytest.mark.unit
class TestPilotValidation:
    """测试机师数据验证"""

    def test_birth_year_validation(self):
        """测试出生年份验证"""
        current_year = datetime.now().year

        pilot = Pilot(nickname="测试机师", birth_year=current_year - 30)
        pilot.clean()  # 应该不抛出异常

        pilot_too_old = Pilot(nickname="测试机师", birth_year=current_year - 70)
        with pytest.raises(ValueError, match="出生年份必须在距今60年前到距今10年前之间"):
            pilot_too_old.clean()

        pilot_too_young = Pilot(nickname="测试机师", birth_year=current_year - 5)
        with pytest.raises(ValueError, match="出生年份必须在距今60年前到距今10年前之间"):
            pilot_too_young.clean()

    def test_rank_validation(self):
        """测试阶级规则验证"""
        candidate = Pilot(nickname="候补机师", rank=Rank.CANDIDATE)
        candidate.clean()  # 应该不抛出异常

        intern = Pilot(nickname="实习机师", rank=Rank.INTERN, platform=Platform.UNKNOWN, work_mode=WorkMode.UNKNOWN)
        with pytest.raises(ValueError, match="实习机师和正式机师必须有所属"):
            intern.clean()

        user = User(username="test_owner", password="password")

        intern_with_owner = Pilot(nickname="实习机师", rank=Rank.INTERN, owner=user, platform=Platform.UNKNOWN, work_mode=WorkMode.UNKNOWN)
        with pytest.raises(ValueError, match="实习机师和正式机师的战区不能是未知"):
            intern_with_owner.clean()

        intern_with_platform = Pilot(nickname="实习机师", rank=Rank.INTERN, owner=user, platform=Platform.KUAISHOU, work_mode=WorkMode.UNKNOWN)
        with pytest.raises(ValueError, match="实习机师和正式机师的参战形式不能是未知"):
            intern_with_platform.clean()

        complete_intern = Pilot(nickname="实习机师", rank=Rank.INTERN, owner=user, platform=Platform.KUAISHOU, work_mode=WorkMode.ONLINE)
        complete_intern.clean()  # 应该不抛出异常

    def test_status_validation(self):
        """测试状态规则验证"""
        not_recruited = Pilot(nickname="未征召机师", status=Status.NOT_RECRUITED)
        not_recruited.clean()  # 应该不抛出异常

        recruited_no_name = Pilot(nickname="已征召机师", status=Status.RECRUITED, birth_year=1995)
        with pytest.raises(ValueError, match="已征召和已签约状态必须填写姓名"):
            recruited_no_name.clean()

        recruited_no_birth = Pilot(nickname="已征召机师", status=Status.RECRUITED, real_name="张三")
        with pytest.raises(ValueError, match="已征召和已签约状态必须填写出生年"):
            recruited_no_birth.clean()

        complete_recruited = Pilot(nickname="已征召机师", status=Status.RECRUITED, real_name="张三", birth_year=1995)
        complete_recruited.clean()  # 应该不抛出异常


@pytest.mark.unit
class TestPilotChangeLog:
    """测试机师变更记录模型"""

    def test_change_log_creation(self):
        """测试变更记录创建"""
        pilot = Pilot(nickname="测试机师")
        user = User(username="test_user", password="password")

        change_log = PilotChangeLog(pilot_id=pilot, user_id=user, field_name="nickname", old_value="旧昵称", new_value="新昵称", ip_address="127.0.0.1")

        assert change_log.pilot_id == pilot
        assert change_log.user_id == user
        assert change_log.field_name == "nickname"
        assert change_log.old_value == "旧昵称"
        assert change_log.new_value == "新昵称"
        assert change_log.ip_address == "127.0.0.1"
        assert change_log.change_time is not None

    def test_field_display_name(self):
        """测试字段显示名称映射"""
        change_log = PilotChangeLog()

        change_log.field_name = "nickname"
        assert change_log.field_display_name == "昵称"

        change_log.field_name = "real_name"
        assert change_log.field_display_name == "姓名"

        change_log.field_name = "gender"
        assert change_log.field_display_name == "性别"

        change_log.field_name = "birth_year"
        assert change_log.field_display_name == "出生年"

        change_log.field_name = "owner"
        assert change_log.field_display_name == "所属"

        change_log.field_name = "platform"
        assert change_log.field_display_name == "战区"

        change_log.field_name = "work_mode"
        assert change_log.field_display_name == "参战形式"

        change_log.field_name = "rank"
        assert change_log.field_display_name == "阶级"

        change_log.field_name = "status"
        assert change_log.field_display_name == "状态"

        change_log.field_name = "unknown_field"
        assert change_log.field_display_name == "unknown_field"


@pytest.mark.integration
@pytest.mark.requires_db
class TestPilotModelIntegration:
    """机师模型集成测试"""

    @pytest.fixture(autouse=True)
    def setup_db(self):
        """依赖 conftest 的连接。"""
        yield

    def test_pilot_save_and_load(self):
        """测试机师保存和加载"""
        pilot = Pilot(nickname="测试机师",
                      real_name="张三",
                      gender=Gender.FEMALE,
                      birth_year=1995,
                      platform=Platform.KUAISHOU,
                      work_mode=WorkMode.ONLINE,
                      rank=Rank.CANDIDATE,
                      status=Status.NOT_RECRUITED)
        pilot.save()

        loaded_pilot = Pilot.objects(nickname="测试机师").first()
        assert loaded_pilot is not None
        assert loaded_pilot.nickname == "测试机师"
        assert loaded_pilot.real_name == "张三"
        assert loaded_pilot.gender == Gender.FEMALE
        assert loaded_pilot.birth_year == 1995
        assert loaded_pilot.platform == Platform.KUAISHOU
        assert loaded_pilot.work_mode == WorkMode.ONLINE
        assert loaded_pilot.rank == Rank.CANDIDATE
        assert loaded_pilot.status == Status.NOT_RECRUITED

    def test_pilot_with_owner(self):
        """测试带所属的机师"""
        role = Role(name="kancho", description="舰长")
        role.save()

        user = User(username="test_owner", password="password", roles=[role])
        user.save()

        pilot = Pilot(nickname="测试机师", owner=user, rank=Rank.INTERN, platform=Platform.KUAISHOU, work_mode=WorkMode.ONLINE)
        pilot.save()

        loaded_pilot = Pilot.objects(nickname="测试机师").first()
        assert loaded_pilot is not None
        assert loaded_pilot.owner is not None
        assert loaded_pilot.owner.username == "test_owner"
        assert loaded_pilot.owner.has_role("kancho")

    def test_pilot_unique_constraints(self):
        """测试机师唯一约束"""
        pilot1 = Pilot(nickname="唯一机师", real_name="张三")
        pilot1.save()

        pilot2 = Pilot(nickname="唯一机师", real_name="李四")
        with pytest.raises(Exception):  # 应该是 NotUniqueError
            pilot2.save()

    def test_change_log_save_and_load(self):
        """测试变更记录保存和加载"""
        pilot = Pilot(nickname="测试机师")
        pilot.save()

        user = User(username="test_user", password="password")
        user.save()

        change_log = PilotChangeLog(pilot_id=pilot, user_id=user, field_name="nickname", old_value="旧昵称", new_value="新昵称", ip_address="127.0.0.1")
        change_log.save()

        loaded_log = PilotChangeLog.objects(pilot_id=pilot).first()
        assert loaded_log is not None
        assert loaded_log.field_name == "nickname"
        assert loaded_log.old_value == "旧昵称"
        assert loaded_log.new_value == "新昵称"
        assert loaded_log.ip_address == "127.0.0.1"
        assert loaded_log.user_id.username == "test_user"

    def test_pilot_update_time(self):
        """测试机师更新时间"""
        pilot = Pilot(nickname="时间测试机师")
        pilot.save()

        original_updated_time = pilot.updated_at

        import time
        time.sleep(0.1)

        pilot.real_name = "更新后的姓名"
        pilot.save()

        assert pilot.updated_at > original_updated_time
