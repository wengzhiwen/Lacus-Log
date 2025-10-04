# pylint: disable=no-member
from flask import Blueprint, render_template, request
from flask_security import roles_accepted

battle_area_bp = Blueprint('battle_area', __name__)


@battle_area_bp.route('/')
@roles_accepted('gicho')
def list_areas():
    """开播地点列表页面（仅管理员）。数据由前端调用 REST 接口加载。"""
    return render_template('areas/list.html')


@battle_area_bp.route('/<area_id>')
@roles_accepted('gicho')
def area_detail(area_id):
    """开播地点详情页面（仅管理员）。数据由前端调用 REST 接口加载。"""
    return render_template('areas/detail.html', area_id=area_id)


@battle_area_bp.route('/new', methods=['GET'])
@roles_accepted('gicho')
def new_area():
    """开播地点创建页面（仅管理员）。提交通过 REST 接口完成。"""
    return render_template('areas/new.html')


@battle_area_bp.route('/<area_id>/edit', methods=['GET'])
@roles_accepted('gicho')
def edit_area(area_id):
    """开播地点编辑页面（仅管理员）。数据加载与提交由 REST 接口处理。"""
    return render_template('areas/edit.html', area_id=area_id)


@battle_area_bp.route('/<area_id>/generate', methods=['GET'])
@roles_accepted('gicho')
def generate_areas(area_id):
    """批量生成开播地点页面（仅管理员）。生成结果通过 REST 接口取得。"""
    result_mode = request.args.get('result') == '1'
    template_name = 'areas/generate_result.html' if result_mode else 'areas/generate.html'
    return render_template(template_name, area_id=area_id)
