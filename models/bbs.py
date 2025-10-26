from datetime import datetime
from enum import Enum
from typing import Optional

from mongoengine import (CASCADE, BooleanField, DateTimeField, DictField, Document, EnumField, IntField, ListField, ReferenceField, StringField)

from utils.timezone_helper import get_current_utc_time

from .battle_record import BattleRecord
from .pilot import Pilot
from .user import User


class BBSBoardType(Enum):
    """板块类型"""
    BASE = "base"
    CUSTOM = "custom"


class BBSPostStatus(Enum):
    """帖子状态"""
    PUBLISHED = "published"
    HIDDEN = "hidden"


class BBSReplyStatus(Enum):
    """回复状态"""
    PUBLISHED = "published"
    HIDDEN = "hidden"


class BBSBoard(Document):
    """内部BBS板块"""

    code = StringField(required=True, unique=True, max_length=64)
    name = StringField(required=True, max_length=128)
    board_type = EnumField(BBSBoardType, default=BBSBoardType.BASE, required=True)
    base_code = StringField(required=False, max_length=64)
    is_active = BooleanField(default=True)
    order = IntField(default=100)

    created_at = DateTimeField(default=get_current_utc_time)
    updated_at = DateTimeField(default=get_current_utc_time)

    meta = {
        'collection': 'bbs_boards',
        'indexes': [
            {
                'fields': ['code'],
                'unique': True
            },
            {
                'fields': ['board_type', 'is_active']
            },
            {
                'fields': ['order', 'name']
            },
        ],
    }

    def clean(self):
        super().clean()
        self.code = (self.code or '').strip()
        self.name = (self.name or '').strip()
        if not self.code:
            raise ValueError("板块编码不能为空")
        if not self.name:
            raise ValueError("板块名称不能为空")
        if self.board_type == BBSBoardType.BASE and not self.base_code:
            raise ValueError("基地板块必须关联基地编码")
        if self.base_code:
            self.base_code = self.base_code.strip()

    def save(self, *args, **kwargs):
        self.updated_at = get_current_utc_time()
        return super().save(*args, **kwargs)


class BBSPost(Document):
    """内部BBS主贴"""

    board = ReferenceField(BBSBoard, required=True, reverse_delete_rule=CASCADE)
    title = StringField(required=True, max_length=200)
    content = StringField(required=True)
    author = ReferenceField(User, required=True)
    author_snapshot = DictField(default=dict)
    status = EnumField(BBSPostStatus, default=BBSPostStatus.PUBLISHED, required=True)
    is_pinned = BooleanField(default=False)
    related_battle_record = ReferenceField(BattleRecord, required=False)
    pending_reviewers = ListField(StringField(max_length=32), default=list)
    last_active_at = DateTimeField(default=get_current_utc_time)

    created_at = DateTimeField(default=get_current_utc_time)
    updated_at = DateTimeField(default=get_current_utc_time)

    meta = {
        'collection':
        'bbs_posts',
        'indexes': [
            {
                'fields': ['board', '-is_pinned', '-last_active_at']
            },
            {
                'fields': ['status']
            },
            {
                'fields': ['related_battle_record']
            },
            {
                'fields': ['author']
            },
            {
                'fields': ['pending_reviewers']
            },
        ],
    }

    def clean(self):
        super().clean()
        self.title = (self.title or '').strip()
        if not self.title:
            raise ValueError("帖子标题不能为空")
        self.content = (self.content or '').strip()
        if not self.content:
            raise ValueError("帖子内容不能为空")

    def save(self, *args, **kwargs):
        self.updated_at = get_current_utc_time()
        if not self.last_active_at:
            self.last_active_at = self.updated_at
        return super().save(*args, **kwargs)

    def touch(self, timestamp: Optional[datetime] = None):
        """更新帖子最近活跃时间。"""
        self.last_active_at = timestamp or get_current_utc_time()
        self.updated_at = self.last_active_at
        super().save()


class BBSReply(Document):
    """内部BBS回复"""

    post = ReferenceField(BBSPost, required=True, reverse_delete_rule=CASCADE)
    parent_reply = ReferenceField('self', required=False, reverse_delete_rule=CASCADE)
    content = StringField(required=True)
    author = ReferenceField(User, required=True)
    author_snapshot = DictField(default=dict)
    status = EnumField(BBSReplyStatus, default=BBSReplyStatus.PUBLISHED, required=True)

    created_at = DateTimeField(default=get_current_utc_time)
    updated_at = DateTimeField(default=get_current_utc_time)

    meta = {
        'collection': 'bbs_replies',
        'indexes': [
            {
                'fields': ['post', '-created_at']
            },
            {
                'fields': ['parent_reply', '-created_at']
            },
            {
                'fields': ['status']
            },
        ],
    }

    def clean(self):
        super().clean()
        self.content = (self.content or '').strip()
        if not self.content:
            raise ValueError("回复内容不能为空")
        if self.parent_reply:
            if self.parent_reply.post.id != self.post.id:
                raise ValueError("楼中楼必须与父回复属于同一主贴")
            if self.parent_reply.parent_reply:
                raise ValueError("不允许回复的回复再被回复")

    def save(self, *args, **kwargs):
        self.updated_at = get_current_utc_time()
        return super().save(*args, **kwargs)


class PilotRelevance(Enum):
    """帖子与主播关联类型"""
    AUTO = "auto"
    MANUAL = "manual"


class BBSPostPilotRef(Document):
    """主贴与主播的关联索引"""

    post = ReferenceField(BBSPost, required=True, reverse_delete_rule=CASCADE)
    pilot = ReferenceField(Pilot, required=True)
    relevance = EnumField(PilotRelevance, default=PilotRelevance.MANUAL, required=True)
    created_at = DateTimeField(default=get_current_utc_time)
    updated_at = DateTimeField(default=get_current_utc_time)

    meta = {
        'collection': 'bbs_post_pilot_refs',
        'indexes': [
            {
                'fields': ['post', 'pilot', 'relevance'],
                'unique': True,
            },
            {
                'fields': ['pilot', '-updated_at']
            },
            {
                'fields': ['post']
            },
        ],
    }

    def save(self, *args, **kwargs):
        self.updated_at = get_current_utc_time()
        return super().save(*args, **kwargs)
