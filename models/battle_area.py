import enum

from mongoengine import DateTimeField, Document, EnumField, StringField
from utils.timezone_helper import get_current_utc_time


class Availability(enum.Enum):
    """可用性枚举"""
    ENABLED = "可用"
    DISABLED = "禁用"


class BattleArea(Document):
    """开播地点模型

    - 基地/场地/坐席 三段坐标，均为字符串且必填
    - 基地+场地+坐席 复合唯一键
    - 可用性枚举，默认可用
    - 创建/更新时间戳
    """

    x_coord = StringField(required=True, max_length=50)
    y_coord = StringField(required=True, max_length=50)
    z_coord = StringField(required=True, max_length=50)
    availability = EnumField(Availability, default=Availability.ENABLED, required=True)

    created_at = DateTimeField(default=get_current_utc_time)
    updated_at = DateTimeField(default=get_current_utc_time)

    meta = {
        'collection':
        'battle_areas',
        'indexes': [
            {
                'fields': ['x_coord', 'y_coord', 'z_coord'],
                'unique': True,
            },
            {
                'fields': ['x_coord']
            },
            {
                'fields': ['y_coord']
            },
            {
                'fields': ['availability']
            },
            {
                'fields': ['x_coord', 'y_coord']
            },
            {
                'fields': ['-x_coord', '-y_coord', '-z_coord']
            },
        ],
    }

    def clean(self):
        """基本验证"""
        super().clean()
        # 去除首尾空格
        if self.x_coord:
            self.x_coord = self.x_coord.strip()
        if self.y_coord:
            self.y_coord = self.y_coord.strip()
        if self.z_coord:
            self.z_coord = self.z_coord.strip()

        # 字段必填控制（StringField required 已管控，再增加最小长度校验）
        if not self.x_coord:
            raise ValueError("基地为必填项")
        if not self.y_coord:
            raise ValueError("场地为必填项")
        if not self.z_coord:
            raise ValueError("坐席为必填项")

    def save(self, *args, **kwargs):
        """保存时更新修改时间"""
        self.updated_at = get_current_utc_time()
        return super().save(*args, **kwargs)
