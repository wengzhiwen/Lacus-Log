import enum
from datetime import datetime, timedelta

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
    # 新六步制流程状态
    PENDING_INTERVIEW = "待面试"
    PENDING_TRAINING_SCHEDULE = "待预约试播"
    PENDING_TRAINING = "待试播"
    PENDING_BROADCAST_SCHEDULE = "待预约开播"
    PENDING_BROADCAST = "待开播"
    ENDED = "已结束"

    # 废弃状态（历史兼容）
    STARTED = "已启动"  # 映射到 PENDING_INTERVIEW
    TRAINING_RECRUITING = "试播招募中"  # 映射到 PENDING_TRAINING
    # 历史兼容值（读老写新）
    TRAINING_RECRUITING_OLD = "训练征召中"  # 映射到 PENDING_TRAINING


class InterviewDecision(enum.Enum):
    """面试决策枚举"""
    SCHEDULE_TRAINING = "预约试播"
    NOT_RECRUIT = "不招募"
    
    # 历史兼容值（读老写新）
    SCHEDULE_TRAINING_OLD = "预约训练"  # 映射到 SCHEDULE_TRAINING
    NOT_RECRUIT_OLD = "不征召"         # 映射到 NOT_RECRUIT


class TrainingDecision(enum.Enum):
    """试播决策枚举"""
    SCHEDULE_BROADCAST = "预约开播"
    NOT_RECRUIT = "不招募"
    
    # 历史兼容值（读老写新）
    NOT_RECRUIT_OLD = "不征召"         # 映射到 NOT_RECRUIT

class BroadcastDecision(enum.Enum):
    """开播决策枚举"""
    OFFICIAL = "正式主播"
    INTERN = "实习主播"
    NOT_RECRUIT = "不招募"
    
    # 历史兼容值（读老写新）
    OFFICIAL_OLD = "正式机师"  # 映射到 OFFICIAL
    INTERN_OLD = "实习机师"    # 映射到 INTERN
    NOT_RECRUIT_OLD = "不征召" # 映射到 NOT_RECRUIT


# 废弃决策枚举（历史兼容）
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

    # 关联信息
    pilot = ReferenceField(Pilot, required=True)
    recruiter = ReferenceField(User, required=True)

    # 招募信息
    appointment_time = DateTimeField(required=True)
    channel = EnumField(RecruitChannel, required=True)
    introduction_fee = DecimalField(min_value=0, precision=2, default=0)
    remarks = StringField(max_length=200)
    status = EnumField(RecruitStatus, default=RecruitStatus.PENDING_INTERVIEW)

    # 新六步制流程字段
    # 面试决策相关字段
    interview_decision = EnumField(InterviewDecision)
    interview_decision_maker = ReferenceField(User)
    interview_decision_time = DateTimeField()

    # 预约试播相关字段
    scheduled_training_time = DateTimeField()
    scheduled_training_decision_maker = ReferenceField(User)
    scheduled_training_decision_time = DateTimeField()

    # 试播决策相关字段
    training_decision = EnumField(TrainingDecision)
    training_decision_maker = ReferenceField(User)
    training_decision_time = DateTimeField()

    # 预约开播相关字段
    scheduled_broadcast_time = DateTimeField()
    scheduled_broadcast_decision_maker = ReferenceField(User)
    scheduled_broadcast_decision_time = DateTimeField()

    # 开播决策相关字段
    broadcast_decision = EnumField(BroadcastDecision)
    broadcast_decision_maker = ReferenceField(User)
    broadcast_decision_time = DateTimeField()

    # 废弃字段（历史兼容）
    # 试播招募相关字段（废弃）
    training_decision_old = EnumField(TrainingDecisionOld)
    training_decision_maker_old = ReferenceField(User)
    training_decision_time_old = DateTimeField()
    training_time = DateTimeField()

    # 结束招募相关字段（废弃）
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
            # 新六步制字段索引
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
            # 征召日报统计所需索引
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
            # 废弃字段索引（历史兼容）
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

        # 验证招募负责人必须是运营或管理员
        if self.recruiter and not (self.recruiter.has_role('kancho') or self.recruiter.has_role('gicho')):
            raise ValueError("招募负责人必须是运营或管理员")

        # 验证介绍费为有效的非负数
        if self.introduction_fee and self.introduction_fee < 0:
            raise ValueError("介绍费必须为非负数")

        # 验证新六步制流程字段的一致性
        # 面试决策相关字段验证
        if self.interview_decision:
            if not self.interview_decision_maker:
                raise ValueError("面试决策时必须有决策人")
            if not self.interview_decision_time:
                raise ValueError("面试决策时必须有决策时间")

        # 预约试播相关字段验证
        if self.scheduled_training_time:
            if not self.scheduled_training_decision_maker:
                raise ValueError("预约试播时必须有决策人")
            if not self.scheduled_training_decision_time:
                raise ValueError("预约试播时必须有决策时间")

        # 试播决策相关字段验证
        if self.training_decision:
            if not self.training_decision_maker:
                raise ValueError("试播决策时必须有决策人")
            if not self.training_decision_time:
                raise ValueError("试播决策时必须有决策时间")

        # 预约开播相关字段验证
        if self.scheduled_broadcast_time:
            if not self.scheduled_broadcast_decision_maker:
                raise ValueError("预约开播时必须有决策人")
            if not self.scheduled_broadcast_decision_time:
                raise ValueError("预约开播时必须有决策时间")

        # 开播决策相关字段验证
        if self.broadcast_decision:
            if not self.broadcast_decision_maker:
                raise ValueError("开播决策时必须有决策人")
            if not self.broadcast_decision_time:
                raise ValueError("开播决策时必须有决策时间")

        # 废弃字段验证（历史兼容）
        # 验证试播招募决策相关字段的一致性
        if self.training_decision_old:
            if not self.training_decision_maker_old:
                raise ValueError("试播招募决策时必须有决策人")
            if not self.training_decision_time_old:
                raise ValueError("试播招募决策时必须有决策时间")
            if self.training_decision_old == TrainingDecisionOld.RECRUIT_AS_TRAINEE and not self.training_time:
                raise ValueError("招募为试播主播时必须填写试播时间")

        # 验证结束招募决策相关字段的一致性
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
        """获取默认预约时间：次日16:00（GMT+8）"""
        from utils.timezone_helper import get_current_local_time, local_to_utc

        # 计算次日16:00的本地时间（基于GMT+8）
        current_local = get_current_local_time()
        tomorrow = current_local.date() + timedelta(days=1)
        local_appointment = datetime.combine(tomorrow, datetime.min.time().replace(hour=16))
        # 转换为UTC时间存储
        return local_to_utc(local_appointment)

    def get_effective_status(self):
        """获取有效状态（处理历史数据映射）"""
        status_val = self.status.value if hasattr(self.status, 'value') else self.status

        # 根据用户提供的规则，将历史状态映射到对应的当前状态
        if status_val == "待预约训练":
            return RecruitStatus.PENDING_TRAINING_SCHEDULE  # 待预约试播
        
        if status_val in ["待训练", "训练征召中", "试播招募中"]:
            return RecruitStatus.PENDING_TRAINING  # 待试播

        if status_val == "已启动":
            return RecruitStatus.PENDING_INTERVIEW  # 待面试

        # 对于已经是新版状态的，直接返回原始枚举成员
        try:
            return RecruitStatus(status_val)
        except ValueError:
            return self.status

    def get_effective_interview_decision(self):
        """获取有效面试决策（处理历史数据降级读取）"""
        if self.interview_decision:
            return self.interview_decision

        # 降级读取：从废弃字段读取
        effective_status = self.get_effective_status()
        if effective_status in [
                RecruitStatus.PENDING_TRAINING_SCHEDULE, RecruitStatus.PENDING_TRAINING, RecruitStatus.PENDING_BROADCAST_SCHEDULE,
                RecruitStatus.PENDING_BROADCAST, RecruitStatus.ENDED
        ]:
            if self.training_decision_old:
                # 根据训练征召决策映射到面试决策
                if self.training_decision_old == TrainingDecisionOld.RECRUIT_AS_TRAINEE:
                    return InterviewDecision.SCHEDULE_TRAINING
                else:
                    return InterviewDecision.NOT_RECRUIT
        return None

    def get_effective_interview_decision_maker(self):
        """获取有效面试决策人（处理历史数据降级读取）"""
        if self.interview_decision_maker:
            return self.interview_decision_maker

        # 降级读取：从废弃字段读取
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

        # 降级读取：从废弃字段读取
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

        # 降级读取：从废弃字段读取
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

        # 降级读取：从废弃字段读取
        effective_status = self.get_effective_status()
        if effective_status in [RecruitStatus.PENDING_BROADCAST_SCHEDULE, RecruitStatus.PENDING_BROADCAST, RecruitStatus.ENDED]:
            if self.training_decision_old:
                # 根据训练征召决策映射到训练决策
                if self.training_decision_old == TrainingDecisionOld.RECRUIT_AS_TRAINEE:
                    return TrainingDecision.SCHEDULE_BROADCAST
                else:
                    return TrainingDecision.NOT_RECRUIT
        return None

    def get_effective_training_decision_maker(self):
        """获取有效训练决策人（处理历史数据降级读取）"""
        if self.training_decision_maker:
            return self.training_decision_maker

        # 降级读取：从废弃字段读取
        effective_status = self.get_effective_status()
        if effective_status in [RecruitStatus.PENDING_BROADCAST_SCHEDULE, RecruitStatus.PENDING_BROADCAST, RecruitStatus.ENDED]:
            return self.training_decision_maker_old
        return None

    def get_effective_training_decision_time(self):
        """获取有效训练决策时间（处理历史数据降级读取）"""
        if self.training_decision_time:
            return self.training_decision_time

        # 降级读取：从废弃字段读取
        effective_status = self.get_effective_status()
        if effective_status in [RecruitStatus.PENDING_BROADCAST_SCHEDULE, RecruitStatus.PENDING_BROADCAST, RecruitStatus.ENDED]:
            return self.training_decision_time_old
        return None

    def get_effective_scheduled_broadcast_time(self):
        """获取有效预约开播时间（处理历史数据降级读取）"""
        if self.scheduled_broadcast_time:
            return self.scheduled_broadcast_time

        # 降级读取：从废弃字段读取
        effective_status = self.get_effective_status()
        if effective_status in [RecruitStatus.PENDING_BROADCAST, RecruitStatus.ENDED]:
            return self.training_time  # 旧版训练时间同时作为预约开播时间
        return None

    def get_effective_broadcast_decision(self):
        """获取有效开播决策（处理历史数据降级读取）"""
        if self.broadcast_decision:
            return self.broadcast_decision

        # 降级读取：从废弃字段读取
        effective_status = self.get_effective_status()
        if effective_status == RecruitStatus.ENDED:
            return self.final_decision
        return None

    def get_effective_broadcast_decision_maker(self):
        """获取有效开播决策人（处理历史数据降级读取）"""
        if self.broadcast_decision_maker:
            return self.broadcast_decision_maker

        # 降级读取：从废弃字段读取
        effective_status = self.get_effective_status()
        if effective_status == RecruitStatus.ENDED:
            return self.final_decision_maker
        return None

    def get_effective_broadcast_decision_time(self):
        """获取有效开播决策时间（处理历史数据降级读取）"""
        if self.broadcast_decision_time:
            return self.broadcast_decision_time

        # 降级读取：从废弃字段读取
        effective_status = self.get_effective_status()
        if effective_status == RecruitStatus.ENDED:
            return self.final_decision_time
        return None

    @classmethod
    def get_effective_status_value(cls, status_value):
        """获取有效的招募状态（兼容历史数据）"""
        if not status_value:
            return None
        
        # 历史数据映射
        old_to_new_mapping = {
            "已启动": RecruitStatus.PENDING_INTERVIEW,
            "训练征召中": RecruitStatus.PENDING_TRAINING,
        }
        
        # 如果是历史数据，返回映射后的新值
        if status_value in old_to_new_mapping:
            return old_to_new_mapping[status_value]
        
        # 如果是新数据，直接返回
        try:
            return RecruitStatus(status_value)
        except ValueError:
            return None

    @classmethod
    def get_effective_interview_decision_value(cls, decision_value):
        """获取有效的面试决策（兼容历史数据）"""
        if not decision_value:
            return None
        
        # 历史数据映射
        old_to_new_mapping = {
            "预约训练": InterviewDecision.SCHEDULE_TRAINING,
            "不征召": InterviewDecision.NOT_RECRUIT,
        }
        
        # 如果是历史数据，返回映射后的新值
        if decision_value in old_to_new_mapping:
            return old_to_new_mapping[decision_value]
        
        # 如果是新数据，直接返回
        try:
            return InterviewDecision(decision_value)
        except ValueError:
            return None

    @classmethod
    def get_effective_training_decision_value(cls, decision_value):
        """获取有效的试播决策（兼容历史数据）"""
        if not decision_value:
            return None
        
        # 历史数据映射
        old_to_new_mapping = {
            "预约开播": TrainingDecision.SCHEDULE_BROADCAST,
            "不征召": TrainingDecision.NOT_RECRUIT,
        }
        
        # 如果是历史数据，返回映射后的新值
        if decision_value in old_to_new_mapping:
            return old_to_new_mapping[decision_value]
        
        # 如果是新数据，直接返回
        try:
            return TrainingDecision(decision_value)
        except ValueError:
            return None

    @classmethod
    def get_effective_broadcast_decision_value(cls, decision_value):
        """获取有效的开播决策（兼容历史数据）"""
        if not decision_value:
            return None
        
        # 历史数据映射
        old_to_new_mapping = {
            "正式机师": BroadcastDecision.OFFICIAL,
            "实习机师": BroadcastDecision.INTERN,
            "不征召": BroadcastDecision.NOT_RECRUIT,
        }
        
        # 如果是历史数据，返回映射后的新值
        if decision_value in old_to_new_mapping:
            return old_to_new_mapping[decision_value]
        
        # 如果是新数据，直接返回
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
            # 新六步制字段
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
            # 废弃字段（历史兼容）
            'training_decision_old': '试播招募决策 (历史)',
            'training_decision_maker_old': '试播招募决策人 (历史)',
            'training_decision_time_old': '试播招募决策时间 (历史)',
            'training_time': '试播时间 (历史)',
            'final_decision': '结束招募决策 (历史)',
            'final_decision_maker': '结束招募决策人 (历史)',
            'final_decision_time': '结束招募决策时间 (历史)',
        }
        return mapping.get(self.field_name, self.field_name)
