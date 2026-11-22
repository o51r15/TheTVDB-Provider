"""Bounded TTL cache with negative caching, single-flight and counters.

Split out of the client so the caching behaviour can be reasoned about
and tested on its own. Three things here are not obvious:

* **Misses are cached too.** Plex retries a failed image lookup hard -
  eight times in a row for one series in the first test library - and
  without remembering the absence each retry was a fresh upstream call
  for a record already known to be missing.
* **Single-flight.** Gunicorn runs multiple workers and Plex fires
  concurrent children requests, so the same uncached episode list could be
  fetched several times at once. A per-key lock collapses that into one
  upstream call; the others wait and read the result.
* **Counters.** Claiming a cache works is worthless without a number, so
  hits, misses and upstream calls are exposed on /health.
"""
import threading
import time

MISSING = object()      # nothing cached under this key
NEGATIVE = object()      # cached knowledge that upstream has nothing


class Cache(object):
    def __init__(self, max_entries=2000):
        self.max_entries = max_entries
        self._data = {}
        self._order = []
        self._lock = threading.Lock()
        self._keylocks = {}
        self.hits = 0
        self.misses = 0
        self.negative_hits = 0
        self.evictions = 0
        self.upstream_calls = 0
        self.upstream_errors = 0
        self.coalesced = 0

    # ------------------------------------------------------------- storage

    def get(self, key, ttl):
        """-> value, NEGATIVE, or MISSING."""
        with self._lock:
            entry = self._data.get(key)
            if entry is None:
                self.misses += 1
                return MISSING
            stored_at, value = entry
            if time.time() - stored_at > ttl:
                self._drop(key)
                self.misses += 1
                return MISSING
            if value is NEGATIVE:
                self.negative_hits += 1
                return NEGATIVE
            self.hits += 1
            return value

    def put(self, key, value):
        with self._lock:
            if key not in self._data and len(self._data) >= self.max_entries:
                # Oldest-first. A plain dict in the ThePornDB provider only
                # ever dropped an entry when that exact key was requested
                # again after expiry, so it grew for the life of the
                # process.
                while self._order and len(self._data) >= self.max_entries:
                    self._drop(self._order[0])
                    self.evictions += 1
            if key not in self._data:
                self._order.append(key)
            self._data[key] = (time.time(), value)

    def _drop(self, key):
        """Remove one key. Caller holds the lock."""
        self._data.pop(key, None)
        try:
            self._order.remove(key)
        except ValueError:
            pass

    def clear(self):
        with self._lock:
            self._data.clear()
            del self._order[:]
            self._keylocks.clear()

    # -------------------------------------------------------- single-flight

    def key_lock(self, key):
        with self._lock:
            lock = self._keylocks.get(key)
            if lock is None:
                lock = threading.Lock()
                self._keylocks[key] = lock
                # Bound this too: one lock per key would otherwise be a
                # slow leak keyed on every URL ever requested.
                if len(self._keylocks) > self.max_entries * 2:
                    for stale in list(self._keylocks)[:self.max_entries]:
                        if stale != key and not self._keylocks[stale].locked():
                            self._keylocks.pop(stale, None)
            return lock

    # --------------------------------------------------------------- report

    def stats(self):
        with self._lock:
            total = self.hits + self.negative_hits + self.misses
            served = self.hits + self.negative_hits
            return {
                'entries': len(self._data),
                'maxEntries': self.max_entries,
                'hits': self.hits,
                'negativeHits': self.negative_hits,
                'misses': self.misses,
                'hitRate': round(served / total, 3) if total else None,
                'evictions': self.evictions,
                'upstreamCalls': self.upstream_calls,
                'upstreamErrors': self.upstream_errors,
                'coalesced': self.coalesced,
            }
