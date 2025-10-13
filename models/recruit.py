import enum

from mongoengine import (DateTimeField, DecimalField, Document, EnumField, ReferenceField, StringField)

from utils.timezone_helper import get_current_utc_time

from .pilot import Pilot
from .user import User


class RecruitChannel(enum.Enum):
    """招募渠道枚举"""
    BOSS = "BOSS"
    JOB_51 = "51"
    INTRODUCTION = "介绍"
    OTHER = "其他"


class RecruitStatus(enum.Enum):
    """招募状态枚举"""
    PENDING_INTERVIEW = "待面试"
    PENDING_TRAINING_SCHEDULE = "待预约试播"
    PENDING_TRAINING = "待试播"
    PENDING_BROADCAST_SCHEDULE = "待预约开播"
    PENDING_BROADCAST = "待开播"
    ENDED = "已结束"

    STARTED = "已启动"  # 映射到 PENDING_INTERVIEW
    PENDING_TRAINING_SCHEDULE_OLD = "待预约训练"  # 映射到 PENDING_TRAINING_SCHEDULE
    PENDING_TRAINING_OLD = "待训练"  # 映射到 PENDING_TRAINING
    TRAINING_RECRUITING = "试播招募中"  # 映射到 PENDING_TRAINING
    TRAINING_RECRUITING_OLD = "训练征召中"  # 映射到 PENDING_TRAINING


class InterviewDecision(enum.Enum):
    """面试决策枚举"""
    SCHEDULE_TRAINING = "预约试播"
    NOT_RECRUIT = "不招募"

    SCHEDULE_TRAINING_OLD = "预约训练"  # 映射到 SCHEDULE_TRAINING
    NOT_RECRUIT_OLD = "不征召"  # 映射到 NOT_RECRUIT


class TrainingDecision(enum.Enum):
    """试播决策枚举"""
    SCHEDULE_BROADCAST = "预约开播"
    NOT_RECRUIT = "不招募"

    NOT_RECRUIT_OLD = "不征召"  # 映射到 NOT_RECRUIT


class BroadcastDecision(enum.Enum):
    """开播决策枚举"""
    OFFICIAL = "正式主播"
    INTERN = "实习主播"
    NOT_RECRUIT = "不招募"

    OFFICIAL_OLD = "正式机师"  # 映射到 OFFICIAL
    INTERN_OLD = "实习机师"  # 映射到 INTERN
    NOT_RECRUIT_OLD = "不征召"  # 映射到 NOT_RECRUIT


class TrainingDecisionOld(enum.Enum):
    """试播招募决策枚举（废弃）"""
    RECRUIT_AS_TRAINEE = "招募为试播主播"
    NOT_RECRUIT = "不招募"


class FinalDecision(enum.Enum):
    """结束招募决策枚举（废弃）"""
    OFFICIAL = "正式主播"
    INTERN = "实习主播"
    NOT_RECRUIT = "不招募"


class Recruit(Document):
    """主播招募模型"""

    pilot = ReferenceField(Pilot, required=True)
    recruiter = ReferenceField(User, required=True)

    appointment_time = DateTimeField(required=True)
    channel = EnumField(RecruitChannel, required=True)
    introduction_fee = DecimalField(min_value=0, precision=2, default=0)
    remarks = StringField(max_length=200)
    status = EnumField(RecruitStatus, default=RecruitStatus.PENDING_INTERVIEW)

    interview_decision = EnumField(InterviewDecision)
    interview_decision_maker = ReferenceField(User)
    interview_decision_time = DateTimeField()

    scheduled_training_time = DateTimeField()
    scheduled_training_decision_maker = ReferenceField(User)
    scheduled_training_decision_time = DateTimeField()

    training_decision = EnumField(TrainingDecision)
    training_decision_maker = ReferenceField(User)
    training_decision_time = DateTimeField()

    scheduled_broadcast_time = DateTimeField()
    scheduled_broadcast_decision_maker = ReferenceField(User)
    scheduled_broadcast_decision_time = DateTimeField()

    broadcast_decision = EnumField(BroadcastDecision)
    broadcast_decision_maker = ReferenceField(User)
    broadcast_decision_time = DateTimeField()

    training_decision_old = EnumField(TrainingDecisionOld)
    training_decision_maker_old = ReferenceField(User)
    training_decision_time_old = DateTimeField()
    training_time = DateTimeField()

    final_decision = EnumField(FinalDecision)
    final_decision_maker = ReferenceField(User)
    final_decision_time = DateTimeField()

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
                'fields': ['interview_decision']
            },
            {
                'fields': ['training_decision']
            },
            {
                'fields': ['broadcast_decision']
            },
            {
                'fields': ['-scheduled_training_time']
            },
            {
                'fields': ['-scheduled_broadcast_time']
            },
            {
                'fields': ['-interview_decision_time']
            },
            {
                'fields': ['-broadcast_decision_time']
            },
            {
                'fields': ['-training_decision_time']
            },
            {
                'fields': ['-scheduled_training_decision_time']
            },
            {
                'fields': ['-scheduled_broadcast_decision_time']
            },
            {
                'fields': ['training_decision_old']
            },
            {
                'fields': ['final_decision']
            },
            {
                'fields': ['-training_time']
            },
            {
                'fields': ['-training_decision_time_old']
            },
            {
                'fields': ['-final_decision_time']
            },
        ],
    }

    def clean(self):
        """数据验证和业务规则检查"""
        super().clean()

        if self.recruiter and not (self.recruiter.has_role('kancho') or self.recruiter.has_role('gicho')):
            raise ValueError("招募负责人必须是运营或管理员")

        if self.introduction_fee and self.introduction_fee < 0:
            raise ValueError("介绍费必须为非负数")

        if self.interview_decision:
            if not self.interview_decision_maker:
                raise ValueError("面试决策时必须有决策人")
            if not self.interview_decision_time:
                raise ValueError("面试决策时必须有决策时间")

        if self.scheduled_training_time:
            if not self.scheduled_training_decision_maker:
                raise ValueError("预约试播时必须有决策人")
            if not self.scheduled_training_decision_time:
                raise ValueError("预约试播时必须有决策时间")

        if self.training_decision:
            if not self.training_decision_maker:
                raise ValueError("试播决策时必须有决策人")
            if not self.training_decision_time:
                raise ValueError("试播决策时必须有决策时间")

        if self.scheduled_broadcast_time:
            if not self.scheduled_broadcast_decision_maker:
                raise ValueError("预约开播时必须有决策人")
            if not self.scheduled_broadcast_decision_time:
                raise ValueError("预约开播时必须有决策时间")

        if self.broadcast_decision:
            if not self.broadcast_decision_maker:
                raise ValueError("开播决策时必须有决策人")
            if not self.broadcast_decision_time:
                raise ValueError("开播决策时必须有决策时间")

        if self.training_decision_old:
            if not self.training_decision_maker_old:
                raise ValueError("试播招募决策时必须有决策人")
            if not self.training_decision_time_old:
                raise ValueError("试播招募决策时必须有决策时间")
            if self.training_decision_old == TrainingDecisionOld.RECRUIT_AS_TRAINEE and not self.training_time:
                raise ValueError("招募为试播主播时必须填写试播时间")

        if self.final_decision:
            if not self.final_decision_maker:
                raise ValueError("结束招募决策时必须有决策人")
            if not self.final_decision_time:
                raise ValueError("结束招募决策时必须有决策时间")

    def save(self, *args, **kwargs):
        """保存时更新修改时间"""
        self.updated_at = get_current_utc_time()
        return super().save(*args, **kwargs)

    @classmethod
    def get_default_appointment_time(cls):
        """获取默认预约时间：下一个14:00（GMT+8）"""
        from utils.timezone_helper import get_next_14_oclock_local, local_to_utc

        local_appointment = get_next_14_oclock_local()
        return local_to_utc(local_appointment)

    def get_effective_status(self):
        """获取有效状态（处理历史数据映射）"""
        status_val = self.status.value if hasattr(self.status, 'value') else self.status

        if status_val == "待预约训练":
            return RecruitStatus.PENDING_TRAINING_SCHEDULE  # 待预约试播

        if status_val in ["待训练", "训练征召中", "试播招募中"]:
            return RecruitStatus.PENDING_TRAINING  # 待试播

        if status_val == "已启动":
            return RecruitStatus.PENDING_INTERVIEW  # 待面试

        try:
            return RecruitStatus(status_val)
        except ValueError:
            return self.status

    def get_effective_interview_decision(self):
        """获取有效面试决策（处理历史数据降级读取）"""
        if self.interview_decision:
            return self.interview_decision

        effective_status = self.get_effective_status()
        if effective_status in [
                RecruitStatus.PENDING_TRAINING_SCHEDULE, RecruitStatus.PENDING_TRAINING, RecruitStatus.PENDING_BROADCAST_SCHEDULE,
                RecruitStatus.PENDING_BROADCAST, RecruitStatus.ENDED
        ]:
            if self.training_decision_old:
                if self.training_decision_old == TrainingDecisionOld.RECRUIT_AS_TRAINEE:
                    return InterviewDecision.SCHEDULE_TRAINING
                else:
                    return InterviewDecision.NOT_RECRUIT
        return None

    def get_effective_interview_decision_maker(self):
        """获取有效面试决策人（处理历史数据降级读取）"""
        if self.interview_decision_maker:
            return self.interview_decision_maker

        effective_status = self.get_effective_status()
        if effective_status in [
                RecruitStatus.PENDING_TRAINING_SCHEDULE, RecruitStatus.PENDING_TRAINING, RecruitStatus.PENDING_BROADCAST_SCHEDULE,
                RecruitStatus.PENDING_BROADCAST, RecruitStatus.ENDED
        ]:
            return self.training_decision_maker_old
        return None

    def get_effective_interview_decision_time(self):
        """获取有效面试决策时间（处理历史数据降级读取）"""
        if self.interview_decision_time:
            return self.interview_decision_time

        effective_status = self.get_effective_status()
        if effective_status in [
                RecruitStatus.PENDING_TRAINING_SCHEDULE, RecruitStatus.PENDING_TRAINING, RecruitStatus.PENDING_BROADCAST_SCHEDULE,
                RecruitStatus.PENDING_BROADCAST, RecruitStatus.ENDED
        ]:
            return self.training_decision_time_old
        return None

    def get_effective_scheduled_training_time(self):
        """获取有效预约训练时间（处理历史数据降级读取）"""
        if self.scheduled_training_time:
            return self.scheduled_training_time

        effective_status = self.get_effective_status()
        if effective_status in [RecruitStatus.PENDING_TRAINING, RecruitStatus.PENDING_BROADCAST_SCHEDULE, RecruitStatus.PENDING_BROADCAST, RecruitStatus.ENDED]:
            return self.training_time
        return None

    def get_effective_scheduled_training_decision_maker(self):
        """获取有效预约训练决策人"""
        return self.scheduled_training_decision_maker

    def get_effective_scheduled_training_decision_time(self):
        """获取有效预约训练决策时间"""
        return self.scheduled_training_decision_time

    def get_effective_scheduled_broadcast_decision_maker(self):
        """获取有效预约开播决策人"""
        return self.scheduled_broadcast_decision_maker

    def get_effective_scheduled_broadcast_decision_time(self):
        """获取有效预约开播决策时间"""
        return self.scheduled_broadcast_decision_time

    def get_effective_training_decision(self):
        """获取有效训练决策（处理历史数据降级读取）"""
        if self.training_decision:
            return self.training_decision

        effective_status = self.get_effective_status()
        if effective_status in [RecruitStatus.PENDING_BROADCAST_SCHEDULE, RecruitStatus.PENDING_BROADCAST, RecruitStatus.ENDED]:
            if self.training_decision_old:
                if self.training_decision_old == TrainingDecisionOld.RECRUIT_AS_TRAINEE:
                    return TrainingDecision.SCHEDULE_BROADCAST
                else:
                    return TrainingDecision.NOT_RECRUIT
        return None

    def get_effective_training_decision_maker(self):
        """获取有效训练决策人（处理历史数据降级读取）"""
        if self.training_decision_maker:
            return self.training_decision_maker

        effective_status = self.get_effective_status()
        if effective_status in [RecruitStatus.PENDING_BROADCAST_SCHEDULE, RecruitStatus.PENDING_BROADCAST, RecruitStatus.ENDED]:
            return self.training_decision_maker_old
        return None

    def get_effective_training_decision_time(self):
        """获取有效训练决策时间（处理历史数据降级读取）"""
        if self.training_decision_time:
            return self.training_decision_time

        effective_status = self.get_effective_status()
        if effective_status in [RecruitStatus.PENDING_BROADCAST_SCHEDULE, RecruitStatus.PENDING_BROADCAST, RecruitStatus.ENDED]:
            return self.training_decision_time_old
        return None

    def get_effective_scheduled_broadcast_time(self):
        """获取有效预约开播时间（处理历史数据降级读取）"""
        if self.scheduled_broadcast_time:
            return self.scheduled_broadcast_time

        effective_status = self.get_effective_status()
        if effective_status in [RecruitStatus.PENDING_BROADCAST, RecruitStatus.ENDED]:
            return self.training_time  # 旧版训练时间同时作为预约开播时间
        return None

    def get_effective_broadcast_decision(self):
        """获取有效开播决策（处理历史数据降级读取）"""
        if self.broadcast_decision:
            return self.broadcast_decision

        effective_status = self.get_effective_status()
        if effective_status == RecruitStatus.ENDED:
            return self.final_decision
        return None

    def get_effective_broadcast_decision_maker(self):
        """获取有效开播决策人（处理历史数据降级读取）"""
        if self.broadcast_decision_maker:
            return self.broadcast_decision_maker

        effective_status = self.get_effective_status()
        if effective_status == RecruitStatus.ENDED:
            return self.final_decision_maker
        return None

    def get_effective_broadcast_decision_time(self):
        """获取有效开播决策时间（处理历史数据降级读取）"""
        if self.broadcast_decision_time:
            return self.broadcast_decision_time

        effective_status = self.get_effective_status()
        if effective_status == RecruitStatus.ENDED:
            return self.final_decision_time
        return None

    @classmethod
    def get_effective_status_value(cls, status_value):
        """获取有效的招募状态（兼容历史数据）"""
        if not status_value:
            return None

        old_to_new_mapping = {
            "已启动": RecruitStatus.PENDING_INTERVIEW,
            "训练征召中": RecruitStatus.PENDING_TRAINING,
        }

        if status_value in old_to_new_mapping:
            return old_to_new_mapping[status_value]

        try:
            return RecruitStatus(status_value)
        except ValueError:
            return None

    @classmethod
    def get_effective_interview_decision_value(cls, decision_value):
        """获取有效的面试决策（兼容历史数据）"""
        if not decision_value:
            return None

        old_to_new_mapping = {
            "预约训练": InterviewDecision.SCHEDULE_TRAINING,
            "不征召": InterviewDecision.NOT_RECRUIT,
        }

        if decision_value in old_to_new_mapping:
            return old_to_new_mapping[decision_value]

        try:
            return InterviewDecision(decision_value)
        except ValueError:
            return None

    @classmethod
    def get_effective_training_decision_value(cls, decision_value):
        """获取有效的试播决策（兼容历史数据）"""
        if not decision_value:
            return None

        old_to_new_mapping = {
            "预约开播": TrainingDecision.SCHEDULE_BROADCAST,
            "不征召": TrainingDecision.NOT_RECRUIT,
        }

        if decision_value in old_to_new_mapping:
            return old_to_new_mapping[decision_value]

        try:
            return TrainingDecision(decision_value)
        except ValueError:
            return None

    @classmethod
    def get_effective_broadcast_decision_value(cls, decision_value):
        """获取有效的开播决策（兼容历史数据）"""
        if not decision_value:
            return None

        old_to_new_mapping = {
            "正式机师": BroadcastDecision.OFFICIAL,
            "实习机师": BroadcastDecision.INTERN,
            "不征召": BroadcastDecision.NOT_RECRUIT,
        }

        if decision_value in old_to_new_mapping:
            return old_to_new_mapping[decision_value]

        try:
            return BroadcastDecision(decision_value)
        except ValueError:
            return None


class RecruitChangeLog(Document):
    """主播招募变更记录模型"""

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
            'pilot': '主播',
            'recruiter': '招募负责人',
            'appointment_time': '预约时间',
            'channel': '渠道',
            'introduction_fee': '介绍费',
            'remarks': '备注',
            'status': '招募状态',
            'interview_decision': '面试决策',
            'interview_decision_maker': '面试决策人',
            'interview_decision_time': '面试决策时间',
            'scheduled_training_time': '预约试播时间',
            'scheduled_training_decision_maker': '预约试播决策人',
            'scheduled_training_decision_time': '预约试播决策时间',
            'training_decision': '试播决策',
            'training_decision_maker': '试播决策人',
            'training_decision_time': '试播决策时间',
            'scheduled_broadcast_time': '预约开播时间',
            'scheduled_broadcast_decision_maker': '预约开播决策人',
            'scheduled_broadcast_decision_time': '预约开播决策时间',
            'broadcast_decision': '开播决策',
            'broadcast_decision_maker': '开播决策人',
            'broadcast_decision_time': '开播决策时间',
            'training_decision_old': '试播招募决策 (历史)',
            'training_decision_maker_old': '试播招募决策人 (历史)',
            'training_decision_time_old': '试播招募决策时间 (历史)',
            'training_time': '试播时间 (历史)',
            'final_decision': '结束招募决策 (历史)',
            'final_decision_maker': '结束招募决策人 (历史)',
            'final_decision_time': '结束招募决策时间 (历史)',
        }
        return mapping.get(self.field_name, self.field_name)


class RecruitOperationType(enum.Enum):
    """招募操作类型枚举"""
    CREATE = "启动招募"
    EDIT = "编辑招募"
    INTERVIEW_DECISION = "面试决策"
    SCHEDULE_TRAINING = "预约试播"
    TRAINING_DECISION = "试播决策"
    SCHEDULE_BROADCAST = "预约开播"
    BROADCAST_DECISION = "开播决策"


class RecruitOperationLog(Document):
    """招募操作记录模型"""

    user_id = ReferenceField(User, required=True)
    operation_type = EnumField(RecruitOperationType, required=True)
    recruit_id = ReferenceField(Recruit, required=True)
    pilot_id = ReferenceField(Pilot, required=True)
    operation_time = DateTimeField(default=get_current_utc_time)
    ip_address = StringField()

    meta = {
        'collection': 'recruit_operation_logs',
        'indexes': [
            {
                'fields': ['-operation_time']
            },
            {
                'fields': ['user_id']
            },
            {
                'fields': ['operation_type']
            },
            {
                'fields': ['recruit_id']
            },
            {
                'fields': ['pilot_id']
            },
        ],
    }

    @property
    def operation_time_gmt8(self):
        """获取GMT+8格式的操作时间"""
        from utils.timezone_helper import utc_to_local
        return utc_to_local(self.operation_time).strftime('%Y-%m-%d %H:%M:%S')

    @property
    def user_nickname(self):
        """获取操作用户昵称"""
        return self.user_id.nickname if self.user_id else '未知用户'

    @property
    def pilot_nickname(self):
        """获取被操作主播昵称"""
        return self.pilot_id.nickname if self.pilot_id else '未知主播'
