import logging
import os
from logging.handlers import TimedRotatingFileHandler


def _custom_namer(default_name: str) -> str:
    """自定义日志文件命名，格式为 name_YYYYMMDD.log。"""
    base_filename, date_suffix = default_name.rsplit('.', 1)
    log_dirname, log_basename = os.path.split(base_filename)
    log_prefix, log_ext = os.path.splitext(log_basename)
    return os.path.join(log_dirname, f"{log_prefix}_{date_suffix}{log_ext}")


def _daily_file_handler(name: str, level: int) -> TimedRotatingFileHandler:
    """构建按自然日切分的文件处理器（log/<name>_YYYYMMDD.log）。"""
    os.makedirs('log', exist_ok=True)
    filename = os.path.join('log', f'{name}.log')

    handler = TimedRotatingFileHandler(filename, when='midnight', backupCount=14, encoding='utf-8')
    handler.suffix = "%Y%m%d"
    handler.namer = _custom_namer
    handler.setLevel(level)
    fmt = logging.Formatter('[%(asctime)s] %(levelname)s %(name)s - %(message)s')
    handler.setFormatter(fmt)
    return handler


def init_logging() -> None:
    """初始化全局日志与第三方库级别。"""
    level_name = os.getenv('LOG_LEVEL', 'INFO')
    level = getattr(logging, level_name.upper(), logging.INFO)

    app_logger = logging.getLogger('app')
    app_logger.setLevel(level)
    app_logger.handlers.clear()
    app_logger.addHandler(_daily_file_handler('app', level))

    flask_app_logger = logging.getLogger('flask.app')
    flask_app_logger.setLevel(level)
    flask_app_logger.handlers.clear()
    flask_app_logger.addHandler(_daily_file_handler('app', level))

    flask_app_logger.addHandler(_daily_file_handler('flask_error', logging.ERROR))

    werkzeug_logger = logging.getLogger('werkzeug')
    werkzeug_logger.setLevel(logging.INFO)
    werkzeug_logger.addHandler(_daily_file_handler('werkzeug_error', logging.ERROR))

    pymongo_level = getattr(logging, os.getenv('PYMONGO_LOG_LEVEL', 'INFO').upper(), logging.INFO)
    logging.getLogger('pymongo').setLevel(pymongo_level)

    logging.getLogger('urllib3').setLevel(logging.INFO)
    logging.getLogger('requests').setLevel(logging.INFO)


def get_logger(name: str) -> logging.Logger:
    """为功能模块创建独立 logger，按日切分。"""
    level_name = os.getenv('LOG_LEVEL', 'INFO')
    level = getattr(logging, level_name.upper(), logging.INFO)
    logger = logging.getLogger(name)
    logger.setLevel(level)
    if not logger.handlers:
        logger.addHandler(_daily_file_handler(name, level))
    return logger
