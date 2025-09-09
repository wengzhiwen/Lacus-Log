# pylint: disable=no-member
from flask import (Blueprint, abort, flash, redirect, render_template, request, url_for)
from flask_security import current_user, roles_accepted
from mongoengine import DoesNotExist, ValidationError

from models.battle_area import Availability, BattleArea
from utils.logging_setup import get_logger

logger = get_logger('battle_area')

battle_area_bp = Blueprint('battle_area', __name__)


@battle_area_bp.route('/')
@roles_accepted('gicho')
def list_areas():
    """战斗区域列表（仅议长可访问）"""
    x_filter = request.args.get('x')
    y_filter = request.args.get('y')
    availability_filter = request.args.get('availability')

    query = BattleArea.objects

    if x_filter:
        query = query.filter(x_coord=x_filter)
    if y_filter:
        query = query.filter(y_coord=y_filter)
    if availability_filter:
        try:
            query = query.filter(availability=Availability(availability_filter))
        except ValueError:
            pass

    # 排序：X、Y、Z 字典序
    areas = query.order_by('x_coord', 'y_coord', 'z_coord').all()

    # 提供筛选选项（去重）
    x_choices = sorted(list(set([a.x_coord for a in BattleArea.objects.only('x_coord').all()])))
    if x_filter:
        y_choices = sorted(list(set([a.y_coord for a in BattleArea.objects(x_coord=x_filter).only('y_coord').all()])))
    else:
        y_choices = sorted(list(set([a.y_coord for a in BattleArea.objects.only('y_coord').all()])))

    return render_template('areas/list.html',
                           areas=areas,
                           x_filter=x_filter,
                           y_filter=y_filter,
                           availability_filter=availability_filter,
                           x_choices=x_choices,
                           y_choices=y_choices,
                           availability_choices=[(a.value, a.value) for a in Availability])


@battle_area_bp.route('/<area_id>')
@roles_accepted('gicho')
def area_detail(area_id):
    """战斗区域详情（仅议长）"""
    try:
        area = BattleArea.objects.get(id=area_id)
        return render_template('areas/detail.html', area=area)
    except DoesNotExist:
        abort(404)


@battle_area_bp.route('/new', methods=['GET', 'POST'])
@roles_accepted('gicho')
def new_area():
    """新建战斗区域（仅议长）"""
    if request.method == 'POST':
        try:
            x_coord = (request.form.get('x_coord') or '').strip()
            y_coord = (request.form.get('y_coord') or '').strip()
            z_coord = (request.form.get('z_coord') or '').strip()
            availability = request.form.get('availability') or Availability.ENABLED.value

            if not x_coord or not y_coord or not z_coord:
                flash('X/Y/Z 坐标均为必填', 'error')
                return render_template('areas/new.html', form=request.form)

            area = BattleArea(x_coord=x_coord, y_coord=y_coord, z_coord=z_coord)
            if availability:
                try:
                    area.availability = Availability(availability)
                except ValueError:
                    pass
            area.save()
            logger.info('用户%s创建战斗区域：%s-%s-%s', current_user.username, x_coord, y_coord, z_coord)
            flash('创建战斗区域成功', 'success')
            return redirect(url_for('battle_area.list_areas'))
        except (ValidationError, ValueError) as e:
            flash(f'数据验证失败：{str(e)}', 'error')
            return render_template('areas/new.html', form=request.form)
        except Exception as e:
            logger.error('创建战斗区域失败：%s', str(e))
            flash(f'创建失败：{str(e)}', 'error')
            return render_template('areas/new.html', form=request.form)

    return render_template('areas/new.html')


@battle_area_bp.route('/<area_id>/edit', methods=['GET', 'POST'])
@roles_accepted('gicho')
def edit_area(area_id):
    """编辑战斗区域（仅议长）"""
    try:
        area = BattleArea.objects.get(id=area_id)
        if request.method == 'POST':
            x_coord = (request.form.get('x_coord') or '').strip()
            y_coord = (request.form.get('y_coord') or '').strip()
            z_coord = (request.form.get('z_coord') or '').strip()
            availability = request.form.get('availability')

            if not x_coord or not y_coord or not z_coord:
                flash('X/Y/Z 坐标均为必填', 'error')
                return render_template('areas/edit.html', area=area)

            # 检查是否与其他记录冲突
            existing = BattleArea.objects(x_coord=x_coord, y_coord=y_coord, z_coord=z_coord).first()
            if existing and existing.id != area.id:
                flash('同一 X+Y+Z 的战斗区域已存在', 'error')
                return render_template('areas/edit.html', area=area)

            area.x_coord = x_coord
            area.y_coord = y_coord
            area.z_coord = z_coord
            if availability:
                try:
                    area.availability = Availability(availability)
                except ValueError:
                    pass

            area.save()
            logger.info('用户%s更新战斗区域：%s-%s-%s', current_user.username, x_coord, y_coord, z_coord)
            flash('更新战斗区域成功', 'success')
            return redirect(url_for('battle_area.area_detail', area_id=area.id))

        return render_template('areas/edit.html', area=area)
    except DoesNotExist:
        abort(404)
    except Exception as e:
        logger.error('编辑战斗区域失败：%s', str(e))
        abort(500)


@battle_area_bp.route('/<area_id>/generate', methods=['GET', 'POST'])
@roles_accepted('gicho')
def generate_areas(area_id):
    """批量生成战斗区域（仅议长）

    输入：源战斗区域 X/Y（不可编辑），Z起始、Z结束（数字）
    步骤：校验 -> 预检查重复 -> 批量保存 -> 显示结果
    """
    try:
        src = BattleArea.objects.get(id=area_id)
    except DoesNotExist:
        abort(404)

    if request.method == 'POST':
        start_str = (request.form.get('z_start') or '').strip()
        end_str = (request.form.get('z_end') or '').strip()

        # 校验为数字
        if not start_str.isdigit() or not end_str.isdigit():
            flash('Z坐标开始与结束必须是数字', 'error')
            return render_template('areas/generate.html', src=src)

        z_start = int(start_str)
        z_end = int(end_str)
        if z_start >= z_end:
            flash('Z坐标开始必须小于结束', 'error')
            return render_template('areas/generate.html', src=src)

        # 构建生成列表
        will_create = []
        for z in range(z_start, z_end + 1):
            will_create.append({'x': src.x_coord, 'y': src.y_coord, 'z': str(z)})

        # 检查重复
        duplicates = []
        for item in will_create:
            if BattleArea.objects(x_coord=item['x'], y_coord=item['y'], z_coord=item['z']).first():
                duplicates.append(item)

        if duplicates:
            flash('存在已存在的区域，未执行生成', 'error')
            return render_template('areas/generate.html', src=src, duplicates=duplicates)

        # 批量保存
        created = []
        for item in will_create:
            area = BattleArea(x_coord=item['x'], y_coord=item['y'], z_coord=item['z'], availability=Availability.ENABLED)
            area.save()
            created.append(area)

        logger.info('用户%s批量创建战斗区域：%s-%s Z=%s..%s 共%d个', current_user.username, src.x_coord, src.y_coord, z_start, z_end, len(created))
        flash('批量生成成功', 'success')
        return render_template('areas/generate_result.html', src=src, created=created)

    return render_template('areas/generate.html', src=src)
