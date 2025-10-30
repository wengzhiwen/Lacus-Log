"""请求相关的辅助函数。

提供获取客户端真实IP地址等功能。
"""

from flask import request


def get_client_ip() -> str:
    """获取客户端真实IP地址。

    优先从 X-Forwarded-For 头部获取真实IP，如果没有则使用 remote_addr。
    这在有反向代理（如Nginx）的情况下特别重要，可以获取到真实的客户端IP
    而不是代理服务器的IP。

    Returns:
        str: 客户端IP地址，如果无法获取则返回'未知'
    """
    # X-Forwarded-For 可能包含多个IP，第一个是真实的客户端IP
    forwarded_for = request.headers.get('X-Forwarded-For')
    if forwarded_for and forwarded_for.strip():
        # 取第一个IP（客户端IP）
        first_ip = forwarded_for.split(',')[0].strip()
        if first_ip:
            return first_ip

    # 如果没有X-Forwarded-For或为空，则尝试从多种方式获取remote_addr
    remote_addr = request.remote_addr
    if not remote_addr:
        # 在某些情况下（如测试环境），需要直接从environ获取
        remote_addr = request.environ.get('REMOTE_ADDR')

    return remote_addr or '未知'


def get_client_ip_for_logging() -> str:
    """获取用于日志记录的客户端IP地址。

    与 get_client_ip() 的区别是，这个函数在无法获取IP时会返回'未知'，
    专门用于日志记录场景。

    Returns:
        str: 客户端IP地址，如果无法获取则返回'未知'
    """
    return get_client_ip() or '未知'