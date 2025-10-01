# pylint: disable=no-member
import enum
from datetime import datetime

from mongoengine import (BooleanField, DateTimeField, Document, EnumField, FloatField, IntField, ReferenceField, StringField)

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
    """开播方式枚举"""
    OFFLINE = "线下"
    ONLINE = "线上"
    UNKNOWN = "未知"


class Rank(enum.Enum):
    """主播分类枚举"""
    CANDIDATE = "候选人"
    TRAINEE = "试播主播"
    INTERN = "实习主播"
    OFFICIAL = "正式主播"

    CANDIDATE_OLD = "候补机师"  # 映射到 CANDIDATE
    TRAINEE_OLD = "训练机师"  # 映射到 TRAINEE
    INTERN_OLD = "实习机师"  # 映射到 INTERN
    OFFICIAL_OLD = "正式机师"  # 映射到 OFFICIAL


class Status(enum.Enum):
    """状态枚举"""
    NOT_RECRUITED = "未招募"
    NOT_RECRUITING = "不招募"
    RECRUITED = "已招募"
    CONTRACTED = "已签约"
    FALLEN = "流失"

    NOT_RECRUITED_OLD = "未征召"  # 映射到 NOT_RECRUITED
    NOT_RECRUITING_OLD = "不征召"  # 映射到 NOT_RECRUITING
    RECRUITED_OLD = "已征召"  # 映射到 RECRUITED
    FALLEN_OLD = "已阵亡"  # 映射到 FALLEN


class Pilot(Document):
    """主播模型"""

    nickname = StringField(required=True, unique=True, max_length=20)
    real_name = StringField(max_length=20)
    gender = EnumField(Gender, default=Gender.FEMALE)
    hometown = StringField(max_length=20)  # 籍贯
    birth_year = IntField()

    owner = ReferenceField(User)

    platform = EnumField(Platform, default=Platform.UNKNOWN)
    work_mode = EnumField(WorkMode, default=WorkMode.UNKNOWN)
    rank = EnumField(Rank, default=Rank.CANDIDATE)
    status = EnumField(Status, default=Status.NOT_RECRUITED)

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

        if self.rank in [Rank.INTERN, Rank.OFFICIAL]:
            if not self.owner:
                raise ValueError("实习主播和正式主播必须有直属运营")
            if self.platform == Platform.UNKNOWN:
                raise ValueError("实习主播和正式主播的开播地点不能是未知")
            if self.work_mode == WorkMode.UNKNOWN:
                raise ValueError("实习主播和正式主播的开播方式不能是未知")

        if self.status in [Status.RECRUITED, Status.CONTRACTED]:
            if not self.real_name:
                raise ValueError("已招募和已签约状态必须填写姓名")
            if not self.birth_year:
                raise ValueError("已招募和已签约状态必须填写出生年")

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

    @property
    def rank_display(self):
        """主播分类显示名称（兼容历史数据）"""
        if self.rank == Rank.CANDIDATE:
            return "候选人"
        elif self.rank == Rank.TRAINEE:
            return "试播主播"
        elif self.rank == Rank.INTERN:
            return "实习主播"
        elif self.rank == Rank.OFFICIAL:
            return "正式主播"
        else:
            return self.rank.value if self.rank else "未知"

    @property
    def status_display(self):
        """状态显示名称（兼容历史数据）"""
        if self.status == Status.NOT_RECRUITED:
            return "未招募"
        elif self.status == Status.NOT_RECRUITING:
            return "不招募"
        elif self.status == Status.RECRUITED:
            return "已招募"
        elif self.status == Status.CONTRACTED:
            return "已签约"
        elif self.status == Status.FALLEN:
            return "流失"
        else:
            return self.status.value if self.status else "未知"

    @property
    def work_mode_display(self):
        """开播方式显示名称（兼容历史数据）"""
        if self.work_mode == WorkMode.OFFLINE:
            return "线下"
        elif self.work_mode == WorkMode.ONLINE:
            return "线上"
        elif self.work_mode == WorkMode.UNKNOWN:
            return "未知"
        else:
            return self.work_mode.value if self.work_mode else "未知"

    @property
    def platform_display(self):
        """开播地点显示名称（兼容历史数据）"""
        if self.platform == Platform.KUAISHOU:
            return "快手"
        elif self.platform == Platform.DOUYIN:
            return "抖音"
        elif self.platform == Platform.OTHER:
            return "其他"
        elif self.platform == Platform.UNKNOWN:
            return "未知"
        else:
            return self.platform.value if self.platform else "未知"

    @classmethod
    def get_effective_rank(cls, rank_value):
        """获取有效的主播分类（兼容历史数据）"""
        if not rank_value:
            return None

        old_to_new_mapping = {
            "候补机师": Rank.CANDIDATE,
            "训练机师": Rank.TRAINEE,
            "实习机师": Rank.INTERN,
            "正式机师": Rank.OFFICIAL,
        }

        if rank_value in old_to_new_mapping:
            return old_to_new_mapping[rank_value]

        try:
            return Rank(rank_value)
        except ValueError:
            return None

    @classmethod
    def get_effective_status(cls, status_value):
        """获取有效的状态（兼容历史数据）"""
        if not status_value:
            return None

        old_to_new_mapping = {
            "未征召": Status.NOT_RECRUITED,
            "不征召": Status.NOT_RECRUITING,
            "已征召": Status.RECRUITED,
            "已阵亡": Status.FALLEN,
        }

        if status_value in old_to_new_mapping:
            return old_to_new_mapping[status_value]

        try:
            return Status(status_value)
        except ValueError:
            return None

    def get_effective_rank_display(self):
        """获取有效的主播分类显示名称（兼容历史数据）"""
        effective_rank = self.get_effective_rank(self.rank.value if self.rank else None)
        if effective_rank:
            return effective_rank.value
        return "未知"

    def get_effective_status_display(self):
        """获取有效的状态显示名称（兼容历史数据）"""
        effective_status = self.get_effective_status(self.status.value if self.status else None)
        if effective_status:
            return effective_status.value
        return "未知"


class PilotChangeLog(Document):
    """主播变更记录模型"""

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
            'hometown': '籍贯',
            'birth_year': '出生年',
            'owner': '直属运营',
            'platform': '开播平台',
            'work_mode': '开播方式',
            'rank': '主播分类',
            'status': '状态',
        }
        return mapping.get(self.field_name, self.field_name)


class PilotCommission(Document):
    """主播分成调整记录模型"""

    pilot_id = ReferenceField(Pilot, required=True)

    adjustment_date = DateTimeField(required=True)  # 调整生效日期（UTC时间）
    commission_rate = FloatField(required=True)  # 分成比例（0-50，表示0%-50%）
    remark = StringField(max_length=200)  # 备注说明

    is_active = BooleanField(default=True)  # 是否有效（用于软删除）

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

        if self.commission_rate < 0 or self.commission_rate > 50:
            raise ValueError("分成比例必须在0-50之间")

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
    """主播分成调整记录变更日志模型"""

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
