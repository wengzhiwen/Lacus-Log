import logging
import os
from datetime import datetime
from logging.handlers import TimedRotatingFileHandler


def _daily_file_handler(name: str, level: int) -> TimedRotatingFileHandler:
    """构建按自然日切分的文件日志处理器。

    文件名格式：log/<name>_YYYYMMDD.log
    """
    os.makedirs('log', exist_ok=True)
    today = datetime.now().strftime('%Y%m%d')
    filename = os.path.join('log', f'{name}_{today}.log')

    handler = TimedRotatingFileHandler(filename,
                                       when='midnight',
                                       backupCount=14,
                                       encoding='utf-8')
    handler.suffix = "%Y%m%d"
    handler.setLevel(level)
    fmt = logging.Formatter(
        '[%(asctime)s] %(levelname)s %(name)s - %(message)s')
    handler.setFormatter(fmt)
    return handler


def init_logging() -> None:
    """初始化全局日志设置。

    - 主应用 logger: app
    - Flask 应用 logger: flask.app
    - 第三方库如 pymongo 的日志级别可由环境变量控制
    """
    level_name = os.getenv('LOG_LEVEL', 'INFO')
    level = getattr(logging, level_name.upper(), logging.INFO)

    # 应用日志
    app_logger = logging.getLogger('app')
    app_logger.setLevel(level)
    app_logger.handlers.clear()
    app_logger.addHandler(_daily_file_handler('app', level))

    # Flask 应用日志也写入按日文件
    flask_app_logger = logging.getLogger('flask.app')
    flask_app_logger.setLevel(level)
    flask_app_logger.handlers.clear()
    flask_app_logger.addHandler(_daily_file_handler('app', level))

    # 控制第三方日志量
    pymongo_level = getattr(logging,
                            os.getenv('PYMONGO_LOG_LEVEL', 'INFO').upper(),
                            logging.INFO)
    logging.getLogger('pymongo').setLevel(pymongo_level)

    # 其他可能产生大量日志的第三方库
    logging.getLogger('urllib3').setLevel(logging.INFO)
    logging.getLogger('requests').setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """为功能模块创建独立 logger，按日切分。"""
    level_name = os.getenv('LOG_LEVEL', 'INFO')
    level = getattr(logging, level_name.upper(), logging.INFO)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    # 避免重复添加handler
    if not logger.handlers:
        logger.addHandler(_daily_file_handler(name, level))
    return logger
