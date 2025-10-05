import os
from datetime import datetime, timedelta

from dotenv import load_dotenv
from flask import Flask
from flask_wtf import CSRFProtect
from mongoengine import connect

from routes.admin import admin_bp
from routes.announcement import announcement_bp
from routes.announcements_api import announcements_api_bp
from routes.battle_area import battle_area_bp
from routes.battle_areas_api import battle_areas_api_bp
from routes.battle_record import battle_record_bp
from routes.battle_records_api import battle_records_api_bp
from routes.calendar import calendar_bp
from routes.calendar_api import calendar_api_bp
from routes.commissions_api import commissions_api_bp
from routes.main import main_bp
from routes.pilot import pilot_bp
from routes.pilots_api import pilots_api_bp
from routes.recruit import recruit_bp
from routes.recruit_reports_api import recruit_reports_api_bp
from routes.recruits_api import recruits_api_bp
from routes.report import report_bp
from routes.reports_api import reports_api_bp
from routes.report_mail import report_mail_bp
from routes.users_api import users_api_bp
from utils.bootstrap import (ensure_database_indexes, ensure_initial_roles_and_admin)
from utils.logging_setup import init_logging
from utils.scheduler import init_scheduled_jobs
from utils.security import create_user_datastore, init_security
from utils.timezone_helper import (format_local_date, format_local_datetime, format_local_time, get_local_date_for_input, get_local_datetime_for_input,
                                   get_local_time_for_input, utc_to_local)


def create_app() -> Flask:
    """Flask 应用工厂：加载配置、初始化日志与数据库、注册蓝图与安全组件。"""
    load_dotenv()

    init_logging()

    flask_app = Flask(__name__, template_folder="templates", static_folder="static")

    flask_app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')
    flask_app.config['SECURITY_PASSWORD_SALT'] = os.getenv('SECURITY_PASSWORD_SALT', 'dev-password-salt')
    flask_app.config['SECURITY_REMEMBER_SALT'] = os.getenv('SECURITY_REMEMBER_SALT', 'dev-remember-salt')
    flask_app.config['SECURITY_DEFAULT_REMEMBER_ME'] = os.getenv('SECURITY_DEFAULT_REMEMBER_ME', 'True') == 'True'
    lifetime = int(os.getenv('PERMANENT_SESSION_LIFETIME', '36000'))
    flask_app.permanent_session_lifetime = timedelta(seconds=lifetime)

    flask_app.config.update(
        SECURITY_REGISTERABLE=False,  # 禁止自注册
        SECURITY_RECOVERABLE=False,  # 未启用邮件找回
        SECURITY_CHANGEABLE=True,  # 允许登录后修改密码
        SECURITY_TRACKABLE=True,  # 记录登录时间
        SECURITY_CONFIRMABLE=False,  # 未启用邮箱确认
        SECURITY_USERNAME_ENABLE=True,  # 启用用户名登录字段（需 bleach）
        SECURITY_EMAIL_REQUIRED=False,  # 不要求邮箱
        SECURITY_PASSWORD_HASH='pbkdf2_sha512',  # 避免对外部加密库的额外依赖
        WTF_CSRF_ENABLED=True,
        SECURITY_FLASH_MESSAGES=True,
        SECURITY_ROLES_ENABLED=True,  # 启用角色功能
        SECURITY_CHANGE_PASSWORD_TEMPLATE='security/change_password.html',
        SECURITY_POST_CHANGE_VIEW='/',  # 修改密码后重定向到首页
        SECURITY_MSG_INVALID_PASSWORD=("用户名或密码错误", "error"),
        SECURITY_MSG_INVALID_USERNAME=("用户名或密码错误", "error"),
        SECURITY_MSG_USER_DOES_NOT_EXIST=("用户名或密码错误", "error"),
        SECURITY_MSG_DISABLED_ACCOUNT=("账户已停用", "error"),
        SECURITY_POST_LOGIN_VIEW='/',
        SECURITY_POST_LOGOUT_VIEW='/login',
    )

    mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://127.0.0.1:27017/lacus')
    try:
        connect(host=mongodb_uri, uuidRepresentation='standard')
        flask_app.logger.info('MongoDB 连接成功：%s', mongodb_uri)
    except Exception as exc:
        flask_app.logger.error('MongoDB 连接失败：%s', exc)
        raise

    try:
        from utils.job_token import JobPlan
        JobPlan.objects.delete()  # type: ignore[attr-defined]  # pylint: disable=no-member
        flask_app.logger.info('已清空所有已存在的任务计划令牌')
    except Exception as exc:  # pylint: disable=broad-except
        flask_app.logger.error('清空任务计划令牌失败：%s', exc)

    CSRFProtect(flask_app)

    user_datastore = create_user_datastore()
    _security = init_security(flask_app, user_datastore)

    flask_app.register_blueprint(main_bp)
    flask_app.register_blueprint(admin_bp, url_prefix='/admin')
    flask_app.register_blueprint(users_api_bp)
    flask_app.register_blueprint(pilots_api_bp)
    flask_app.register_blueprint(commissions_api_bp)
    flask_app.register_blueprint(recruits_api_bp)
    flask_app.register_blueprint(recruit_reports_api_bp)
    flask_app.register_blueprint(announcements_api_bp)
    flask_app.register_blueprint(battle_areas_api_bp)
    flask_app.register_blueprint(pilot_bp, url_prefix='/pilots')
    flask_app.register_blueprint(recruit_bp, url_prefix='/recruits')
    flask_app.register_blueprint(battle_area_bp, url_prefix='/areas')
    flask_app.register_blueprint(announcement_bp, url_prefix='/announcements')
    flask_app.register_blueprint(battle_records_api_bp, url_prefix='/battle-records/api')
    flask_app.register_blueprint(battle_record_bp, url_prefix='/battle-records')
    flask_app.register_blueprint(calendar_api_bp, url_prefix='/calendar/api')
    flask_app.register_blueprint(calendar_bp, url_prefix='/calendar')
    flask_app.register_blueprint(reports_api_bp, url_prefix='/reports/api')
    flask_app.register_blueprint(report_bp, url_prefix='/reports')
    flask_app.register_blueprint(report_mail_bp, url_prefix='/reports')

    @flask_app.template_filter('role_display_name')
    def role_display_name(role_name):
        """将角色英文代码转换为中文显示名称"""
        role_mapping = {'gicho': '管理员', 'kancho': '运营'}
        return role_mapping.get(role_name, role_name)

    @flask_app.template_filter('roles_display_names')
    def roles_display_names(roles):
        """将角色列表转换为中文显示名称列表"""
        role_mapping = {'gicho': '管理员', 'kancho': '运营'}
        if isinstance(roles, list):
            return [role_mapping.get(role.name if hasattr(role, 'name') else role, role.name if hasattr(role, 'name') else role) for role in roles]
        return [role_mapping.get(roles, roles)]

    @flask_app.template_filter('local_datetime')
    def local_datetime_filter(utc_dt, format_str='%Y年%m月%d日 %H:%M'):
        """将UTC时间转换为GMT+8时间并格式化"""
        return format_local_datetime(utc_dt, format_str)

    @flask_app.template_filter('local_date')
    def local_date_filter(utc_dt, format_str='%Y-%m-%d'):
        """将UTC时间转换为GMT+8日期并格式化"""
        return format_local_date(utc_dt, format_str)

    @flask_app.template_filter('local_time')
    def local_time_filter(utc_dt, format_str='%H:%M'):
        """将UTC时间转换为GMT+8时间并格式化"""
        return format_local_time(utc_dt, format_str)

    @flask_app.template_filter('local_datetime_for_input')
    def local_datetime_for_input_filter(utc_dt):
        """将UTC时间转换为适合HTML datetime-local输入框的格式"""
        return get_local_datetime_for_input(utc_dt)

    @flask_app.context_processor
    def inject_template_vars():
        return {'datetime': datetime, 'timedelta': timedelta}

    @flask_app.template_filter('local_date_for_input')
    def local_date_for_input_filter(utc_dt):
        """将UTC时间转换为适合HTML date输入框的格式"""
        return get_local_date_for_input(utc_dt)

    @flask_app.template_filter('utc_to_local')
    def utc_to_local_filter(utc_dt):
        """将UTC时间转换为GMT+8时间"""
        return utc_to_local(utc_dt)

    @flask_app.template_filter('local_time_for_input')
    def local_time_for_input_filter(utc_dt):
        """将UTC时间转换为适合HTML time输入框的格式"""
        return get_local_time_for_input(utc_dt)

    @flask_app.template_filter('normalize_rank')
    def normalize_rank_filter(rank_value):
        """将主播分类旧用语转换为新用语显示"""
        rank_mapping = {
            '候补机师': '候选人',
            '训练机师': '试播主播',
            '实习机师': '实习主播',
            '正式机师': '正式主播',
        }
        return rank_mapping.get(rank_value, rank_value)

    @flask_app.template_filter('normalize_status')
    def normalize_status_filter(status_value):
        """将主播状态旧用语转换为新用语显示"""
        status_mapping = {
            '未征召': '未招募',
            '不征召': '不招募',
            '已征召': '已招募',
            '已阵亡': '流失',
        }
        return status_mapping.get(status_value, status_value)

    def _render_500(error):
        """统一记录并渲染 500 错误页面。"""
        from flask import render_template, request
        logger = flask_app.logger

        logger.error("500内部服务器错误: %s", str(error), exc_info=True)
        logger.error("请求URL: %s", request.url)
        logger.error("请求方法: %s", request.method)
        logger.error("用户代理: %s", request.headers.get('User-Agent', 'Unknown'))
        logger.error("客户端IP: %s", request.remote_addr)

        return render_template('errors/500.html'), 500

    @flask_app.errorhandler(500)
    def handle_500_error(error):
        """处理500内部服务器错误（框架转换后的 HTTP 500）。"""
        return _render_500(error)

    @flask_app.errorhandler(Exception)
    def handle_uncaught_exception(error):  # pylint: disable=unused-argument
        """兜底的未捕获异常处理，确保所有 500 都被记录。"""
        return _render_500(error)

    @flask_app.errorhandler(404)
    def handle_404_error(_error):
        """处理404页面未找到错误"""
        from flask import request
        logger = flask_app.logger
        logger.warning("404页面未找到: %s", request.url)
        from flask import render_template
        return render_template('errors/404.html'), 404

    @flask_app.errorhandler(403)
    def handle_403_error(_error):
        """处理403禁止访问错误"""
        from flask import request
        logger = flask_app.logger
        logger.warning("403禁止访问: %s", request.url)
        from flask import render_template
        return render_template('errors/403.html'), 403

    with flask_app.app_context():
        ensure_database_indexes()
        ensure_initial_roles_and_admin(user_datastore)

    # 说明：生产多进程/多实例部署时，应仅在“领导实例”启用该开关，避免重复触发任务
    enable_scheduler = os.getenv('ENABLE_SCHEDULER', 'false').lower() == 'true'
    is_dev = os.getenv('FLASK_ENV', '').lower() == 'development'
    is_reloader_main = os.environ.get('WERKZEUG_RUN_MAIN') == 'true'

    if not enable_scheduler:
        flask_app.logger.info('ENABLE_SCHEDULER=false，跳过启动内置定时任务')
    else:
        if (not is_dev) or (is_dev and is_reloader_main):
            try:
                init_scheduled_jobs(flask_app)
            except Exception as exc:
                flask_app.logger.error('初始化定时任务失败：%s', exc)
        else:
            flask_app.logger.info('开发环境下的首次加载，跳过调度器启动（等待重载主进程）')

    return flask_app


app = create_app()


def run_dev() -> None:
    """开发环境启动入口。

    仅用于本地调试，不用于生产环境。
    """
    port = int(os.getenv('FLASK_APP_PORT', '5080'))
    is_debug = os.getenv('LOG_LEVEL', 'DEBUG') == 'DEBUG'
    host_ip = "127.0.0.1"
    if is_debug:
        host_ip = "0.0.0.0"

    app.logger.info('以开发模式启动，监听端口：%s，IP地址：%s', port, host_ip)
    app.run(host=host_ip, port=port, debug=is_debug, use_reloader=True)


if __name__ == '__main__':
    run_dev()
