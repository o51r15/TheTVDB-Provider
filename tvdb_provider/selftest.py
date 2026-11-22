"""Validate the upstream contract with real API calls.

Exists because the failure that matters most is silent: if a provider
answers an empty container, Plex logs 'Primary provider failed to return a
result, skipping item' and quietly reverts the library to its built-in
agent. By then the symptom is 'Plex ignored my provider', which says
nothing about the cause. This walks the whole chain and names the step
that broke.
"""
from .config import config
from . import mapping, series, tvdb


def run(query, identifier=None, order='default'):
    report = {
        'query': query,
        'order': order,
        'identifier': identifier or config.identifier,
        'apiKeyConfigured': bool(config.api_key),
        'pinConfigured': bool(config.pin),
        'steps': {},
    }
    steps = report['steps']

    # 1. auth
    token = tvdb.login()
    steps['login'] = 'ok' if token else 'failed'
    if not token:
        report['status'] = 'error'
        report['error'] = ('authentication failed - check TVDB_API_KEY and '
                           'TVDB_PIN (a project key needs a subscriber PIN)')
        return report

    # 2. the order exists upstream
    types = tvdb.season_types()
    known = [t.get('type') for t in types if isinstance(t, dict)]
    steps['seasonTypes'] = known or 'failed'
    if known and order != 'default' and order not in known:
        report['status'] = 'error'
        report['error'] = ('%r is not a season type TheTVDB offers (%s)'
                           % (order, ', '.join(str(k) for k in known)))
        return report

    # 3. search
    results = tvdb.search(query)
    steps['search'] = {'resultCount': len(results)}
    if not results:
        report['status'] = 'error'
        report['error'] = 'search returned nothing for %r' % query
        return report

    first = results[0] if isinstance(results[0], dict) else {}
    series_id = mapping.text_of(first.get('tvdb_id')
                                or first.get('id')).split('-')[-1]
    steps['search']['seriesId'] = series_id
    steps['search']['name'] = mapping.text_of(first.get('name'))
    if not series_id:
        report['status'] = 'error'
        report['error'] = 'first search result carried no usable series id'
        return report

    # 4. series record
    base = tvdb.series(series_id)
    steps['series'] = 'ok' if base else 'failed'
    if not base:
        report['status'] = 'error'
        report['error'] = 'series %s could not be read' % series_id
        return report

    # 5. episodes in the requested order - the point of the provider
    wanted = series.resolve_order(series_id, order)
    episodes = series.ordered_episodes(series_id, wanted)
    if episodes is None:
        report['status'] = 'error'
        report['error'] = ('episode list for %s in %r order could not be '
                           'read' % (series_id, wanted))
        return report

    seasons = series.seasons_from(episodes, wanted)
    steps['episodes'] = {
        'orderServed': wanted,
        'count': len(episodes),
        'seasons': {str(k): v for k, v in sorted(seasons.items())},
    }
    if not episodes:
        report['status'] = 'error'
        report['error'] = ('no episodes in %r order, and no fallback '
                           '(TVDB_ORDER_FALLBACK is off)' % wanted)
        return report

    # 6. the mapped documents Plex will actually receive
    ident = report['identifier']
    extended = tvdb.series_extended(series_id)
    show = series.series_to_show(base, ident, extended, None, wanted)
    sample = series.episode_to_item(episodes[0], ident, wanted, base)

    missing = [f for f in ('ratingKey', 'guid', 'type', 'title')
               if not show.get(f)]
    missing += ['episode.%s' % f for f in
                ('ratingKey', 'guid', 'type', 'parentRatingKey',
                 'grandparentRatingKey') if not sample.get(f)]
    steps['mapped'] = {
        'show': {'ratingKey': show.get('ratingKey'),
                 'title': show.get('title'),
                 'year': show.get('year'),
                 'seasons': len(seasons)},
        'firstEpisode': {'ratingKey': sample.get('ratingKey'),
                         'title': sample.get('title'),
                         'parentIndex': sample.get('parentIndex'),
                         'index': sample.get('index'),
                         'absoluteIndex': sample.get('absoluteIndex')},
        'missingFields': missing,
    }

    report['status'] = 'error' if missing else 'ok'
    if missing:
        report['error'] = 'mapped documents are missing: %s' % ', '.join(
            missing)
    return report
