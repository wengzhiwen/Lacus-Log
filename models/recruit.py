import enum
from datetime import datetime, timedelta

from mongoengine import (DateTimeField, DecimalField, Document, EnumField, ReferenceField, StringField)

from utils.timezone_helper import get_current_utc_time

from .pilot import Pilot
from .user import User


class RecruitChannel(enum.Enum):
    """征召渠道枚举"""
    BOSS = "BOSS"
    JOB_51 = "51"
    INTRODUCTION = "介绍"
    OTHER = "其他"


class RecruitStatus(enum.Enum):
    """征召状态枚举"""
    STARTED = "已启动"
    TRAINING_RECRUITING = "训练征召中"
    ENDED = "已结束"


class TrainingDecision(enum.Enum):
    """训练征召决策枚举"""
    RECRUIT_AS_TRAINEE = "征召为训练机师"
    NOT_RECRUIT = "不征召"


class FinalDecision(enum.Enum):
    """结束征召决策枚举"""
    OFFICIAL = "正式机师"
    INTERN = "实习机师"
    NOT_RECRUIT = "不征召"


class Recruit(Document):
    """机师征召模型"""

    # 关联信息
    pilot = ReferenceField(Pilot, required=True)
    recruiter = ReferenceField(User, required=True)

    # 征召信息
    appointment_time = DateTimeField(required=True)
    channel = EnumField(RecruitChannel, required=True)
    introduction_fee = DecimalField(min_value=0, precision=2, default=0)
    remarks = StringField(max_length=200)
    status = EnumField(RecruitStatus, default=RecruitStatus.STARTED)

    # 训练征召相关字段
    training_decision = EnumField(TrainingDecision)
    training_decision_maker = ReferenceField(User)
    training_decision_time = DateTimeField()
    training_time = DateTimeField()

    # 结束征召相关字段
    final_decision = EnumField(FinalDecision)
    final_decision_maker = ReferenceField(User)
    final_decision_time = DateTimeField()

    # 系统字段
    created_at = DateTimeField(default=get_current_utc_time)
    updated_at = DateTimeField(default=get_current_utc_time)

    meta = {
        'collection':
        'recruits',
        'indexes': [
            {
                'fields': ['pilot']
            },
            {
                'fields': ['recruiter']
            },
            {
                'fields': ['status']
            },
            {
                'fields': ['-appointment_time']
            },
            {
                'fields': ['-created_at']
            },
            {
                'fields': ['training_decision']
            },
            {
                'fields': ['final_decision']
            },
            {
                'fields': ['-training_time']
            },
        ],
    }

    def clean(self):
        """数据验证和业务规则检查"""
        super().clean()

        # 验证征召负责人必须是舰长或议长
        if self.recruiter and not (self.recruiter.has_role('kancho') or self.recruiter.has_role('gicho')):
            raise ValueError("征召负责人必须是舰长或议长")

        # 验证介绍费为有效的非负数
        if self.introduction_fee and self.introduction_fee < 0:
            raise ValueError("介绍费必须为非负数")

        # 验证训练时间不能早于预约时间
        if self.training_time and self.appointment_time:
            if self.training_time < self.appointment_time:
                raise ValueError("训练时间不能早于预约时间")

        # 验证训练征召决策相关字段的一致性
        if self.training_decision:
            if not self.training_decision_maker:
                raise ValueError("训练征召决策时必须有决策人")
            if not self.training_decision_time:
                raise ValueError("训练征召决策时必须有决策时间")
            if self.training_decision == TrainingDecision.RECRUIT_AS_TRAINEE and not self.training_time:
                raise ValueError("征召为训练机师时必须填写训练时间")

        # 验证结束征召决策相关字段的一致性
        if self.final_decision:
            if not self.final_decision_maker:
                raise ValueError("结束征召决策时必须有决策人")
            if not self.final_decision_time:
                raise ValueError("结束征召决策时必须有决策时间")

    def save(self, *args, **kwargs):
        """保存时更新修改时间"""
        self.updated_at = get_current_utc_time()
        return super().save(*args, **kwargs)

    @classmethod
    def get_default_appointment_time(cls):
        """获取默认预约时间：次日16:00（GMT+8）"""
        from utils.timezone_helper import get_current_local_time, local_to_utc

        # 计算次日16:00的本地时间（基于GMT+8）
        current_local = get_current_local_time()
        tomorrow = current_local.date() + timedelta(days=1)
        local_appointment = datetime.combine(tomorrow, datetime.min.time().replace(hour=16))
        # 转换为UTC时间存储
        return local_to_utc(local_appointment)


class RecruitChangeLog(Document):
    """机师征召变更记录模型"""

    recruit_id = ReferenceField(Recruit, required=True)
    user_id = ReferenceField(User, required=True)
    field_name = StringField(required=True)
    old_value = StringField()
    new_value = StringField()
    change_time = DateTimeField(default=get_current_utc_time)
    ip_address = StringField()

    meta = {
        'collection': 'recruit_change_logs',
        'indexes': [
            {
                'fields': ['recruit_id', '-change_time']
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
            'pilot': '机师',
            'recruiter': '征召负责人',
            'appointment_time': '预约时间',
            'channel': '渠道',
            'introduction_fee': '介绍费',
            'remarks': '备注',
            'status': '征召状态',
            'training_decision': '训练征召决策',
            'training_decision_maker': '训练征召决策人',
            'training_decision_time': '训练征召决策时间',
            'training_time': '训练时间',
            'final_decision': '结束征召决策',
            'final_decision_maker': '结束征召决策人',
            'final_decision_time': '结束征召决策时间',
        }
        return mapping.get(self.field_name, self.field_name)
