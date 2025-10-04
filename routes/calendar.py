# pylint: disable=no-member

from flask import Blueprint, render_template
from flask_login import login_required
from flask_security import current_user, roles_accepted

from utils.logging_setup import get_logger

logger = get_logger('calendar')

calendar_bp = Blueprint('calendar', __name__)


@calendar_bp.route('/')
@login_required
@roles_accepted('gicho', 'kancho')
def index():
    """日历主页，默认进入周视图"""
    logger.debug('用户进入通告日历：%s', getattr(current_user, 'username', 'anonymous'))
    return render_template('calendar/week.html')


@calendar_bp.route('/month')
@login_required
@roles_accepted('gicho', 'kancho')
def month_view():
    """月视图"""
    return render_template('calendar/month.html')


@calendar_bp.route('/week')
@login_required
@roles_accepted('gicho', 'kancho')
def week_view():
    """周视图"""
    return render_template('calendar/week.html')


@calendar_bp.route('/day')
@login_required
@roles_accepted('gicho', 'kancho')
def day_view():
    """日视图"""
    return render_template('calendar/day.html')
