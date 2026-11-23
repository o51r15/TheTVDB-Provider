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
  only through it. The order is chosen per show in Plex itself, so it is
  not configured here.
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
    version = _str('TVDB_VERSION', '1.0.1')

    # --- ordering ---
    # Each show lists its orders to Plex and Plex picks one per show, so
    # there is nothing to configure here except the fallback: when a show
    # has no aired-order episodes, serve its default order rather than an
    # empty show - Plex takes an empty container as final.
    order_fallback = _bool('TVDB_ORDER_FALLBACK', True)
    # Only list an alternate order (DVD, absolute, ...) when it contains
    # every released aired episode. Off (the default) lists partial orders
    # as well, and picking one leaves the missing episodes without metadata.
    full_orders_only = _bool('TVDB_FULL_ORDERS_ONLY', False)

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
