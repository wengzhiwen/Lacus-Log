from __future__ import annotations

# pylint: disable=no-member

import logging
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from mongoengine.errors import DoesNotExist

from models.bbs import (BBSBoard, BBSPost, BBSReply, BBSReplyStatus, BBSPostStatus, BBSPostPilotRef, PilotRelevance)
from utils.timezone_helper import format_local_datetime, utc_to_local

logger = logging.getLogger('bbs')


def create_success_response(data: Any = None, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建成功响应。"""
    return {'success': True, 'data': data, 'error': None, 'meta': meta or {}}


def create_error_response(code: str, message: str, meta: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """创建失败响应。"""
    return {'success': False, 'data': None, 'error': {'code': code, 'message': message}, 'meta': meta or {}}


def _format_timestamp(utc_dt: Optional[datetime], fmt: str = '%Y-%m-%d %H:%M') -> Dict[str, Optional[str]]:
    """统一格式化UTC时间，返回iso和display。"""
    if not utc_dt:
        return {'iso': None, 'display': None}
    local_dt = utc_to_local(utc_dt)
    return {'iso': local_dt.isoformat() if local_dt else None, 'display': format_local_datetime(utc_dt, fmt)}


def _serialize_author(snapshot: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """标准化作者信息，提供昵称回退。"""
    snapshot = snapshot or {}
    nickname = snapshot.get('nickname') or ''
    username = snapshot.get('username') or ''
    display_name = snapshot.get('display_name') or nickname or username
    return {
        'id': snapshot.get('id'),
        'nickname': nickname,
        'username': username,
        'display_name': display_name,
        'roles': snapshot.get('roles', []),
        'avatar': snapshot.get('avatar'),
    }


def _safe_related_record(post: BBSPost) -> Dict[str, Any]:
    """安全获取关联开播记录信息，防止脏数据导致异常。"""
    dbref = getattr(post, '_data', {}).get('related_battle_record')
    record_id = None
    if dbref is not None:
        record_id = str(dbref.id)
    try:
        related = post.related_battle_record
    except DoesNotExist:
        if record_id:
            logger.warning('BBS帖子关联的开播记录已被删除：post=%s record=%s', post.id, record_id)
        else:
            logger.warning('BBS帖子关联的开播记录已被删除：post=%s record=未知', post.id)
        return {'id': record_id, 'missing': True}
    if not related:
        return {'id': None, 'missing': False}
    return {'id': str(related.id), 'missing': False}


def serialize_board(board: BBSBoard) -> Dict[str, Any]:
    """序列化板块信息。"""
    return {
        'id': str(board.id),
        'code': board.code,
        'name': board.name,
        'type': board.board_type.value if board.board_type else None,
        'base_code': board.base_code or '',
        'is_active': bool(board.is_active),
        'order': board.order or 0,
        'created_at': _format_timestamp(board.created_at),
        'updated_at': _format_timestamp(board.updated_at),
    }


def serialize_board_list(boards: Iterable[BBSBoard]) -> List[Dict[str, Any]]:
    """序列化板块列表。"""
    return [serialize_board(board) for board in boards]


def serialize_post_summary(post: BBSPost,
                           reply_count: int = 0,
                           last_reply_user: Optional[Dict[str, Any]] = None,
                           last_reply_time: Optional[datetime] = None) -> Dict[str, Any]:
    """序列化用于列表展示的帖子摘要。"""
    record_info = _safe_related_record(post)
    return {
        'id': str(post.id),
        'board_id': str(post.board.id) if post.board else None,
        'board': {
            'id': str(post.board.id) if post.board else None,
            'name': post.board.name if post.board else ''
        } if post.board else None,
        'title': post.title,
        'status': post.status.value if post.status else BBSPostStatus.PUBLISHED.value,
        'is_pinned': bool(post.is_pinned),
        'reply_count': reply_count,
        'author': _serialize_author(post.author_snapshot),
        'related_battle_record_id': record_info['id'],
        'related_battle_record_missing': record_info['missing'],
        'created_at': _format_timestamp(post.created_at),
        'updated_at': _format_timestamp(post.updated_at),
        'last_active_at': _format_timestamp(post.last_active_at),
        'last_reply': {
            'author': _serialize_author(last_reply_user),
            'time': _format_timestamp(last_reply_time)
        } if last_reply_time else None,
    }


def serialize_reply(reply: BBSReply, child_replies: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """序列化单条回复，附带楼中楼。"""
    return {
        'id': str(reply.id),
        'post_id': str(reply.post.id) if reply.post else None,
        'parent_reply_id': str(reply.parent_reply.id) if reply.parent_reply else None,
        'content': reply.content,
        'status': reply.status.value if reply.status else BBSReplyStatus.PUBLISHED.value,
        'author': _serialize_author(reply.author_snapshot),
        'created_at': _format_timestamp(reply.created_at),
        'updated_at': _format_timestamp(reply.updated_at),
        'children': child_replies or []
    }


def serialize_post_detail(post: BBSPost,
                          replies: Iterable[BBSReply],
                          pilot_refs: Optional[Iterable[BBSPostPilotRef]] = None,
                          latest_reply_time: Optional[datetime] = None,
                          latest_reply_author: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """序列化帖子详情（包含回复树与关联主播）。"""
    record_info = _safe_related_record(post)
    top_level: Dict[str, Dict[str, Any]] = {}
    for reply in replies:
        if reply.parent_reply:
            continue
        top_level[str(reply.id)] = serialize_reply(reply, [])

    for reply in replies:
        if not reply.parent_reply:
            continue
        parent_id = str(reply.parent_reply.id)
        if parent_id not in top_level:
            continue
        top_level[parent_id]['children'].append(serialize_reply(reply, []))

    reply_list = list(top_level.values())
    for item in reply_list:
        item['children'].sort(key=lambda x: x['created_at']['iso'] or '')
    reply_list.sort(key=lambda x: x['created_at']['iso'] or '')

    pilot_list = []
    for ref in pilot_refs or []:
        pilot_list.append({
            'post_id': str(ref.post.id) if ref.post else None,
            'pilot_id': str(ref.pilot.id) if ref.pilot else None,
            'pilot_name': getattr(ref.pilot, 'nickname', ''),
            'pilot_real_name': getattr(ref.pilot, 'real_name', ''),
            'relevance': ref.relevance.value if ref.relevance else PilotRelevance.MANUAL.value,
            'updated_at': _format_timestamp(ref.updated_at),
        })

    return {
        'post': {
            'id': str(post.id),
            'board_id': str(post.board.id) if post.board else None,
            'title': post.title,
            'content': post.content,
            'status': post.status.value if post.status else BBSPostStatus.PUBLISHED.value,
            'is_pinned': bool(post.is_pinned),
            'related_battle_record_id': record_info['id'],
            'related_battle_record_missing': record_info['missing'],
            'author': _serialize_author(post.author_snapshot),
            'created_at': _format_timestamp(post.created_at),
            'updated_at': _format_timestamp(post.updated_at),
            'last_active_at': _format_timestamp(post.last_active_at),
            'last_reply': {
                'author': _serialize_author(latest_reply_author),
                'time': _format_timestamp(latest_reply_time)
            } if latest_reply_time else None,
        },
        'replies': reply_list,
        'pilots': pilot_list,
    }
