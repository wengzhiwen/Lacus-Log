from decimal import Decimal

from mongoengine import (DateTimeField, DecimalField, Document, EnumField,
                         ReferenceField, StringField)

from utils.timezone_helper import get_current_utc_time

from .announcement import Announcement
from .pilot import Pilot, WorkMode
from .user import User


class BattleRecord(Document):
    """开播记录模型
    
    记录主播实际参与开播的结果数据。
    所有日期时间在数据库中存储为UTC，界面显示和输入为GMT+8。
    """

    # 关联信息字段
    pilot = ReferenceField(Pilot, required=True)
    related_announcement = ReferenceField(Announcement)  # 关联通告（可选）

    # 时间信息字段
    start_time = DateTimeField(required=True)
    end_time = DateTimeField(required=True)

    # 金额字段（人民币元，两位小数）
    revenue_amount = DecimalField(min_value=0, precision=2, default=Decimal('0.00'))
    base_salary = DecimalField(min_value=0, precision=2, default=Decimal('0.00'))

    # 坐标快照字段（仅线下必填；线上可为空）
    x_coord = StringField(required=False, max_length=50)  # 基地
    y_coord = StringField(required=False, max_length=50)  # 场地
    z_coord = StringField(required=False, max_length=50)  # 坐席

    # 开播方式（可从主播复制，但允许修改）
    work_mode = EnumField(WorkMode, required=True)

    # 直属运营快照（从主播复制，仅显示不可编辑；可为空表示主播无直属运营）
    owner_snapshot = ReferenceField(User, required=False)

    # 登记人（首次登记的操作人，仅显示不可编辑）
    registered_by = ReferenceField(User, required=True)

    # 备注
    notes = StringField(max_length=200)

    # 系统字段
    created_at = DateTimeField(default=get_current_utc_time)
    updated_at = DateTimeField(default=get_current_utc_time)

    meta = {
        'collection':
        'battle_records',
        'indexes': [
            # 主要查询索引：时间范围查询（开播日报的核心查询）
            {
                'fields': ['start_time']
            },
            # 复合索引：时间 + 主播（用于主播相关的时间范围查询）
            {
                'fields': ['start_time', 'pilot']
            },
            # 复合索引：时间 + 直属运营快照（用于筛选查询）
            {
                'fields': ['start_time', 'owner_snapshot']
            },
            # 复合索引：主播 + 时间（用于主播业绩等查询）
            {
                'fields': ['pilot', '-start_time']
            },
            # 排序索引：时间 + 流水（用于列表排序）
            {
                'fields': ['-start_time', '-revenue_amount']
            },
            # 单字段索引：直属运营快照
            {
                'fields': ['owner_snapshot']
            },
            # 单字段索引：登记人
            {
                'fields': ['registered_by']
            },
            # 单字段索引：关联通告
            {
                'fields': ['related_announcement']
            },
            # 月度查询优化索引：年月 + 主播（用于月度统计）
            {
                'fields': ['start_time', 'pilot', 'revenue_amount']
            },
        ],
    }

    def clean(self):
        """数据验证和业务规则检查"""
        super().clean()

        # 时间验证：结束时间必须大于开始时间
        if self.start_time and self.end_time:
            if self.end_time <= self.start_time:
                raise ValueError("结束时间必须大于开始时间")

        # 金额验证：保留两位小数
        if self.revenue_amount is not None:
            if self.revenue_amount < 0:
                raise ValueError("流水金额不能为负数")

        if self.base_salary is not None:
            if self.base_salary < 0:
                raise ValueError("底薪金额不能为负数")

        # 开播地点坐标：仅线下必填
        if self.work_mode == WorkMode.OFFLINE:
            if not (self.x_coord and self.y_coord and self.z_coord):
                raise ValueError("线下开播时必须填写基地/场地/坐席")
        else:
            # 线上：确保为空，避免误保存
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
            'revenue_amount': '流水金额',
            'base_salary': '底薪金额',
            'x_coord': 'X坐标',
            'y_coord': 'Y坐标',
            'z_coord': 'Z坐标',
            'work_mode': '开播方式',
            'notes': '备注',
        }
        return mapping.get(self.field_name, self.field_name)
