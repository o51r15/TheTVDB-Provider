"""Configuration for the TheTVDB custom metadata provider.

Everything is read from environment variables: the new Plex metadata
provider API has no Plex-side preferences UI, so there is nowhere else to
put settings.

Two things here differ from the ThePornDB provider and are worth knowing:

* TheTVDB v4 keys are **per project, not per user**. A key is paired with
  each end user's own subscriber PIN. So both TVDB_API_KEY and TVDB_PIN
  are needed, and an empty PIN is valid only for a negotiated
  commercial-licence key.
* Episode **ordering** is the reason this provider exists. Plex is
  dropping TheTVDB on 2026-12-03, and DVD/absolute ordering exists in Plex
  only through it. TVDB_SEASON_TYPE sets the default order and
  TVDB_ORDER_OVERRIDES sets it per series, so one library can hold
  aired-order shows and absolute-order anime at the same time.
"""
import os
import sys


def truthy(value):
    """One definition of true, for env flags and query parameters alike.

    The ThePornDB provider had two that disagreed about 'True', so
    includeChildren was honoured in one place and ignored in another - and
    a season returned without its children binds no files at all. One
    definition, used everywhere.
    """
    return str(value).strip().lower() in ('1', 'true', 'yes', 'on')


def _bool(name, default=False):
    raw = os.environ.get(name)
    if raw is None:
        return default
    return truthy(raw)


def _str(name, default=''):
    val = os.environ.get(name)
    return default if val is None else val


def _int(name, default):
    """An int setting that falls back instead of killing the process.

    Evaluated at class-definition time, so a non-numeric value would
    otherwise crash the container at import with a bare ValueError and no
    indication of which variable was at fault.
    """
    raw = os.environ.get(name)
    if raw is None or raw.strip() == '':
        return default
    try:
        return int(raw.strip())
    except ValueError:
        sys.stderr.write(
            '%s=%r is not a number; using %d\n' % (name, raw, default))
        return default


def _csv(name, default=()):
    raw = os.environ.get(name)
    if raw is None or not raw.strip():
        return list(default)
    return [part.strip() for part in raw.split(',') if part.strip()]


def _order_map(name):
    """TVDB_ORDER_OVERRIDES='121361:dvd,79349:absolute' -> dict.

    Keyed by TheTVDB series id as a string. A malformed pair is reported
    and skipped rather than taking the whole mapping down, because this is
    the setting most likely to be hand-edited.
    """
    out = {}
    for pair in _csv(name):
        series_id, sep, order = pair.partition(':')
        series_id, order = series_id.strip(), order.strip().lower()
        if not sep or not series_id or not order:
            sys.stderr.write(
                '%s: ignoring %r, expected <seriesId>:<seasonType>\n'
                % (name, pair))
            continue
        out[series_id] = order
    return out


class Config(object):
    # --- upstream ---
    # Trailing slash matters: the official client builds every path by
    # concatenation onto this base.
    api_base = _str('TVDB_API_BASE', 'https://api4.thetvdb.com/v4')
    api_key = _str('TVDB_API_KEY')
    # Each end user's own $12/year subscriber PIN. Blank is valid only for
    # a negotiated commercial-licence key.
    pin = _str('TVDB_PIN')
    timeout = _int('TVDB_TIMEOUT', 30)
    retries = _int('TVDB_RETRIES', 3)
    cache_ttl = _int('TVDB_CACHE_TTL', 3600)
    # Reference data (season types, languages, artwork types) barely ever
    # changes; TheTVDB's own guidance is to cache it for about a week.
    static_cache_ttl = _int('TVDB_STATIC_CACHE_TTL', 604800)
    # Episode lists are the most expensive thing here - a long-running
    # series is dozens of paged calls - and they change rarely, so they
    # get their own, longer TTL.
    episode_cache_ttl = _int('TVDB_EPISODE_CACHE_TTL', 86400)
    # Remember that something is missing, too. Plex retries hard on a
    # failed image lookup (eight times in a row, observed), and without
    # this each retry was a fresh upstream call for a known-absent record.
    negative_cache_ttl = _int('TVDB_NEGATIVE_CACHE_TTL', 300)
    cache_max_entries = _int('TVDB_CACHE_MAX_ENTRIES', 2000)
    # A v4 token is long-lived, but re-login on 401 is what actually keeps
    # the provider up; this only forces a refresh before that happens.
    token_ttl = _int('TVDB_TOKEN_TTL', 2592000)

    # --- provider identity ---
    identifier = _str('TVDB_IDENTIFIER', 'tv.plex.agents.custom.tvdb')
    title = _str('TVDB_TITLE', 'TheTVDB')
    version = _str('TVDB_VERSION', '1.0.0')

    # --- ordering: the whole point of this provider ---
    # Each registered provider carries its own season type, so there is
    # deliberately no single TVDB_SEASON_TYPE: the order is chosen by
    # which provider a library points at. Set TVDB_ORDER_PROVIDERS to one
    # value for a single-order deployment.
    #
    # Per-series overrides so one library can mix orderings:
    #   TVDB_ORDER_OVERRIDES=121361:dvd,79349:absolute
    order_overrides = _order_map('TVDB_ORDER_OVERRIDES')
    # Expose one extra provider per listed order, each with its own
    # identifier, for anyone who would rather separate libraries than
    # maintain an overrides map.
    order_providers = _csv('TVDB_ORDER_PROVIDERS')
    # When a series has no episodes in the requested order, fall back to
    # its default order rather than returning an empty season - an empty
    # container is taken by Plex as authoritative.
    order_fallback = _bool('TVDB_ORDER_FALLBACK', True)
    # /test: one provider whose shows list their orders in SeasonType, so
    # Plex's own per-show Episode ordering setting chooses. Defaults to
    # aired order. Under test alongside the one-agent-per-order providers.
    test_provider = _bool('TVDB_TEST_PROVIDER', True)

    # --- matching ---
    language = _str('TVDB_LANGUAGE', 'eng')
    # Fall back to these in order when the requested language has no
    # translation for a field.
    language_fallbacks = _csv('TVDB_LANGUAGE_FALLBACKS', ('eng',))
    max_results = _int('TVDB_MAX_RESULTS', 20)
    max_page_size = _int('TVDB_MAX_PAGE_SIZE', 500)
    max_episode_pages = _int('TVDB_MAX_EPISODE_PAGES', 40)
    # Plex's scanner cannot be influenced by a provider at all, so a
    # {tvdb-nnnnn} id in the folder name is the only reliable way to pin a
    # stubborn show. Honoured from the title and the filename hints.
    match_by_id_hint = _bool('TVDB_MATCH_BY_ID_HINT', True)
    match_by_filename = _bool('TVDB_MATCH_BY_FILENAME', True)
    strip_path = _bool('TVDB_STRIP_PATH', True)

    # --- metadata shaping ---
    include_cast = _bool('TVDB_INCLUDE_CAST', True)
    include_crew = _bool('TVDB_INCLUDE_CREW', True)
    max_cast = _int('TVDB_MAX_CAST', 40)
    collections_from_networks = _bool('TVDB_COLLECTIONS_FROM_NETWORKS', False)
    collections_from_genres = _bool('TVDB_COLLECTIONS_FROM_GENRES', False)
    artwork_language_filter = _bool('TVDB_ARTWORK_LANGUAGE_FILTER', True)

    # --- service ---
    log_level = _str('TVDB_LOG_LEVEL', 'INFO')


config = Config()
