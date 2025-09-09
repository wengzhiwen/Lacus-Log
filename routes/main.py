from flask import Blueprint, render_template, request, flash, redirect, url_for
from flask_login import login_required
from flask_security import current_user
from flask_security.utils import hash_password

from utils.logging_setup import get_logger

logger = get_logger('main')

main_bp = Blueprint('main', __name__)


@main_bp.route('/')
@login_required
def home():
    """用户首页（移动端优先）。"""
    logger.debug('用户进入首页：%s', getattr(current_user, 'username', 'anonymous'))
    return render_template('index.html')


@main_bp.route('/change-password', methods=['GET', 'POST'])
@login_required
def change_password():
    """修改密码页面（自定义实现）。"""
    if request.method == 'POST':
        current_password = request.form.get('password', '').strip()
        new_password = request.form.get('new_password', '').strip()
        confirm_password = request.form.get('new_password_confirm', '').strip()
        
        # 验证输入
        if not current_password or not new_password or not confirm_password:
            flash('所有字段都是必填的', 'error')
            return render_template('security/change_password.html')
        
        if new_password != confirm_password:
            flash('新密码和确认密码不匹配', 'error')
            return render_template('security/change_password.html')
        
        if len(new_password) < 6:
            flash('新密码长度至少6个字符', 'error')
            return render_template('security/change_password.html')
        
        # 验证当前密码
        if not current_user.verify_and_update_password(current_password):
            flash('当前密码错误', 'error')
            return render_template('security/change_password.html')
        
        # 更新密码
        current_user.password = hash_password(new_password)
        current_user.save()
        
        flash('密码修改成功', 'success')
        logger.info('用户修改密码：%s', current_user.username)
        return redirect(url_for('main.home'))
    
    return render_template('security/change_password.html')
