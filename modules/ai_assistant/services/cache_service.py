"""In-memory cache z TTL dla danych Baselinker"""

import time
import threading


class CacheService:
    _instance = None
    _lock = threading.Lock()
    DEFAULT_TTL = 3600

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._cache = {}
        return cls._instance

    def get(self, key: str):
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            if time.time() > entry['expires']:
                del self._cache[key]
                return None
            return entry['data']

    def set(self, key: str, data, ttl: int = None):
        with self._lock:
            self._cache[key] = {
                'data': data,
                'expires': time.time() + (ttl or self.DEFAULT_TTL)
            }

    def invalidate(self, key: str):
        with self._lock:
            self._cache.pop(key, None)

    def clear(self):
        with self._lock:
            self._cache.clear()

    def stats(self) -> dict:
        with self._lock:
            now = time.time()
            total = len(self._cache)
            expired = sum(1 for e in self._cache.values() if now > e['expires'])
            return {'total': total, 'expired': expired, 'active': total - expired}
