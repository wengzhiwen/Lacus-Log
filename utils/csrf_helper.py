"""CSRF Helper

为REST API提供简单的CSRF校验机制：在用户Session中缓存随机Token，前端通过自定义Header回传。
"""
from secrets import token_hex
from typing import Optional

from flask import request, session


class CSRFError(Exception):
    """CSRF校验失败异常。"""

    def __init__(self, code: str, message: str):
        self.code = code
        self.message = message
        super().__init__(message)


def ensure_csrf_token() -> str:
    """确保Session中存在CSRF Token，并返回该值。"""
    token = session.get('csrf_token')
    if not token:
        token = token_hex(32)
        session['csrf_token'] = token
    return token


def validate_csrf_header(header_name: str = 'X-CSRF-Token', session_key: str = 'csrf_token') -> None:
    """校验请求头中的CSRF Token与Session中的是否一致。"""
    expected = session.get(session_key)
    if not expected:
        raise CSRFError('CSRF_SESSION_MISSING', 'CSRF校验失败，请刷新页面后重试')

    header_candidates = {header_name, header_name.replace('-', ''), 'X-CSRFToken'}
    provided: Optional[str] = None
    for candidate in header_candidates:
        provided = request.headers.get(candidate)
        if provided:
            break
    if not provided:
        raise CSRFError('CSRF_TOKEN_MISSING', '缺少CSRF校验信息')

    if provided != expected:
        raise CSRFError('CSRF_TOKEN_INVALID', 'CSRF校验失败，请刷新页面后重试')
