"""The TV-shaped provider: one blueprint per episode ordering.

Plex's episode-ordering dropdown belongs to its own agents; the provider
contract exposes only `metadata` and `match`, so there is no way to add an
entry to it. What a provider *can* do is register more than one
identifier, so each TheTVDB season type is offered as its own agent:

    TheTVDB (Aired Order)      tv.plex.agents.custom.tvdb.aired
    TheTVDB (DVD Order)        tv.plex.agents.custom.tvdb.dvd
    TheTVDB (Absolute Order)   tv.plex.agents.custom.tvdb.absolute

Picking the agent is therefore picking the order - which is the choice
Plex is removing on 2026-12-03. TVDB_ORDER_OVERRIDES layers per-series
exceptions on top, so one library can mix orders.

Rating keys are prefixed so one metadata endpoint can dispatch on them:
    show-<seriesId>                e.g. show-121361
    season-<seriesId>-<seasonNo>   e.g. season-121361-3
    ep-<episodeId>                 e.g. ep-9123456
"""
import logging

from flask import Blueprint, jsonify, request

from .config import config, truthy
from . import mapping, tvdb

log = logging.getLogger(__name__)

SHOW, SEASON, EPISODE = 2, 3, 4


# --------------------------------------------------------------- keys / guids

def show_key(series_id):
    return 'show-%s' % mapping.safe_rating_key(series_id)


def season_key(series_id, season_no):
    return 'season-%s-%s' % (mapping.safe_rating_key(series_id), season_no)


def episode_key(episode_id):
    return 'ep-%s' % mapping.safe_rating_key(episode_id)


def parse_key(rating_key):
    """-> (kind, series_id|episode_id, season_no|None)

    An unparseable key yields (None, None, None) so the route can 404.
    Validating the season segment matters: 'season-121361' with no season
    number would otherwise rpartition into series_id='' and season='121361',
    look up series '', and answer with a ratingKey Plex never asked for -
    which Plex discards silently.
    """
    rating_key = mapping.text_of(rating_key)
    if rating_key.startswith('season-'):
        rest = rating_key[len('season-'):]
        series_id, _, season_no = rest.rpartition('-')
        if not series_id or not season_no.isdigit():
            return None, None, None
        return 'season', series_id, int(season_no)
    if rating_key.startswith('show-'):
        ident = rating_key[len('show-'):]
        return ('show', ident, None) if ident else (None, None, None)
    if rating_key.startswith('ep-'):
        ident = rating_key[len('ep-'):]
        return ('episode', ident, None) if ident else (None, None, None)
    return None, None, None


# ------------------------------------------------------------------- ordering

def resolve_order(series_id, default_order):
    """The season type to serve for one series.

    A per-series override wins over the provider's own order, so a single
    library can hold aired-order shows and absolute-order anime.
    """
    return config.order_overrides.get(mapping.text_of(series_id),
                                      default_order)


def ordered_episodes(series_id, order):
    """Episodes of a series in the wanted order, or None on failure.

    Falls back to the series' default order when the requested one holds
    nothing: TheTVDB's own note is that "episodes don't have to exist
    within every season type", and an empty season is read by Plex as
    authoritative rather than as something to retry.
    """
    rows = tvdb.series_episodes(series_id, order)
    if rows:
        return rows
    if rows is None:
        return None
    if config.order_fallback and order != 'default':
        log.info('series %s has no episodes in %r order; using default',
                 series_id, order)
        return tvdb.series_episodes(series_id, 'default')
    return []


def episode_numbers(ep, order):
    """-> (season_number, episode_number) as Plex should file it.

    In absolute order TheTVDB returns a continuous number and no
    meaningful season, so everything lands in season 1 - which is what
    absolute ordering means to Plex as well.
    """
    number = ep.get('number')
    if number is None:
        number = ep.get('episodeNumber')
    season_no = ep.get('seasonNumber')
    if order == 'absolute':
        absolute = ep.get('absoluteNumber') or number
        return 1, absolute
    if season_no is None:
        season_no = 1
    return season_no, number


# -------------------------------------------------------------------- mapping

def series_to_show(series, identifier, extended=None, translations=None,
                   order=None):
    series_id = series.get('id')
    rating_key = show_key(series_id)
    record = extended if isinstance(extended, dict) else series
    title = mapping.translated(record, translations, 'name') or ''

    item = {
        'ratingKey': rating_key,
        'key': '/library/metadata/%s' % rating_key,
        'guid': '%s://show/%s' % (identifier, rating_key),
        'type': 'show',
        'title': title,
    }

    overview = mapping.translated(record, translations, 'overview')
    if overview:
        item['summary'] = overview

    year = mapping.year_of(record)
    if year:
        item['year'] = year
    aired = mapping.date_of(record)
    if aired:
        item['originallyAvailableAt'] = aired

    status = record.get('status')
    if isinstance(status, dict) and status.get('name'):
        item['status'] = status['name']

    runtime = record.get('averageRuntime') or record.get('runtime')
    if isinstance(runtime, int) and runtime > 0:
        item['duration'] = runtime * 60000

    rating = record.get('contentRatings')
    if isinstance(rating, list) and rating:
        first = rating[0]
        if isinstance(first, dict) and first.get('name'):
            item['contentRating'] = first['name']

    networks = record.get('companies')
    if isinstance(networks, list):
        for company in networks:
            if isinstance(company, dict) and company.get('name'):
                item['studio'] = company['name']
                break
    if not item.get('studio'):
        network = record.get('originalNetwork')
        if isinstance(network, dict) and network.get('name'):
            item['studio'] = network['name']

    genres = mapping.tags_from(record, 'genres')
    if genres:
        item['Genre'] = genres
    roles = mapping.people_from(record)
    if roles:
        item['Role'] = roles

    images = mapping.images_for(record, title)
    if images:
        item['Image'] = images
        for img in images:
            if img['type'] == 'coverPoster' and 'thumb' not in item:
                item['thumb'] = img['url']
            if img['type'] == 'background' and 'art' not in item:
                item['art'] = img['url']

    collections = []
    if config.collections_from_networks and item.get('studio'):
        collections.append({'tag': item['studio']})
    if config.collections_from_genres:
        collections.extend(genres)
    if collections:
        item['Collection'] = collections

    # Useful for debugging a mismatched library: the order actually served.
    if order:
        item['slug'] = mapping.text_of(record.get('slug'))
    return item


def make_season(series, season_no, identifier, episode_count=None,
                series_id=None, poster=None):
    # The caller passes the id from the requested key so the response
    # echoes the ratingKey Plex asked for; rebuilding it from the record
    # would produce a different key on any alias or redirect, and Plex
    # discards a response whose key it did not request.
    if series_id is None:
        series_id = series.get('id')
    rating_key = season_key(series_id, season_no)
    parent_rk = show_key(series_id)
    series_title = mapping.text_of(series.get('name'))

    item = {
        'ratingKey': rating_key,
        'key': '/library/metadata/%s' % rating_key,
        'guid': '%s://season/%s' % (identifier, rating_key),
        'type': 'season',
        'title': 'Season %s' % season_no,
        'index': int(season_no),
        'parentRatingKey': parent_rk,
        'parentKey': '/library/metadata/%s' % parent_rk,
        'parentGuid': '%s://show/%s' % (identifier, parent_rk),
        'parentTitle': series_title,
        'parentType': 'show',
    }
    if episode_count is not None:
        item['leafCount'] = episode_count
    # Only a poster the caller already language-ranked. Taking
    # series['image'] directly is how Arabic and Bulgarian posters reached
    # a library whose shows had English ones: the base field carries no
    # language, so it bypassed the filter entirely.
    if poster:
        item['thumb'] = poster
    return item


def episode_to_item(ep, identifier, order, series=None, translations=None):
    episode_id = ep.get('id')
    rating_key = episode_key(episode_id)
    series_id = ep.get('seriesId') or (series or {}).get('id')
    season_no, number = episode_numbers(ep, order)

    parent_rk = season_key(series_id, season_no)
    grandparent_rk = show_key(series_id)

    item = {
        'ratingKey': rating_key,
        'key': '/library/metadata/%s' % rating_key,
        'guid': '%s://episode/%s' % (identifier, rating_key),
        'type': 'episode',
        'title': mapping.translated(ep, translations, 'name') or '',
        'parentRatingKey': parent_rk,
        'parentKey': '/library/metadata/%s' % parent_rk,
        'parentGuid': '%s://season/%s' % (identifier, parent_rk),
        'parentIndex': int(season_no),
        'parentType': 'season',
        'grandparentRatingKey': grandparent_rk,
        'grandparentKey': '/library/metadata/%s' % grandparent_rk,
        'grandparentGuid': '%s://show/%s' % (identifier, grandparent_rk),
        'grandparentType': 'show',
    }
    if number is not None:
        item['index'] = int(number)
    if series and series.get('name'):
        item['grandparentTitle'] = mapping.text_of(series['name'])

    overview = mapping.translated(ep, translations, 'overview')
    if overview:
        item['summary'] = overview
    aired = mapping.date_of(ep)
    if aired:
        item['originallyAvailableAt'] = aired
        if aired[:4].isdigit():
            item['year'] = int(aired[:4])

    runtime = ep.get('runtime')
    if isinstance(runtime, int) and runtime > 0:
        item['duration'] = runtime * 60000

    absolute = ep.get('absoluteNumber')
    if isinstance(absolute, int) and absolute > 0:
        item['absoluteIndex'] = absolute

    still = mapping._image_url(ep.get('image'))
    if still:
        item['thumb'] = still
        item['Image'] = [{'type': 'snapshot', 'url': still,
                          'alt': item['title']}]
    return item


# ------------------------------------------------------------------- plumbing

def container(items, identifier, offset=0, total=None):
    items = items if isinstance(items, list) else [items]
    return jsonify({'MediaContainer': {
        'identifier': identifier,
        'size': len(items),
        'totalSize': len(items) if total is None else total,
        'offset': offset,
        'Metadata': items,
    }})


def paging():
    """Plex sends X-Plex-Container-Start/Size as QUERY PARAMETERS on GETs,
    not only as headers. Reading headers alone makes every children page
    return the same slice, and Plex will walk offsets 0..580 receiving
    identical bodies without ever complaining."""
    def _int(name, default):
        raw = request.args.get(name)
        if raw is None:
            raw = request.headers.get(name)
        try:
            return int(raw)
        except (TypeError, ValueError):
            return default

    start = max(0, _int('X-Plex-Container-Start', 0))
    size = _int('X-Plex-Container-Size', config.max_results)
    # max(0, ...): Plex sends Size=0 to read totalSize cheaply, and
    # clamping that to 1 returns an item it did not ask for.
    return start, max(0, min(size, config.max_page_size))


def children_block(items):
    """Plex wants Children as a CONTAINER, not a bare array.

    A list fails the *whole* response with
    'failed to parse JSON response: object expected at 1:NN', NN being the
    byte offset of the offending '[' - so every season match is discarded
    and no episode can ever bind.
    """
    return {'size': len(items), 'Metadata': items}


def wants_children():
    # One truthy definition everywhere. Two that disagreed about 'True'
    # meant includeChildren was honoured on one route and ignored on
    # another, and a season returned without children binds nothing.
    return truthy(request.args.get('includeChildren'))


def season_posters(series_id, order):
    """season number -> best poster URL, for the order being served.

    Two details matter. The extended record's `seasons` array is **per
    season type**, so a DVD-ordered library must read the dvd rows or it
    numbers posters against the aired seasons. And season artwork (type 7)
    carries a `seasonId`, so the best language-ranked poster can be picked
    per season rather than falling back to the series image - which is
    what was happening when wrong-language posters appeared.
    """
    extended = tvdb.series_extended(series_id)
    if not isinstance(extended, dict):
        return {}

    prefer = [config.language] + [l for l in config.language_fallbacks
                                  if l != config.language]

    best = {}
    for art in (extended.get('artworks') or []):
        if not isinstance(art, dict) or art.get('type') != 7:
            continue
        sid = art.get('seasonId')
        url = mapping._image_url(art.get('image'))
        if not sid or not url:
            continue
        rank = (mapping._lang_rank(art.get('language'), prefer),
                -(art.get('score') or 0))
        if sid not in best or rank < best[sid][0]:
            best[sid] = (rank, url)

    rows = [s for s in (extended.get('seasons') or []) if isinstance(s, dict)]

    def season_type_of(row):
        kind = row.get('type')
        return kind.get('type') if isinstance(kind, dict) else None

    want = None if order == 'default' else order
    matching = [s for s in rows if season_type_of(s) == want] if want else []
    if not matching:
        matching = rows

    out = {}
    for row in matching:
        number = row.get('number')
        if number is None:
            continue
        chosen = best.get(row.get('id'))
        url = chosen[1] if chosen else mapping._image_url(row.get('image'))
        if url:
            out[int(number)] = url
    return out


def seasons_from(episodes, order):
    """Season numbers and their episode counts, from the ordered list."""
    counts = {}
    for ep in episodes:
        season_no, _ = episode_numbers(ep, order)
        if season_no is None:
            continue
        counts[int(season_no)] = counts.get(int(season_no), 0) + 1
    return counts


# --------------------------------------------------------------- the provider

def make_tv_provider(name, identifier, title, order):
    """One TV provider bound to one TheTVDB season type.

    Registered once per order, so the agent dropdown in Plex becomes the
    ordering picker.
    """
    bp = Blueprint(name, __name__)

    def box(items, offset=0, total=None):
        return container(items, identifier, offset, total)

    def not_found():
        # Never an empty 200. Plex treats an empty container as
        # authoritative and stops; an error it will retry.
        return jsonify({'error': 'not found'}), 404

    def unavailable():
        """503 when the upstream is unusable, rather than 'no results'.

        An auth failure answering an empty match container tells Plex
        there is genuinely no such show - which it believes, skipping the
        item and reverting the library to its built-in agent. A 5xx it
        retries instead.
        """
        return jsonify({
            'error': 'upstream unavailable',
            'detail': 'could not authenticate to TheTVDB; check '
                      'TVDB_API_KEY and TVDB_PIN',
        }), 503

    def upstream_down():
        return not tvdb.login()

    def load_series(series_id):
        """Extended record (+ translation), falling back to the base one.

        The extended record is a superset - name, overview, artworks,
        characters, genres - so fetching the base record as well was a
        third upstream call per show for nothing. Only asked for if
        extended is unavailable.
        """
        extended = tvdb.series_extended(series_id)
        base = extended or tvdb.series(series_id)
        if not base:
            return None, None, None
        translations = tvdb.series_translation(series_id, config.language)
        return base, extended, translations

    @bp.route('', methods=['GET'])
    @bp.route('/', methods=['GET'])
    def manifest():
        schemes = [{'scheme': identifier}]
        return jsonify({'MediaProvider': {
            'identifier': identifier,
            'title': title,
            'version': config.version,
            'Types': [
                {'type': SHOW, 'Scheme': schemes},
                {'type': SEASON, 'Scheme': schemes},
                {'type': EPISODE, 'Scheme': schemes},
            ],
            'Feature': [
                {'type': 'metadata', 'key': '/library/metadata'},
                {'type': 'match', 'key': '/library/metadata/matches'},
            ],
        }})

    # ------------------------------------------------------------- matching

    def series_from_hints(hints):
        """A series id from an explicit guid or an id hint, else None."""
        if not config.match_by_id_hint:
            return None
        found = mapping.guid_tvdb_id(hints, identifier)
        if found:
            return found
        for keys in (mapping.TITLE_KEYS, mapping.FILE_KEYS):
            found = mapping.extract_tvdb_id(mapping.hint(hints, keys))
            if found:
                return found
        # A folder carrying only {imdb-...} or {tmdb-...} still resolves,
        # which is common for Sonarr-managed libraries.
        for keys in (mapping.TITLE_KEYS, mapping.FILE_KEYS):
            remote = mapping.extract_remote_id(mapping.hint(hints, keys))
            if not remote:
                continue
            for row in tvdb.search_remote_id(remote):
                record = row.get('series') if isinstance(row, dict) else None
                if isinstance(record, dict) and record.get('id'):
                    return record['id']
                if isinstance(row, dict) and row.get('tvdb_id'):
                    return row['tvdb_id']
        return None

    def match_show(hints):
        series_id = series_from_hints(hints)
        if series_id:
            base, extended, translations = load_series(series_id)
            if not base:
                return box([])
            item = series_to_show(base, identifier, extended, translations,
                                  order)
            item['score'] = 100
            return box([item])

        query = mapping.clean_title(mapping.hint(hints, mapping.TITLE_KEYS))
        if not query and config.match_by_filename:
            query = mapping.clean_title(mapping.hint(hints, mapping.FILE_KEYS))
        if not query:
            return box([])

        year = mapping.hint_year(hints)
        results = tvdb.search(query, year=year)
        if not results and year:
            # A wrong year in a folder name should not cost the match.
            results = tvdb.search(query)

        items = []
        for idx, row in enumerate(results):
            if not isinstance(row, dict):
                continue
            series_id = row.get('tvdb_id') or row.get('id')
            if not series_id:
                continue
            series_id = mapping.text_of(series_id).split('-')[-1]
            item = {
                'ratingKey': show_key(series_id),
                'key': '/library/metadata/%s' % show_key(series_id),
                'guid': '%s://show/%s' % (identifier, show_key(series_id)),
                'type': 'show',
                'title': mapping.text_of(row.get('name')),
                'score': max(1, 100 - idx * 2),
            }
            year_value = mapping.text_of(row.get('year'))
            if year_value.isdigit():
                item['year'] = int(year_value)
            overview = row.get('overview')
            if isinstance(overview, str) and overview:
                item['summary'] = overview
            thumb = mapping._image_url(row.get('image_url')) or \
                mapping._image_url(row.get('thumbnail'))
            if thumb:
                item['thumb'] = thumb
            items.append(item)

        start, size = paging()
        # Truncate to the automatic-match cap BEFORE paging and report the
        # true size. Truncating to the page size first made every page
        # after the first empty while totalSize reported the truncated
        # count.
        if not hints.get('manual'):
            items = items[:config.max_results]
        total = len(items)
        return box(items[start:start + size], offset=start, total=total)

    def match_season(hints):
        series_id = series_from_hints(hints)
        if not series_id:
            parent = mapping.hint(hints, ('parentGuid', 'grandparentGuid'))
            series_id = mapping.extract_tvdb_id(parent) or \
                mapping.guid_tvdb_id({'guid': parent}, identifier)
        if not series_id:
            return box([])

        try:
            season_no = int(mapping.hint(hints, ('index', 'season',
                                                 'seasonNumber')) or 0)
        except (TypeError, ValueError):
            season_no = 0

        base = tvdb.series(series_id)
        if not base:
            return box([])

        wanted = resolve_order(series_id, order)
        episodes = ordered_episodes(series_id, wanted)
        if episodes is None:
            return box([])

        in_season = [e for e in episodes
                     if episode_numbers(e, wanted)[0] == season_no]
        item = make_season(base, season_no, identifier, len(in_season),
                           series_id,
                           season_posters(series_id, wanted).get(season_no))
        item['score'] = 100
        # Plex sends includeChildren=1 on the season match and binds its
        # files to the children in that response. A season returned
        # without its episodes binds nothing at all.
        if truthy(hints.get('includeChildren')) or wants_children():
            translations = None
            item['Children'] = children_block(
                [episode_to_item(e, identifier, wanted, base, translations)
                 for e in in_season])
        return box([item])

    def match_episode(hints):
        # Plex does not currently send a type 4 match - it matches the show,
        # then the season with includeChildren=1, and binds files to those
        # children. Implemented anyway so the route is not a silent hole.
        episode_id = mapping.extract_tvdb_id(
            mapping.hint(hints, mapping.TITLE_KEYS))
        if not episode_id:
            return box([])
        ep = tvdb.episode(episode_id)
        if not ep:
            return box([])
        item = episode_to_item(ep, identifier, order)
        item['score'] = 100
        return box([item])

    @bp.route('/library/metadata/matches', methods=['POST'])
    def matches():
        hints = request.get_json(silent=True) or {}
        if not hints:
            hints = request.form.to_dict() or request.args.to_dict()
        log.debug('[%s] match hints: %s', name, hints)

        if upstream_down():
            return unavailable()

        try:
            mtype = int(hints.get('type') or 0)
        except (TypeError, ValueError):
            mtype = 0

        if mtype == SHOW:
            return match_show(hints)
        if mtype == SEASON:
            return match_season(hints)
        if mtype == EPISODE:
            return match_episode(hints)
        return box([])

    # ------------------------------------------------------------- metadata

    @bp.route('/library/metadata/<rating_key>', methods=['GET'])
    def metadata(rating_key):
        kind, ident, season_no = parse_key(rating_key)

        # A bad key is the caller's fault whatever the upstream is doing,
        # so it answers 404 before the auth check.
        if kind is None:
            return jsonify({'error': 'unrecognised rating key'}), 404
        if upstream_down():
            return unavailable()

        if kind == 'show':
            base, extended, translations = load_series(ident)
            if not base:
                return not_found()
            item = series_to_show(base, identifier, extended, translations,
                                  order)
            if wants_children():
                wanted = resolve_order(ident, order)
                episodes = ordered_episodes(ident, wanted)
                if episodes is None:
                    return not_found()
                counts = seasons_from(episodes, wanted)
                posters = season_posters(ident, wanted)
                # Plex asks for the show with includeChildren=1 and expects
                # the seasons inline; a bare show reads as having none, so
                # nothing underneath can ever match.
                item['Children'] = children_block(
                    [make_season(base, no, identifier, counts[no], ident,
                                 posters.get(no))
                     for no in sorted(counts)])
            return box([item])

        if kind == 'season':
            base = tvdb.series(ident)
            if not base:
                return not_found()
            wanted = resolve_order(ident, order)
            episodes = ordered_episodes(ident, wanted)
            if episodes is None:
                return not_found()
            in_season = [e for e in episodes
                         if episode_numbers(e, wanted)[0] == season_no]
            item = make_season(base, season_no, identifier, len(in_season),
                               ident,
                               season_posters(ident, wanted).get(season_no))
            if wants_children():
                item['Children'] = children_block(
                    [episode_to_item(e, identifier, wanted, base)
                     for e in in_season])
            return box([item])

        if kind == 'episode':
            ep = tvdb.episode_extended(ident) or tvdb.episode(ident)
            if not ep:
                return not_found()
            translations = tvdb.episode_translation(ident, config.language)
            series_id = ep.get('seriesId')
            base = tvdb.series(series_id) if series_id else None
            wanted = resolve_order(series_id, order) if series_id else order
            return box([episode_to_item(ep, identifier, wanted, base,
                                        translations)])

        return jsonify({'error': 'unrecognised rating key'}), 404

    @bp.route('/library/metadata/<rating_key>/children', methods=['GET'])
    def children(rating_key):
        kind, ident, season_no = parse_key(rating_key)
        start, size = paging()

        # An unparseable key is not an empty collection. A 200 with an
        # empty container tells Plex the thing exists and is empty, which
        # it takes as final.
        if kind is None:
            return jsonify({'error': 'unrecognised rating key'}), 404
        if upstream_down():
            return unavailable()

        if kind == 'show':
            base = tvdb.series(ident)
            if not base:
                return not_found()
            wanted = resolve_order(ident, order)
            episodes = ordered_episodes(ident, wanted)
            if episodes is None:
                return not_found()
            counts = seasons_from(episodes, wanted)
            posters = season_posters(ident, wanted)
            seasons = [make_season(base, no, identifier, counts[no], ident,
                                   posters.get(no))
                       for no in sorted(counts)]
            return box(seasons[start:start + size], offset=start,
                       total=len(seasons))

        if kind == 'season':
            base = tvdb.series(ident)
            if not base:
                return not_found()
            wanted = resolve_order(ident, order)
            episodes = ordered_episodes(ident, wanted)
            if episodes is None:
                return not_found()
            in_season = [e for e in episodes
                         if episode_numbers(e, wanted)[0] == season_no]
            page = [episode_to_item(e, identifier, wanted, base)
                    for e in in_season[start:start + size]]
            return box(page, offset=start, total=len(in_season))

        if kind is None:
            # An unparseable key is not an empty collection. A 200 with an
            # empty container tells Plex the thing exists and is empty,
            # which it takes as final.
            return jsonify({'error': 'unrecognised rating key'}), 404
        return box([], total=0)

    @bp.route('/library/metadata/<rating_key>/grandchildren', methods=['GET'])
    def grandchildren(rating_key):
        kind, ident, _ = parse_key(rating_key)
        start, size = paging()

        if kind is None:
            return jsonify({'error': 'unrecognised rating key'}), 404
        if kind != 'show':
            return box([], total=0)
        if upstream_down():
            return unavailable()

        base = tvdb.series(ident)
        if not base:
            return not_found()
        wanted = resolve_order(ident, order)
        episodes = ordered_episodes(ident, wanted)
        if episodes is None:
            return not_found()
        page = [episode_to_item(e, identifier, wanted, base)
                for e in episodes[start:start + size]]
        return box(page, offset=start, total=len(episodes))

    @bp.route('/library/metadata/<rating_key>/extras', methods=['GET'])
    def extras(rating_key):
        # Plex asks every show for extras; an empty container beats a 404.
        return box([], total=0)

    @bp.route('/library/metadata/<rating_key>/images', methods=['GET'])
    def images(rating_key):
        """Artwork for an item.

        Plex asks for this on every show and retries hard on a 404 - eight
        times in a row for one series in the first test library - so it
        answers a container even when there is no art to give.
        """
        kind, ident, _ = parse_key(rating_key)
        if kind is None:
            return jsonify({'error': 'unrecognised rating key'}), 404

        art = []
        if kind == 'episode':
            ep = tvdb.episode(ident)
            if ep:
                art = mapping.images_for(ep, mapping.text_of(ep.get('name')))
        elif kind in ('show', 'season'):
            # The extended record carries the full artworks array; the base
            # record only has one poster.
            record = tvdb.series_extended(ident) or tvdb.series(ident)
            if record:
                art = mapping.images_for(
                    record, mapping.text_of(record.get('name')))

        return jsonify({'MediaContainer': {
            'identifier': identifier,
            'size': len(art),
            'totalSize': len(art),
            'offset': 0,
            'Image': art,
        }})

    @bp.route('/selftest', methods=['GET'])
    def selftest_route():
        from . import selftest
        report = selftest.run(request.args.get('q') or 'Breaking Bad',
                              identifier=identifier, order=order)
        return jsonify(report), 200 if report.get('status') == 'ok' else 503

    return bp
