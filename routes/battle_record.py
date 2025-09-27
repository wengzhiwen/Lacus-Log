"""作战记录路由

注意：mongoengine 的动态属性在pylint中会触发 no-member 误报，这里统一抑制。
"""
# pylint: disable=no-member
from datetime import datetime, timedelta
from decimal import Decimal

from flask import (Blueprint, flash, jsonify, redirect, render_template, request, url_for)
from flask_security import current_user, roles_accepted

from models.announcement import Announcement
from models.battle_record import BattleRecord, BattleRecordChangeLog
from models.pilot import Pilot, WorkMode
from models.user import Role, User
from utils.filter_state import persist_and_restore_filters
from utils.logging_setup import get_logger
from utils.timezone_helper import (get_current_utc_time, local_to_utc, utc_to_local)

# 创建日志器（按模块分文件）
logger = get_logger('battle_record')

battle_record_bp = Blueprint('battle_record', __name__)


def log_battle_record_change(battle_record, field_name, old_value, new_value, user_id, ip_address):
    """记录开播记录变更日志"""
    try:
        change_log = BattleRecordChangeLog(battle_record_id=battle_record,
                                           user_id=user_id,
                                           field_name=field_name,
                                           old_value=str(old_value) if old_value is not None else '',
                                           new_value=str(new_value) if new_value is not None else '',
                                           ip_address=ip_address)
        change_log.save()
        logger.debug(f"记录开播记录变更: {field_name} {old_value} -> {new_value}")
    except Exception as e:
        logger.error(f"记录开播记录变更失败: {e}")


def get_time_rounded_to_half_hour(dt, backward=True):  # pylint: disable=unused-argument
    """获取向前取最近的整点或半点时间
    
    向前取最近的整点或半点定义：
    - 若分钟∈(30,59]，则取到 hh:30
    - 若分钟∈[0,30]，则取到 hh:00  
    - 若恰为hh:30或hh:00，直接取该时间点
    
    Args:
        dt: 输入的datetime对象
        backward: 是否向前取（True为向前，False为向后）
        
    Returns:
        rounded datetime对象
    """
    if dt.minute == 0 or dt.minute == 30:
        # 恰好是整点或半点
        return dt.replace(second=0, microsecond=0)
    elif dt.minute <= 30:
        # 取到整点
        return dt.replace(minute=0, second=0, microsecond=0)
    else:
        # 取到半点
        return dt.replace(minute=30, second=0, microsecond=0)


@battle_record_bp.route('/')
@roles_accepted('gicho', 'kancho')
def list_battle_records():
    """开播记录列表页"""
    logger.info(f"用户 {current_user.username} 访问开播记录列表")

    # 获取并持久化筛选参数（会话）
    filters = persist_and_restore_filters(
        'battle_records_list',
        allowed_keys=['owner', 'rank', 'pilot', 'time'],
        default_filters={
            'owner': 'all',
            'rank': '',
            'pilot': '',
            'time': 'two_days'
        },
    )

    owner_filter = filters.get('owner') or 'all'
    rank_filter = filters.get('rank') or ''
    pilot_filter = filters.get('pilot') or ''
    time_filter = filters.get('time') or 'two_days'

    # 构建查询条件
    query = BattleRecord.objects

    # 所属筛选
    if owner_filter == 'self':
        query = query.filter(owner_snapshot=current_user.id)
    elif owner_filter and owner_filter != 'all':
        try:
            owner_user = User.objects.get(id=owner_filter)
            query = query.filter(owner_snapshot=owner_user.id)
        except Exception:
            pass

    # 阶级筛选
    if rank_filter:
        pilots_with_rank = Pilot.objects.filter(rank=rank_filter)
        query = query.filter(pilot__in=pilots_with_rank)

    # 主播筛选
    if pilot_filter:
        try:
            pilot = Pilot.objects.get(id=pilot_filter)
            query = query.filter(pilot=pilot)
        except Pilot.DoesNotExist:
            pass

    # 时间筛选
    now_utc = get_current_utc_time()
    if time_filter == 'today':
        # 今天（GMT+8）
        local_today_start = utc_to_local(now_utc).replace(hour=0, minute=0, second=0, microsecond=0)
        local_today_end = local_today_start + timedelta(days=1)
        utc_today_start = local_to_utc(local_today_start)
        utc_today_end = local_to_utc(local_today_end)
        query = query.filter(start_time__gte=utc_today_start, start_time__lt=utc_today_end)
    elif time_filter == 'two_days':
        # 这两天：昨天+今天+明天（以本地时区计算边界）
        now_local = utc_to_local(now_utc)
        today_local_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        yesterday_local_start = today_local_start - timedelta(days=1)
        day_after_tomorrow_local_start = today_local_start + timedelta(days=2)
        range_start_utc = local_to_utc(yesterday_local_start)
        range_end_utc = local_to_utc(day_after_tomorrow_local_start)
        query = query.filter(start_time__gte=range_start_utc, start_time__lt=range_end_utc)
    elif time_filter == 'recent_7_days':
        # 近7天
        seven_days_ago = now_utc - timedelta(days=7)
        query = query.filter(start_time__gte=seven_days_ago)

    # 排序：开始时间逆序，流水金额逆序
    query = query.order_by('-start_time', '-revenue_amount')

    # 分页：每次100条
    page = int(request.args.get('page', 1))
    per_page = 100
    skip = (page - 1) * per_page

    battle_records = query.skip(skip).limit(per_page)
    total_count = query.count()

    # 获取筛选器选项数据
    # 只列出拥有 管理员/运营 角色的用户
    gicho = Role.objects(name='gicho').first()
    kancho = Role.objects(name='kancho').first()
    role_list = [r for r in [gicho, kancho] if r]
    owners = User.objects(roles__in=role_list).order_by('username') if role_list else []

    return render_template('battle_records/list.html',
                           battle_records=battle_records,
                           owners=owners,
                           current_filters={
                               'owner': owner_filter,
                               'rank': rank_filter,
                               'pilot': pilot_filter,
                               'time': time_filter
                           },
                           current_page=page,
                           total_count=total_count,
                           has_more=total_count > page * per_page)


@battle_record_bp.route('/new')
@roles_accepted('gicho', 'kancho')
def new_battle_record():
    """新建作战记录页"""
    logger.info(f"用户 {current_user.username} 访问新建作战记录页")

    # 获取预填参数
    announcement_id = request.args.get('announcement_id')

    # 计算默认时间
    current_local = utc_to_local(get_current_utc_time())

    # 开始时间默认：当前时间向前6小时，再"向前取最近的整点或半点"
    default_start_local = current_local - timedelta(hours=6)
    default_start_local = get_time_rounded_to_half_hour(default_start_local)

    # 结束时间默认：当前时间"向前取最近的整点或半点"
    default_end_local = get_time_rounded_to_half_hour(current_local)

    default_data = {
        'start_time': default_start_local,
        'end_time': default_end_local,
        'revenue_amount': Decimal('0'),
        'base_salary': Decimal('0'),
    }

    # 如果指定了关联通告，预填数据
    related_announcement = None
    if announcement_id:
        try:
            related_announcement = Announcement.objects.get(id=announcement_id)
            default_data.update({
                'pilot': related_announcement.pilot,
                'related_announcement': related_announcement,
                'start_time': utc_to_local(related_announcement.start_time),
                'end_time': utc_to_local(related_announcement.end_time),
                'x_coord': related_announcement.x_coord,
                'y_coord': related_announcement.y_coord,
                'z_coord': related_announcement.z_coord,
                'work_mode': WorkMode.OFFLINE,
                'owner_snapshot': related_announcement.pilot.owner,
            })
            logger.debug(f"从通告 {announcement_id} 预填作战记录数据")
        except Announcement.DoesNotExist:
            logger.warning(f"指定的通告 {announcement_id} 不存在")

    return render_template('battle_records/new.html', default_data=default_data, related_announcement=related_announcement)


@battle_record_bp.route('/create', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def create_battle_record():
    """创建作战记录"""
    logger.info(f"用户 {current_user.username} 创建作战记录")

    try:
        # 获取表单数据
        pilot_id = request.form.get('pilot')
        related_announcement_id = request.form.get('related_announcement')
        start_time_str = request.form.get('start_time')
        end_time_str = request.form.get('end_time')
        revenue_amount_str = request.form.get('revenue_amount', '0')
        base_salary_str = request.form.get('base_salary', '0')
        x_coord = request.form.get('x_coord') or ''
        y_coord = request.form.get('y_coord') or ''
        z_coord = request.form.get('z_coord') or ''
        work_mode = request.form.get('work_mode')
        notes = request.form.get('notes', '')

        # 验证必填字段（作战区域仅线下必填）
        if not all([pilot_id, start_time_str, end_time_str, work_mode]):
            flash('请填写所有必填项', 'error')
            return redirect(url_for('battle_record.new_battle_record'))

        # 参战形式枚举
        try:
            wm_enum = WorkMode(work_mode)
        except Exception:
            flash('参战形式不正确', 'error')
            return redirect(url_for('battle_record.new_battle_record'))

        # 获取主播对象
        try:
            pilot = Pilot.objects.get(id=pilot_id)
        except Pilot.DoesNotExist:
            flash('选择的主播不存在', 'error')
            return redirect(url_for('battle_record.new_battle_record'))

        # 获取关联通告（如果有）
        related_announcement = None
        if related_announcement_id:
            try:
                related_announcement = Announcement.objects.get(id=related_announcement_id)
            except Announcement.DoesNotExist:
                pass

        # 解析时间（从GMT+8转换为UTC）
        try:
            start_time_local = datetime.fromisoformat(start_time_str)
            end_time_local = datetime.fromisoformat(end_time_str)
            start_time_utc = local_to_utc(start_time_local)
            end_time_utc = local_to_utc(end_time_local)
        except ValueError:
            flash('时间格式错误', 'error')
            return redirect(url_for('battle_record.new_battle_record'))

        # 解析金额
        try:
            revenue_amount = Decimal(revenue_amount_str)
            base_salary = Decimal(base_salary_str)
        except (ValueError, TypeError):
            flash('金额格式错误', 'error')
            return redirect(url_for('battle_record.new_battle_record'))

        # 线下：要求坐标必填；线上：坐标可空
        if wm_enum == WorkMode.OFFLINE:
            if not (x_coord and y_coord and z_coord):
                flash('线下开播时必须选择X/Y/Z坐标', 'error')
                return redirect(url_for('battle_record.new_battle_record'))

        # 创建作战记录
        battle_record = BattleRecord(
            pilot=pilot,
            related_announcement=related_announcement,
            start_time=start_time_utc,
            end_time=end_time_utc,
            revenue_amount=revenue_amount,
            base_salary=base_salary,
            x_coord=x_coord,
            y_coord=y_coord,
            z_coord=z_coord,
            work_mode=wm_enum,
            owner_snapshot=pilot.owner,  # 无所属机师不使用当前用户作为快照
            registered_by=current_user,
            notes=notes.strip() if notes else '')

        battle_record.save()

        logger.info(f"开播记录创建成功，ID: {battle_record.id}")
        flash('开播记录创建成功', 'success')

        return redirect(url_for('battle_record.detail_battle_record', record_id=battle_record.id))

    except Exception as e:
        logger.error(f"创建开播记录失败: {e}")
        flash('创建开播记录失败，请重试', 'error')
        return redirect(url_for('battle_record.new_battle_record'))


@battle_record_bp.route('/<record_id>')
@roles_accepted('gicho', 'kancho')
def detail_battle_record(record_id):
    """开播记录详情页"""
    try:
        battle_record = BattleRecord.objects.get(id=record_id)
        logger.info(f"用户 {current_user.username} 查看开播记录详情 {record_id}")

        # 安全处理关联通告：若已被删除，则不触发模板中的懒加载异常
        related_announcement = None
        related_announcement_deleted = False
        try:
            # 触发一次解引用；若目标不存在会抛出 DoesNotExist
            related_announcement = battle_record.related_announcement
            _ = related_announcement.id if related_announcement else None
        except Exception as e:  # mongoengine.errors.DoesNotExist 等
            related_announcement_deleted = True
            # 提升为 WARNING，并带上堆栈，确保写入日志文件
            logger.warning(f"开播记录 {record_id} 的关联通告不存在，显示已删除占位。原因: {e}", exc_info=True)

        return render_template('battle_records/detail.html',
                               battle_record=battle_record,
                               related_announcement=related_announcement,
                               related_announcement_deleted=related_announcement_deleted)
    except BattleRecord.DoesNotExist:
        flash('开播记录不存在', 'error')
        return redirect(url_for('battle_record.list_battle_records'))


@battle_record_bp.route('/<record_id>/edit')
@roles_accepted('gicho', 'kancho')
def edit_battle_record(record_id):
    """编辑开播记录页"""
    try:
        battle_record = BattleRecord.objects.get(id=record_id)
        logger.info(f"用户 {current_user.username} 编辑开播记录 {record_id}")

        # 安全处理关联通告，避免模板中解引用触发异常
        related_announcement = None
        related_announcement_deleted = False
        try:
            related_announcement = battle_record.related_announcement
            _ = related_announcement.id if related_announcement else None
        except Exception as e:
            related_announcement_deleted = True
            logger.warning(f"开播记录 {record_id} 的关联通告不存在（编辑页），显示已删除占位。原因: {e}", exc_info=True)

        return render_template('battle_records/edit.html',
                               battle_record=battle_record,
                               related_announcement=related_announcement,
                               related_announcement_deleted=related_announcement_deleted)
    except BattleRecord.DoesNotExist:
        flash('开播记录不存在', 'error')
        return redirect(url_for('battle_record.list_battle_records'))


@battle_record_bp.route('/<record_id>/update', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def update_battle_record(record_id):
    """更新开播记录"""
    try:
        battle_record = BattleRecord.objects.get(id=record_id)
        logger.info(f"用户 {current_user.username} 更新开播记录 {record_id}")

        # 记录变更前的值
        # 注意：直接访问 related_announcement 可能触发懒加载并在目标不存在时抛异常
        try:
            old_related_announcement = battle_record.related_announcement
            _ = old_related_announcement.id if old_related_announcement else None
        except Exception:
            old_related_announcement = None

        old_values = {
            'pilot': battle_record.pilot,
            'related_announcement': old_related_announcement,
            'start_time': battle_record.start_time,
            'end_time': battle_record.end_time,
            'revenue_amount': battle_record.revenue_amount,
            'base_salary': battle_record.base_salary,
            'x_coord': battle_record.x_coord,
            'y_coord': battle_record.y_coord,
            'z_coord': battle_record.z_coord,
            'work_mode': battle_record.work_mode,
            'notes': battle_record.notes,
        }

        # 获取表单数据并更新
        pilot_id = request.form.get('pilot')
        if pilot_id:
            pilot = Pilot.objects.get(id=pilot_id)
            battle_record.pilot = pilot
            # 更新所属快照
            battle_record.owner_snapshot = pilot.owner

        # 关联通告：编辑页不可修改。
        # 若当前存量关联通告已被删除，则在保存时强制清空，避免后续界面再次 500。
        try:
            _tmp_ann = battle_record.related_announcement
            _ = _tmp_ann.id if _tmp_ann else None
        except Exception as e:
            logger.warning(f"开播记录 {record_id} 的关联通告在保存时检测为不存在，自动清空该引用。原因: {e}", exc_info=True)
            battle_record.related_announcement = None

        # 更新时间
        start_time_str = request.form.get('start_time')
        end_time_str = request.form.get('end_time')
        if start_time_str and end_time_str:
            start_time_local = datetime.fromisoformat(start_time_str)
            end_time_local = datetime.fromisoformat(end_time_str)
            battle_record.start_time = local_to_utc(start_time_local)
            battle_record.end_time = local_to_utc(end_time_local)

        # 更新金额
        revenue_amount_str = request.form.get('revenue_amount')
        base_salary_str = request.form.get('base_salary')
        if revenue_amount_str:
            battle_record.revenue_amount = Decimal(revenue_amount_str)
        if base_salary_str:
            battle_record.base_salary = Decimal(base_salary_str)

        # 更新开播方式
        work_mode = request.form.get('work_mode')
        if work_mode:
            battle_record.work_mode = WorkMode(work_mode)

        # 根据开播方式更新坐标：线下必填，线上可空（若线上则清空为后端一致性）
        if battle_record.work_mode == WorkMode.OFFLINE:
            x_coord = request.form.get('x_coord')
            y_coord = request.form.get('y_coord')
            z_coord = request.form.get('z_coord')
            if not all([x_coord, y_coord, z_coord]):
                flash('线下开播时必须选择X/Y/Z坐标', 'error')
                return redirect(url_for('battle_record.edit_battle_record', record_id=record_id))
            battle_record.x_coord = x_coord
            battle_record.y_coord = y_coord
            battle_record.z_coord = z_coord
        else:
            battle_record.x_coord = ''
            battle_record.y_coord = ''
            battle_record.z_coord = ''

        # 更新备注
        notes = request.form.get('notes', '')
        battle_record.notes = notes.strip()

        battle_record.save()

        # 记录变更日志
        client_ip = request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR')

        for field_name, old_value in old_values.items():
            new_value = getattr(battle_record, field_name)
            if old_value != new_value:
                log_battle_record_change(battle_record, field_name, old_value, new_value, current_user, client_ip)

        flash('开播记录更新成功', 'success')
        return redirect(url_for('battle_record.detail_battle_record', record_id=record_id))

    except BattleRecord.DoesNotExist:
        flash('开播记录不存在', 'error')
        return redirect(url_for('battle_record.list_battle_records'))
    except Exception as e:
        logger.error(f"更新开播记录失败: {e}")
        flash('更新开播记录失败，请重试', 'error')
        return redirect(url_for('battle_record.edit_battle_record', record_id=record_id))


@battle_record_bp.route('/<record_id>/delete', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def delete_battle_record(record_id):
    """删除开播记录"""
    try:
        battle_record = BattleRecord.objects.get(id=record_id)
        logger.info(f"用户 {current_user.username} 删除开播记录 {record_id}")

        # 删除相关的变更记录
        BattleRecordChangeLog.objects.filter(battle_record_id=battle_record).delete()

        # 删除开播记录
        battle_record.delete()

        flash('开播记录删除成功', 'success')
        return redirect(url_for('battle_record.list_battle_records'))

    except BattleRecord.DoesNotExist:
        flash('开播记录不存在', 'error')
        return redirect(url_for('battle_record.list_battle_records'))
    except Exception as e:
        logger.error(f"删除开播记录失败: {e}")
        flash('删除开播记录失败，请重试', 'error')
        return redirect(url_for('battle_record.detail_battle_record', record_id=record_id))


@battle_record_bp.route('/<record_id>/changes')
@roles_accepted('gicho', 'kancho')
def view_battle_record_changes(record_id):
    """查看开播记录变更记录"""
    try:
        battle_record = BattleRecord.objects.get(id=record_id)
        changes = BattleRecordChangeLog.objects.filter(battle_record_id=battle_record).order_by('-change_time').limit(100)

        logger.info(f"用户 {current_user.username} 查看开播记录变更记录 {record_id}")

        return jsonify({
            'success':
            True,
            'changes': [{
                'change_time': change.change_time.isoformat(),
                'user_name': change.user_id.username if change.user_id else '未知',
                'field_name': change.field_display_name,
                'old_value': change.old_value,
                'new_value': change.new_value,
                'ip_address': change.ip_address
            } for change in changes]
        })

    except BattleRecord.DoesNotExist:
        return jsonify({'success': False, 'error': '开播记录不存在'}), 404
    except Exception as e:
        logger.error(f"获取开播记录变更记录失败: {e}")
        return jsonify({'success': False, 'error': '获取变更记录失败'}), 500


# API接口


@battle_record_bp.route('/api/pilot-filters')
@roles_accepted('gicho', 'kancho')
def api_pilot_filters():
    """获取主播筛选器数据"""
    try:
        # 获取所有运营和管理员作为直属运营选项
        gicho = Role.objects(name='gicho').first()
        kancho = Role.objects(name='kancho').first()
        role_list = [r for r in [gicho, kancho] if r]
        owners = User.objects(roles__in=role_list).order_by('username') if role_list else []
        owners_data = [{'id': str(owner.id), 'name': owner.nickname or owner.username} for owner in owners]

        # 获取所有阶级选项
        from models.pilot import Rank
        ranks_data = [{'value': rank.value, 'name': rank.value} for rank in Rank]

        return jsonify({'success': True, 'owners': owners_data, 'ranks': ranks_data})

    except Exception as e:
        logger.error(f"获取主播筛选器数据失败: {e}")
        return jsonify({'success': False, 'error': '获取筛选器数据失败'}), 500


@battle_record_bp.route('/api/pilots-filtered')
@roles_accepted('gicho', 'kancho')
def api_pilots_filtered():
    """根据筛选条件获取主播列表"""
    try:
        owner_id = request.args.get('owner')
        rank = request.args.get('rank')

        # 构建查询条件
        query = Pilot.objects.filter(status__in=['已招募', '已签约', '已征召'])

        if owner_id and owner_id != 'all':
            try:
                owner = User.objects.get(id=owner_id)
                query = query.filter(owner=owner)
            except User.DoesNotExist:
                pass

        if rank:
            query = query.filter(rank=rank)

        # 排序：已征召/已签约排前，其他状态排后，状态相同的按主播昵称字典顺序
        pilots = query.order_by('nickname')

        pilots_data = []
        for pilot in pilots:
            age_str = f"({pilot.age})" if pilot.age else ""
            gender_icon = "♂" if pilot.gender.value == 0 else "♀" if pilot.gender.value == 1 else "?"
            display_name = f"{pilot.nickname}{age_str}[{pilot.status.value}]{gender_icon}"

            # 优先使用所属用户的昵称，若无昵称则使用用户名；无所属则返回空字符串
            owner_name = ''
            if pilot.owner:
                owner_name = (pilot.owner.nickname or pilot.owner.username) or ''

            pilots_data.append({
                'id': str(pilot.id),
                'name': display_name,
                'nickname': pilot.nickname,
                'real_name': pilot.real_name or '',
                'age': pilot.age or '',
                'gender': pilot.gender.value if hasattr(pilot, 'gender') and pilot.gender is not None else None,
                'status': pilot.status.value,
                'rank': pilot.rank.value,
                'owner': owner_name
            })

        return jsonify({'success': True, 'pilots': pilots_data})

    except Exception as e:
        logger.error(f"获取主播列表失败: {e}")
        return jsonify({'success': False, 'error': '获取主播列表失败'}), 500


@battle_record_bp.route('/api/battle-areas')
@roles_accepted('gicho', 'kancho')
def api_battle_areas():
    """获取开播地点数据（三联选择）"""
    try:
        from models.battle_area import Availability, BattleArea

        # 获取所有可用的开播地点
        areas = BattleArea.objects.filter(availability=Availability.ENABLED).order_by('x_coord', 'y_coord', 'z_coord')

        # 构建三级联动数据结构
        x_coords = {}

        for area in areas:
            x_coord = area.x_coord
            y_coord = area.y_coord
            z_coord = area.z_coord

            if x_coord not in x_coords:
                x_coords[x_coord] = {}

            if y_coord not in x_coords[x_coord]:
                x_coords[x_coord][y_coord] = []

            x_coords[x_coord][y_coord].append(z_coord)

        # 转换为前端需要的格式
        result = {}
        for x_coord in sorted(x_coords.keys()):
            result[x_coord] = {}
            for y_coord in sorted(x_coords[x_coord].keys()):
                # Z坐标排序：如果是数字优先按数值排序
                z_coords = x_coords[x_coord][y_coord]
                try:
                    z_coords.sort(key=lambda z: int(z))
                except ValueError:
                    z_coords.sort()  # 如果不是数字，按字典顺序排序
                result[x_coord][y_coord] = z_coords

        return jsonify({'success': True, 'areas': result})

    except Exception as e:
        logger.error(f"获取开播地点数据失败: {e}")
        return jsonify({'success': False, 'error': '获取开播地点数据失败'}), 500


@battle_record_bp.route('/api/announcements/<announcement_id>')
@roles_accepted('gicho', 'kancho')
def api_announcement_detail(announcement_id):
    """获取通告详情用于预填"""
    try:
        announcement = Announcement.objects.get(id=announcement_id)

        return jsonify({
            'success': True,
            'announcement': {
                'id': str(announcement.id),
                'pilot_id': str(announcement.pilot.id),
                'pilot_name': announcement.pilot.nickname,
                'start_time': utc_to_local(announcement.start_time).isoformat(),
                'end_time': utc_to_local(announcement.end_time).isoformat(),
                'x_coord': announcement.x_coord,
                'y_coord': announcement.y_coord,
                'z_coord': announcement.z_coord,
                # 按需求：选中关联通告时参战形式预设为线下
                'work_mode': WorkMode.OFFLINE.value,
                'owner_id': str(announcement.pilot.owner.id) if announcement.pilot.owner else '',
                'owner_name': announcement.pilot.owner.nickname or announcement.pilot.owner.username if announcement.pilot.owner else ''
            }
        })

    except Announcement.DoesNotExist:
        return jsonify({'success': False, 'error': '通告不存在'}), 404
    except Exception as e:
        logger.error(f"获取通告详情失败: {e}")
        return jsonify({'success': False, 'error': '获取通告详情失败'}), 500


@battle_record_bp.route('/api/related-announcements')
@roles_accepted('gicho', 'kancho')
def api_related_announcements():
    """根据机师返回昨天/今天/明天的通告列表（本地时区计算）。

    返回：[{id, label}]，label格式：yyyy-mm-dd 星期M N小时 @X-Y-Z
    排序：今天在前，随后昨天、明天。
    """
    try:
        pilot_id = request.args.get('pilot_id')
        if not pilot_id:
            return jsonify({'success': True, 'announcements': []})

        # 获取机师
        try:
            pilot = Pilot.objects.get(id=pilot_id)
        except Pilot.DoesNotExist:
            return jsonify({'success': True, 'announcements': []})

        # 计算本地昨天/今天/明天的 UTC 范围
        now_utc = get_current_utc_time()
        now_local = utc_to_local(now_utc)

        today_local_start = now_local.replace(hour=0, minute=0, second=0, microsecond=0)
        tomorrow_local_start = today_local_start + timedelta(days=1)
        day_after_tomorrow_local_start = today_local_start + timedelta(days=2)
        yesterday_local_start = today_local_start - timedelta(days=1)

        # 合并查询范围：昨天0点 至 明天的明天0点（覆盖昨天/今天/明天）
        range_start_utc = local_to_utc(yesterday_local_start)
        range_end_utc = local_to_utc(day_after_tomorrow_local_start)

        candidates = Announcement.objects(pilot=pilot, start_time__gte=range_start_utc, start_time__lt=range_end_utc)

        weekday_names = ['一', '二', '三', '四', '五', '六', '日']

        result_today = []
        result_yesterday = []
        result_tomorrow = []

        for ann in candidates:
            local_dt = utc_to_local(ann.start_time)
            # 判断所属日期段
            if today_local_start <= local_dt < tomorrow_local_start:
                bucket = result_today
            elif yesterday_local_start <= local_dt < today_local_start:
                bucket = result_yesterday
            elif tomorrow_local_start <= local_dt < day_after_tomorrow_local_start:
                bucket = result_tomorrow
            else:
                continue

            date_str = local_dt.strftime('%Y-%m-%d')
            weekday_str = f"星期{weekday_names[local_dt.weekday()]}"
            duration_str = f"{ann.duration_hours}小时" if ann.duration_hours == int(ann.duration_hours) else f"{ann.duration_hours}小时"
            label = f"{date_str} {weekday_str} {duration_str} @{ann.x_coord}-{ann.y_coord}-{ann.z_coord}"
            bucket.append({'id': str(ann.id), 'label': label, 'local_ts': local_dt.timestamp()})

        # 排序：今天按时间升序；昨天、明天各自按时间升序；整体今天在前，然后昨天、明天
        result_today.sort(key=lambda x: x['local_ts'])
        result_yesterday.sort(key=lambda x: x['local_ts'])
        result_tomorrow.sort(key=lambda x: x['local_ts'])

        merged = result_today + result_yesterday + result_tomorrow
        # 移除排序辅助字段
        for item in merged:
            item.pop('local_ts', None)

        return jsonify({'success': True, 'announcements': merged})

    except Exception as e:
        logger.error(f"获取关联开播记录失败: {e}")
        return jsonify({'success': False, 'error': '获取关联通告失败'}), 500
