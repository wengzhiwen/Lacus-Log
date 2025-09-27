# pylint: disable=no-member
from datetime import timedelta

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template,
                   request, url_for)
from flask_security import current_user, roles_accepted
from mongoengine import DoesNotExist, ValidationError

from models.pilot import (Gender, Pilot, PilotChangeLog, PilotCommission,
                          PilotCommissionChangeLog, Platform, Rank, Status,
                          WorkMode)
from models.user import User
from utils.logging_setup import get_logger
from utils.timezone_helper import get_current_utc_time
from utils.filter_state import persist_and_restore_filters

logger = get_logger('pilot')

pilot_bp = Blueprint('pilot', __name__)


def _get_client_ip():
    """获取客户端IP地址"""
    return request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR')


def _record_changes(pilot, old_data, user, ip_address):
    """记录主播字段变更"""
    changes = []
    field_mapping = {
        'nickname': pilot.nickname,
        'real_name': pilot.real_name,
        'gender': pilot.gender.value if pilot.gender else None,
        'hometown': pilot.hometown,
        'birth_year': pilot.birth_year,
        'owner': str(pilot.owner.id) if pilot.owner else None,
        'platform': pilot.platform.value if pilot.platform else None,
        'work_mode': pilot.work_mode.value if pilot.work_mode else None,
        'rank': pilot.rank.value if pilot.rank else None,
        'status': pilot.status.value if pilot.status else None,
    }

    for field_name, new_value in field_mapping.items():
        old_value = old_data.get(field_name)
        if str(old_value) != str(new_value):
            change_log = PilotChangeLog(pilot_id=pilot,
                                        user_id=user,
                                        field_name=field_name,
                                        old_value=str(old_value) if old_value is not None else '',
                                        new_value=str(new_value) if new_value is not None else '',
                                        ip_address=ip_address)
            changes.append(change_log)

    if changes:
        PilotChangeLog.objects.insert(changes)
        logger.info('记录主播变更：%s，共%d个字段', pilot.nickname, len(changes))


def _check_pilot_permission(_pilot):
    """检查用户对主播的操作权限"""
    # 管理员与运营权限一致：均可访问/编辑所有主播
    if current_user.has_role('gicho') or current_user.has_role('kancho'):
        return True
    return False


def _get_user_choices():
    """获取用户选择列表，按特定顺序排序"""
    users = User.objects.all()
    choices = [('', '无')]

    # 第二顺位：当前用户
    if current_user.has_role('kancho') or current_user.has_role('gicho'):
        choices.append((str(current_user.id), current_user.nickname or current_user.username))

    # 第三顺位：其他活跃运营/管理员（昵称字典顺序）
    active_users = [u for u in users if u.active and u.id != current_user.id and (u.has_role('kancho') or u.has_role('gicho'))]
    active_users.sort(key=lambda x: x.nickname or x.username)
    for user in active_users:
        choices.append((str(user.id), user.nickname or user.username))

    # 第四顺位：其他非活跃运营/管理员（昵称字典顺序，标记[流失]）
    inactive_users = [u for u in users if not u.active and u.id != current_user.id and (u.has_role('kancho') or u.has_role('gicho'))]
    inactive_users.sort(key=lambda x: x.nickname or x.username)
    for user in inactive_users:
        display_name = f"{user.nickname or user.username}[流失]"
        choices.append((str(user.id), display_name))

    return choices


@pilot_bp.route('/')
@roles_accepted('gicho', 'kancho')
def list_pilots():
    """主播列表页面"""
    # 获取并持久化筛选参数（会话）
    filters = persist_and_restore_filters(
        'pilots_list',
        allowed_keys=['rank', 'status', 'owner', 'days'],
        default_filters={'rank': '', 'status': '', 'owner': '', 'days': ''},
    )

    rank_filter = filters.get('rank') or None
    status_filter = filters.get('status') or None
    owner_filter = filters.get('owner') or None
    days_raw = filters.get('days') or None
    try:
        days_filter = int(days_raw) if days_raw else None
    except ValueError:
        days_filter = None

    # 构建查询
    query = Pilot.objects

    # 权限控制：管理员与运营权限一致，不做按直属运营的强制过滤

    # 应用筛选条件
    if rank_filter:
        try:
            rank_enum = Rank(rank_filter)
            query = query.filter(rank=rank_enum)
        except ValueError:
            pass

    if status_filter:
        try:
            status_enum = Status(status_filter)
            query = query.filter(status=status_enum)
        except ValueError:
            pass

    if owner_filter:
        if owner_filter == 'none':
            query = query.filter(owner=None)
        else:
            try:
                owner_user = User.objects.get(id=owner_filter)
                query = query.filter(owner=owner_user)
            except (DoesNotExist, ValidationError):
                pass

    if days_filter:
        cutoff_date = get_current_utc_time() - timedelta(days=days_filter)
        query = query.filter(created_at__gte=cutoff_date)

    pilots = query.order_by('-created_at').all()

    # 获取筛选选项
    user_choices = _get_user_choices()

    return render_template('pilots/list.html',
                           pilots=pilots,
                           rank_filter=rank_filter,
                           status_filter=status_filter,
                           owner_filter=owner_filter,
                           days_filter=days_filter,
                           user_choices=user_choices,
                           rank_choices=[(r.value, r.value) for r in Rank],
                           status_choices=[(s.value, s.value) for s in Status])


@pilot_bp.route('/<pilot_id>')
@roles_accepted('gicho', 'kancho')
def pilot_detail(pilot_id):
    """主播详情页面"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)

        # 权限检查
        if not _check_pilot_permission(pilot):
            abort(403)

        # 获取当前分成信息
        current_rate, effective_date, remark = _get_pilot_current_commission_rate(pilot_id)
        calculation_info = _calculate_commission_distribution(current_rate)

        return render_template('pilots/detail.html',
                               pilot=pilot,
                               current_rate=current_rate,
                               effective_date=effective_date,
                               remark=remark,
                               calculation_info=calculation_info)
    except DoesNotExist:
        abort(404)


@pilot_bp.route('/new', methods=['GET', 'POST'])
@roles_accepted('gicho', 'kancho')
def new_pilot():
    """新建主播"""
    if request.method == 'POST':
        try:
            # 获取表单数据
            nickname = request.form.get('nickname', '').strip()
            real_name = request.form.get('real_name', '').strip() or None
            gender = request.form.get('gender')
            hometown = request.form.get('hometown', '').strip() or None
            birth_year = request.form.get('birth_year')
            owner_id = request.form.get('owner') or None
            platform = request.form.get('platform')
            work_mode = request.form.get('work_mode')
            rank = request.form.get('rank')
            status = request.form.get('status')

            # 基础验证
            if not nickname:
                flash('昵称为必填项', 'error')
                return render_template('pilots/new.html', form=request.form, user_choices=_get_user_choices())

            # 检查昵称唯一性
            if Pilot.objects(nickname=nickname).first():
                flash('该昵称已存在', 'error')
                return render_template('pilots/new.html', form=request.form, user_choices=_get_user_choices())

            # 创建主播对象
            pilot = Pilot(nickname=nickname)

            if real_name:
                pilot.real_name = real_name

            if gender:
                pilot.gender = Gender(int(gender))

            if hometown:
                pilot.hometown = hometown

            if birth_year:
                pilot.birth_year = int(birth_year)

            if owner_id:
                try:
                    owner = User.objects.get(id=owner_id)
                    pilot.owner = owner
                except DoesNotExist:
                    flash('所属用户不存在', 'error')
                    return render_template('pilots/new.html', form=request.form, user_choices=_get_user_choices())
            elif current_user.has_role('kancho') and not current_user.has_role('gicho'):
                # 运营新建的主播默认属于自己
                pilot.owner = current_user

            if platform:
                pilot.platform = Platform(platform)

            if work_mode:
                pilot.work_mode = WorkMode(work_mode)

            if rank:
                pilot.rank = Rank(rank)

            if status:
                pilot.status = Status(status)

            # 保存主播
            pilot.save()
            flash('创建主播成功', 'success')
            logger.info('用户%s创建主播：%s', current_user.username, nickname)
            return redirect(url_for('pilot.list_pilots'))

        except (ValueError, ValidationError) as e:
            flash(f'数据验证失败：{str(e)}', 'error')
            return render_template('pilots/new.html', form=request.form, user_choices=_get_user_choices())
        except Exception as e:
            flash(f'创建失败：{str(e)}', 'error')
            logger.error('创建主播失败：%s', str(e))
            return render_template('pilots/new.html', form=request.form, user_choices=_get_user_choices())

    return render_template('pilots/new.html', user_choices=_get_user_choices())


@pilot_bp.route('/<pilot_id>/edit', methods=['GET', 'POST'])
@roles_accepted('gicho', 'kancho')
def edit_pilot(pilot_id):
    """编辑主播"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)

        # 权限检查
        if not _check_pilot_permission(pilot):
            abort(403)

        if request.method == 'POST':
            # 记录原始数据用于变更记录
            old_data = {
                'nickname': pilot.nickname,
                'real_name': pilot.real_name,
                'gender': pilot.gender.value if pilot.gender else None,
                'hometown': pilot.hometown,
                'birth_year': pilot.birth_year,
                'owner': str(pilot.owner.id) if pilot.owner else None,
                'platform': pilot.platform.value if pilot.platform else None,
                'work_mode': pilot.work_mode.value if pilot.work_mode else None,
                'rank': pilot.rank.value if pilot.rank else None,
                'status': pilot.status.value if pilot.status else None,
            }

            try:
                # 获取表单数据
                nickname = request.form.get('nickname', '').strip()
                real_name = request.form.get('real_name', '').strip() or None
                gender = request.form.get('gender')
                hometown = request.form.get('hometown', '').strip() or None
                birth_year = request.form.get('birth_year')
                owner_id = request.form.get('owner') or None
                platform = request.form.get('platform')
                work_mode = request.form.get('work_mode')
                rank = request.form.get('rank')
                status = request.form.get('status')

                # 基础验证
                if not nickname:
                    flash('昵称为必填项', 'error')
                    return render_template('pilots/edit.html', pilot=pilot, user_choices=_get_user_choices())

                # 检查昵称唯一性（排除自己）
                existing_pilot = Pilot.objects(nickname=nickname).first()
                if existing_pilot and existing_pilot.id != pilot.id:
                    flash('该昵称已存在', 'error')
                    return render_template('pilots/edit.html', pilot=pilot, user_choices=_get_user_choices())

                # 更新主播数据
                pilot.nickname = nickname
                pilot.real_name = real_name

                if gender:
                    pilot.gender = Gender(int(gender))

                pilot.hometown = hometown

                if birth_year:
                    pilot.birth_year = int(birth_year)
                else:
                    pilot.birth_year = None

                if owner_id:
                    try:
                        owner = User.objects.get(id=owner_id)
                        pilot.owner = owner
                    except DoesNotExist:
                        flash('所属用户不存在', 'error')
                        return render_template('pilots/edit.html', pilot=pilot, user_choices=_get_user_choices())
                else:
                    pilot.owner = None

                if platform:
                    pilot.platform = Platform(platform)

                if work_mode:
                    pilot.work_mode = WorkMode(work_mode)

                if rank:
                    pilot.rank = Rank(rank)

                if status:
                    pilot.status = Status(status)

                # 保存主播
                pilot.save()

                # 记录变更
                _record_changes(pilot, old_data, current_user, _get_client_ip())

                flash('更新主播成功', 'success')
                logger.info('用户%s更新主播：%s', current_user.username, nickname)
                return redirect(url_for('pilot.pilot_detail', pilot_id=pilot_id))

            except (ValueError, ValidationError) as e:
                flash(f'数据验证失败：{str(e)}', 'error')
                return render_template('pilots/edit.html', pilot=pilot, user_choices=_get_user_choices())
            except Exception as e:
                flash(f'更新失败：{str(e)}', 'error')
                logger.error('更新主播失败：%s', str(e))
                return render_template('pilots/edit.html', pilot=pilot, user_choices=_get_user_choices())

        return render_template('pilots/edit.html', pilot=pilot, user_choices=_get_user_choices())
    except DoesNotExist:
        abort(404)


@pilot_bp.route('/<pilot_id>/changes')
@roles_accepted('gicho', 'kancho')
def pilot_changes(pilot_id):
    """主播变更记录"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)

        # 权限检查
        if not _check_pilot_permission(pilot):
            abort(403)

        # 获取最近100条变更记录
        changes = PilotChangeLog.objects(pilot_id=pilot).order_by('-change_time').limit(100)

        return jsonify({
            'success':
            True,
            'changes': [{
                'field_name': change.field_display_name,
                'old_value': change.old_value,
                'new_value': change.new_value,
                'change_time': change.change_time.strftime('%Y-%m-%d %H:%M:%S'),
                'user_name': change.user_id.nickname or change.user_id.username if change.user_id else '未知用户',
                'ip_address': change.ip_address or '未知'
            } for change in changes]
        })
    except DoesNotExist:
        return jsonify({'success': False, 'error': '主播不存在'}), 404
    except Exception as e:
        logger.error('获取变更记录失败：%s', str(e))
        return jsonify({'success': False, 'error': '获取变更记录失败'}), 500


# ==================== 分成管理相关函数 ====================


def _record_commission_changes(commission, old_data, user, ip_address):
    """记录分成调整记录字段变更"""
    changes = []
    field_mapping = {
        'adjustment_date': commission.adjustment_date.strftime('%Y-%m-%d') if commission.adjustment_date else None,
        'commission_rate': commission.commission_rate,
        'remark': commission.remark,
        'is_active': commission.is_active,
    }

    for field_name, new_value in field_mapping.items():
        old_value = old_data.get(field_name)
        if str(old_value) != str(new_value):
            change_log = PilotCommissionChangeLog(commission_id=commission,
                                                  user_id=user,
                                                  field_name=field_name,
                                                  old_value=str(old_value) if old_value is not None else '',
                                                  new_value=str(new_value) if new_value is not None else '',
                                                  ip_address=ip_address)
            changes.append(change_log)

    if changes:
        PilotCommissionChangeLog.objects.insert(changes)
        logger.info('记录分成调整记录变更：%s，共%d个字段', commission.pilot_id.nickname, len(changes))


def _get_pilot_current_commission_rate(pilot_id):
    """获取主播当前有效的分成比例"""
    # 获取当前UTC时间
    current_time = get_current_utc_time()

    # 查询主播的所有有效调整记录，按调整日升序排列
    commissions = PilotCommission.objects(pilot_id=pilot_id, is_active=True).order_by('adjustment_date')

    # 使用更安全的方法检查是否有记录
    commission_list = list(commissions)
    if not commission_list:
        # 如果没有记录，返回默认20%
        return 20.0, None, "默认分成比例"

    # 根据当前日期找到生效的分成记录
    # 找到调整日小于等于当前日期的最后一条记录
    effective_commission = None
    for commission in reversed(commission_list):  # 从最新记录开始查找
        if commission.adjustment_date <= current_time:
            effective_commission = commission
            break

    # 如果没有找到生效的记录（所有记录的调整日都是未来日期），返回默认值
    if effective_commission is None:
        return 20.0, None, "默认分成比例"

    return effective_commission.commission_rate, effective_commission.adjustment_date, effective_commission.remark


def _calculate_commission_distribution(commission_rate):
    """根据分成比例计算主播和公司的收入分配"""
    # 固定参数
    BASE_RATE = 50.0  # 50%
    COMPANY_RATE = 42.0  # 42%

    # 主播收入 = (分成比例/50%) * 42%
    pilot_income = (commission_rate / BASE_RATE) * COMPANY_RATE

    # 公司收入 = 42% - 主播收入
    company_income = COMPANY_RATE - pilot_income

    return {'pilot_income': pilot_income, 'company_income': company_income, 'calculation_formula': f'({commission_rate}%/50%) * 42% = {pilot_income:.1f}%'}


# ==================== 分成管理路由 ====================


@pilot_bp.route('/<pilot_id>/commission/')
@roles_accepted('gicho', 'kancho')
def pilot_commission_index(pilot_id):
    """主播分成管理页面"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)

        # 权限检查
        if not _check_pilot_permission(pilot):
            abort(403)

        # 获取当前分成信息
        current_rate, effective_date, remark = _get_pilot_current_commission_rate(pilot_id)
        calculation_info = _calculate_commission_distribution(current_rate)

        # 获取调整记录列表（按调整日降序排列）
        commissions = PilotCommission.objects(pilot_id=pilot_id).order_by('-adjustment_date')

        return render_template('pilots/commission/index.html',
                               pilot=pilot,
                               current_rate=current_rate,
                               effective_date=effective_date,
                               remark=remark,
                               calculation_info=calculation_info,
                               commissions=commissions)

    except DoesNotExist:
        abort(404)


@pilot_bp.route('/<pilot_id>/commission/new', methods=['GET', 'POST'])
@roles_accepted('gicho', 'kancho')
def pilot_commission_new(pilot_id):
    """新增分成调整记录"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)

        # 权限检查
        if not _check_pilot_permission(pilot):
            abort(403)

        if request.method == 'POST':
            try:
                # 获取表单数据
                adjustment_date_str = request.form.get('adjustment_date', '').strip()
                commission_rate_str = request.form.get('commission_rate', '').strip()
                remark = request.form.get('remark', '').strip() or None

                # 基础验证
                if not adjustment_date_str:
                    flash('调整日为必填项', 'error')
                    return render_template('pilots/commission/new.html', pilot=pilot)

                if not commission_rate_str:
                    flash('分成比例为必填项', 'error')
                    return render_template('pilots/commission/new.html', pilot=pilot)

                # 转换数据类型
                try:
                    from datetime import datetime
                    adjustment_date = datetime.strptime(adjustment_date_str, '%Y-%m-%d')
                    # 转换为UTC时间（假设输入的是GMT+8时间）
                    from utils.timezone_helper import local_to_utc
                    adjustment_date = local_to_utc(adjustment_date)
                except ValueError:
                    flash('调整日格式错误', 'error')
                    return render_template('pilots/commission/new.html', pilot=pilot)

                try:
                    commission_rate = float(commission_rate_str)
                except ValueError:
                    flash('分成比例必须是数字', 'error')
                    return render_template('pilots/commission/new.html', pilot=pilot)

                # 创建分成调整记录
                commission = PilotCommission(pilot_id=pilot, adjustment_date=adjustment_date, commission_rate=commission_rate, remark=remark)

                # 保存记录
                commission.save()

                flash('创建分成调整记录成功', 'success')
                logger.info('用户%s为主播%s创建分成调整记录：%s%%', current_user.username, pilot.nickname, commission_rate)
                return redirect(url_for('pilot.pilot_commission_index', pilot_id=pilot_id))

            except (ValueError, ValidationError) as e:
                flash(f'数据验证失败：{str(e)}', 'error')
                return render_template('pilots/commission/new.html', pilot=pilot)
            except Exception as e:
                flash(f'创建失败：{str(e)}', 'error')
                logger.error('创建分成调整记录失败：%s', str(e))
                return render_template('pilots/commission/new.html', pilot=pilot)

        return render_template('pilots/commission/new.html', pilot=pilot)

    except DoesNotExist:
        abort(404)


@pilot_bp.route('/<pilot_id>/commission/<commission_id>/edit', methods=['GET', 'POST'])
@roles_accepted('gicho', 'kancho')
def pilot_commission_edit(pilot_id, commission_id):
    """编辑分成调整记录"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)
        commission = PilotCommission.objects.get(id=commission_id, pilot_id=pilot_id)

        # 权限检查
        if not _check_pilot_permission(pilot):
            abort(403)

        if request.method == 'POST':
            # 记录原始数据用于变更记录
            old_data = {
                'adjustment_date': commission.adjustment_date.strftime('%Y-%m-%d') if commission.adjustment_date else None,
                'commission_rate': commission.commission_rate,
                'remark': commission.remark,
                'is_active': commission.is_active,
            }

            try:
                # 获取表单数据
                commission_rate = request.form.get('commission_rate')
                remark = request.form.get('remark', '').strip() or None
                is_active = request.form.get('is_active') == 'on'  # checkbox返回'on'或None

                # 验证分成比例
                if commission_rate is not None:
                    try:
                        commission_rate = float(commission_rate)
                        if not 0 <= commission_rate <= 50:
                            flash('分成比例必须在0-50之间', 'error')
                            return render_template('pilots/commission/edit.html', pilot=pilot, commission=commission)
                    except ValueError:
                        flash('分成比例必须是有效数字', 'error')
                        return render_template('pilots/commission/edit.html', pilot=pilot, commission=commission)

                # 更新数据
                if commission_rate is not None:
                    commission.commission_rate = commission_rate
                commission.remark = remark
                commission.is_active = is_active
                commission.save()

                # 记录变更
                _record_commission_changes(commission, old_data, current_user, _get_client_ip())

                flash('更新分成调整记录成功', 'success')
                logger.info('用户%s更新主播%s的分成调整记录', current_user.username, pilot.nickname)
                return redirect(url_for('pilot.pilot_commission_index', pilot_id=pilot_id))

            except Exception as e:
                flash(f'更新失败：{str(e)}', 'error')
                logger.error('更新分成调整记录失败：%s', str(e))
                return render_template('pilots/commission/edit.html', pilot=pilot, commission=commission)

        return render_template('pilots/commission/edit.html', pilot=pilot, commission=commission)

    except DoesNotExist:
        abort(404)


@pilot_bp.route('/<pilot_id>/commission/<commission_id>/delete', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def pilot_commission_delete(pilot_id, commission_id):
    """软删除分成调整记录"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)
        commission = PilotCommission.objects.get(id=commission_id, pilot_id=pilot_id)

        # 权限检查
        if not _check_pilot_permission(pilot):
            abort(403)

        # 记录原始数据用于变更记录
        old_data = {
            'adjustment_date': commission.adjustment_date.strftime('%Y-%m-%d') if commission.adjustment_date else None,
            'commission_rate': commission.commission_rate,
            'remark': commission.remark,
            'is_active': commission.is_active,
        }

        # 软删除
        commission.is_active = False
        commission.save()

        # 记录变更
        _record_commission_changes(commission, old_data, current_user, _get_client_ip())

        flash('删除分成调整记录成功', 'success')
        logger.info('用户%s软删除主播%s的分成调整记录', current_user.username, pilot.nickname)
        return redirect(url_for('pilot.pilot_commission_index', pilot_id=pilot_id))

    except DoesNotExist:
        abort(404)


@pilot_bp.route('/<pilot_id>/commission/<commission_id>/restore', methods=['POST'])
@roles_accepted('gicho', 'kancho')
def pilot_commission_restore(pilot_id, commission_id):
    """恢复软删除的分成调整记录"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)
        commission = PilotCommission.objects.get(id=commission_id, pilot_id=pilot_id)

        # 权限检查
        if not _check_pilot_permission(pilot):
            abort(403)

        # 记录原始数据用于变更记录
        old_data = {
            'adjustment_date': commission.adjustment_date.strftime('%Y-%m-%d') if commission.adjustment_date else None,
            'commission_rate': commission.commission_rate,
            'remark': commission.remark,
            'is_active': commission.is_active,
        }

        # 恢复
        commission.is_active = True
        commission.save()

        # 记录变更
        _record_commission_changes(commission, old_data, current_user, _get_client_ip())

        flash('恢复分成调整记录成功', 'success')
        logger.info('用户%s恢复主播%s的分成调整记录', current_user.username, pilot.nickname)
        return redirect(url_for('pilot.pilot_commission_index', pilot_id=pilot_id))

    except DoesNotExist:
        abort(404)


@pilot_bp.route('/<pilot_id>/commission/current')
@roles_accepted('gicho', 'kancho')
def pilot_commission_current(pilot_id):
    """获取主播当前分成信息API"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)

        # 权限检查
        if not _check_pilot_permission(pilot):
            abort(403)

        # 获取当前分成信息
        current_rate, effective_date, remark = _get_pilot_current_commission_rate(pilot_id)
        calculation_info = _calculate_commission_distribution(current_rate)

        return jsonify({
            'success': True,
            'current_rate': current_rate,
            'effective_date': effective_date.strftime('%Y-%m-%d') if effective_date else None,
            'remark': remark,
            'calculation_info': calculation_info
        })

    except DoesNotExist:
        return jsonify({'success': False, 'error': '主播不存在'}), 404
    except Exception as e:
        logger.error('获取当前分成信息失败：%s', str(e))
        return jsonify({'success': False, 'error': '获取当前分成信息失败'}), 500


@pilot_bp.route('/<pilot_id>/commission/<commission_id>/changes')
@roles_accepted('gicho', 'kancho')
def pilot_commission_changes(pilot_id, commission_id):
    """分成调整记录变更记录"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)
        commission = PilotCommission.objects.get(id=commission_id, pilot_id=pilot_id)

        # 权限检查
        if not _check_pilot_permission(pilot):
            abort(403)

        # 获取最近100条变更记录
        changes = PilotCommissionChangeLog.objects(commission_id=commission).order_by('-change_time').limit(100)

        return jsonify({
            'success':
            True,
            'changes': [{
                'field_name': change.field_display_name,
                'old_value': change.old_value,
                'new_value': change.new_value,
                'change_time': change.change_time.strftime('%Y-%m-%d %H:%M:%S'),
                'user_name': change.user_id.nickname or change.user_id.username if change.user_id else '未知用户',
                'ip_address': change.ip_address or '未知'
            } for change in changes]
        })

    except DoesNotExist:
        return jsonify({'success': False, 'error': '记录不存在'}), 404
    except Exception as e:
        logger.error('获取变更记录失败：%s', str(e))
        return jsonify({'success': False, 'error': '获取变更记录失败'}), 500
