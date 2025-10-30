from __future__ import annotations

# pylint: disable=no-member,too-many-return-statements,too-many-branches,too-many-locals

from typing import Dict, Iterable, List, Optional, Set

from flask import Blueprint, jsonify, request
from mongoengine import DoesNotExist, ValidationError
from mongoengine.queryset.visitor import Q

from bson import ObjectId

from models.bbs import (BBSBoard, BBSPost, BBSPostStatus, BBSReply, BBSReplyStatus, BBSPostPilotRef)
from models.battle_record import BattleRecord
from models.pilot import Pilot
from utils.bbs_serializers import (create_error_response, create_success_response, serialize_board_list, serialize_post_detail, serialize_post_summary)
from utils.bbs_service import (build_author_snapshot, ensure_base_boards_from_battle_areas, ensure_manual_pilot_refs, fetch_recent_posts_for_pilot,
                               filter_posts_for_user, filter_replies_for_user, get_last_reply_info, logger, user_can_view_post)
from utils.bbs_notifications import notify_parent_reply_author, notify_post_author_new_reply
from utils.csrf_helper import CSRFError, validate_csrf_header
from utils.jwt_roles import get_jwt_user, jwt_roles_accepted, jwt_roles_required

bbs_api_bp = Blueprint('bbs_api', __name__, url_prefix='/api/bbs')


def _get_current_user():
    user = get_jwt_user()
    if not user:
        raise CSRFError('UNAUTHORIZED', '用户未登录')
    return user


def _is_admin(user) -> bool:
    role_names = {role.name for role in getattr(user, 'roles', [])}
    return 'gicho' in role_names


def _to_user_id(value) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, ObjectId):
        return str(value)
    if hasattr(value, 'id'):
        return str(value.id)
    if hasattr(value, 'pk'):
        return str(value.pk)
    return str(value)


def _get_current_user_id(user) -> Optional[str]:
    return _to_user_id(user)


def _add_pending_reviewers(post: BBSPost, reviewer_ids: Iterable[str]) -> None:
    pending = set(post.pending_reviewers or [])
    added = False
    for reviewer_id in reviewer_ids:
        if not reviewer_id:
            continue
        if reviewer_id in pending:
            continue
        pending.add(reviewer_id)
        added = True
    if added:
        post.pending_reviewers = list(pending)


def _collect_unread_targets(post: BBSPost, reply_author_id: str) -> Set[str]:
    targets: Set[str] = set()
    post_author_id = _to_user_id(getattr(post, 'author', None))
    if post_author_id and post_author_id != reply_author_id:
        targets.add(post_author_id)

    author_ids = BBSReply.objects(post=post, status=BBSReplyStatus.PUBLISHED).distinct('author')  # type: ignore[attr-defined]
    for author in author_ids:
        candidate = _to_user_id(author)
        if candidate and candidate != reply_author_id:
            targets.add(candidate)
    return targets


def _apply_unread_targets(post: BBSPost, reply: BBSReply) -> None:
    reply_author_id = _to_user_id(getattr(reply, 'author', None))
    if not reply_author_id:
        return
    targets = _collect_unread_targets(post, reply_author_id)
    _add_pending_reviewers(post, targets)


def _mark_post_as_read(post: BBSPost, user) -> None:
    user_id = _get_current_user_id(user)
    if not user_id:
        return
    pending = post.pending_reviewers or []
    if user_id not in pending:
        return
    try:
        pending.remove(user_id)
    except ValueError:
        pass
    BBSPost.objects(id=post.id).update(pull__pending_reviewers=user_id)  # type: ignore[attr-defined]


@bbs_api_bp.route('/boards', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def list_boards():
    """获取板块列表。"""
    ensure_base_boards_from_battle_areas()
    is_active = request.args.get('is_active')
    query = BBSBoard.objects  # type: ignore[attr-defined]
    if is_active is not None:
        if is_active.lower() in {'1', 'true', 'yes'}:
            query = query.filter(is_active=True)
        elif is_active.lower() in {'0', 'false', 'no'}:
            query = query.filter(is_active=False)
    boards = query.order_by('order', 'name')
    return jsonify(create_success_response({'items': serialize_board_list(boards)}))


@bbs_api_bp.route('/posts', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def list_posts():
    """帖子列表。"""
    current_user = get_jwt_user()
    current_user_id = _get_current_user_id(current_user)
    page = max(int(request.args.get('page', 1) or 1), 1)
    per_page = max(min(int(request.args.get('per_page', 20) or 20), 100), 1)
    skip = (page - 1) * per_page

    query = filter_posts_for_user(BBSPost.objects.order_by('-is_pinned', '-last_active_at'), current_user)  # type: ignore[attr-defined]

    board_id = request.args.get('board_id')
    if board_id:
        try:
            board = BBSBoard.objects.get(id=board_id)  # type: ignore[attr-defined]
        except DoesNotExist:
            return jsonify(create_error_response('BOARD_NOT_FOUND', '板块不存在')), 404
        query = query.filter(board=board)

    keyword = (request.args.get('keyword') or '').strip()
    if keyword:
        query = query.filter(Q(title__icontains=keyword) | Q(content__icontains=keyword))

    status_filter = (request.args.get('status') or '').strip()
    if status_filter in {status.value for status in BBSPostStatus}:
        query = query.filter(status=status_filter)

    mine_flag = request.args.get('mine')
    if mine_flag in {'1', 'true'} and current_user:
        query = query.filter(author=current_user)

    unread_flag = request.args.get('unread')
    if unread_flag in {'1', 'true'} and current_user_id:
        query = query.filter(pending_reviewers=current_user_id)

    pilot_id = (request.args.get('pilot_id') or '').strip()
    if pilot_id:
        post_ids = BBSPostPilotRef.objects(pilot=pilot_id).distinct('post')  # type: ignore[attr-defined]
        query = query.filter(id__in=post_ids)

    total = query.count()
    posts = list(query.skip(skip).limit(per_page))

    items: List[Dict[str, object]] = []
    for post in posts:
        include_hidden = current_user and (_is_admin(current_user) or str(post.author.id) == str(current_user.id))
        replies_query = BBSReply.objects(post=post).order_by('created_at')  # type: ignore[attr-defined]
        replies_query = filter_replies_for_user(replies_query, current_user if include_hidden else None)
        replies = list(replies_query)
        reply_count = len(replies)
        last_reply_time = replies[-1].created_at if replies else None
        last_reply_author = replies[-1].author_snapshot if replies else None
        items.append(serialize_post_summary(post, reply_count, last_reply_author, last_reply_time, current_user_id))

    meta = {
        'page': page,
        'per_page': per_page,
        'total': total,
        'has_more': page * per_page < total,
    }
    return jsonify(create_success_response({'items': items}, meta))


def _load_post(post_id: str) -> BBSPost:
    try:
        return BBSPost.objects.get(id=post_id)  # type: ignore[attr-defined]
    except DoesNotExist as exc:
        raise ValueError('帖子不存在') from exc


@bbs_api_bp.route('/posts', methods=['POST'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def create_post():
    """创建帖子。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    payload = request.get_json(silent=True) or {}
    board_id = (payload.get('board_id') or '').strip()
    title = (payload.get('title') or '').strip()
    content = (payload.get('content') or '').strip()
    related_record_id = (payload.get('related_battle_record_id') or '').strip()
    pilot_ids = payload.get('pilot_ids') or []

    if not board_id:
        return jsonify(create_error_response('BOARD_REQUIRED', '请选择板块')), 400
    if not title:
        return jsonify(create_error_response('TITLE_REQUIRED', '请输入标题')), 400
    if not content:
        return jsonify(create_error_response('CONTENT_REQUIRED', '请输入内容')), 400

    try:
        board = BBSBoard.objects.get(id=board_id)  # type: ignore[attr-defined]
    except DoesNotExist:
        return jsonify(create_error_response('BOARD_NOT_FOUND', '板块不存在')), 404

    current_user = get_jwt_user()
    if not current_user:
        return jsonify(create_error_response('UNAUTHORIZED', '未认证')), 401
    current_user_id = _get_current_user_id(current_user)
    current_user_id = _get_current_user_id(current_user)
    current_user_id = _get_current_user_id(current_user)

    related_record = None
    if related_record_id:
        try:
            related_record = BattleRecord.objects.get(id=related_record_id)  # type: ignore[attr-defined]
        except DoesNotExist:
            return jsonify(create_error_response('BATTLE_RECORD_NOT_FOUND', '关联的开播记录不存在')), 404

    post = BBSPost(
        board=board,
        title=title,
        content=content,
        author=current_user,
        author_snapshot=build_author_snapshot(current_user),
        status=BBSPostStatus.PUBLISHED,
        related_battle_record=related_record,
    )

    try:
        post.save()
    except ValidationError as exc:
        return jsonify(create_error_response('VALIDATION_FAILED', str(exc))), 400

    ensure_manual_pilot_refs(post, pilot_ids)

    replies = []
    post_detail = serialize_post_detail(post, replies, [], current_user_id=current_user_id)
    return jsonify(create_success_response(post_detail)), 201


@bbs_api_bp.route('/posts/<post_id>', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def get_post_detail(post_id: str):
    """帖子详情。"""
    try:
        post = _load_post(post_id)
    except ValueError:
        return jsonify(create_error_response('POST_NOT_FOUND', '帖子不存在')), 404

    current_user = get_jwt_user()
    current_user_id = _get_current_user_id(current_user)
    if not user_can_view_post(current_user, post):
        return jsonify(create_error_response('FORBIDDEN', '没有权限查看该帖子')), 403

    _mark_post_as_read(post, current_user)

    replies_query = BBSReply.objects(post=post).order_by('created_at')  # type: ignore[attr-defined]
    replies_query = filter_replies_for_user(replies_query, current_user)
    replies = list(replies_query)

    pilot_refs = list(BBSPostPilotRef.objects(post=post))  # type: ignore[attr-defined]
    latest_reply, latest_author = get_last_reply_info(post)
    detail = serialize_post_detail(post, replies, pilot_refs, latest_reply.created_at if latest_reply else None, latest_author, current_user_id=current_user_id)
    return jsonify(create_success_response(detail))


@bbs_api_bp.route('/posts/<post_id>', methods=['PATCH'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def update_post(post_id: str):
    """编辑帖子。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    try:
        post = _load_post(post_id)
    except ValueError:
        return jsonify(create_error_response('POST_NOT_FOUND', '帖子不存在')), 404

    current_user = get_jwt_user()
    if not current_user:
        return jsonify(create_error_response('UNAUTHORIZED', '未认证')), 401
    current_user_id = _get_current_user_id(current_user)

    is_admin = _is_admin(current_user)
    is_author = str(post.author.id) == str(current_user.id)
    if not (is_admin or is_author):
        return jsonify(create_error_response('FORBIDDEN', '没有权限编辑该帖子')), 403

    payload = request.get_json(silent=True) or {}
    title = payload.get('title')
    content = payload.get('content')
    is_pinned = payload.get('is_pinned')

    if title is not None:
        title = title.strip()
        if not title:
            return jsonify(create_error_response('TITLE_REQUIRED', '标题不能为空')), 400
        post.title = title
    if content is not None:
        content = content.strip()
        if not content:
            return jsonify(create_error_response('CONTENT_REQUIRED', '内容不能为空')), 400
        post.content = content
    if is_admin and is_pinned is not None:
        post.is_pinned = bool(is_pinned)

    try:
        post.save()
        post.touch()
    except ValidationError as exc:
        return jsonify(create_error_response('VALIDATION_FAILED', str(exc))), 400

    replies = list(filter_replies_for_user(BBSReply.objects(post=post).order_by('created_at'), current_user))  # type: ignore[attr-defined]
    pilot_refs = list(BBSPostPilotRef.objects(post=post))  # type: ignore[attr-defined]
    latest_reply, latest_author = get_last_reply_info(post)
    detail = serialize_post_detail(post, replies, pilot_refs, latest_reply.created_at if latest_reply else None, latest_author, current_user_id=current_user_id)
    return jsonify(create_success_response(detail))


@bbs_api_bp.route('/posts/<post_id>/hide', methods=['POST'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def hide_post(post_id: str):
    """隐藏帖子。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    try:
        post = _load_post(post_id)
    except ValueError:
        return jsonify(create_error_response('POST_NOT_FOUND', '帖子不存在')), 404

    current_user = get_jwt_user()
    if not current_user:
        return jsonify(create_error_response('UNAUTHORIZED', '未认证')), 401

    is_admin = _is_admin(current_user)
    is_author = str(post.author.id) == str(current_user.id)
    if not (is_admin or is_author):
        return jsonify(create_error_response('FORBIDDEN', '没有权限隐藏该帖子')), 403

    post.status = BBSPostStatus.HIDDEN
    post.save()
    BBSReply.objects(post=post).update(status=BBSReplyStatus.HIDDEN)  # type: ignore[attr-defined]
    logger.info('帖子隐藏：post=%s operator=%s', post.id, current_user.username)
    return jsonify(create_success_response({'post_id': post_id, 'status': post.status.value}))


@bbs_api_bp.route('/posts/<post_id>/unhide', methods=['POST'])
@jwt_roles_required('gicho')
def unhide_post(post_id: str):
    """取消隐藏帖子，仅管理员。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    try:
        post = _load_post(post_id)
    except ValueError:
        return jsonify(create_error_response('POST_NOT_FOUND', '帖子不存在')), 404

    post.status = BBSPostStatus.PUBLISHED
    post.save()
    logger.info('帖子取消隐藏：post=%s', post.id)
    return jsonify(create_success_response({'post_id': post_id, 'status': post.status.value}))


@bbs_api_bp.route('/posts/<post_id>/pin', methods=['POST'])
@jwt_roles_required('gicho')
def pin_post(post_id: str):
    """置顶帖子，仅管理员。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    payload = request.get_json(silent=True) or {}
    is_pinned = bool(payload.get('is_pinned', True))

    try:
        post = _load_post(post_id)
    except ValueError:
        return jsonify(create_error_response('POST_NOT_FOUND', '帖子不存在')), 404

    post.is_pinned = is_pinned
    post.touch()
    logger.info('帖子置顶状态修改：post=%s pinned=%s', post.id, is_pinned)
    return jsonify(create_success_response({'post_id': post_id, 'is_pinned': post.is_pinned}))


@bbs_api_bp.route('/posts/<post_id>/replies', methods=['POST'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def add_reply(post_id: str):
    """新增回复。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    try:
        post = _load_post(post_id)
    except ValueError:
        return jsonify(create_error_response('POST_NOT_FOUND', '帖子不存在')), 404

    current_user = get_jwt_user()
    current_user_id = _get_current_user_id(current_user)
    if not current_user or not user_can_view_post(current_user, post):
        return jsonify(create_error_response('FORBIDDEN', '没有权限回复该帖子')), 403

    payload = request.get_json(silent=True) or {}
    content = (payload.get('content') or '').strip()
    parent_reply_id = (payload.get('parent_reply_id') or '').strip()

    if not content:
        return jsonify(create_error_response('CONTENT_REQUIRED', '回复内容不能为空')), 400

    parent_reply = None
    if parent_reply_id:
        try:
            parent_reply = BBSReply.objects.get(id=parent_reply_id, post=post)  # type: ignore[attr-defined]
        except DoesNotExist:
            return jsonify(create_error_response('REPLY_NOT_FOUND', '父回复不存在')), 404
        if parent_reply.parent_reply:
            return jsonify(create_error_response('REPLY_INVALID_PARENT', '不支持多层嵌套回复')), 400

    reply = BBSReply(
        post=post,
        parent_reply=parent_reply,
        content=content,
        author=current_user,
        author_snapshot=build_author_snapshot(current_user),
        status=BBSReplyStatus.PUBLISHED,
    )
    try:
        reply.save()
    except ValidationError as exc:
        return jsonify(create_error_response('VALIDATION_FAILED', str(exc))), 400

    _apply_unread_targets(post, reply)
    post.touch()
    notify_post_author_new_reply(post, reply)
    if parent_reply:
        notify_parent_reply_author(post, parent_reply, reply)

    replies_query = filter_replies_for_user(BBSReply.objects(post=post).order_by('created_at'), current_user)  # type: ignore[attr-defined]
    pilot_refs = list(BBSPostPilotRef.objects(post=post))  # type: ignore[attr-defined]
    latest_reply, latest_author = get_last_reply_info(post)
    detail = serialize_post_detail(post,
                                   list(replies_query),
                                   pilot_refs,
                                   latest_reply.created_at if latest_reply else None,
                                   latest_author,
                                   current_user_id=current_user_id)
    return jsonify(create_success_response(detail))


@bbs_api_bp.route('/replies/<reply_id>', methods=['PATCH'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def update_reply(reply_id: str):
    """编辑回复。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    try:
        reply = BBSReply.objects.get(id=reply_id)  # type: ignore[attr-defined]
    except DoesNotExist:
        return jsonify(create_error_response('REPLY_NOT_FOUND', '回复不存在')), 404

    current_user = get_jwt_user()
    current_user_id = _get_current_user_id(current_user)
    if not current_user:
        return jsonify(create_error_response('UNAUTHORIZED', '未认证')), 401

    is_admin = _is_admin(current_user)
    is_author = str(reply.author.id) == str(current_user.id)
    if not (is_admin or is_author):
        return jsonify(create_error_response('FORBIDDEN', '没有权限编辑该回复')), 403

    payload = request.get_json(silent=True) or {}
    content = (payload.get('content') or '').strip()
    if not content:
        return jsonify(create_error_response('CONTENT_REQUIRED', '回复内容不能为空')), 400

    reply.content = content
    try:
        reply.save()
    except ValidationError as exc:
        return jsonify(create_error_response('VALIDATION_FAILED', str(exc))), 400

    post = reply.post
    post.touch()
    replies_query = filter_replies_for_user(BBSReply.objects(post=post).order_by('created_at'), current_user)  # type: ignore[attr-defined]
    pilot_refs = list(BBSPostPilotRef.objects(post=post))  # type: ignore[attr-defined]
    latest_reply, latest_author = get_last_reply_info(post)
    detail = serialize_post_detail(post,
                                   list(replies_query),
                                   pilot_refs,
                                   latest_reply.created_at if latest_reply else None,
                                   latest_author,
                                   current_user_id=current_user_id)
    return jsonify(create_success_response(detail))


@bbs_api_bp.route('/replies/<reply_id>/hide', methods=['POST'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def hide_reply(reply_id: str):
    """隐藏回复。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    try:
        reply = BBSReply.objects.get(id=reply_id)  # type: ignore[attr-defined]
    except DoesNotExist:
        return jsonify(create_error_response('REPLY_NOT_FOUND', '回复不存在')), 404

    current_user = get_jwt_user()
    if not current_user:
        return jsonify(create_error_response('UNAUTHORIZED', '未认证')), 401

    is_admin = _is_admin(current_user)
    is_author = str(reply.author.id) == str(current_user.id)
    if not (is_admin or is_author):
        return jsonify(create_error_response('FORBIDDEN', '没有权限隐藏该回复')), 403

    reply.status = BBSReplyStatus.HIDDEN
    reply.save()

    if not reply.parent_reply:
        BBSReply.objects(parent_reply=reply).update(status=BBSReplyStatus.HIDDEN)  # type: ignore[attr-defined]

    logger.info('回复隐藏：reply=%s operator=%s', reply.id, current_user.username)
    return jsonify(create_success_response({'reply_id': reply_id, 'status': reply.status.value}))


@bbs_api_bp.route('/posts/<post_id>/pilots', methods=['PUT'])
@jwt_roles_required('gicho')
def update_post_pilots(post_id: str):
    """更新帖子关联主播（仅管理员）。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    try:
        post = _load_post(post_id)
    except ValueError:
        return jsonify(create_error_response('POST_NOT_FOUND', '帖子不存在')), 404

    payload = request.get_json(silent=True) or {}
    pilot_ids = payload.get('pilot_ids') or []
    refs, missing = ensure_manual_pilot_refs(post, pilot_ids)
    logger.info('更新帖子关联主播：post=%s pilots=%s missing=%s', post.id, pilot_ids, missing)

    replies = list(BBSReply.objects(post=post).order_by('created_at'))  # type: ignore[attr-defined]
    detail = serialize_post_detail(post, replies, refs)
    meta = {'missing_pilots': missing}
    return jsonify(create_success_response(detail, meta))


@bbs_api_bp.route('/pilots/<pilot_id>/recent', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def recent_posts_for_pilot(pilot_id: str):
    """获取主播最近活跃的帖子。"""
    current_user = get_jwt_user()
    current_user_id = _get_current_user_id(current_user)
    try:
        pilot = Pilot.objects.get(id=pilot_id)  # type: ignore[attr-defined]
    except DoesNotExist:
        return jsonify(create_error_response('PILOT_NOT_FOUND', '主播不存在')), 404

    recent_candidates = fetch_recent_posts_for_pilot(pilot, limit=10)
    posts: List[BBSPost] = []
    for post in recent_candidates:
        if user_can_view_post(current_user, post):
            posts.append(post)
        if len(posts) >= 3:
            break

    items: List[Dict[str, object]] = []
    for post in posts:
        include_hidden = current_user and (_is_admin(current_user) or str(post.author.id) == str(current_user.id))
        replies_query = BBSReply.objects(post=post).order_by('created_at')  # type: ignore[attr-defined]
        replies_query = filter_replies_for_user(replies_query, current_user if include_hidden else None)
        replies = list(replies_query)
        reply_count = len(replies)
        last_reply_time = replies[-1].created_at if replies else None
        last_reply_author = replies[-1].author_snapshot if replies else None
        items.append(serialize_post_summary(post, reply_count, last_reply_author, last_reply_time, current_user_id))

    return jsonify(create_success_response({'items': items}))
