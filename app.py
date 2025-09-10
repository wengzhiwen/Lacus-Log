import os
from datetime import timedelta

from dotenv import load_dotenv
from flask import Flask
from flask_wtf import CSRFProtect
from mongoengine import connect

from routes.admin import admin_bp
from routes.announcement import announcement_bp
from routes.battle_area import battle_area_bp
from routes.main import main_bp
from routes.pilot import pilot_bp
from utils.bootstrap import ensure_initial_roles_and_admin
from utils.logging_setup import init_logging
from utils.security import create_user_datastore, init_security


def create_app() -> Flask:
    """Flask应用工厂。

    - 读取环境变量
    - 初始化日志
    - 连接MongoDB
    - 配置Flask-Security-Too
    - 注册蓝图
    - 创建默认角色与默认议长
    """
    # 读取 .env
    load_dotenv()

    # 初始化日志（最早进行，便于后续记录）
    init_logging()

    flask_app = Flask(__name__, template_folder="templates", static_folder="static")

    # 基础配置
    flask_app.config['SECRET_KEY'] = os.getenv('SECRET_KEY') or os.getenv('FLASK_SECRET_KEY', 'dev-secret-key')
    flask_app.config['SECURITY_PASSWORD_SALT'] = os.getenv('SECURITY_PASSWORD_SALT', 'dev-password-salt')
    flask_app.config['SECURITY_REMEMBER_SALT'] = os.getenv('SECURITY_REMEMBER_SALT', 'dev-remember-salt')
    flask_app.config['SECURITY_DEFAULT_REMEMBER_ME'] = os.getenv('SECURITY_DEFAULT_REMEMBER_ME', 'True') == 'True'
    # 会话时长
    lifetime = int(os.getenv('PERMANENT_SESSION_LIFETIME', '36000'))
    flask_app.permanent_session_lifetime = timedelta(seconds=lifetime)

    # Flask-Security-Too 配置（仅启用必须项）
    flask_app.config.update(
        SECURITY_REGISTERABLE=False,  # 禁止自注册
        SECURITY_RECOVERABLE=False,  # 本期不启用邮件找回流程
        SECURITY_CHANGEABLE=True,  # 允许登录后修改密码
        SECURITY_TRACKABLE=True,  # 记录登录时间
        SECURITY_CONFIRMABLE=False,  # 本期不启用邮箱确认
        SECURITY_USERNAME_ENABLE=True,  # 启用用户名登录字段（需 bleach）
        SECURITY_EMAIL_REQUIRED=False,  # 不要求邮箱
        SECURITY_PASSWORD_HASH='pbkdf2_sha512',  # 避免对外部加密库的额外依赖
        WTF_CSRF_ENABLED=True,
        SECURITY_FLASH_MESSAGES=True,
        # 角色相关配置
        SECURITY_ROLES_ENABLED=True,  # 启用角色功能
        # 修改密码相关配置
        SECURITY_CHANGE_PASSWORD_TEMPLATE='security/change_password.html',
        SECURITY_POST_CHANGE_VIEW='/',  # 修改密码后重定向到首页
        # 登录失败与账户状态提示（中文）
        SECURITY_MSG_INVALID_PASSWORD=("用户名或密码错误", "error"),
        SECURITY_MSG_INVALID_USERNAME=("用户名或密码错误", "error"),
        SECURITY_MSG_USER_DOES_NOT_EXIST=("用户名或密码错误", "error"),
        SECURITY_MSG_DISABLED_ACCOUNT=("账户已停用", "error"),
        SECURITY_POST_LOGIN_VIEW='/',
        SECURITY_POST_LOGOUT_VIEW='/login',
    )

    # 连接 MongoDB（直接使用 mongoengine.connect）
    mongodb_uri = os.getenv('MONGODB_URI', 'mongodb://127.0.0.1:27017/lacus')
    try:
        connect(host=mongodb_uri, uuidRepresentation='standard')
        flask_app.logger.info('MongoDB 连接成功：%s', mongodb_uri)
    except Exception as exc:
        flask_app.logger.error('MongoDB 连接失败：%s', exc)
        raise

    # 启用全局 CSRF 保护（包含自定义表单）
    CSRFProtect(flask_app)

    # 初始化安全组件
    user_datastore = create_user_datastore()
    _security = init_security(flask_app, user_datastore)

    # 注册蓝图
    flask_app.register_blueprint(main_bp)
    flask_app.register_blueprint(admin_bp, url_prefix='/admin')
    flask_app.register_blueprint(pilot_bp, url_prefix='/pilots')
    flask_app.register_blueprint(battle_area_bp, url_prefix='/areas')
    flask_app.register_blueprint(announcement_bp, url_prefix='/announcements')

    # 注册Jinja2过滤器
    @flask_app.template_filter('role_display_name')
    def role_display_name(role_name):
        """将角色英文代码转换为中文显示名称"""
        role_mapping = {'gicho': '议长', 'kancho': '舰长'}
        return role_mapping.get(role_name, role_name)

    @flask_app.template_filter('roles_display_names')
    def roles_display_names(roles):
        """将角色列表转换为中文显示名称列表"""
        role_mapping = {'gicho': '议长', 'kancho': '舰长'}
        if isinstance(roles, list):
            return [role_mapping.get(role.name if hasattr(role, 'name') else role, role.name if hasattr(role, 'name') else role) for role in roles]
        return [role_mapping.get(roles, roles)]

    # 启动时确保角色与默认议长存在（需要应用上下文以支持密码哈希等）
    with flask_app.app_context():
        ensure_initial_roles_and_admin(user_datastore)

    return flask_app


# 便于 flask 命令行运行
app = create_app()


def run_dev() -> None:
    """开发环境启动入口。

    仅用于本地调试，不用于生产环境。
    读取 `FLASK_APP_PORT` 作为端口，默认 5080。
    """
    port = int(os.getenv('FLASK_APP_PORT', '5080'))
    # 使用 127.0.0.1 防止非本机访问
    app.logger.info('以开发模式启动，端口：%s', port)
    app.run(host='127.0.0.1', port=port, debug=True, use_reloader=True)


if __name__ == '__main__':
    # 允许：python app.py 直接启动调试
    run_dev()
