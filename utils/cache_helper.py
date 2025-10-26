# -*- coding: utf-8 -*-
"""
缓存工具模块

为开播月报等计算密集型功能提供缓存支持
"""

import functools
import hashlib
import json
import logging
from typing import Any, Callable, Dict

from cachetools import TTLCache

logger = logging.getLogger(__name__)

monthly_report_cache = TTLCache(maxsize=1000, ttl=900)  # 900秒 = 15分钟

pilot_performance_cache = TTLCache(maxsize=500, ttl=300)  # 300秒 = 5分钟

active_pilot_cache = TTLCache(maxsize=10, ttl=3600)  # 3600秒 = 60分钟


def generate_cache_key(func_name: str, *args, **kwargs) -> str:
    """生成缓存键
    
    Args:
        func_name: 函数名
        *args: 位置参数
        **kwargs: 关键字参数
        
    Returns:
        str: 缓存键
    """
    key_data = {'func': func_name, 'args': args, 'kwargs': kwargs}

    key_str = json.dumps(key_data, sort_keys=True, default=str)
    return hashlib.md5(key_str.encode('utf-8')).hexdigest()


def cached_monthly_report(ttl: int = 900):  # pylint: disable=unused-argument
    """开播月报缓存装饰器
    
    Args:
        ttl: 缓存过期时间（秒），默认15分钟
    """

    def decorator(func: Callable) -> Callable:

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = generate_cache_key(func.__name__, *args, **kwargs)

            if cache_key in monthly_report_cache:
                logger.debug('缓存命中：%s', func.__name__)
                return monthly_report_cache[cache_key]

            logger.debug('缓存未命中，开始计算：%s', func.__name__)
            result = func(*args, **kwargs)

            monthly_report_cache[cache_key] = result
            logger.debug('计算结果已缓存：%s', func.__name__)

            return result

        return wrapper

    return decorator


def _clear_report_cache(log_message: str):
    """统一清空报告缓存并记录日志"""
    monthly_report_cache.clear()
    logger.info(log_message)


def clear_monthly_report_cache():
    """清空开播月报缓存"""
    _clear_report_cache('开播月报缓存已清空')


def clear_daily_report_cache():
    """清空开播日报缓存"""
    _clear_report_cache('开播日报缓存已清空')


def cached_pilot_performance(ttl: int = 300):  # pylint: disable=unused-argument
    """主播业绩缓存装饰器
    
    Args:
        ttl: 缓存过期时间（秒），默认5分钟
    """

    def decorator(func: Callable) -> Callable:

        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            cache_key = generate_cache_key(func.__name__, *args, **kwargs)

            if cache_key in pilot_performance_cache:
                logger.debug('主播业绩缓存命中：%s', func.__name__)
                return pilot_performance_cache[cache_key]

            logger.debug('主播业绩缓存未命中，开始计算：%s', func.__name__)
            result = func(*args, **kwargs)

            pilot_performance_cache[cache_key] = result
            logger.debug('主播业绩计算结果已缓存：%s', func.__name__)

            return result

        return wrapper

    return decorator


def clear_pilot_performance_cache():
    """清空主播业绩缓存"""
    pilot_performance_cache.clear()
    logger.info('主播业绩缓存已清空')


def get_cached_active_pilots(cache_key: str, builder: Callable[[], Any]) -> Any:
    """获取活跃主播缓存结果，未命中时执行builder构建数据"""
    if cache_key in active_pilot_cache:
        logger.debug('活跃主播缓存命中：%s', cache_key)
        return active_pilot_cache[cache_key]

    result = builder()
    active_pilot_cache[cache_key] = result
    size = len(result) if hasattr(result, '__len__') else '未知'
    logger.debug('活跃主播缓存构建完成：%s，数量：%s', cache_key, size)
    return result


def clear_active_pilot_cache():
    """清空活跃主播缓存"""
    active_pilot_cache.clear()
    logger.info('活跃主播缓存已清空')


def get_cache_info() -> Dict[str, Any]:
    """获取缓存信息
    
    Returns:
        dict: 缓存统计信息
    """
    return {
        'monthly_report_cache': {
            'cache_size': len(monthly_report_cache),
            'max_size': monthly_report_cache.maxsize,
            'ttl': monthly_report_cache.ttl
        },
        'pilot_performance_cache': {
            'cache_size': len(pilot_performance_cache),
            'max_size': pilot_performance_cache.maxsize,
            'ttl': pilot_performance_cache.ttl
        }
    }
