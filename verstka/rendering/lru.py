"""A bounded, thread-safe cache for the picture readings a long-running server keeps (final review I7): the least
recently used entries go once the cache holds `size` of them."""

from __future__ import annotations

import hashlib
import threading
from collections import OrderedDict
from typing import Any, Hashable

_MISS = object()


def blob_key(blob: bytes) -> str:
    """A picture's identity by its content: two templates' `/ppt/media/image1.png` of the same length are two pictures."""
    return hashlib.blake2b(blob, digest_size=16).hexdigest()


class Lru:
    def __init__(self, size: int) -> None:
        self.size = size
        self._d: "OrderedDict[Hashable, Any]" = OrderedDict()
        self._lock = threading.Lock()

    def get(self, key: Hashable, default: Any = None) -> Any:
        with self._lock:
            got = self._d.get(key, _MISS)
            if got is _MISS:
                return default
            self._d.move_to_end(key)
            return got

    def __contains__(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._d

    def put(self, key: Hashable, value: Any) -> Any:
        with self._lock:
            self._d[key] = value
            self._d.move_to_end(key)
            while len(self._d) > self.size:
                self._d.popitem(last=False)
        return value

    def __len__(self) -> int:
        with self._lock:
            return len(self._d)

    def clear(self) -> None:
        with self._lock:
            self._d.clear()
