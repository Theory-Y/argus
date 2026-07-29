"""server.jobs.queue — enqueue background work.

Defaults to an in-process thread pool (zero infra, good for self-host and dev).
Set QUEUE_BACKEND=rq + REDIS_URL to fan out across worker processes at scale.
"""

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from functools import lru_cache

from ..config import get_settings


class InProcessQueue:
    def __init__(self, max_workers: int = 2) -> None:
        self._pool = ThreadPoolExecutor(max_workers=max_workers)

    def enqueue(self, func: Callable, *args, **kwargs) -> None:
        self._pool.submit(func, *args, **kwargs)


class RQQueue:
    def __init__(self, redis_url: str) -> None:
        from redis import Redis
        from rq import Queue

        self._queue = Queue(connection=Redis.from_url(redis_url))

    def enqueue(self, func: Callable, *args, **kwargs) -> None:
        self._queue.enqueue(func, *args, **kwargs)


@lru_cache
def get_queue():
    s = get_settings()
    if s.queue_backend == "rq":
        return RQQueue(s.redis_url)
    return InProcessQueue()
