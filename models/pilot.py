#pylint: disable=no-member
import enum
from datetime import datetime

from mongoengine import (BooleanField, DateTimeField, Document, EnumField,
                         FloatField, IntField, ReferenceField, StringField)

from utils.timezone_helper import get_current_utc_time

from .user import User


class Gender(enum.Enum):
    """性别枚举"""
    MALE = 0  # 男
    FEMALE = 1  # 女
    UNKNOWN = 2  # 不明确


class Platform(enum.Enum):
    """平台枚举"""
    KUAISHOU = "快手"
    DOUYIN = "抖音"
    OTHER = "其他"
    UNKNOWN = "未知"


class WorkMode(enum.Enum):
    """参战形式枚举"""
    OFFLINE = "线下"
    ONLINE = "线上"
    UNKNOWN = "未知"


class Rank(enum.Enum):
    """阶级枚举"""
    CANDIDATE = "候补机师"
    TRAINEE = "训练机师"
    INTERN = "实习机师"
    OFFICIAL = "正式机师"


class Status(enum.Enum):
    """状态枚举"""
    NOT_RECRUITED = "未征召"
    NOT_RECRUITING = "不征召"
    RECRUITED = "已征召"
    CONTRACTED = "已签约"
    FALLEN = "已阵亡"


class Pilot(Document):
    """机师模型"""

    # 基础信息字段
    nickname = StringField(required=True, unique=True, max_length=20)
    real_name = StringField(max_length=20)
    gender = EnumField(Gender, default=Gender.FEMALE)
    birth_year = IntField()

    # 关联信息字段
    owner = ReferenceField(User)

    # 业务信息字段
    platform = EnumField(Platform, default=Platform.UNKNOWN)
    work_mode = EnumField(WorkMode, default=WorkMode.UNKNOWN)
    rank = EnumField(Rank, default=Rank.CANDIDATE)
    status = EnumField(Status, default=Status.NOT_RECRUITED)

    # 系统字段
    created_at = DateTimeField(default=get_current_utc_time)
    updated_at = DateTimeField(default=get_current_utc_time)

    meta = {
        'collection':
        'pilots',
        'indexes': [
            {
                'fields': ['nickname'],
                'unique': True
            },
            {
                'fields': ['owner']
            },
            {
                'fields': ['rank']
            },
            {
                'fields': ['status']
            },
            {
                'fields': ['platform']
            },
            {
                'fields': ['-created_at']
            },
        ],
    }

    def clean(self):
        """数据验证和业务规则检查"""
        super().clean()

        # 阶级规则：实习机师和正式机师必须有所属、战区不能是未知、参战形式不能是未知
        if self.rank in [Rank.INTERN, Rank.OFFICIAL]:
            if not self.owner:
                raise ValueError("实习机师和正式机师必须有所属")
            if self.platform == Platform.UNKNOWN:
                raise ValueError("实习机师和正式机师的战区不能是未知")
            if self.work_mode == WorkMode.UNKNOWN:
                raise ValueError("实习机师和正式机师的参战形式不能是未知")

        # 状态规则：已征召和已签约状态必须填写姓名和出生年
        if self.status in [Status.RECRUITED, Status.CONTRACTED]:
            if not self.real_name:
                raise ValueError("已征召和已签约状态必须填写姓名")
            if not self.birth_year:
                raise ValueError("已征召和已签约状态必须填写出生年")

        # 出生年份验证（距今60年前到距今10年前）
        if self.birth_year:
            current_year = datetime.now().year
            if self.birth_year < current_year - 60 or self.birth_year > current_year - 10:
                raise ValueError("出生年份必须在距今60年前到距今10年前之间")

    def save(self, *args, **kwargs):
        """保存时更新修改时间"""
        self.updated_at = get_current_utc_time()
        return super().save(*args, **kwargs)

    @property
    def age(self):
        """计算年龄"""
        if self.birth_year:
            return datetime.now().year - self.birth_year
        return None

    @property
    def gender_display(self):
        """性别显示名称"""
        mapping = {Gender.MALE: "男", Gender.FEMALE: "女", Gender.UNKNOWN: "不明确"}
        return mapping.get(self.gender, "未知")


class PilotChangeLog(Document):
    """机师变更记录模型"""

    pilot_id = ReferenceField(Pilot, required=True)
    user_id = ReferenceField(User, required=True)
    field_name = StringField(required=True)
    old_value = StringField()
    new_value = StringField()
    change_time = DateTimeField(default=get_current_utc_time)
    ip_address = StringField()

    meta = {
        'collection': 'pilot_change_logs',
        'indexes': [
            {
                'fields': ['pilot_id', '-change_time']
            },
            {
                'fields': ['user_id']
            },
            {
                'fields': ['-change_time']
            },
        ],
    }

    @property
    def field_display_name(self):
        """字段显示名称"""
        mapping = {
            'nickname': '昵称',
            'real_name': '姓名',
            'gender': '性别',
            'birth_year': '出生年',
            'owner': '所属',
            'platform': '战区',
            'work_mode': '参战形式',
            'rank': '阶级',
            'status': '状态',
        }
        return mapping.get(self.field_name, self.field_name)


class PilotCommission(Document):
    """机师分成调整记录模型"""

    # 关联字段
    pilot_id = ReferenceField(Pilot, required=True)

    # 业务字段
    adjustment_date = DateTimeField(required=True)  # 调整生效日期（UTC时间）
    commission_rate = FloatField(required=True)  # 分成比例（0-50，表示0%-50%）
    remark = StringField(max_length=200)  # 备注说明

    # 状态字段
    is_active = BooleanField(default=True)  # 是否有效（用于软删除）

    # 系统字段
    created_at = DateTimeField(default=get_current_utc_time)
    updated_at = DateTimeField(default=get_current_utc_time)

    meta = {
        'collection':
        'pilot_commissions',
        'indexes': [
            {
                'fields': ['pilot_id', 'adjustment_date']
            },
            {
                'fields': ['pilot_id', 'is_active']
            },
            {
                'fields': ['adjustment_date']
            },
            {
                'fields': ['is_active']
            },
            {
                'fields': ['-created_at']
            },
        ],
    }

    def clean(self):
        """数据验证和业务规则检查"""
        super().clean()

        # 分成比例范围验证（0-50）
        if self.commission_rate < 0 or self.commission_rate > 50:
            raise ValueError("分成比例必须在0-50之间")

        # 同一机师同一调整日唯一性验证（仅对有效记录）
        if self.is_active:
            existing = PilotCommission.objects(pilot_id=self.pilot_id, adjustment_date=self.adjustment_date, is_active=True).first()
            if existing and existing.id != self.id:
                raise ValueError("同一机师同一调整日只能有一条有效记录")

    def save(self, *args, **kwargs):
        """保存时更新修改时间"""
        self.updated_at = get_current_utc_time()
        return super().save(*args, **kwargs)

    @property
    def commission_rate_display(self):
        """分成比例显示格式"""
        return f"{self.commission_rate}%"

    @property
    def adjustment_date_local(self):
        """调整日期的本地时间显示"""
        from utils.timezone_helper import format_local_date
        return format_local_date(self.adjustment_date, '%Y-%m-%d')


class PilotCommissionChangeLog(Document):
    """机师分成调整记录变更日志模型"""

    commission_id = ReferenceField(PilotCommission, required=True)
    user_id = ReferenceField(User, required=True)
    field_name = StringField(required=True)
    old_value = StringField()
    new_value = StringField()
    change_time = DateTimeField(default=get_current_utc_time)
    ip_address = StringField()

    meta = {
        'collection': 'pilot_commission_change_logs',
        'indexes': [
            {
                'fields': ['commission_id', '-change_time']
            },
            {
                'fields': ['user_id']
            },
            {
                'fields': ['-change_time']
            },
        ],
    }

    @property
    def field_display_name(self):
        """字段显示名称"""
        mapping = {
            'adjustment_date': '调整日',
            'commission_rate': '分成比例',
            'remark': '备注',
            'is_active': '状态',
        }
        return mapping.get(self.field_name, self.field_name)
