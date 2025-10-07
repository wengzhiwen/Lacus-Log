"""CSRF 校验辅助模块。

提供统一的 Double-submit Cookie + Custom Header 校验机制。
"""
from flask import request
from flask_wtf.csrf import validate_csrf
from werkzeug.exceptions import BadRequest

from utils.logging_setup import get_logger

logger = get_logger('csrf')


class CSRFError(Exception):
    """CSRF 校验错误。"""

    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def validate_csrf_header():
    """验证 CSRF 令牌（Double-submit Cookie + Custom Header）。
    
    校验逻辑：
    1. 检查 X-CSRFToken 请求头是否存在
    2. 使用 Flask-WTF 的 validate_csrf 验证令牌
    
    异常：
        CSRFError: CSRF 校验失败
    """
    csrf_token = request.headers.get('X-CSRFToken')

    if not csrf_token:
        logger.warning('CSRF校验失败：缺少X-CSRFToken请求头，来源IP=%s',
                       request.remote_addr)
        raise CSRFError('CSRF_TOKEN_MISSING', '缺少CSRF令牌')

    try:
        validate_csrf(csrf_token)
    except BadRequest as exc:
        logger.warning('CSRF校验失败：令牌无效，来源IP=%s，错误=%s',
                       request.remote_addr,
                       str(exc))
        raise CSRFError('CSRF_TOKEN_INVALID', 'CSRF令牌无效') from exc

