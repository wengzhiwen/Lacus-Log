# pylint: disable=no-member
import enum
import json
from datetime import datetime, timedelta

from mongoengine import (DateTimeField, Document, EnumField, FloatField, ReferenceField, StringField)

from utils.timezone_helper import get_current_utc_time

from .battle_area import BattleArea
from .pilot import Pilot
from .user import User


class RecurrenceType(enum.Enum):
    """重复类型枚举"""
    NONE = "无重复"
    DAILY = "每日"
    WEEKLY = "每周"
    CUSTOM = "自定义"


class Announcement(Document):
    """通告模型

    通告的核心数据模型，支持重复事件管理、时间冲突检查、
    坐标快照等功能，类似日历应用的事件管理。
    """

    # 关联信息字段
    pilot = ReferenceField(Pilot, required=True)
    battle_area = ReferenceField(BattleArea, required=True)

    # 坐标快照字段（用于显示，避免关联数据变更影响历史记录）
    x_coord = StringField(required=True, max_length=50)  # 基地
    y_coord = StringField(required=True, max_length=50)  # 场地
    z_coord = StringField(required=True, max_length=50)  # 坐席

    # 时间信息字段
    start_time = DateTimeField(required=True)
    duration_hours = FloatField(required=True, min_value=1.0, max_value=16.0)

    # 重复规则字段
    recurrence_type = EnumField(RecurrenceType, default=RecurrenceType.NONE)
    recurrence_pattern = StringField()  # JSON格式存储重复规则
    recurrence_end = DateTimeField()  # 重复结束时间
    parent_announcement = ReferenceField('self')  # 父通告ID（用于关联重复事件组）

    # 系统字段
    created_at = DateTimeField(default=get_current_utc_time)
    updated_at = DateTimeField(default=get_current_utc_time)
    created_by = ReferenceField(User, required=True)

    meta = {
        'collection':
        'announcements',
        'indexes': [
            {
                'fields': ['pilot', 'start_time']
            },
            {
                'fields': ['battle_area', 'start_time']
            },
            {
                'fields': ['start_time']
            },
            {
                'fields': ['parent_announcement']
            },
            {
                'fields': ['created_by']
            },
            {
                'fields': ['-start_time']
            },
            # 优化冲突检查性能的复合索引
            {
                'fields': ['start_time', 'duration_hours']
            },
            {
                'fields': ['pilot', 'start_time', 'duration_hours']
            },
            {
                'fields': ['battle_area', 'start_time', 'duration_hours']
            },
        ],
    }

    def clean(self):
        """数据验证和业务规则检查"""
        super().clean()

        # 时间验证（移除开始时间不能早于当前时间的限制，允许创建历史记录）

        # 时长验证（通过字段定义的min_value和max_value进行）
        if self.duration_hours:
            if self.duration_hours < 1.0 or self.duration_hours > 16.0:
                raise ValueError("时长必须在1-16小时之间")
            # 检查是否为0.5的倍数
            if (self.duration_hours * 2) % 1 != 0:
                raise ValueError("时长必须是0.5小时的倍数")

        # 重复规则验证
        if self.recurrence_type != RecurrenceType.NONE:
            if not self.recurrence_pattern:
                raise ValueError("设置重复类型时必须提供重复规则")

            # 验证JSON格式
            try:
                pattern = json.loads(self.recurrence_pattern)
                self._validate_recurrence_pattern(pattern)
            except (json.JSONDecodeError, ValueError) as e:
                raise ValueError(f"重复规则格式错误：{str(e)}") from e

            # 重复跨度不能超过60天
            if self.recurrence_end:
                max_span = self.start_time + timedelta(days=60)
                if self.recurrence_end > max_span:
                    raise ValueError("重复跨度不能超过60天")

        # 从关联的开播地点复制坐标快照
        if self.battle_area and not self.x_coord:
            self.x_coord = self.battle_area.x_coord
            self.y_coord = self.battle_area.y_coord
            self.z_coord = self.battle_area.z_coord

    def _validate_recurrence_pattern(self, pattern):
        """验证重复规则的内容"""
        if not isinstance(pattern, dict):
            raise ValueError("重复规则必须是JSON对象")

        pattern_type = pattern.get('type')
        if pattern_type != self.recurrence_type.value.lower():
            raise ValueError("重复规则类型与设置不匹配")

        if pattern_type == 'daily':
            interval = pattern.get('interval', 1)
            if not isinstance(interval, int) or interval < 1:
                raise ValueError("每日重复间隔必须是正整数")

        elif pattern_type == 'weekly':
            interval = pattern.get('interval', 1)
            if not isinstance(interval, int) or interval < 1:
                raise ValueError("每周重复间隔必须是正整数")

            days_of_week = pattern.get('days_of_week', [])
            if not isinstance(days_of_week, list) or not days_of_week:
                raise ValueError("每周重复必须指定星期几")

            for day in days_of_week:
                if not isinstance(day, int) or day < 1 or day > 7:
                    raise ValueError("星期几必须是1-7的整数")

        elif pattern_type == 'custom':
            specific_dates = pattern.get('specific_dates', [])
            if not isinstance(specific_dates, list) or not specific_dates:
                raise ValueError("自定义重复必须指定具体日期")

    def save(self, *args, **kwargs):
        """保存时更新修改时间"""
        self.updated_at = get_current_utc_time()
        return super().save(*args, **kwargs)

    @property
    def end_time(self):
        """计算结束时间"""
        if self.start_time and self.duration_hours:
            return self.start_time + timedelta(hours=self.duration_hours)
        return None

    @property
    def duration_display(self):
        """时长显示格式"""
        if self.duration_hours:
            if self.duration_hours == int(self.duration_hours):
                return f"{int(self.duration_hours)}小时"
            else:
                return f"{self.duration_hours}小时"
        return "未知"

    @property
    def recurrence_display(self):
        """重复规则显示"""
        if self.recurrence_type == RecurrenceType.NONE:
            return "不重复"

        if not self.recurrence_pattern:
            return self.recurrence_type.value

        try:
            pattern = json.loads(self.recurrence_pattern)

            if self.recurrence_type == RecurrenceType.DAILY:
                interval = pattern.get('interval', 1)
                if interval == 1:
                    return "每天"
                else:
                    return f"每{interval}天"

            elif self.recurrence_type == RecurrenceType.WEEKLY:
                interval = pattern.get('interval', 1)
                days_of_week = pattern.get('days_of_week', [])
                day_names = {1: '一', 2: '二', 3: '三', 4: '四', 5: '五', 6: '六', 7: '日'}
                day_str = '、'.join([f"周{day_names[day]}" for day in sorted(days_of_week)])

                if interval == 1:
                    return f"每周{day_str}"
                else:
                    return f"每{interval}周{day_str}"

            elif self.recurrence_type == RecurrenceType.CUSTOM:
                dates_count = len(pattern.get('specific_dates', []))
                return f"自定义（{dates_count}个日期）"

        except (json.JSONDecodeError, KeyError):
            return self.recurrence_type.value

        return self.recurrence_type.value

    def check_conflicts(self, exclude_self=True, exclude_ids=None):
        """检查时间冲突
        
        Args:
            exclude_self: 是否排除自身（用于编辑时检查）
            exclude_ids: 要排除的通告ID列表（用于编辑未来所有时排除多个通告）
            
        Returns:
            dict: 冲突检查结果
        """
        conflicts = {'area_conflicts': [], 'pilot_conflicts': []}

        if not self.start_time or not self.duration_hours:
            return conflicts

        end_time = self.end_time

        # 构建查询，排除指定的通告
        query = Announcement.objects
        exclude_list = []

        if exclude_self and self.id:
            exclude_list.append(self.id)

        if exclude_ids:
            exclude_list.extend(exclude_ids)

        if exclude_list:
            query = query.filter(id__nin=exclude_list)

        # 查找时间重叠的通告
        overlapping = query.filter(start_time__lt=end_time,
                                   # 这里需要计算其他通告的结束时间，MongoDB中无法直接计算，需要在应用层处理
                                   )

        for other in overlapping:
            other_end = other.end_time
            if other_end and other.start_time < end_time and other_end > self.start_time:
                # 检查区域冲突
                if other.battle_area.id == self.battle_area.id:
                    conflicts['area_conflicts'].append({
                        'announcement': other,
                        'conflict_start': max(self.start_time, other.start_time),
                        'conflict_end': min(end_time, other_end)
                    })

                # 检查主播冲突
                if other.pilot.id == self.pilot.id:
                    conflicts['pilot_conflicts'].append({
                        'announcement': other,
                        'conflict_start': max(self.start_time, other.start_time),
                        'conflict_end': min(end_time, other_end)
                    })

        return conflicts

    @classmethod
    def generate_recurrence_instances(cls, base_announcement):
        """根据重复规则生成具体的事件实例
        
        Args:
            base_announcement: 基础通告对象
            
        Returns:
            list: 生成的通告实例列表
        """
        if base_announcement.recurrence_type == RecurrenceType.NONE:
            return [base_announcement]

        if not base_announcement.recurrence_pattern:
            return [base_announcement]

        try:
            pattern = json.loads(base_announcement.recurrence_pattern)
        except json.JSONDecodeError:
            return [base_announcement]

        instances = [base_announcement]

        if base_announcement.recurrence_type == RecurrenceType.DAILY:
            instances.extend(cls._generate_daily_instances(base_announcement, pattern))
        elif base_announcement.recurrence_type == RecurrenceType.WEEKLY:
            instances.extend(cls._generate_weekly_instances(base_announcement, pattern))
        elif base_announcement.recurrence_type == RecurrenceType.CUSTOM:
            instances.extend(cls._generate_custom_instances(base_announcement, pattern))

        return instances

    @classmethod
    def _generate_daily_instances(cls, base, pattern):
        """生成每日重复的实例"""
        instances = []
        interval = pattern.get('interval', 1)
        end_date = base.recurrence_end or (base.start_time + timedelta(days=60))
        max_instances = 60  # 最多生成60个实例

        current_date = base.start_time + timedelta(days=interval)

        while current_date <= end_date and len(instances) < max_instances:
            instance = cls(pilot=base.pilot,
                           battle_area=base.battle_area,
                           x_coord=base.x_coord,
                           y_coord=base.y_coord,
                           z_coord=base.z_coord,
                           start_time=current_date,
                           duration_hours=base.duration_hours,
                           recurrence_type=RecurrenceType.NONE,
                           parent_announcement=base,
                           created_by=base.created_by)
            instances.append(instance)
            current_date += timedelta(days=interval)

        return instances

    @classmethod
    def _generate_weekly_instances(cls, base, pattern):
        """生成每周重复的实例"""
        instances = []
        interval = pattern.get('interval', 1)
        days_of_week = pattern.get('days_of_week', [])
        end_date = base.recurrence_end or (base.start_time + timedelta(days=60))
        max_instances = 60  # 最多生成60个实例

        # 从基准周的周一开始计算，再按间隔推进
        # Python中isoweekday: 周一=1, 周日=7
        base_week_monday = base.start_time - timedelta(days=base.start_time.isoweekday() - 1)
        week_start = base_week_monday

        while week_start <= end_date and len(instances) < max_instances:
            for day_of_week in days_of_week:
                if len(instances) >= max_instances:
                    break
                # 确保day_of_week是整数
                day_of_week = int(day_of_week) if isinstance(day_of_week, str) else day_of_week
                # 计算具体日期（1=周一，7=周日）
                days_ahead = day_of_week - 1  # 转换为0-6
                target_date = week_start + timedelta(days=days_ahead)
                target_datetime = target_date.replace(hour=base.start_time.hour, minute=base.start_time.minute, second=base.start_time.second)

                # 仅生成不早于基准开始时间的实例，避免本周内回溯生成
                if (target_datetime <= end_date and target_datetime >= base.start_time and target_datetime != base.start_time):
                    instance = cls(pilot=base.pilot,
                                   battle_area=base.battle_area,
                                   x_coord=base.x_coord,
                                   y_coord=base.y_coord,
                                   z_coord=base.z_coord,
                                   start_time=target_datetime,
                                   duration_hours=base.duration_hours,
                                   recurrence_type=RecurrenceType.NONE,
                                   parent_announcement=base,
                                   created_by=base.created_by)
                    instances.append(instance)

            week_start += timedelta(days=7 * interval)

        return instances

    @classmethod
    def _generate_custom_instances(cls, base, pattern):
        """生成自定义重复的实例"""
        instances = []
        specific_dates = pattern.get('specific_dates', [])
        max_instances = 60  # 最多生成60个实例

        for date_str in specific_dates:
            if len(instances) >= max_instances:
                break
            try:
                # 解析ISO格式的日期时间
                target_datetime = datetime.fromisoformat(date_str.replace('Z', '+00:00'))

                instance = cls(pilot=base.pilot,
                               battle_area=base.battle_area,
                               x_coord=base.x_coord,
                               y_coord=base.y_coord,
                               z_coord=base.z_coord,
                               start_time=target_datetime,
                               duration_hours=base.duration_hours,
                               recurrence_type=RecurrenceType.NONE,
                               parent_announcement=base,
                               created_by=base.created_by)
                instances.append(instance)
            except (ValueError, TypeError):
                continue  # 跳过无效的日期

        return instances

    def split_recurrence_group_from_current(self):
        """从当前通告开始分割循环组，创建新的循环组
        
        将原循环组分为两部分：
        1. 当前通告之前的保持原样
        2. 从当前通告开始的创建新循环组
        
        Returns:
            list: 从当前通告开始的新循环组通告列表（包含当前通告）
        """
        if not self.parent_announcement and self.recurrence_type == RecurrenceType.NONE:
            # 不是循环事件，直接返回当前通告
            return [self]

        # 确定父通告和所有子通告
        if self.parent_announcement:
            parent = self.parent_announcement
        else:
            parent = self

        # 获取所有相关通告（包括父通告）
        all_related = [parent] + list(Announcement.objects(parent_announcement=parent))

        # 按开始时间排序
        all_related.sort(key=lambda x: x.start_time)

        # 找到当前通告在序列中的位置
        current_index = -1
        for i, announcement in enumerate(all_related):
            if announcement.id == self.id:
                current_index = i
                break

        if current_index == -1:
            # 找不到当前通告，返回单个通告
            return [self]

        # 分割：current_index之前的保持原样，从current_index开始创建新组
        future_announcements = all_related[current_index:]

        if len(future_announcements) <= 1:
            # 只有当前一个通告，无需分割
            return future_announcements

        # 创建新的父通告（当前通告）
        new_parent = future_announcements[0]
        new_parent.parent_announcement = None

        # 重新设置重复规则（基于原父通告的规则）
        if parent.recurrence_type != RecurrenceType.NONE and parent.recurrence_pattern:
            new_parent.recurrence_type = parent.recurrence_type
            new_parent.recurrence_pattern = parent.recurrence_pattern
            new_parent.recurrence_end = parent.recurrence_end
        else:
            new_parent.recurrence_type = RecurrenceType.NONE
            new_parent.recurrence_pattern = None
            new_parent.recurrence_end = None

        new_parent.save()

        # 更新后续通告的父引用
        for announcement in future_announcements[1:]:
            announcement.parent_announcement = new_parent
            announcement.save()

        return future_announcements

    def get_future_announcements_in_group(self, include_self=True):
        """获取循环组中从当前通告开始的未来通告
        
        Args:
            include_self: 是否包含当前通告
            
        Returns:
            list: 未来通告列表
        """
        if not self.parent_announcement and self.recurrence_type == RecurrenceType.NONE:
            return [self] if include_self else []

        # 确定父通告
        if self.parent_announcement:
            parent = self.parent_announcement
        else:
            parent = self

        # 获取所有相关通告
        all_related = [parent] + list(Announcement.objects(parent_announcement=parent))

        # 按开始时间排序
        all_related.sort(key=lambda x: x.start_time)

        # 找到当前通告的位置
        current_index = -1
        for i, announcement in enumerate(all_related):
            if announcement.id == self.id:
                current_index = i
                break

        if current_index == -1:
            return [self] if include_self else []

        # 返回从当前开始的未来通告
        start_index = current_index if include_self else current_index + 1
        return all_related[start_index:]

    @property
    def is_in_recurrence_group(self):
        """判断是否在循环组中"""
        return self.parent_announcement is not None or (self.recurrence_type != RecurrenceType.NONE
                                                        and Announcement.objects(parent_announcement=self).count() > 0)


class AnnouncementChangeLog(Document):
    """通告变更记录模型"""

    announcement_id = ReferenceField(Announcement, required=True)
    user_id = ReferenceField(User, required=True)
    field_name = StringField(required=True)
    old_value = StringField()
    new_value = StringField()
    change_time = DateTimeField(default=get_current_utc_time)
    ip_address = StringField()

    meta = {
        'collection': 'announcement_change_logs',
        'indexes': [
            {
                'fields': ['announcement_id', '-change_time']
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
            'battle_area': '开播地点',
            'x_coord': '基地',
            'y_coord': '场地',
            'z_coord': '坐席',
            'start_time': '开始时间',
            'duration_hours': '时长',
            'recurrence_type': '重复类型',
            'recurrence_pattern': '重复模式',
            'recurrence_end': '重复结束时间',
        }
        return mapping.get(self.field_name, self.field_name)
