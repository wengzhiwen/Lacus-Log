from decimal import Decimal
from enum import Enum

from mongoengine import (DateTimeField, DecimalField, Document, EnumField, ReferenceField, StringField)

from utils.timezone_helper import get_current_utc_time

from .announcement import Announcement
from .pilot import Pilot, WorkMode
from .user import User


class BattleRecordStatus(Enum):
    """开播记录状态枚举"""
    LIVE = "live"  # 开播中
    ENDED = "ended"  # 已下播


class BattleRecord(Document):
    """开播记录模型
    
    记录主播实际参与开播的结果数据。
    所有日期时间在数据库中存储为UTC，界面显示和输入为GMT+8。
    """

    pilot = ReferenceField(Pilot, required=True)
    related_announcement = ReferenceField(Announcement)  # 关联通告（可选）

    start_time = DateTimeField(required=True)
    end_time = DateTimeField(required=True)

    status = EnumField(BattleRecordStatus, required=False)

    revenue_amount = DecimalField(min_value=0, precision=2, default=Decimal('0.00'))
    base_salary = DecimalField(min_value=0, precision=2, default=Decimal('0.00'))

    x_coord = StringField(required=False, max_length=50)  # 基地
    y_coord = StringField(required=False, max_length=50)  # 场地
    z_coord = StringField(required=False, max_length=50)  # 坐席

    work_mode = EnumField(WorkMode, required=True)

    owner_snapshot = ReferenceField(User, required=False)

    registered_by = ReferenceField(User, required=True)

    notes = StringField(max_length=200)

    created_at = DateTimeField(default=get_current_utc_time)
    updated_at = DateTimeField(default=get_current_utc_time)

    meta = {
        'collection':
        'battle_records',
        'indexes': [
            {
                'fields': ['start_time']
            },
            {
                'fields': ['start_time', 'pilot']
            },
            {
                'fields': ['start_time', 'owner_snapshot']
            },
            {
                'fields': ['pilot', '-start_time']
            },
            {
                'fields': ['-start_time', '-revenue_amount']
            },
            {
                'fields': ['owner_snapshot']
            },
            {
                'fields': ['registered_by']
            },
            {
                'fields': ['related_announcement']
            },
            {
                'fields': ['start_time', 'pilot', 'revenue_amount']
            },
        ],
    }

    def clean(self):
        """数据验证和业务规则检查"""
        super().clean()

        if self.start_time and self.end_time:
            if self.end_time <= self.start_time:
                raise ValueError("结束时间必须大于开始时间")

        if self.revenue_amount is not None:
            if self.revenue_amount < 0:
                raise ValueError("流水金额不能为负数")

        if self.base_salary is not None:
            if self.base_salary < 0:
                raise ValueError("底薪金额不能为负数")

        if self.work_mode == WorkMode.OFFLINE:
            if not (self.x_coord and self.y_coord and self.z_coord):
                raise ValueError("线下开播时必须填写基地/场地/坐席")
        else:
            self.x_coord = self.x_coord or ''
            self.y_coord = self.y_coord or ''
            self.z_coord = self.z_coord or ''

    def save(self, *args, **kwargs):
        """保存时更新修改时间"""
        self.updated_at = get_current_utc_time()
        return super().save(*args, **kwargs)

    @property
    def duration_hours(self):
        """计算开播时长（小时）"""
        if self.start_time and self.end_time:
            delta = self.end_time - self.start_time
            return round(delta.total_seconds() / 3600, 1)
        return None

    @property
    def battle_location(self):
        """返回开播地点位置字符串"""
        return f"{self.x_coord}-{self.y_coord}-{self.z_coord}"

    def get_work_mode_display(self):
        """开播方式显示名称"""
        if self.work_mode == WorkMode.OFFLINE:
            return "线下"
        if self.work_mode == WorkMode.ONLINE:
            return "线上"
        if self.work_mode == WorkMode.UNKNOWN:
            return "未知"
        return self.work_mode.value if self.work_mode else "未知"

    def get_status_display(self):
        """状态显示名称"""
        current = self.current_status
        if current == BattleRecordStatus.LIVE:
            return "开播中"
        if current == BattleRecordStatus.ENDED:
            return "已下播"
        return "未知状态"

    @property
    def current_status(self):
        """获取当前状态，兼容老数据"""
        # 老数据如果status字段为空，一律认定为"已下播"
        if not self.status or self.status.value == '':
            return BattleRecordStatus.ENDED
        return self.status

    def update_from_announcement(self, announcement):
        """从关联通告更新信息
        
        Args:
            announcement: 关联的通告对象
        """
        if announcement:
            self.start_time = announcement.start_time
            self.end_time = announcement.end_time
            self.x_coord = announcement.x_coord
            self.y_coord = announcement.y_coord
            self.z_coord = announcement.z_coord
            self.work_mode = announcement.pilot.work_mode
            self.owner_snapshot = announcement.pilot.owner


class BattleRecordChangeLog(Document):
    """作战记录变更记录模型"""

    battle_record_id = ReferenceField(BattleRecord, required=True)
    user_id = ReferenceField(User, required=True)
    field_name = StringField(required=True)
    old_value = StringField()
    new_value = StringField()
    change_time = DateTimeField(default=get_current_utc_time)
    ip_address = StringField()

    meta = {
        'collection': 'battle_record_change_logs',
        'indexes': [
            {
                'fields': ['battle_record_id', '-change_time']
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
            'related_announcement': '关联通告',
            'start_time': '开始时间',
            'end_time': '结束时间',
            'status': '状态',
            'revenue_amount': '流水金额',
            'base_salary': '底薪金额',
            'x_coord': 'X坐标',
            'y_coord': 'Y坐标',
            'z_coord': 'Z坐标',
            'work_mode': '开播方式',
            'notes': '备注',
        }
        return mapping.get(self.field_name, self.field_name)
