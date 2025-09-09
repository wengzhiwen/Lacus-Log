# pylint: disable=no-member
from datetime import datetime, timedelta

from flask import (Blueprint, abort, flash, jsonify, redirect, render_template, request, url_for)
from flask_security import current_user, roles_accepted
from mongoengine import DoesNotExist, ValidationError

from models.pilot import (Gender, Pilot, PilotChangeLog, Platform, Rank, Status, WorkMode)
from models.user import User
from utils.logging_setup import get_logger

logger = get_logger('pilot')

pilot_bp = Blueprint('pilot', __name__)


def _get_client_ip():
    """获取客户端IP地址"""
    return request.environ.get('HTTP_X_FORWARDED_FOR') or request.environ.get('REMOTE_ADDR')


def _record_changes(pilot, old_data, user, ip_address):
    """记录机师字段变更"""
    changes = []
    field_mapping = {
        'nickname': pilot.nickname,
        'real_name': pilot.real_name,
        'gender': pilot.gender.value if pilot.gender else None,
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
        logger.info('记录机师变更：%s，共%d个字段', pilot.nickname, len(changes))


def _check_pilot_permission(pilot):
    """检查用户对机师的操作权限"""
    if current_user.has_role('gicho'):
        return True
    if current_user.has_role('kancho') and pilot.owner and pilot.owner.id == current_user.id:
        return True
    return False


def _get_user_choices():
    """获取用户选择列表，按特定顺序排序"""
    users = User.objects.all()
    choices = [('', '无')]

    # 第二顺位：当前用户
    if current_user.has_role('kancho') or current_user.has_role('gicho'):
        choices.append((str(current_user.id), current_user.nickname or current_user.username))

    # 第三顺位：其他活跃舰长/议长（昵称字典顺序）
    active_users = [u for u in users if u.active and u.id != current_user.id and (u.has_role('kancho') or u.has_role('gicho'))]
    active_users.sort(key=lambda x: x.nickname or x.username)
    for user in active_users:
        choices.append((str(user.id), user.nickname or user.username))

    # 第四顺位：其他非活跃舰长/议长（昵称字典顺序，标记[阵亡]）
    inactive_users = [u for u in users if not u.active and u.id != current_user.id and (u.has_role('kancho') or u.has_role('gicho'))]
    inactive_users.sort(key=lambda x: x.nickname or x.username)
    for user in inactive_users:
        display_name = f"{user.nickname or user.username}[阵亡]"
        choices.append((str(user.id), display_name))

    return choices


@pilot_bp.route('/')
@roles_accepted('gicho', 'kancho')
def list_pilots():
    """机师列表页面"""
    # 获取筛选参数
    rank_filter = request.args.get('rank')
    status_filter = request.args.get('status')
    owner_filter = request.args.get('owner')
    days_filter = request.args.get('days', type=int)

    # 构建查询
    query = Pilot.objects

    # 权限控制：舰长只能看到自己的机师
    if current_user.has_role('kancho') and not current_user.has_role('gicho'):
        query = query.filter(owner=current_user)

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
        cutoff_date = datetime.utcnow() - timedelta(days=days_filter)
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
    """机师详情页面"""
    try:
        pilot = Pilot.objects.get(id=pilot_id)

        # 权限检查
        if not _check_pilot_permission(pilot):
            abort(403)

        return render_template('pilots/detail.html', pilot=pilot)
    except DoesNotExist:
        abort(404)


@pilot_bp.route('/new', methods=['GET', 'POST'])
@roles_accepted('gicho', 'kancho')
def new_pilot():
    """新建机师"""
    if request.method == 'POST':
        try:
            # 获取表单数据
            nickname = request.form.get('nickname', '').strip()
            real_name = request.form.get('real_name', '').strip() or None
            gender = request.form.get('gender')
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

            # 创建机师对象
            pilot = Pilot(nickname=nickname)

            if real_name:
                pilot.real_name = real_name

            if gender:
                pilot.gender = Gender(int(gender))

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
                # 舰长新建的机师默认属于自己
                pilot.owner = current_user

            if platform:
                pilot.platform = Platform(platform)

            if work_mode:
                pilot.work_mode = WorkMode(work_mode)

            if rank:
                pilot.rank = Rank(rank)

            if status:
                pilot.status = Status(status)

            # 保存机师
            pilot.save()
            flash('创建机师成功', 'success')
            logger.info('用户%s创建机师：%s', current_user.username, nickname)
            return redirect(url_for('pilot.list_pilots'))

        except (ValueError, ValidationError) as e:
            flash(f'数据验证失败：{str(e)}', 'error')
            return render_template('pilots/new.html', form=request.form, user_choices=_get_user_choices())
        except Exception as e:
            flash(f'创建失败：{str(e)}', 'error')
            logger.error('创建机师失败：%s', str(e))
            return render_template('pilots/new.html', form=request.form, user_choices=_get_user_choices())

    return render_template('pilots/new.html', user_choices=_get_user_choices())


@pilot_bp.route('/<pilot_id>/edit', methods=['GET', 'POST'])
@roles_accepted('gicho', 'kancho')
def edit_pilot(pilot_id):
    """编辑机师"""
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

                # 更新机师数据
                pilot.nickname = nickname
                pilot.real_name = real_name

                if gender:
                    pilot.gender = Gender(int(gender))

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

                # 保存机师
                pilot.save()

                # 记录变更
                _record_changes(pilot, old_data, current_user, _get_client_ip())

                flash('更新机师成功', 'success')
                logger.info('用户%s更新机师：%s', current_user.username, nickname)
                return redirect(url_for('pilot.pilot_detail', pilot_id=pilot_id))

            except (ValueError, ValidationError) as e:
                flash(f'数据验证失败：{str(e)}', 'error')
                return render_template('pilots/edit.html', pilot=pilot, user_choices=_get_user_choices())
            except Exception as e:
                flash(f'更新失败：{str(e)}', 'error')
                logger.error('更新机师失败：%s', str(e))
                return render_template('pilots/edit.html', pilot=pilot, user_choices=_get_user_choices())

        return render_template('pilots/edit.html', pilot=pilot, user_choices=_get_user_choices())
    except DoesNotExist:
        abort(404)


@pilot_bp.route('/<pilot_id>/changes')
@roles_accepted('gicho', 'kancho')
def pilot_changes(pilot_id):
    """机师变更记录"""
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
        return jsonify({'success': False, 'error': '机师不存在'}), 404
    except Exception as e:
        logger.error('获取变更记录失败：%s', str(e))
        return jsonify({'success': False, 'error': '获取变更记录失败'}), 500
