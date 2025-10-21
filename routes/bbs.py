from flask import Blueprint, render_template
from flask_security import roles_accepted

from utils.csrf_helper import ensure_csrf_token

bbs_bp = Blueprint('bbs', __name__, url_prefix='/bbs')


@bbs_bp.route('/')
@roles_accepted('gicho', 'kancho')
def bbs_index():
    """内部BBS列表页。"""
    csrf_token = ensure_csrf_token()
    return render_template('bbs/index.html', csrf_token=csrf_token, initial_post_id=None)


@bbs_bp.route('/posts/<post_id>')
@roles_accepted('gicho', 'kancho')
def bbs_post_entry(post_id: str):
    """直接访问某帖时，仍渲染列表页并在前端打开弹窗。"""
    csrf_token = ensure_csrf_token()
    return render_template('bbs/index.html', csrf_token=csrf_token, initial_post_id=post_id)
