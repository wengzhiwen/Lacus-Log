# -*- coding: utf-8 -*-
"""
招募操作 Server-Sent Events (SSE) 推送管理器。
负责维护订阅队列，并在有新操作时向所有订阅者广播。
"""

import json
import queue
import threading
from typing import Generator

from utils.logging_setup import get_logger

logger = get_logger('recruit_sse')


class RecruitEventStreamManager:
    """SSE 订阅管理器"""

    def __init__(self):
        self._subscribers: list[queue.Queue] = []
        self._lock = threading.Lock()

    def register(self) -> queue.Queue:
        """注册订阅，返回事件队列。"""
        event_queue: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._subscribers.append(event_queue)
            logger.info('SSE订阅建立，当前订阅数=%d', len(self._subscribers))
        return event_queue

    def unregister(self, event_queue: queue.Queue) -> None:
        """注销订阅。"""
        with self._lock:
            if event_queue in self._subscribers:
                self._subscribers.remove(event_queue)
                logger.info('SSE订阅断开，剩余订阅数=%d', len(self._subscribers))

    def publish(self, payload: dict) -> None:
        """向所有订阅者广播事件。"""
        serialized = json.dumps(payload, ensure_ascii=False)
        with self._lock:
            subscribers = list(self._subscribers)

        dropped = 0
        for event_queue in subscribers:
            try:
                event_queue.put_nowait(serialized)
            except queue.Full:
                dropped += 1

        if dropped:
            logger.warning('SSE订阅队列已满，丢弃事件 %d 个', dropped)

    def stream(self) -> Generator[str, None, None]:
        """生成器：循环输出事件流。"""
        event_queue = self.register()
        try:
            while True:
                try:
                    message = event_queue.get(timeout=30)
                    yield f"data: {message}\n\n"
                except queue.Empty:
                    # 发送心跳，保持连接
                    yield ": keep-alive\n\n"
        finally:
            self.unregister(event_queue)


_manager = RecruitEventStreamManager()


def recruit_operation_event_stream() -> Generator[str, None, None]:
    """供蓝图使用的事件流生成器。"""
    return _manager.stream()


def publish_recruit_operation_event(payload: dict) -> None:
    """广播招募操作事件。"""
    _manager.publish(payload)
