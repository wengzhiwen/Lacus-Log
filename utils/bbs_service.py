from __future__ import annotations

# pylint: disable=no-member

import re
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from bson import ObjectId, errors as bson_errors
from mongoengine.queryset.visitor import Q

from models.battle_area import BattleArea
from models.battle_record import BattleRecord, BattleRecordStatus
from models.bbs import (BBSBoard, BBSBoardType, BBSPost, BBSPostStatus, BBSReply, BBSReplyStatus, BBSPostPilotRef, PilotRelevance)
from models.pilot import Pilot
from models.user import User
from utils.bbs_notifications import notify_direct_operator_auto_post
from utils.logging_setup import get_logger
from utils.timezone_helper import format_local_datetime, get_current_utc_time

logger = get_logger('bbs')


def build_author_snapshot(user: User, display_name: Optional[str] = None) -> Dict[str, object]:
    """构建作者快照，包含展示名与角色列表。"""
    roles = [role.name for role in getattr(user, 'roles', [])]
    return {
        'id': str(user.id),
        'nickname': user.nickname or '',
        'username': user.username,
        'display_name': display_name or user.nickname or user.username,
        'roles': roles,
    }


def _slugify_code(value: str) -> str:
    """将任意字符串转换为板块编码。"""
    value = (value or '').strip().lower()
    value = value.replace(' ', '-')
    slug = re.sub(r'[^a-z0-9_-]+', '', value)
    if not slug:
        slug = f"base-{abs(hash(value)) % 1_000_000}"
    return slug[:64]


def ensure_board_for_base(base_name: str) -> BBSBoard:
    """确保存在对应基地板块，若不存在则创建。"""
    base_name = (base_name or '').strip()
    if not base_name:
        raise ValueError('基地名称不能为空')

    code = _slugify_code(base_name)
    board = BBSBoard.objects(code=code).first()  # type: ignore[attr-defined]
    if board:
        if not board.is_active:
            board.is_active = True
            board.save()
            logger.info('自动启用基地板块：%s(%s)', base_name, code)
        return board

    board = BBSBoard(
        code=code,
        name=base_name,
        board_type=BBSBoardType.BASE,
        base_code=base_name,
        order=50,
    )
    board.save()
    logger.info('自动创建基地板块：%s(%s)', base_name, code)
    return board


def ensure_base_boards_from_battle_areas() -> List[BBSBoard]:
    """确保现有开播地点基地都拥有对应板块。"""
    created: List[BBSBoard] = []
    base_names = BattleArea.objects.distinct('x_coord')  # type: ignore[attr-defined]
    for base_name in base_names:
        if not base_name:
            continue
        board = ensure_board_for_base(base_name)
        if board not in created:
            created.append(board)
    return created


def ensure_manual_pilot_refs(post: BBSPost, pilot_ids: Sequence[str]) -> Tuple[List[BBSPostPilotRef], List[str]]:
    """根据传入的主播ID列表同步手动关联。

    返回（当前关联对象列表，缺失ID列表）。
    """
    existing_manual = list(BBSPostPilotRef.objects(post=post, relevance=PilotRelevance.MANUAL))  # type: ignore[attr-defined]
    existing_map = {str(ref.pilot.id): ref for ref in existing_manual if ref.pilot}

    desired_ids = [pid for pid in pilot_ids if pid]
    to_delete = [ref for pid, ref in existing_map.items() if pid not in desired_ids]
    for ref in to_delete:
        ref.delete()

    linked_refs: List[BBSPostPilotRef] = []
    missing_ids: List[str] = []

    for pid in desired_ids:
        if pid in existing_map:
            ref = existing_map[pid]
            ref.updated_at = get_current_utc_time()
            ref.save()
            linked_refs.append(ref)
            continue
        try:
            pilot = Pilot.objects.get(id=pid)  # type: ignore[attr-defined]
        except Exception as exc:  # pylint: disable=broad-except
            logger.warning('关联主播失败，ID=%s：%s', pid, exc)
            missing_ids.append(pid)
            continue
        ref = BBSPostPilotRef(post=post, pilot=pilot, relevance=PilotRelevance.MANUAL)
        ref.save()
        linked_refs.append(ref)

    return linked_refs, missing_ids


def create_reply_snapshot(user: User) -> Dict[str, object]:
    """创建回复的作者快照。"""
    return build_author_snapshot(user)


def _resolve_post_object_id(value) -> Optional[ObjectId]:
    """将各种帖子引用值转换为ObjectId。"""
    candidate = value
    if isinstance(candidate, BBSPost):
        candidate = getattr(candidate, 'id', None)
    elif hasattr(candidate, 'id') and not isinstance(candidate, ObjectId):
        candidate = getattr(candidate, 'id', None)

    if isinstance(candidate, ObjectId):
        return candidate

    if candidate is None:
        return None

    try:
        return ObjectId(str(candidate))
    except (TypeError, bson_errors.InvalidId):
        logger.warning('无法解析帖子ID为ObjectId：%s', candidate)
        return None


def _format_decimal(value: Optional[Decimal]) -> str:
    """统一格式化金额。"""
    if value is None:
        return '0.00'
    return f"{value:.2f}"


def build_battle_record_content(record: BattleRecord) -> Tuple[str, str]:  # pylint: disable=too-many-locals
    """根据开播记录创建帖子标题和正文。"""
    pilot_name = getattr(record.pilot, 'nickname', None) or getattr(record.pilot, 'real_name', '') or '未知主播'
    start_display = format_local_datetime(record.start_time, '%Y-%m-%d %H:%M')
    end_display = format_local_datetime(record.end_time, '%H:%M')
    work_mode = getattr(record.work_mode, 'name', 'UNKNOWN')
    location = record.battle_location if work_mode != 'ONLINE' else '线上'
    if not location:
        location = '未指定地点'
    revenue_display = _format_decimal(record.revenue_amount)
    base_salary_display = _format_decimal(record.base_salary)
    notes = record.notes or '无'

    title = f"[开播记录] {pilot_name} {start_display}"
    lines = [
        f"【开播记录】{pilot_name} 于 {start_display} - {end_display} 在 {location} 完成开播。",
        f"流水：¥{revenue_display}，底薪：¥{base_salary_display}。",
        f"备注：{notes}",
    ]
    if record.related_announcement:
        announcement = record.related_announcement
        announcement_time = format_local_datetime(announcement.start_time, '%Y-%m-%d %H:%M')
        coord_parts = [announcement.x_coord, announcement.y_coord, announcement.z_coord]
        location_display = '-'.join([part for part in coord_parts if part]) or '未指定地点'
        lines.append(f"关联通告：{announcement_time} @ {location_display}")

    content = '\n'.join(lines)
    return title, content


def _get_system_user() -> Optional[User]:
    """获取系统账号，找不到时返回None。"""
    try:
        return User.objects.get(username='system')  # type: ignore[attr-defined]
    except Exception:  # pylint: disable=broad-except
        return None


def create_post_for_battle_record(record: BattleRecord) -> Optional[BBSPost]:
    """在满足条件时自动为开播记录生成主贴。"""
    status_value = record.current_status.value if record.current_status else 'unknown'
    revenue_value = str(record.revenue_amount or Decimal('0'))
    notes_length = len(record.notes or '')
    base_name = record.x_coord or ''
    logger.debug(
        '自动建贴前记录状态：record=%s status=%s revenue=%s notes_len=%d base=%s announcement=%s',
        record.id,
        status_value,
        revenue_value,
        notes_length,
        base_name,
        getattr(getattr(record, 'related_announcement', None), 'id', None),
    )
    if record.current_status != BattleRecordStatus.ENDED:
        logger.debug('开播记录状态未结束，跳过自动建贴：%s', record.id)
        return None
    if record.revenue_amount is None or record.revenue_amount == Decimal('0'):
        logger.debug('开播记录流水为0，跳过自动建贴：%s', record.id)
        return None
    if not record.notes:
        logger.debug('开播记录备注为空，跳过自动建贴：%s', record.id)
        return None
    base_name = record.x_coord or ''
    if not base_name:
        logger.debug('开播记录无基地信息，跳过自动建贴：%s', record.id)
        return None

    existing = BBSPost.objects(related_battle_record=record).first()  # type: ignore[attr-defined]
    if existing:
        logger.info('开播记录已存在关联帖子，跳过：record=%s post=%s', record.id, existing.id)
        return existing

    board = ensure_board_for_base(base_name)
    pilot_owner = getattr(record.pilot, 'owner', None) if record.pilot else None
    author = pilot_owner or _get_system_user() or record.registered_by
    display_name = '系统自动投稿' if author and author.username == 'system' else None
    snapshot = build_author_snapshot(author, display_name=display_name)
    title, content = build_battle_record_content(record)

    post = BBSPost(
        board=board,
        title=title,
        content=content,
        author=author,
        author_snapshot=snapshot,
        status=BBSPostStatus.PUBLISHED,
        related_battle_record=record,
        last_active_at=get_current_utc_time(),
    )
    post.save()
    logger.info('自动创建开播记录帖子：record=%s post=%s board=%s', record.id, post.id, board.code)

    if record.pilot:
        ref = BBSPostPilotRef(post=post, pilot=record.pilot, relevance=PilotRelevance.AUTO)
        ref.save()
        logger.debug('自动关联帖子与主播：post=%s pilot=%s', post.id, record.pilot.id)
    notify_direct_operator_auto_post(record, post)
    return post


def get_last_reply_info(post: BBSPost) -> Tuple[Optional[BBSReply], Optional[Dict[str, object]]]:
    """获取最新回复及其作者快照。"""
    latest = BBSReply.objects(post=post).order_by('-created_at').first()  # type: ignore[attr-defined]
    if not latest:
        return None, None
    return latest, latest.author_snapshot or {}


def fetch_post_reply_summary(posts: Iterable[BBSPost], include_hidden: bool = False, _current_user: Optional[User] = None) -> Dict[str, Dict[str, object]]:
    """批量获取帖子回复计数与最新回复信息。"""
    post_ids = [post.id for post in posts]
    if not post_ids:
        return {}

    query = BBSReply.objects(post__in=post_ids)  # type: ignore[attr-defined]
    if not include_hidden:
        query = query.filter(status=BBSReplyStatus.PUBLISHED)
    replies = list(query.order_by('created_at'))

    summary: Dict[str, Dict[str, object]] = {}
    for reply in replies:
        pid = str(reply.post.id)
        info = summary.setdefault(pid, {'count': 0, 'latest': None})
        if not include_hidden and reply.status == BBSReplyStatus.HIDDEN:
            continue
        info['count'] += 1
        info['latest'] = reply

    for post in posts:
        pid = str(post.id)
        info = summary.get(pid)
        if not info:
            continue
        latest = info.get('latest')
        if isinstance(latest, BBSReply):
            info['latest_author'] = latest.author_snapshot
            info['latest_time'] = latest.created_at
    return summary


def fetch_recent_posts_for_pilot(pilot: Pilot, accessible_post_ids: Optional[Iterable[str]] = None, limit: int = 3) -> List[BBSPost]:
    """获取与主播相关的最近更新帖子。"""
    raw_refs = BBSPostPilotRef.objects(pilot=pilot).no_dereference().distinct('post')  # type: ignore[attr-defined]
    if not raw_refs:
        return []

    object_ids: set[ObjectId] = set()
    for ref in raw_refs:
        resolved = _resolve_post_object_id(ref)
        if resolved:
            object_ids.add(resolved)

    if accessible_post_ids is not None:
        allowed: set[ObjectId] = set()
        for pid in accessible_post_ids:
            resolved = _resolve_post_object_id(pid)
            if resolved:
                allowed.add(resolved)
        object_ids = object_ids.intersection(allowed)

    if not object_ids:
        return []

    posts = BBSPost.objects(id__in=list(object_ids)).order_by('-last_active_at').limit(limit)  # type: ignore[attr-defined]
    return list(posts)


def user_can_view_post(user: Optional[User], post: BBSPost) -> bool:
    """判断用户是否可见帖子。"""
    if not post:
        return False
    if post.status == BBSPostStatus.PUBLISHED:
        return True
    if user is None:
        return False
    if str(post.author.id) == str(user.id):
        return True
    role_names = {role.name for role in getattr(user, 'roles', [])}
    return 'gicho' in role_names


def filter_posts_for_user(queryset, user: Optional[User]):
    """按用户权限过滤帖子查询集。"""
    if user is None:
        return queryset.filter(status=BBSPostStatus.PUBLISHED)
    role_names = {role.name for role in getattr(user, 'roles', [])}
    if 'gicho' in role_names:
        return queryset
    return queryset.filter(Q(status=BBSPostStatus.PUBLISHED) | Q(author=user))


def filter_replies_for_user(queryset, user: Optional[User]):
    """按用户权限过滤回复查询集。"""
    if user is None:
        return queryset.filter(status=BBSReplyStatus.PUBLISHED)
    role_names = {role.name for role in getattr(user, 'roles', [])}
    if 'gicho' in role_names:
        return queryset
    return queryset.filter(Q(status=BBSReplyStatus.PUBLISHED) | Q(author=user))
