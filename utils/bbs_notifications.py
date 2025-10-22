from __future__ import annotations

import os
from datetime import timezone
from decimal import Decimal
from typing import Optional, Sequence

from models.battle_record import BattleRecord
from models.bbs import BBSPost, BBSReply
from models.user import User
from utils.mail_utils import send_email_md
from utils.logging_setup import get_logger
from utils.timezone_helper import GMT_PLUS_8, utc_to_local

logger = get_logger('bbs')


def _resolve_email(user: Optional[User]) -> Optional[str]:
    if not user:
        return None
    if hasattr(user, 'active') and not getattr(user, 'active', True):
        return None
    email = getattr(user, 'email', None)
    if not email:
        return None
    return email


def _same_user(left: Optional[User], right: Optional[User]) -> bool:
    if not left or not right:
        return False
    return str(getattr(left, 'id', '')) == str(getattr(right, 'id', ''))


def _build_link(path: str) -> str:
    base_url = os.getenv('BASE_URL', '').rstrip('/')
    normalized = path if path.startswith('/') else f'/{path}'
    if base_url:
        return f"{base_url}{normalized}"
    return normalized


def _slice_text(content: str, limit: int = 120) -> str:
    condensed = ' '.join((content or '').split())
    if not condensed:
        return '（无内容）'
    if len(condensed) <= limit:
        return condensed
    safe_limit = max(limit - 3, 0)
    return f"{condensed[:safe_limit]}..."


def _display_name(snapshot: Optional[dict], fallback: str = '未知用户') -> str:
    if not snapshot:
        return fallback
    for key in ('display_name', 'nickname', 'username'):
        value = snapshot.get(key)
        if value:
            return str(value)
    return fallback


def _normalize_to_local(timestamp):
    """将任意时间统一转换为GMT+8下的naive datetime。"""
    if timestamp is None:
        return None

    if timestamp.tzinfo is None:
        return utc_to_local(timestamp)

    offset = timestamp.utcoffset()
    gmt8_offset = GMT_PLUS_8.utcoffset(None)
    if offset == gmt8_offset:
        localized = timestamp.astimezone(GMT_PLUS_8)
        return localized.replace(tzinfo=None)

    utc_dt = timestamp.astimezone(timezone.utc)
    local_dt = utc_dt.astimezone(GMT_PLUS_8)
    return local_dt.replace(tzinfo=None)


def _format_datetime(timestamp) -> str:
    local_dt = _normalize_to_local(timestamp)
    if local_dt is None:
        return '未知时间'
    return local_dt.strftime('%Y-%m-%d %H:%M')


def _format_decimal(value: Optional[Decimal]) -> str:
    if value is None:
        return '0.00'
    return f"{Decimal(value):.2f}"


def _send_notification(recipients: Sequence[str], subject: str, md_content: str) -> None:
    unique_recipients = sorted({email for email in recipients if email})
    if not unique_recipients:
        return
    if not send_email_md(unique_recipients, subject, md_content):
        logger.warning('BBS邮件提醒发送失败：subject=%s recipients=%s', subject, unique_recipients)


def notify_post_author_new_reply(post: BBSPost, reply: BBSReply) -> None:
    recipient = _resolve_email(getattr(post, 'author', None))
    if not recipient:
        return
    if _same_user(getattr(post, 'author', None), getattr(reply, 'author', None)):
        return

    board_name = getattr(getattr(post, 'board', None), 'name', '未知板块')
    reply_author = _display_name(getattr(reply, 'author_snapshot', {}) or {})
    reply_time = _format_datetime(getattr(reply, 'created_at', None))
    summary = _slice_text(getattr(reply, 'content', ''), 160)
    link = _build_link(f'/bbs/posts/{post.id}')

    lines = [
        '### 主贴回复提醒',
        f'- 所属板块：{board_name}',
        f'- 帖子标题：{post.title}',
        f'- {reply_author} @ {reply_time}',
    ]

    parent_reply = getattr(reply, 'parent_reply', None)
    if parent_reply:
        target_name = _display_name(getattr(parent_reply, 'author_snapshot', {}) or {}, '未指定')
        lines.append(f'- 回复对象：{target_name}')

    lines.extend([
        '',
        '### 回复内容摘要',
        f'> {summary}',
        '',
        '### 快速入口',
        f'- [打开帖子]({link})',
    ])

    subject = "【拉科斯聊天装置】来看一下别人对你的回复"
    _send_notification([recipient], subject, '\n'.join(lines))


def notify_parent_reply_author(post: BBSPost, parent_reply: BBSReply, reply: BBSReply) -> None:
    recipient = _resolve_email(getattr(parent_reply, 'author', None))
    if not recipient:
        return
    if _same_user(getattr(parent_reply, 'author', None), getattr(reply, 'author', None)):
        return
    if _same_user(getattr(post, 'author', None), getattr(parent_reply, 'author', None)):
        return

    board_name = getattr(getattr(post, 'board', None), 'name', '未知板块')
    reply_author = _display_name(getattr(reply, 'author_snapshot', {}) or {})
    reply_time = _format_datetime(getattr(reply, 'created_at', None))
    summary = _slice_text(getattr(reply, 'content', ''), 160)
    parent_summary = _slice_text(getattr(parent_reply, 'content', ''), 160)
    link = _build_link(f'/bbs/posts/{post.id}')

    lines = [
        '### 回复提醒',
        f'- 所属板块：{board_name}',
        f'- 帖子标题：{post.title}',
        f'- {reply_time} @ {reply_author}',
        '',
        '### 回复摘要',
        f'> {summary}',
        '',
        '### 之前的内容',
        f'> {parent_summary}',
        '',
        '### 快速入口',
        f'- [打开帖子]({link})',
    ]

    subject = "【拉科斯聊天装置】大明星，您的回复收到了新的反馈"
    _send_notification([recipient], subject, '\n'.join(lines))


def notify_direct_operator_auto_post(record: BattleRecord, post: BBSPost) -> None:
    pilot = getattr(record, 'pilot', None)
    owner = getattr(pilot, 'owner', None) if pilot else None
    recipient = _resolve_email(owner)
    if not recipient:
        return

    pilot_name = getattr(pilot, 'nickname', None) or getattr(pilot, 'real_name', None) or '未知主播'
    board_name = getattr(getattr(post, 'board', None), 'name', '未知板块')
    trigger_time = _format_datetime(getattr(record, 'start_time', None))
    revenue = _format_decimal(getattr(record, 'revenue_amount', None))
    base_salary = _format_decimal(getattr(record, 'base_salary', None))
    notes = _slice_text(getattr(record, 'notes', '') or '', 300)
    post_link = _build_link(f'/bbs/posts/{post.id}')
    record_link = _build_link(f'/battle-records/{record.id}')

    lines = [
        '### 系统自动发帖提醒',
        f'- 主播：{pilot_name}',
        f'- 所属板块：{board_name}',
        f'- 开播时间：{trigger_time}',
        f'- 流水金额：¥{revenue}',
        f'- 底薪金额：¥{base_salary}',
        '- 因为被设定了备注而触发了自动发帖',
        '',
        '### 备注摘要',
        f'> {notes}',
        '',
        '### 快速入口',
        f'- [打开帖子]({post_link})',
        f'- [查看开播记录]({record_link})',
    ]

    subject = "【拉科斯聊天装置】为您旗下的重要主播自动生成了新贴"
    _send_notification([recipient], subject, '\n'.join(lines))
