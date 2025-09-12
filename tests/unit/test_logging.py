"""
日志系统测试
"""
import os
import tempfile
import logging
from pathlib import Path

import pytest

from utils.logging_setup import init_logging, get_logger, _daily_file_handler


@pytest.mark.unit
class TestLoggingSetup:
    """测试日志系统"""

    def test_daily_file_handler_creation(self, temp_log_dir):
        """测试按日切分文件处理器创建"""
        # 临时修改日志目录
        original_cwd = os.getcwd()
        os.chdir(temp_log_dir)

        try:
            handler = _daily_file_handler('test', logging.INFO)
            assert handler is not None
            assert isinstance(handler, logging.handlers.TimedRotatingFileHandler)
            assert handler.level == logging.INFO
        finally:
            os.chdir(original_cwd)

    def test_init_logging(self, temp_log_dir):
        """测试日志初始化"""
        # 临时修改日志目录
        original_cwd = os.getcwd()
        os.chdir(temp_log_dir)

        try:
            # 设置环境变量
            os.environ['LOG_LEVEL'] = 'DEBUG'
            os.environ['PYMONGO_LOG_LEVEL'] = 'WARNING'

            # 初始化日志
            init_logging()

            # 检查日志记录器
            app_logger = logging.getLogger('app')
            flask_logger = logging.getLogger('flask.app')

            assert app_logger.level == logging.DEBUG
            assert flask_logger.level == logging.DEBUG
            assert len(app_logger.handlers) > 0
            assert len(flask_logger.handlers) > 0

            # 检查第三方库日志级别
            pymongo_logger = logging.getLogger('pymongo')
            assert pymongo_logger.level == logging.WARNING

        finally:
            os.chdir(original_cwd)

    def test_get_logger(self, temp_log_dir):
        """测试获取功能模块日志记录器"""
        # 临时修改日志目录
        original_cwd = os.getcwd()
        os.chdir(temp_log_dir)

        try:
            logger = get_logger('test_module')
            assert logger is not None
            assert logger.name == 'test_module'
            assert len(logger.handlers) > 0

            # 测试日志输出
            logger.info('测试日志消息')

        finally:
            os.chdir(original_cwd)

    def test_log_file_creation(self, temp_log_dir):
        """测试日志文件创建"""
        # 临时修改日志目录
        original_cwd = os.getcwd()
        os.chdir(temp_log_dir)

        try:
            logger = get_logger('test_file')
            logger.info('测试文件创建')

            # 检查日志文件是否存在
            log_files = list(Path('log').glob('test_file_*.log'))
            assert len(log_files) > 0

        finally:
            os.chdir(original_cwd)
