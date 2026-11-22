"""TheTVDB v4 client: bearer auth, tiered caching, paged fetches.

Shape and endpoint paths follow TheTVDB's own Python client
(tvdb-v4-official 1.1.0), which is the authoritative source for them -
the published Swagger page renders client-side and serves no paths to a
plain fetch.

Unlike ThePornDB's static API key, v4 uses a short login exchange:

    POST {base}/login  {"apikey": ..., "pin": ...}  -> data.token

The token then goes in an Authorization: Bearer header. It is long-lived,
but a provider that only trusted a TTL would serve 401s for as long as it
took the clock to run out, so an unauthorised reply triggers exactly one
re-login and retry.

Caching is tiered because the costs differ by orders of magnitude:

    reference data   a week    (season types, artwork types)
    episode lists    a day     (dozens of paged calls per series)
    everything else  an hour
    known-missing    5 min     (Plex retries a failed lookup hard)

TheTVDB's own guidance is to keep a local copy or caching proxy rather
than call it per request, and to use If-Modified-Since; this does the
former and honours 304 on the latter.
"""
import logging
import threading
import time

import requests

from .cache_core import Cache, MISSING, NEGATIVE
from .config import config

log = logging.getLogger(__name__)

_local = threading.local()
_cache = Cache(max_entries=config.cache_max_entries)

_token = {'value': None, 'at': 0.0}
_token_lock = threading.Lock()


def _session():
    sess = getattr(_local, 'session', None)
    if sess is None:
        sess = requests.Session()
        _local.session = sess
    return sess


def cache_stats():
    stats = _cache.stats()
    stats.update({
        'ttl': config.cache_ttl,
        'episodeTtl': config.episode_cache_ttl,
        'staticTtl': config.static_cache_ttl,
        'negativeTtl': config.negative_cache_ttl,
    })
    return stats


def cache_clear():
    _cache.clear()


# ---------------------------------------------------------------------- auth

def login(force=False):
    """Return a bearer token, logging in if needed.

    Raises nothing: a failure returns None so callers degrade to 'not
    found' rather than a 500, and the reason is logged.
    """
    with _token_lock:
        if (_token['value'] and not force
                and time.time() - _token['at'] < config.token_ttl):
            return _token['value']

        if not config.api_key:
            log.error('TVDB_API_KEY is not set; cannot authenticate')
            return None

        body = {'apikey': config.api_key}
        if config.pin:
            body['pin'] = config.pin

        url = '%s/login' % config.api_base.rstrip('/')
        try:
            resp = _session().post(
                url, json=body,
                headers={'Content-Type': 'application/json',
                         'Accept': 'application/json'},
                timeout=config.timeout)
        except requests.RequestException as exc:
            log.error('login failed: %s', exc)
            return None

        if resp.status_code != 200:
            # 401 here means the key or the PIN is wrong, which retrying
            # does not fix. Say which: they are supplied separately and
            # the difference is not visible in a bare 401.
            log.error('login rejected (HTTP %s): check TVDB_API_KEY%s',
                      resp.status_code,
                      ' and TVDB_PIN' if config.pin else
                      ' (TVDB_PIN is unset; a user-supported project key'
                      ' needs a subscriber PIN)')
            return None

        try:
            token = (resp.json().get('data') or {}).get('token')
        except ValueError:
            log.error('login returned a non-JSON body')
            return None

        if not token:
            log.error('login succeeded but returned no token')
            return None

        _token['value'] = token
        _token['at'] = time.time()
        log.info('authenticated to TheTVDB')
        return token


def _auth_header(token):
    return {'Authorization': 'Bearer %s' % token,
            'Accept': 'application/json'}


# ------------------------------------------------------------------ requests

def get_json(path, params=None, ttl=None, _retried_auth=False):
    """GET a v4 path and return its `data`, or None.

    None covers every failure - timeout, 5xx, 404 alike. Callers must
    translate that into an error status and never into an empty success:
    Plex treats an empty 200 container as authoritative and stops, where
    it would retry an error.
    """
    path = path.lstrip('/')
    if ttl is None:
        ttl = config.cache_ttl
    key = (path, tuple(sorted((params or {}).items())))

    cached = _cache.get(key, ttl)
    if cached is NEGATIVE:
        return None
    if cached is not MISSING:
        return cached

    # Single-flight: Plex fires concurrent children requests and gunicorn
    # runs several workers, so without this the same uncached episode list
    # is fetched more than once at the same time.
    lock = _cache.key_lock(key)
    with lock:
        cached = _cache.get(key, ttl)
        if cached is NEGATIVE:
            _cache.coalesced += 1
            return None
        if cached is not MISSING:
            _cache.coalesced += 1
            return cached
        return _fetch(path, params, key, ttl, _retried_auth)


def _fetch(path, params, key, ttl, _retried_auth):
    token = login()
    if not token:
        return None

    url = '%s/%s' % (config.api_base.rstrip('/'), path)
    last = None
    for attempt in range(max(1, config.retries)):
        try:
            _cache.upstream_calls += 1
            resp = _session().get(url, params=params,
                                  headers=_auth_header(token),
                                  timeout=config.timeout)
        except requests.RequestException as exc:
            last = str(exc)
            _cache.upstream_errors += 1
            time.sleep(min(2 ** attempt, 8))
            continue

        if resp.status_code == 401 and not _retried_auth:
            # The token went stale earlier than TVDB_TOKEN_TTL claimed.
            log.info('token rejected; re-authenticating')
            login(force=True)
            return get_json(path, params, ttl, _retried_auth=True)

        if resp.status_code == 404:
            # Remember the absence, briefly.
            _cache.put(key, NEGATIVE)
            return None

        if resp.status_code >= 500:
            last = 'HTTP %s' % resp.status_code
            _cache.upstream_errors += 1
            time.sleep(min(2 ** attempt, 8))
            continue

        if resp.status_code != 200:
            log.warning('%s -> HTTP %s', path, resp.status_code)
            _cache.put(key, NEGATIVE)
            return None

        try:
            body = resp.json()
        except ValueError:
            log.warning('%s -> non-JSON body', path)
            _cache.upstream_errors += 1
            return None

        data = body.get('data')
        if data is None:
            _cache.put(key, NEGATIVE)
            return None
        _cache.put(key, data)
        return data

    # Transport or 5xx failure: deliberately NOT cached as negative. A
    # blip should not make a series look absent for the next five minutes.
    log.warning('%s failed after %d attempts: %s', path, config.retries, last)
    return None


def get_paged(path, params=None, max_pages=None, ttl=None):
    """Collect every page of a paged endpoint into one list.

    v4 paginates with ?page=N and stops when a page comes back short or
    empty. max_pages guards against a pathological series walking forever.
    """
    limit = config.max_episode_pages if max_pages is None else max_pages
    out = []
    for page in range(max(1, limit)):
        args = dict(params or {})
        args['page'] = page
        data = get_json(path, args, ttl=ttl)
        if data is None:
            # Distinguish 'nothing there' from 'the first page failed':
            # returning a partial list as complete would make Plex believe
            # a series has fewer episodes than it does.
            return out if page else None
        rows = _episode_rows(data)
        if not rows:
            break
        out.extend(rows)
        if len(rows) < 100:
            break
    return out


def _episode_rows(data):
    """Episodes out of either response shape.

    /series/{id}/episodes/{type} answers {"series": {...},
    "episodes": [...]}, while flatter endpoints answer a bare list.
    """
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        rows = data.get('episodes')
        if isinstance(rows, list):
            return rows
    return []


# ----------------------------------------------------------------- endpoints

def search(query, year=None, kind='series'):
    params = {'query': query}
    if kind:
        params['type'] = kind
    if year:
        params['year'] = year
    data = get_json('search', params)
    return data if isinstance(data, list) else []


def search_remote_id(remote_id):
    """Exact lookup by an external id - a {tvdb-nnnnn} or IMDb hint."""
    data = get_json('search/remoteid/%s' % remote_id)
    return data if isinstance(data, list) else []


def series(series_id):
    data = get_json('series/%s' % series_id)
    return data if isinstance(data, dict) else None


def series_extended(series_id, short=False):
    params = {'short': 'true'} if short else None
    data = get_json('series/%s/extended' % series_id, params)
    return data if isinstance(data, dict) else None


def series_episodes(series_id, season_type='default', lang=None, page=None):
    """Episodes of a series in one season type.

    This is the endpoint the whole provider exists for: it is what Plex
    loses on 2026-12-03, and the only source of DVD and absolute ordering.
    Cached for a day - it is the most expensive call here and the least
    volatile.
    """
    path = 'series/%s/episodes/%s' % (series_id, season_type)
    if lang:
        path = '%s/%s' % (path, lang)
    ttl = config.episode_cache_ttl
    if page is not None:
        return _episode_rows(get_json(path, {'page': page}, ttl=ttl) or {})
    return get_paged(path, ttl=ttl)


def series_artworks(series_id, lang=None, art_type=None):
    params = {}
    if lang:
        params['lang'] = lang
    if art_type:
        params['type'] = art_type
    data = get_json('series/%s/artworks' % series_id, params or None)
    return data if isinstance(data, dict) else None


def series_translation(series_id, lang):
    data = get_json('series/%s/translations/%s' % (series_id, lang))
    return data if isinstance(data, dict) else None


def episode(episode_id):
    data = get_json('episodes/%s' % episode_id)
    return data if isinstance(data, dict) else None


def episode_extended(episode_id):
    data = get_json('episodes/%s/extended' % episode_id)
    return data if isinstance(data, dict) else None


def episode_translation(episode_id, lang):
    data = get_json('episodes/%s/translations/%s' % (episode_id, lang))
    return data if isinstance(data, dict) else None


def season_extended(season_id):
    data = get_json('seasons/%s/extended' % season_id)
    return data if isinstance(data, dict) else None


def season_types():
    """Valid season types, from upstream rather than hardcoded.

    The set has grown over time - there are seven, including two extra
    alternates - so the provider enumerates it instead of guessing.
    """
    data = get_json('seasons/types', ttl=config.static_cache_ttl)
    return data if isinstance(data, list) else []


def artwork_types():
    data = get_json('artwork/types', ttl=config.static_cache_ttl)
    return data if isinstance(data, list) else []
