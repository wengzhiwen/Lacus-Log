# -*- coding: utf-8 -*-
"""开播记录 REST API 路由集合。"""

# pylint: disable=no-member,too-many-return-statements,too-many-branches,too-many-locals,too-many-statements,duplicate-code

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from flask import Blueprint, jsonify, request, url_for
from flask_security import current_user
from mongoengine import DoesNotExist, Q

from models.announcement import Announcement
from models.battle_area import Availability, BattleArea
from models.battle_record import (BaseSalaryApplication, BattleRecord, BattleRecordChangeLog, BattleRecordStatus)
from models.pilot import Pilot, Rank, WorkMode
from models.user import Role, User
from routes.battle_record import (log_battle_record_change, validate_notes_required)
from utils.bbs_service import add_rant_reply, create_post_for_battle_record, ensure_battle_record_post_for_rant
from utils.announcement_serializers import (create_error_response, create_success_response)
from utils.csrf_helper import CSRFError, validate_csrf_header
from utils.filter_state import persist_and_restore_filters
from utils.jwt_roles import jwt_roles_accepted
from utils.logging_setup import get_logger
from utils.pilot_activity import sort_pilots_with_active_priority
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)

logger = get_logger('battle_records_api')

battle_records_api_bp = Blueprint('battle_records_api', __name__)


def _persist_filters_from_request() -> Dict[str, str]:
    filters = persist_and_restore_filters(
        'battle_records_list',
        allowed_keys=['owner', 'x', 'status', 'date'],
        default_filters={
            'owner': 'all',
            'x': '',
            'status': 'all',
            'date': _get_today_date_string()
        },
    )

    # 如果没有传递日期参数，确保使用今天的日期作为默认值
    if not filters.get('date'):
        filters['date'] = _get_today_date_string()

    return filters


def _get_today_date_string() -> str:
    """获取GMT+8时区的今天日期字符串 YYYY-MM-DD"""
    now_utc = get_current_utc_time()
    now_local = utc_to_local(now_utc)
    return now_local.strftime('%Y-%m-%d')


def _apply_owner_filter(queryset, owner_filter: str):
    if owner_filter == 'self':
        return queryset.filter(owner_snapshot=current_user.id)
    if owner_filter and owner_filter not in ('', 'all'):
        try:
            owner_user = User.objects.get(id=owner_filter)
            return queryset.filter(owner_snapshot=owner_user.id)
        except DoesNotExist:
            return queryset.none()
    return queryset


def _apply_x_filter(queryset, x_filter: str):
    if x_filter:
        return queryset.filter(x_coord=x_filter)
    return queryset


def _apply_date_filter(queryset, date_filter: str):
    """根据指定的日期筛选开播记录（GMT+8时区）"""
    if not date_filter:
        # 如果没有指定日期，使用今天的日期
        date_filter = _get_today_date_string()

    try:
        # 解析日期字符串 YYYY-MM-DD
        date_obj = datetime.strptime(date_filter, '%Y-%m-%d')
        # 设置为GMT+8时区的当天开始时间
        date_local = date_obj.replace(hour=0, minute=0, second=0, microsecond=0)

        # 转换为UTC时间进行数据库查询
        start_utc = local_to_utc(date_local)
        # 查询这一天的记录（从当天00:00到第二天00:00）
        end_utc = local_to_utc(date_local + timedelta(days=1))

        return queryset.filter(start_time__gte=start_utc, start_time__lt=end_utc)
    except ValueError:
        # 如果日期格式无效，返回空查询集
        logger.warning('无效的日期格式：%s', date_filter)
        return queryset.none()


def _apply_status_filter(queryset, status_filter: str):
    if status_filter and status_filter not in ('', 'all'):
        try:
            status_enum = BattleRecordStatus(status_filter)
            if status_enum == BattleRecordStatus.ENDED:
                # 已下播包括：状态为已下播的记录 + 状态为空的老数据
                return queryset.filter(Q(status=status_enum) | Q(status__exists=False) | Q(status=None))
            # 开播中：只查找状态明确为开播中的记录
            return queryset.filter(status=status_enum)
        except ValueError:
            return queryset.none()
    return queryset


def _build_filter_options() -> Dict[str, List[Dict[str, str]]]:
    gicho = Role.objects(name='gicho').first()
    kancho = Role.objects(name='kancho').first()
    role_list = [role for role in (gicho, kancho) if role]
    owners = User.objects(roles__in=role_list).order_by('username') if role_list else []

    owner_options = [{'value': 'all', 'label': '全部'}, {'value': 'self', 'label': '自己'}]
    owner_options.extend([{'value': str(owner.id), 'label': owner.nickname or owner.username} for owner in owners])

    x_coords = BattleRecord.objects.filter(x_coord__ne='').distinct(field='x_coord')
    x_options = [{'value': '', 'label': '全部基地'}]
    x_options.extend([{'value': coord, 'label': coord} for coord in sorted(x_coords or [])])

    status_options = [{'value': 'all', 'label': '全部状态'}, {'value': 'live', 'label': '开播中'}, {'value': 'ended', 'label': '已下播'}]

    return {'owners': owner_options, 'x_coords': x_options, 'statuses': status_options}


def _serialize_pilot_basic(pilot: Optional[Pilot]) -> Dict[str, Optional[str]]:
    if not pilot:
        return {'id': None, 'nickname': '', 'real_name': '', 'status': '', 'rank': '', 'gender': None, 'age': None, 'owner_display': ''}

    owner_display = ''
    if pilot.owner:
        owner_display = pilot.owner.nickname or pilot.owner.username

    gender_value = None
    try:
        gender_value = pilot.gender.value if pilot.gender is not None else None
    except AttributeError:
        gender_value = None

    return {
        'id': str(pilot.id),
        'nickname': pilot.nickname or '',
        'real_name': pilot.real_name or '',
        'status': pilot.status.value if pilot.status else '',
        'rank': pilot.rank.value if pilot.rank else '',
        'gender': gender_value,
        'age': pilot.age,
        'owner_display': owner_display or '无'
    }


def _serialize_battle_record_summary(record: BattleRecord, base_salary_summary: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    pilot_info = _serialize_pilot_basic(record.pilot)
    start_local = utc_to_local(record.start_time) if record.start_time else None

    data = {
        'id': str(record.id),
        'pilot': pilot_info,
        'owner_display': pilot_info['owner_display'],
        'work_mode': record.work_mode.value if record.work_mode else '',
        'status': record.current_status.value,
        'status_display': str(record.get_status_display()) if record.get_status_display() else '',
        'revenue_amount': format(record.revenue_amount or Decimal('0'), 'f'),
        'base_salary': format(record.base_salary or Decimal('0'), 'f'),
        'duration_hours': record.duration_hours or 0,
        'duration_display': f"{record.duration_hours:.1f}小时" if record.duration_hours is not None else '0.0小时',
        'start_time': {
            'iso': start_local.isoformat() if start_local else None,
            'display': start_local.strftime('%m月%d日 %H:%M') if start_local else '',
        },
        'location': {
            'x': record.x_coord or '',
            'y': record.y_coord or '',
            'z': record.z_coord or '',
            'display': f"{record.x_coord}-{record.y_coord}-{record.z_coord}" if (record.x_coord or record.y_coord or record.z_coord) else '--'
        },
        'links': {
            'detail': url_for('battle_record.detail_battle_record', record_id=record.id)
        },
        'search': {
            'nickname': pilot_info['nickname'],
            'real_name': pilot_info['real_name']
        }
    }
    data['base_salary_summary'] = base_salary_summary
    return data


def _build_base_salary_summary(records: List[BattleRecord]) -> Dict[str, Dict[str, object]]:
    """批量构建开播记录对应的底薪申请摘要"""
    record_ids = [record.id for record in records if record.id]
    if not record_ids:
        return {}

    applications = BaseSalaryApplication.objects.filter(battle_record_id__in=record_ids).order_by('-updated_at')
    summary_map: Dict[str, Dict[str, object]] = {}

    for application in applications:
        battle_record = application.battle_record_id
        if not battle_record:
            continue

        record_key = str(battle_record.id)
        latest_entry = summary_map.get(record_key)
        latest_updated_at = latest_entry.get('_updated_at') if latest_entry else None
        application_updated_at = application.updated_at or application.created_at

        if latest_updated_at and application_updated_at and application_updated_at < latest_updated_at:
            continue

        summary_map[record_key] = {
            'amount': format(application.base_salary_amount or Decimal('0'), 'f'),
            'status': application.status.value if application.status else None,
            'status_display': application.status_display,
            'application_id': str(application.id),
            '_updated_at': application_updated_at,
        }

    for value in summary_map.values():
        value.pop('_updated_at', None)

    return summary_map


def _serialize_related_announcement(record: BattleRecord) -> Tuple[Optional[Dict[str, str]], bool]:
    try:
        announcement = record.related_announcement
        _ = announcement.id if announcement else None
    except Exception as err:  # pylint: disable=broad-except
        logger.warning('开播记录 %s 的关联通告不存在：%s', record.id, err, exc_info=True)
        return None, True

    if not announcement:
        return None, False

    local_start = utc_to_local(announcement.start_time) if announcement.start_time else None
    weekday_map = ['一', '二', '三', '四', '五', '六', '日']
    if local_start:
        date_str = local_start.strftime('%Y-%m-%d')
        weekday = weekday_map[local_start.weekday()]
        duration = f"{announcement.duration_hours}小时"
        label = f"{date_str} 星期{weekday} {duration} @{announcement.x_coord}-{announcement.y_coord}-{announcement.z_coord}"
    else:
        label = ''

    return {'id': str(announcement.id), 'label': label, 'detail_url': url_for('announcement.announcement_detail', announcement_id=announcement.id)}, False


def _serialize_battle_record_detail(record: BattleRecord) -> Dict[str, object]:
    pilot_info = _serialize_pilot_basic(record.pilot)
    start_local = utc_to_local(record.start_time) if record.start_time else None
    end_local = utc_to_local(record.end_time) if record.end_time else None
    related_payload, related_deleted = _serialize_related_announcement(record)

    return {
        'id': str(record.id),
        'pilot': pilot_info,
        'owner_display': pilot_info['owner_display'],
        'work_mode': record.work_mode.value if record.work_mode else '',
        'status': record.current_status.value,
        'status_display': str(record.get_status_display()) if record.get_status_display() else '',
        'location': {
            'x': record.x_coord or '',
            'y': record.y_coord or '',
            'z': record.z_coord or '',
            'display': f"{record.x_coord}-{record.y_coord}-{record.z_coord}"
        },
        'time': {
            'start': start_local.strftime('%Y年%m月%d日 %H:%M') if start_local else '',
            'end': end_local.strftime('%Y年%m月%d日 %H:%M') if end_local else '',
            'start_iso': start_local.isoformat() if start_local else None,
            'end_iso': end_local.isoformat() if end_local else None,
            'duration_hours': record.duration_hours or 0,
            'duration_display': f"{record.duration_hours:.1f}小时" if record.duration_hours is not None else '0.0小时'
        },
        'financial': {
            'revenue_amount': format(record.revenue_amount or Decimal('0'), 'f'),
            'base_salary': format(record.base_salary or Decimal('0'), 'f')
        },
        'notes': record.notes or '',
        'system': {
            'registered_by': (record.registered_by.nickname or record.registered_by.username) if record.registered_by else '未知',
            'created_at': utc_to_local(record.created_at).strftime('%Y年%m月%d日 %H:%M') if record.created_at else '',
            'updated_at': utc_to_local(record.updated_at).strftime('%Y年%m月%d日 %H:%M') if record.updated_at else ''
        },
        'related_announcement': related_payload,
        'related_announcement_deleted': related_deleted,
        'links': {
            'detail': url_for('battle_record.detail_battle_record', record_id=record.id)
        },
    }


def _serialize_change_logs(change_logs: Iterable[BattleRecordChangeLog]) -> List[Dict[str, str]]:
    items: List[Dict[str, str]] = []
    for change in change_logs:
        change_time_local = utc_to_local(change.change_time) if change.change_time else None
        items.append({
            'change_time': change_time_local.strftime('%Y-%m-%d %H:%M:%S') if change_time_local else '',
            'user_name': (change.user_id.nickname or change.user_id.username) if change.user_id else '未知用户',
            'field_name': change.field_display_name,
            'old_value': change.old_value or '',
            'new_value': change.new_value or '',
            'ip_address': change.ip_address or '未知'
        })
    return items


def _parse_decimal(value: Optional[object], field_name: str) -> Decimal:
    if value is None or value == '':
        return Decimal('0')
    try:
        return Decimal(str(value))
    except (ValueError, TypeError, ArithmeticError) as exc:
        raise ValueError(f'{field_name}格式错误') from exc


def _ensure_work_mode(value: str) -> WorkMode:
    try:
        return WorkMode(value)
    except Exception as exc:
        raise ValueError('开播方式不正确') from exc


def _load_pilot(pilot_id: str) -> Pilot:
    try:
        return Pilot.objects.get(id=pilot_id)
    except DoesNotExist as exc:
        raise ValueError('选择的主播不存在') from exc


def _load_announcement(announcement_id: str) -> Optional[Announcement]:
    if not announcement_id:
        return None
    try:
        return Announcement.objects.get(id=announcement_id)
    except DoesNotExist as exc:
        raise ValueError('关联通告不存在') from exc


def _collect_change_fields(record: BattleRecord) -> Dict[str, object]:
    try:
        related = record.related_announcement
        _ = related.id if related else None
    except Exception:  # pylint: disable=broad-except
        related = None

    return {
        'pilot': record.pilot,
        'related_announcement': related,
        'start_time': record.start_time,
        'end_time': record.end_time,
        'revenue_amount': record.revenue_amount,
        'base_salary': record.base_salary,
        'x_coord': record.x_coord,
        'y_coord': record.y_coord,
        'z_coord': record.z_coord,
        'work_mode': record.work_mode.value if record.work_mode else None,
        'status': record.status.value if record.status else None,
        'notes': record.notes,
    }


def _get_client_ip() -> str:
    return request.headers.get('X-Forwarded-For') or request.remote_addr or '未知'


@battle_records_api_bp.route('/battle-records', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def list_records():
    """获取开播记录列表。"""
    try:
        filters = _persist_filters_from_request()
        owner_filter = filters.get('owner', 'all')
        x_filter = filters.get('x', '')
        status_filter = filters.get('status', 'all')
        date_filter = filters.get('date', _get_today_date_string())

        page = max(int(request.args.get('page', 1) or 1), 1)
        per_page = 500
        skip = (page - 1) * per_page

        base_query = BattleRecord.objects.order_by('-start_time', '-revenue_amount')
        filtered_query = _apply_owner_filter(base_query, owner_filter)
        filtered_query = _apply_x_filter(filtered_query, x_filter)
        filtered_query = _apply_status_filter(filtered_query, status_filter)
        filtered_query = _apply_date_filter(filtered_query, date_filter)

        total_count = filtered_query.count()
        records = list(filtered_query.skip(skip).limit(per_page))

        base_salary_summaries = _build_base_salary_summary(records)
        items = [_serialize_battle_record_summary(record, base_salary_summaries.get(str(record.id))) for record in records]

        meta = {
            'filters': {
                'owner': owner_filter,
                'x': x_filter,
                'status': status_filter,
                'date': date_filter,
            },
            'options': _build_filter_options(),
            'total': total_count,
            'page': page,
            'per_page': per_page,
            'has_more': page * per_page < total_count,
        }

        return jsonify(create_success_response({'items': items}, meta))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取开播记录列表失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@battle_records_api_bp.route('/battle-records/<record_id>', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def get_record(record_id: str):
    """获取指定开播记录详情。"""
    try:
        record = BattleRecord.objects.get(id=record_id)
        data = _serialize_battle_record_detail(record)
        return jsonify(create_success_response(data))
    except DoesNotExist:
        return jsonify(create_error_response('BATTLE_RECORD_NOT_FOUND', '开播记录不存在')), 404
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取开播记录详情失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '服务器内部错误')), 500


@battle_records_api_bp.route('/battle-records', methods=['POST'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def create_record():
    """创建开播记录。"""
    # JWT认证的API不需要CSRF验证，因为JWT cookie已有CSRF保护

    payload = request.get_json(silent=True) or {}

    try:
        pilot_id = (payload.get('pilot') or '').strip()
        related_announcement_id = (payload.get('related_announcement') or '').strip()
        start_time_str = (payload.get('start_time') or '').strip()
        end_time_str = (payload.get('end_time') or '').strip()
        status_str = (payload.get('status') or '').strip()
        work_mode_str = (payload.get('work_mode') or '').strip()
        x_coord = (payload.get('x_coord') or '').strip()
        y_coord = (payload.get('y_coord') or '').strip()
        z_coord = (payload.get('z_coord') or '').strip()
        notes = (payload.get('notes') or '').strip()

        required_map = {
            'pilot': ('主播', pilot_id),
            'start_time': ('开始时间', start_time_str),
            'end_time': ('结束时间', end_time_str),
            'work_mode': ('开播方式', work_mode_str),
        }
        missing = [label for label, value in required_map.values() if not value]
        if missing:
            return jsonify(create_error_response('INVALID_PARAMS', f"请填写必填项：{'、'.join(missing)}")), 400

        pilot = _load_pilot(pilot_id)
        related_announcement = None
        if related_announcement_id:
            related_announcement = _load_announcement(related_announcement_id)

        try:
            start_time_local = datetime.fromisoformat(start_time_str)
            end_time_local = datetime.fromisoformat(end_time_str)
        except ValueError as exc:
            raise ValueError('时间格式错误') from exc

        work_mode = _ensure_work_mode(work_mode_str)

        # 验证和处理状态
        if not status_str:
            status_enum = BattleRecordStatus.LIVE  # 默认为开播中
        else:
            try:
                status_enum = BattleRecordStatus(status_str)
            except ValueError as exc:
                raise ValueError('状态值无效') from exc

        revenue_amount = _parse_decimal(payload.get('revenue_amount'), '流水金额')
        base_salary = _parse_decimal(payload.get('base_salary'), '底薪金额')

        if work_mode == WorkMode.OFFLINE:
            if not (x_coord and y_coord and z_coord):
                return jsonify(create_error_response('INVALID_PARAMS', '线下开播时必须选择X/Y/Z坐标')), 400
        else:
            x_coord = ''
            y_coord = ''
            z_coord = ''

        start_time_utc = local_to_utc(start_time_local)
        end_time_utc = local_to_utc(end_time_local)

        validation_error = validate_notes_required(start_time_utc, end_time_utc, revenue_amount, base_salary, related_announcement, notes)
        if validation_error:
            return jsonify(create_error_response('VALIDATION_FAILED', validation_error)), 400

        record = BattleRecord(
            pilot=pilot,
            related_announcement=related_announcement,
            start_time=start_time_utc,
            end_time=end_time_utc,
            status=status_enum,
            revenue_amount=revenue_amount,
            base_salary=base_salary,
            x_coord=x_coord,
            y_coord=y_coord,
            z_coord=z_coord,
            work_mode=work_mode,
            owner_snapshot=pilot.owner,
            registered_by=current_user,
            notes=notes,
        )
        record.save()

        logger.debug(
            '创建开播记录后准备自动BBS发帖：record=%s status=%s revenue=%s notes_len=%d base=%s announcement=%s work_mode=%s',
            record.id,
            record.current_status.value,
            str(record.revenue_amount or Decimal('0')),
            len(record.notes or ''),
            record.x_coord or '',
            getattr(getattr(record, 'related_announcement', None), 'id', None),
            record.work_mode.value if record.work_mode else None,
        )

        try:
            create_post_for_battle_record(record)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error('自动创建BBS帖子失败（创建）：record=%s error=%s', record.id, exc, exc_info=True)

        data = _serialize_battle_record_detail(record)
        meta = {'message': '开播记录创建成功'}
        return jsonify(create_success_response(data, meta)), 201
    except ValueError as exc:
        return jsonify(create_error_response('INVALID_PARAMS', str(exc))), 400
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('创建开播记录失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '创建开播记录失败')), 500


@battle_records_api_bp.route('/battle-records/<record_id>', methods=['PUT'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def update_record(record_id: str):
    """更新开播记录。"""
    # JWT认证的API不需要CSRF验证，因为JWT cookie已有CSRF保护

    payload = request.get_json(silent=True) or {}

    try:
        record = BattleRecord.objects.get(id=record_id)
    except DoesNotExist:
        return jsonify(create_error_response('BATTLE_RECORD_NOT_FOUND', '开播记录不存在')), 404

    try:
        old_values = _collect_change_fields(record)

        pilot_id = (payload.get('pilot') or '').strip()
        if pilot_id:
            pilot = _load_pilot(pilot_id)
            record.pilot = pilot
            record.owner_snapshot = pilot.owner

        related_field_provided = 'related_announcement' in payload
        if related_field_provided:
            related_id = (payload.get('related_announcement') or '').strip()
            record.related_announcement = _load_announcement(related_id) if related_id else None

        start_time_str = (payload.get('start_time') or '').strip()
        end_time_str = (payload.get('end_time') or '').strip()
        if start_time_str and end_time_str:
            try:
                record.start_time = local_to_utc(datetime.fromisoformat(start_time_str))
                record.end_time = local_to_utc(datetime.fromisoformat(end_time_str))
            except ValueError as exc:
                raise ValueError('时间格式错误') from exc

        if payload.get('revenue_amount') is not None:
            record.revenue_amount = _parse_decimal(payload.get('revenue_amount'), '流水金额')
        if payload.get('base_salary') is not None:
            record.base_salary = _parse_decimal(payload.get('base_salary'), '底薪金额')

        work_mode_val = payload.get('work_mode')
        if work_mode_val is not None:
            record.work_mode = _ensure_work_mode(str(work_mode_val))

        # 更新状态
        status_val = payload.get('status')
        if status_val is not None:
            try:
                record.status = BattleRecordStatus(str(status_val))
            except ValueError as exc:
                raise ValueError('状态值无效') from exc

        if record.work_mode == WorkMode.OFFLINE:
            x_coord = (payload.get('x_coord') or '').strip()
            y_coord = (payload.get('y_coord') or '').strip()
            z_coord = (payload.get('z_coord') or '').strip()
            if not (x_coord and y_coord and z_coord):
                return jsonify(create_error_response('INVALID_PARAMS', '线下开播时必须选择X/Y/Z坐标')), 400
            record.x_coord = x_coord
            record.y_coord = y_coord
            record.z_coord = z_coord
        else:
            record.x_coord = ''
            record.y_coord = ''
            record.z_coord = ''

        notes = (payload.get('notes') or '').strip()
        record.notes = notes

        validation_error = validate_notes_required(record.start_time, record.end_time, record.revenue_amount, record.base_salary, record.related_announcement,
                                                   record.notes)
        if validation_error:
            return jsonify(create_error_response('VALIDATION_FAILED', validation_error)), 400

        record.save()

        logger.debug(
            '更新开播记录后准备自动BBS发帖：record=%s status=%s revenue=%s notes_len=%d base=%s announcement=%s work_mode=%s',
            record.id,
            record.current_status.value,
            str(record.revenue_amount or Decimal('0')),
            len(record.notes or ''),
            record.x_coord or '',
            getattr(getattr(record, 'related_announcement', None), 'id', None),
            record.work_mode.value if record.work_mode else None,
        )

        try:
            create_post_for_battle_record(record)
        except Exception as exc:  # pylint: disable=broad-except
            logger.error('自动创建BBS帖子失败：record=%s error=%s', record.id, exc, exc_info=True)

        client_ip = _get_client_ip()
        for field_name, old_value in old_values.items():
            new_value = getattr(record, field_name)
            if old_value != new_value:
                log_battle_record_change(record, field_name, old_value, new_value, current_user, client_ip)

        data = _serialize_battle_record_detail(record)
        meta = {'message': '开播记录更新成功'}
        return jsonify(create_success_response(data, meta))
    except ValueError as exc:
        return jsonify(create_error_response('INVALID_PARAMS', str(exc))), 400
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('更新开播记录失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '更新开播记录失败')), 500


@battle_records_api_bp.route('/battle-records/<record_id>', methods=['DELETE'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def delete_record(record_id: str):
    """删除开播记录。"""
    # JWT认证的API不需要CSRF验证，因为JWT cookie已有CSRF保护

    try:
        record = BattleRecord.objects.get(id=record_id)
        BattleRecordChangeLog.objects.filter(battle_record_id=record).delete()
        record.delete()
        meta = {'message': '开播记录删除成功'}
        return jsonify(create_success_response({}, meta))
    except DoesNotExist:
        return jsonify(create_error_response('BATTLE_RECORD_NOT_FOUND', '开播记录不存在')), 404
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('删除开播记录失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '删除开播记录失败')), 500


@battle_records_api_bp.route('/battle-records/<record_id>/rant', methods=['POST'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def rant_record(record_id: str):
    """吐槽：强制创建帖子并追加回复。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    try:
        record = BattleRecord.objects.get(id=record_id)
    except DoesNotExist:
        return jsonify(create_error_response('BATTLE_RECORD_NOT_FOUND', '开播记录不存在')), 404

    operator = current_user
    if not operator or not getattr(operator, 'is_authenticated', False):
        return jsonify(create_error_response('UNAUTHORIZED', '未认证')), 401

    try:
        post = ensure_battle_record_post_for_rant(record, operator)
        operator_name = operator.nickname or operator.username or '未知运营'
        message = f"{operator_name}表示要吐槽一下"
        add_rant_reply(post, operator, message)
    except ValueError as exc:
        return jsonify(create_error_response('INVALID_OPERATION', str(exc))), 400
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('吐槽操作失败：record=%s error=%s', record_id, exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '吐槽失败，请稍后重试')), 500

    data = {'post_id': str(post.id)}
    meta = {'redirect': url_for('bbs.bbs_index')}
    return jsonify(create_success_response(data, meta))


@battle_records_api_bp.route('/battle-records/<record_id>/changes', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def record_changes(record_id: str):
    """获取开播记录变更日志。"""
    try:
        record = BattleRecord.objects.get(id=record_id)
        changes = BattleRecordChangeLog.objects.filter(battle_record_id=record).order_by('-change_time').limit(100)
        data = {'items': _serialize_change_logs(changes)}
        return jsonify(create_success_response(data))
    except DoesNotExist:
        return jsonify(create_error_response('BATTLE_RECORD_NOT_FOUND', '开播记录不存在')), 404
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取开播记录变更记录失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取变更记录失败')), 500


@battle_records_api_bp.route('/pilot-filters', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def pilot_filters():
    """获取主播筛选器数据。"""
    try:
        gicho = Role.objects(name='gicho').first()
        kancho = Role.objects(name='kancho').first()
        role_list = [role for role in (gicho, kancho) if role]
        owners = User.objects(roles__in=role_list).order_by('username') if role_list else []

        owner_options = [{'id': str(owner.id), 'name': owner.nickname or owner.username} for owner in owners]

        ranks = [{
            'value': Rank.CANDIDATE.value,
            'name': Rank.CANDIDATE.value
        }, {
            'value': Rank.TRAINEE.value,
            'name': Rank.TRAINEE.value
        }, {
            'value': Rank.INTERN.value,
            'name': Rank.INTERN.value
        }, {
            'value': Rank.OFFICIAL.value,
            'name': Rank.OFFICIAL.value
        }]

        data = {'owners': owner_options, 'ranks': ranks}
        return jsonify(create_success_response(data))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取主播筛选器数据失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取筛选器数据失败')), 500


@battle_records_api_bp.route('/pilots-filtered', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def pilots_filtered():
    """按筛选条件获取主播列表。"""
    try:
        pilot_id = (request.args.get('pilot_id') or '').strip()
        owner_id = (request.args.get('owner') or '').strip()
        rank_value = (request.args.get('rank') or '').strip()

        if pilot_id:
            try:
                pilot = Pilot.objects.get(id=pilot_id)
                pilots = [pilot]
            except DoesNotExist:
                pilots = []
        else:
            status_whitelist = ['已招募', '已签约', '已征召', '已就业']
            query = Pilot.objects(status__in=status_whitelist)

            if owner_id and owner_id not in ('', 'all'):
                try:
                    owner = User.objects.get(id=owner_id)
                    query = query.filter(owner=owner)
                except DoesNotExist:
                    query = query.none()

            if rank_value:
                try:
                    rank_enum = Rank(rank_value)
                    if rank_enum == Rank.CANDIDATE:
                        query = query.filter(rank__in=[Rank.CANDIDATE, Rank.CANDIDATE_OLD])
                    elif rank_enum == Rank.TRAINEE:
                        query = query.filter(rank__in=[Rank.TRAINEE, Rank.TRAINEE_OLD])
                    elif rank_enum == Rank.INTERN:
                        query = query.filter(rank__in=[Rank.INTERN, Rank.INTERN_OLD])
                    elif rank_enum == Rank.OFFICIAL:
                        query = query.filter(rank__in=[Rank.OFFICIAL, Rank.OFFICIAL_OLD])
                    else:
                        query = query.filter(rank=rank_enum)
                except ValueError:
                    logger.warning('无效的rank参数：%s', rank_value)

            pilots = sort_pilots_with_active_priority(list(query.order_by('nickname')))

        items = []
        for pilot in pilots:
            pilot_info = _serialize_pilot_basic(pilot)
            work_mode_value = pilot.work_mode.value if getattr(pilot, 'work_mode', None) else ''
            gender_icon = '♂'
            try:
                gender_icon = '♂' if pilot.gender.value == 0 else '♀' if pilot.gender.value == 1 else '?'
            except AttributeError:
                gender_icon = '?'
            age_part = f"({pilot_info['age']})" if pilot_info['age'] else ''
            display = f"{pilot_info['nickname']}{age_part}[{pilot_info['status']}]{gender_icon}"

            items.append({
                'id': pilot_info['id'],
                'display': display,
                'nickname': pilot_info['nickname'],
                'real_name': pilot_info['real_name'],
                'age': pilot_info['age'] or '',
                'gender': pilot_info['gender'],
                'status': pilot_info['status'],
                'rank': pilot_info['rank'],
                'owner': pilot_info['owner_display'],
                'work_mode': work_mode_value,
            })

        return jsonify(create_success_response({'items': items}))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取主播列表失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取主播列表失败')), 500


@battle_records_api_bp.route('/battle-areas', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def battle_areas():
    """获取开播地点三联数据。"""
    try:
        areas = BattleArea.objects.filter(availability=Availability.ENABLED).order_by('x_coord', 'y_coord', 'z_coord')

        mapping: Dict[str, Dict[str, List[str]]] = {}
        for area in areas:
            mapping.setdefault(area.x_coord, {}).setdefault(area.y_coord, []).append(area.z_coord)

        result: Dict[str, Dict[str, List[str]]] = {}
        for x_coord, y_dict in mapping.items():
            result[x_coord] = {}
            for y_coord, z_list in y_dict.items():
                try:
                    z_list.sort(key=lambda value: int(value))  # pylint: disable=unnecessary-lambda
                except ValueError:
                    z_list.sort()
                result[x_coord][y_coord] = z_list

        return jsonify(create_success_response({'areas': result}))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取开播地点数据失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取开播地点数据失败')), 500


@battle_records_api_bp.route('/announcements/<announcement_id>', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def announcement_detail(announcement_id: str):
    """获取通告详情用于预填。"""
    try:
        announcement = Announcement.objects.get(id=announcement_id)
        local_start = utc_to_local(announcement.start_time) if announcement.start_time else None
        local_end = utc_to_local(announcement.end_time) if announcement.end_time else None

        data = {
            'announcement': {
                'id': str(announcement.id),
                'pilot_id': str(announcement.pilot.id) if announcement.pilot else '',
                'pilot_name': announcement.pilot.nickname if announcement.pilot else '',
                'start_time': local_start.isoformat() if local_start else '',
                'end_time': local_end.isoformat() if local_end else '',
                'x_coord': announcement.x_coord,
                'y_coord': announcement.y_coord,
                'z_coord': announcement.z_coord,
                'work_mode': WorkMode.OFFLINE.value,
                'owner_id': str(announcement.pilot.owner.id) if announcement.pilot and announcement.pilot.owner else '',
                'owner_name':
                (announcement.pilot.owner.nickname or announcement.pilot.owner.username) if announcement.pilot and announcement.pilot.owner else '',
            }
        }
        return jsonify(create_success_response(data))
    except DoesNotExist:
        return jsonify(create_error_response('ANNOUNCEMENT_NOT_FOUND', '通告不存在')), 404
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取通告详情失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取通告详情失败')), 500


@battle_records_api_bp.route('/related-announcements', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho', 'gunsou')
def related_announcements():
    """根据主播获取昨天/今天/明天的通告列表。"""
    try:
        pilot_id = (request.args.get('pilot_id') or '').strip()
        if not pilot_id:
            return jsonify(create_success_response({'announcements': []}))

        try:
            pilot = Pilot.objects.get(id=pilot_id)
        except DoesNotExist:
            return jsonify(create_success_response({'announcements': []}))

        now_local = utc_to_local(get_current_utc_time())
        today_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_start = today_start + timedelta(days=1)
        day_after_tomorrow_start = today_start + timedelta(days=2)
        yesterday_start = today_start - timedelta(days=1)

        range_start = local_to_utc(yesterday_start)
        range_end = local_to_utc(day_after_tomorrow_start)

        candidate_announcements = Announcement.objects(pilot=pilot, start_time__gte=range_start, start_time__lt=range_end)

        weekday_names = ['一', '二', '三', '四', '五', '六', '日']

        buckets = {'today': [], 'yesterday': [], 'tomorrow': []}

        for announcement in candidate_announcements:
            local_dt = utc_to_local(announcement.start_time)
            if today_start <= local_dt < tomorrow_start:
                bucket_key = 'today'
            elif yesterday_start <= local_dt < today_start:
                bucket_key = 'yesterday'
            elif tomorrow_start <= local_dt < day_after_tomorrow_start:
                bucket_key = 'tomorrow'
            else:
                continue

            date_str = local_dt.strftime('%Y-%m-%d')
            weekday_str = weekday_names[local_dt.weekday()]
            duration_str = f"{announcement.duration_hours}小时"
            label = f"{date_str} 星期{weekday_str} {duration_str} @{announcement.x_coord}-{announcement.y_coord}-{announcement.z_coord}"
            buckets[bucket_key].append({'id': str(announcement.id), 'label': label, 'timestamp': local_dt.timestamp()})

        ordered_list: List[Dict[str, str]] = []
        for key in ('today', 'yesterday', 'tomorrow'):
            entries = buckets[key]
            entries.sort(key=lambda item: item['timestamp'])
            for entry in entries:
                entry.pop('timestamp', None)
                ordered_list.append(entry)

        return jsonify(create_success_response({'announcements': ordered_list}))
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('获取关联通告列表失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '获取关联通告失败')), 500
