"""Bounded per-user ordering and short-lived duplicate suppression."""

import asyncio
import time
from collections import OrderedDict
from collections.abc import Awaitable
from typing import Any

from telegram.ext import BaseUpdateProcessor


class OrderedUpdateProcessor(BaseUpdateProcessor):
    def __init__(self, concurrency: int, stripes: int = 256) -> None:
        super().__init__(concurrency)
        self._locks = [asyncio.Lock() for _ in range(stripes)]
        self._seen: OrderedDict[int, float] = OrderedDict()

    async def initialize(self) -> None:
        pass

    async def shutdown(self) -> None:
        self._seen.clear()

    async def do_process_update(self, update: object, coroutine: Awaitable[Any]) -> None:
        user = getattr(update, "effective_user", None)
        key = user.id if user else getattr(update, "update_id", 0)
        async with self._locks[key % len(self._locks)]:
            update_id = getattr(update, "update_id", None)
            now = time.monotonic()
            while self._seen and next(iter(self._seen.values())) < now - 300:
                self._seen.popitem(last=False)
            if update_id is not None and update_id in self._seen:
                coroutine.close()
                return
            await coroutine
            if update_id is not None:
                self._seen[update_id] = now
                if len(self._seen) > 4096:
                    self._seen.popitem(last=False)
