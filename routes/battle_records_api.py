# -*- coding: utf-8 -*-
"""开播记录 REST API 路由集合。"""

# pylint: disable=no-member,too-many-return-statements,too-many-branches,too-many-locals,too-many-statements,duplicate-code

from datetime import datetime, timedelta
from decimal import Decimal
from typing import Dict, Iterable, List, Optional, Tuple

from flask import Blueprint, jsonify, request, url_for
from flask_security import current_user, roles_accepted
from mongoengine import DoesNotExist

from models.announcement import Announcement
from models.battle_area import Availability, BattleArea
from models.battle_record import BattleRecord, BattleRecordChangeLog
from models.pilot import Pilot, Rank, WorkMode
from models.user import Role, User
from routes.battle_record import (log_battle_record_change, validate_notes_required)
from utils.announcement_serializers import (create_error_response, create_success_response)
from utils.csrf_helper import CSRFError, validate_csrf_header
from utils.filter_state import persist_and_restore_filters
from utils.james_alert import trigger_james_alert_if_needed
from utils.jwt_roles import jwt_roles_accepted, jwt_roles_required
from utils.logging_setup import get_logger
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)

logger = get_logger('battle_records_api')

battle_records_api_bp = Blueprint('battle_records_api', __name__)


def _persist_filters_from_request() -> Dict[str, str]:
    return persist_and_restore_filters(
        'battle_records_list',
        allowed_keys=['owner', 'x', 'time'],
        default_filters={
            'owner': 'all',
            'x': '',
            'time': 'two_days'
        },
    )


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


def _apply_time_filter(queryset, time_filter: str):
    now_utc = get_current_utc_time()
    now_local = utc_to_local(now_utc)
    start_local = now_local.replace(hour=0, minute=0, second=0, microsecond=0)

    if time_filter == 'today':
        start_utc = local_to_utc(start_local)
        end_utc = local_to_utc(start_local + timedelta(days=1))
    elif time_filter == 'seven_days':
        start_utc = local_to_utc(start_local - timedelta(days=7))
        end_utc = local_to_utc(start_local + timedelta(days=1))
    elif time_filter == 'month_to_date':
        month_start_local = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        tomorrow_local_start = start_local + timedelta(days=1)
        start_utc = local_to_utc(month_start_local)
        end_utc = local_to_utc(tomorrow_local_start)
    elif time_filter == 'last_month':
        if now_local.month == 1:
            last_month_start = now_local.replace(year=now_local.year - 1, month=12, day=1, hour=0, minute=0, second=0, microsecond=0)
            this_month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        else:
            last_month_start = now_local.replace(month=now_local.month - 1, day=1, hour=0, minute=0, second=0, microsecond=0)
            this_month_start = now_local.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_utc = local_to_utc(last_month_start)
        end_utc = local_to_utc(this_month_start)
    else:  # 默认两天窗口：昨天-明天
        start_utc = local_to_utc(start_local - timedelta(days=1))
        end_utc = local_to_utc(start_local + timedelta(days=2))

    return queryset.filter(start_time__gte=start_utc, start_time__lt=end_utc)


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

    time_options = [{
        'value': 'two_days',
        'label': '这两天'
    }, {
        'value': 'seven_days',
        'label': '近7天'
    }, {
        'value': 'today',
        'label': '今天'
    }, {
        'value': 'month_to_date',
        'label': '月初以来'
    }, {
        'value': 'last_month',
        'label': '前月'
    }]

    return {'owners': owner_options, 'x_coords': x_options, 'time_ranges': time_options}


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


def _serialize_battle_record_summary(record: BattleRecord) -> Dict[str, object]:
    pilot_info = _serialize_pilot_basic(record.pilot)
    start_local = utc_to_local(record.start_time) if record.start_time else None

    return {
        'id': str(record.id),
        'pilot': pilot_info,
        'owner_display': pilot_info['owner_display'],
        'work_mode': record.work_mode.value if record.work_mode else '',
        'revenue_amount': format(record.revenue_amount or Decimal('0'), 'f'),
        'base_salary': format(record.base_salary or Decimal('0'), 'f'),
        'duration_hours': record.duration_hours or 0,
        'duration_display': f"{record.duration_hours:.1f}小时" if record.duration_hours is not None else '0.0小时',
        'start_time': {
            'iso': start_local.isoformat() if start_local else None,
            'display': start_local.strftime('%m月%d日 %H:%M') if start_local else '',
        },
        'links': {
            'detail': url_for('battle_record.detail_battle_record', record_id=record.id)
        },
        'search': {
            'nickname': pilot_info['nickname'],
            'real_name': pilot_info['real_name']
        }
    }


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


def _build_old_record_snapshot(record: BattleRecord) -> object:

    class _Snapshot:  # pylint: disable=too-few-public-methods

        def __init__(self, src: BattleRecord):
            self.revenue_amount = src.revenue_amount
            self.base_salary = src.base_salary
            self.start_time = src.start_time
            self.end_time = src.end_time
            duration_hours = 0
            if src.start_time and src.end_time:
                delta = src.end_time - src.start_time
                duration_hours = round(delta.total_seconds() / 3600, 1)
            self.duration_hours = duration_hours

    return _Snapshot(record)


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
        'work_mode': record.work_mode,
        'notes': record.notes,
    }


def _get_client_ip() -> str:
    return request.headers.get('X-Forwarded-For') or request.remote_addr or '未知'


@battle_records_api_bp.route('/battle-records', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
def list_records():
    """获取开播记录列表。"""
    try:
        filters = _persist_filters_from_request()
        owner_filter = filters.get('owner', 'all')
        x_filter = filters.get('x', '')
        time_filter = filters.get('time', 'two_days')

        page = max(int(request.args.get('page', 1) or 1), 1)
        per_page = 500
        skip = (page - 1) * per_page

        base_query = BattleRecord.objects.order_by('-start_time', '-revenue_amount')
        filtered_query = _apply_owner_filter(base_query, owner_filter)
        filtered_query = _apply_x_filter(filtered_query, x_filter)
        filtered_query = _apply_time_filter(filtered_query, time_filter)

        total_count = filtered_query.count()
        records = list(filtered_query.skip(skip).limit(per_page))

        items = [_serialize_battle_record_summary(record) for record in records]

        meta = {
            'filters': {
                'owner': owner_filter,
                'x': x_filter,
                'time': time_filter,
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
@jwt_roles_accepted('gicho', 'kancho')
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
@jwt_roles_accepted('gicho', 'kancho')
def create_record():
    """创建开播记录。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    payload = request.get_json(silent=True) or {}

    try:
        pilot_id = (payload.get('pilot') or '').strip()
        related_announcement_id = (payload.get('related_announcement') or '').strip()
        start_time_str = (payload.get('start_time') or '').strip()
        end_time_str = (payload.get('end_time') or '').strip()
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

        trigger_james_alert_if_needed(record)

        data = _serialize_battle_record_detail(record)
        meta = {'message': '开播记录创建成功'}
        return jsonify(create_success_response(data, meta)), 201
    except ValueError as exc:
        return jsonify(create_error_response('INVALID_PARAMS', str(exc))), 400
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('创建开播记录失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '创建开播记录失败')), 500


@battle_records_api_bp.route('/battle-records/<record_id>', methods=['PUT'])
@jwt_roles_accepted('gicho', 'kancho')
def update_record(record_id: str):
    """更新开播记录。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

    payload = request.get_json(silent=True) or {}

    try:
        record = BattleRecord.objects.get(id=record_id)
    except DoesNotExist:
        return jsonify(create_error_response('BATTLE_RECORD_NOT_FOUND', '开播记录不存在')), 404

    try:
        old_snapshot = _build_old_record_snapshot(record)
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

        client_ip = _get_client_ip()
        for field_name, old_value in old_values.items():
            new_value = getattr(record, field_name)
            if old_value != new_value:
                log_battle_record_change(record, field_name, old_value, new_value, current_user, client_ip)

        trigger_james_alert_if_needed(record, old_snapshot)

        data = _serialize_battle_record_detail(record)
        meta = {'message': '开播记录更新成功'}
        return jsonify(create_success_response(data, meta))
    except ValueError as exc:
        return jsonify(create_error_response('INVALID_PARAMS', str(exc))), 400
    except Exception as exc:  # pylint: disable=broad-except
        logger.error('更新开播记录失败：%s', exc, exc_info=True)
        return jsonify(create_error_response('INTERNAL_ERROR', '更新开播记录失败')), 500


@battle_records_api_bp.route('/battle-records/<record_id>', methods=['DELETE'])
@jwt_roles_accepted('gicho', 'kancho')
def delete_record(record_id: str):
    """删除开播记录。"""
    try:
        validate_csrf_header()
    except CSRFError as exc:
        return jsonify(create_error_response(exc.code, exc.message)), 401

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


@battle_records_api_bp.route('/battle-records/<record_id>/changes', methods=['GET'])
@jwt_roles_accepted('gicho', 'kancho')
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
@jwt_roles_accepted('gicho', 'kancho')
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
@jwt_roles_accepted('gicho', 'kancho')
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

            pilots = list(query.order_by('nickname'))

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
@jwt_roles_accepted('gicho', 'kancho')
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
@jwt_roles_accepted('gicho', 'kancho')
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
@jwt_roles_accepted('gicho', 'kancho')
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
