"""筛选条件持久化工具。

使用 Flask session 记录每个列表页的筛选参数。

约定：
- 每个页面使用唯一的 page_key 作为 session 下的命名空间
- 仅记录 allowed_keys 中的筛选键
- 当本次请求未携带任何筛选键时，回填上次保存的筛选条件；若不存在则使用默认值
"""

from typing import Dict, Iterable

from flask import request, session


def _ensure_session_bucket() -> Dict:
    """确保 session 中存在筛选状态总表。"""
    bucket = session.get('filter_state')
    if bucket is None:
        bucket = {}
        session['filter_state'] = bucket
        session.modified = True
    return bucket


def persist_and_restore_filters(page_key: str, *, allowed_keys: Iterable[str], default_filters: Dict[str, str]) -> Dict[str, str]:
    """根据请求参数与历史记录，返回本次生效的筛选字典，并在需要时写入 session。

    Args:
        page_key: 页面唯一键，如 'pilots_list'
        allowed_keys: 允许管理的筛选键集合
        default_filters: 当无请求参数且无历史记录时使用的默认值

    Returns:
        dict: 本次应当生效的筛选条件（只包含 allowed_keys）
    """
    allowed_keys = list(allowed_keys)

    has_filter_in_request = any(key in request.args for key in allowed_keys)

    effective = dict(default_filters)

    bucket = _ensure_session_bucket()
    saved: Dict[str, str] = bucket.get(page_key) or {}

    if has_filter_in_request:
        # 保存所有筛选器状态，包括空值
        to_save = {}
        for key in allowed_keys:
            if key in request.args:
                to_save[key] = request.args.get(key, '')
                effective[key] = to_save[key]
            else:
                # 如果请求中没有这个参数，保持之前的保存值或设为空
                to_save[key] = saved.get(key, '')
                effective[key] = to_save[key]
        bucket[page_key] = to_save
        session['filter_state'] = bucket
        session.modified = True
        return effective

    if saved:
        for key in allowed_keys:
            if key in saved:
                effective[key] = saved.get(key)

    return effective


