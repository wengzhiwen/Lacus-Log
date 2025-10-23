# pylint: disable=no-member

from datetime import datetime
from typing import Dict, Optional, Tuple

from flask import (Blueprint, flash, jsonify, redirect, render_template, request, url_for)
from flask_login import login_required
from flask_security import current_user
from flask_security.utils import hash_password

from routes.report import (build_dashboard_feature_banner, calculate_dashboard_announcement_metrics, calculate_dashboard_battle_metrics,
                           calculate_dashboard_conversion_rate_metrics, calculate_dashboard_pilot_ranking_metrics, calculate_dashboard_recruit_metrics)
from utils.dashboard_serializers import create_success_response
from utils.jwt_roles import jwt_roles_accepted
from utils.logging_setup import get_logger
from utils.timezone_helper import format_local_datetime
from models.bbs import BBSPost, BBSPostStatus, BBSReply, BBSReplyStatus

logger = get_logger('main')

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
@login_required
def home():
    """用户首页（移动端优先）。
    
    注意：页面中的API请求使用JWT认证。
    用户通过传统表单登录后，前端会调用REST API登录以获取JWT token。
    """
    logger.debug('用户进入首页：%s', getattr(current_user, 'username', 'anonymous'))
    return render_template('dashboard/index.html')


@main_bp.route('/api/dashboard/recruit', methods=['GET'])
@jwt_roles_accepted("gicho", "kancho")
def dashboard_recruit_data():
    """仪表盘招募统计接口。"""
    data = calculate_dashboard_recruit_metrics()
    meta = {'segment': 'recruit', 'link': url_for('report.recruit_daily_report')}
    return jsonify(create_success_response(data, meta))


@main_bp.route('/api/dashboard/announcements', methods=['GET'])
@jwt_roles_accepted("gicho", "kancho")
def dashboard_announcement_data():
    """仪表盘通告统计接口。"""
    data = calculate_dashboard_announcement_metrics()
    meta = {'segment': 'announcement', 'link': url_for('calendar.day_view')}
    return jsonify(create_success_response(data, meta))


@main_bp.route('/api/dashboard/battle-records', methods=['GET'])
@jwt_roles_accepted("gicho", "kancho")
def dashboard_battle_data():
    """仪表盘开播记录统计接口。"""
    data = calculate_dashboard_battle_metrics()
    meta = {'segment': 'battle', 'link': url_for('report.daily_report')}
    return jsonify(create_success_response(data, meta))


@main_bp.route('/api/dashboard/feature', methods=['GET'])
@jwt_roles_accepted("gicho", "kancho")
def dashboard_feature_data():
    """仪表盘横幅展示接口。"""
    data = build_dashboard_feature_banner()
    meta = {'segment': 'feature'}
    return jsonify(create_success_response(data, meta))


def _dashboard_user_can_view_post(user, post: BBSPost) -> bool:
    if post.status == BBSPostStatus.PUBLISHED:
        return True
    if not user:
        return False
    if user.has_role('gicho'):
        return True
    if post.author and str(post.author.id) == str(user.id):
        return True
    return False


def _resolve_last_activity(post: BBSPost) -> Tuple[str, Optional[datetime]]:
    """获取帖子最后一次活跃的作者昵称与时间。"""
    reply = (BBSReply.objects(post=post, status=BBSReplyStatus.PUBLISHED).only('author_snapshot',
                                                                               'created_at').order_by('-created_at').first())  # type: ignore[attr-defined]
    if reply:
        snapshot = reply.author_snapshot or {}
        display_name = snapshot.get('nickname') or snapshot.get('display_name') or snapshot.get('username') or '--'
        return display_name, reply.created_at

    snapshot = post.author_snapshot or {}
    display_name = snapshot.get('nickname') or snapshot.get('display_name') or snapshot.get('username') or '--'
    return display_name, post.created_at or post.last_active_at


def _build_last_activity_meta(post: BBSPost) -> Dict[str, Optional[str]]:
    """构建最后更新展示信息。"""
    operator_name, timestamp = _resolve_last_activity(post)
    operator_display = operator_name if operator_name and operator_name != '--' else ''
    display_time = format_local_datetime(timestamp, '%Y-%m-%d %H:%M') if timestamp else ''
    time_iso = timestamp.isoformat() if timestamp else None
    if operator_display and display_time:
        display_text = f"{operator_display}（{display_time}）"
    elif operator_display:
        display_text = operator_display
    elif display_time:
        display_text = display_time
    else:
        display_text = '--'
    return {
        'operator': operator_name,
        'time': time_iso,
        'time_display': display_time,
        'display': display_text,
    }


@main_bp.route('/api/dashboard/bbs-latest', methods=['GET'])
@jwt_roles_accepted("gicho", "kancho")
def dashboard_bbs_latest_data():
    """仪表盘内部BBS最新主贴。"""
    query = (BBSPost.objects.only('title', 'board', 'status', 'author', 'author_snapshot', 'created_at',
                                  'last_active_at').order_by('-last_active_at'))  # type: ignore[attr-defined]
    items = []
    for post in query[:50]:
        if not _dashboard_user_can_view_post(current_user, post):
            continue
        board_name = post.board.name if getattr(post, 'board', None) else ''
        item = {
            'id': str(post.id),
            'title': post.title or '',
            'board': board_name,
        }
        last_activity = _build_last_activity_meta(post)
        item['last_activity'] = last_activity
        items.append(item)
        if len(items) >= 5:
            break

    data = {'items': items, 'generated_at': datetime.utcnow().isoformat()}
    meta = {'segment': 'bbs_latest', 'link': url_for('bbs.bbs_index')}
    return jsonify(create_success_response(data, meta))


@main_bp.route('/api/dashboard/conversion-rate', methods=['GET'])
@jwt_roles_accepted("gicho", "kancho")
def dashboard_conversion_rate_data():
    """仪表盘底薪流水转化率统计接口。"""
    data = calculate_dashboard_conversion_rate_metrics()
    meta = {'segment': 'conversion_rate', 'link': url_for('new_report_fast.monthly_report_fast', mode='offline')}
    return jsonify(create_success_response(data, meta))


@main_bp.route('/api/dashboard/pilot-ranking', methods=['GET'])
@jwt_roles_accepted("gicho", "kancho")
def dashboard_pilot_ranking_data():
    """仪表盘昨日主播排名统计接口。"""
    data = calculate_dashboard_pilot_ranking_metrics()
    meta = {'segment': 'pilot_ranking'}
    return jsonify(create_success_response(data, meta))


@main_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """修改密码页面（自定义实现）。"""
    if request.method == 'POST':
        current_password = request.form.get('password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('new_password_confirm', '').strip()

        if not current_password or not new_password or not confirm_password:
            flash('所有字段都是必填的', 'error')
            return render_template('security/change_password.html')

        if new_password != confirm_password:
            flash('新密码和确认密码不匹配', 'error')
            return render_template('security/change_password.html')

        if len(new_password) < 6:
            flash('新密码长度至少6个字符', 'error')
            return render_template('security/change_password.html')

        if not current_user.verify_and_update_password(current_password):
            flash('当前密码错误', 'error')
            return render_template('security/change_password.html')

        current_user.password = hash_password(new_password)
        current_user.save()

        flash('密码修改成功', 'success')
        logger.info('用户修改密码：%s', current_user.username)
        return redirect(url_for('main.home'))

    return render_template('security/change_password.html')
