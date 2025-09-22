#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MongoDB 任务计划令牌（Job Plan Token）工具。

用途：
- 单机/多进程下，保证同一“计划时间点”的任务只会被消费一次。
- 机制：启动/任务完成时写入下一次计划；触发时原子性消费计划（存在则删并执行，不存在则跳过）。
"""

from __future__ import annotations

from datetime import datetime, timezone

from mongoengine import DateTimeField, Document, StringField


class JobPlan(Document):
    """任务计划令牌。

    唯一键：job_code + fire_minute（UTC分钟精度）。
    """

    meta = {
        'collection': 'job_plans',
        'indexes': [
            {
                'fields': ['job_code', 'fire_minute'],
                'unique': True
            },
            {
                'fields': ['expire_at'],
                'expireAfterSeconds': 7 * 24 * 3600
            },  # 一周自动清理
        ],
    }

    job_code = StringField(required=True)
    fire_minute = StringField(required=True)  # 格式：YYYYMMDDHHMM（UTC）
    planned_at = DateTimeField(default=lambda: datetime.now(timezone.utc))
    expire_at = DateTimeField(default=lambda: datetime.now(timezone.utc))


def _to_minute_str(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime('%Y%m%d%H%M')


def plan_fire(job_code: str, fire_dt_utc: datetime) -> None:
    """写入/刷新“下一次执行计划”。幂等。

    Args:
        job_code: 任务代码
        fire_dt_utc: 下一次触发UTC时间（必须是tz-aware的UTC时间）
    """
    minute = _to_minute_str(fire_dt_utc)
    # 使用底层collection执行upsert，避免动态属性的类型检查告警
    coll = JobPlan._get_collection()  # type: ignore[attr-defined]  # noqa: SLF001, E1101
    coll.update_one(
        {'job_code': job_code, 'fire_minute': minute},
        {
            '$set': {
                'planned_at': datetime.now(timezone.utc),
                'expire_at': fire_dt_utc,
            },
            '$setOnInsert': {
                'job_code': job_code,
                'fire_minute': minute,
            },
        },
        upsert=True,
    )


def consume_fire(job_code: str, fire_dt_utc: datetime) -> bool:
    """尝试原子性消费本次计划：成功返回True；不存在返回False。

    Args:
        job_code: 任务代码
        fire_dt_utc: 本次应触发的UTC时间（分钟精度）
    """
    minute = _to_minute_str(fire_dt_utc)
    # 使用底层collection原子删除
    coll = JobPlan._get_collection()  # type: ignore[attr-defined]  # noqa: SLF001, E1101
    doc = coll.find_one_and_delete({'job_code': job_code, 'fire_minute': minute})
    return doc is not None
