"""Plex custom metadata providers for TheTVDB.

Plex is removing TheTVDB as a metadata source on 2026-12-03, and DVD and
absolute episode ordering exist in Plex only through it. TMDB episode
groups are the stated replacement, with no ship date and no promise that
they reproduce every TheTVDB order.

A provider cannot add an entry to Plex's episode-ordering dropdown - the
contract exposes only `metadata` and `match`. So each season type is
registered as its own provider instead, and choosing the agent becomes
choosing the order:

    /aired      TheTVDB (Aired Order)
    /dvd        TheTVDB (DVD Order)
    /absolute   TheTVDB (Absolute Order)
    /alternate  TheTVDB (Alternate Order)

Implements the provider contract documented at
https://developer.plex.tv/pms/  (API Info -> Metadata Providers).
"""
import logging

from flask import Flask, jsonify

from .config import config
from . import series, tvdb

log = logging.getLogger(__name__)

# season type -> (url path, blueprint name, human label)
#
# These are TheTVDB's real season types, read from /seasons/types rather
# than assumed: aired order is the type 'official' (id 1), and there are
# two more alternates than the obvious list suggests.
#
#   id=1 official   Aired Order          id=5 regional  Regional Order
#   id=2 dvd        DVD Order            id=6 altdvd    Alternate DVD Order
#   id=3 absolute   Absolute Order       id=7 alttwo    Alternate Order 2
#   id=4 alternate  Alternate Order
#
# 'default' is not a type - it is TheTVDB's shorthand for whichever order
# a given series calls its own. Offered separately for anyone who wants
# that rather than a fixed order.
ORDERS = {
    'official': ('/aired', 'aired', 'Aired Order'),
    'dvd': ('/dvd', 'dvd', 'DVD Order'),
    'absolute': ('/absolute', 'absolute', 'Absolute Order'),
    'alternate': ('/alternate', 'alternate', 'Alternate Order'),
    'regional': ('/regional', 'regional', 'Regional Order'),
    'altdvd': ('/altdvd', 'altdvd', 'Alternate DVD Order'),
    'alttwo': ('/alttwo', 'alttwo', 'Alternate Order 2'),
    'default': ('/default', 'default', 'Series Default Order'),
}

# Accepted spellings for the same thing, so TVDB_ORDER_PROVIDERS=aired
# does what it looks like it does.
ALIASES = {'aired': 'official', 'air': 'official', 'tvdb': 'official'}

# Registered when TVDB_ORDER_PROVIDERS is unset: aired, plus the two
# orders Plex is actually taking away, plus alternate for the anime that
# uses it.
DEFAULT_ORDERS = ('official', 'dvd', 'absolute', 'alternate')


def create_app():
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    app = Flask(__name__)
    registered = {}

    wanted = config.order_providers or list(DEFAULT_ORDERS)
    for order in wanted:
        order = order.strip().lower()
        order = ALIASES.get(order, order)
        if order not in ORDERS:
            log.warning('TVDB_ORDER_PROVIDERS: unknown order %r, skipping '
                        '(known: %s)', order, ', '.join(sorted(ORDERS)))
            continue
        path, name, label = ORDERS[order]
        identifier = '%s.%s' % (config.identifier, name)
        title = '%s (%s)' % (config.title, label)
        if name in registered:
            continue
        app.register_blueprint(
            series.make_tv_provider(name, identifier, title, order),
            url_prefix=path)
        registered[name] = {
            'path': path,
            'identifier': identifier,
            'title': title,
            'seasonType': order,
        }

    if config.test_provider:
        identifier = '%s.test' % config.identifier
        title = '%s (Test - Selectable Order)' % config.title
        app.register_blueprint(
            series.make_tv_provider('test', identifier, title, 'official',
                                    selectable=True),
            url_prefix='/test')
        registered['test'] = {
            'path': '/test',
            'identifier': identifier,
            'title': title,
            'seasonType': 'selectable (default official)',
        }

    if not registered:
        log.error('no providers registered; check TVDB_ORDER_PROVIDERS')

    @app.route('/health')
    def health():
        return jsonify({
            'status': 'ok',
            'apiKeyConfigured': bool(config.api_key),
            'pinConfigured': bool(config.pin),
            'language': config.language,
            'providers': registered,
            'orderOverrides': config.order_overrides,
            'orderFallback': config.order_fallback,
            'cache': tvdb.cache_stats(),
            'selftest': '%s/selftest?q=<show>' % (
                list(registered.values())[0]['path'] if registered else ''),
        })

    @app.route('/orders')
    def orders():
        """TheTVDB's season types, live.

        Doubles as the cheapest proof that the key and PIN work: it is an
        authenticated call that needs no series id.
        """
        types = tvdb.season_types()
        if not types:
            return jsonify({
                'status': 'error',
                'error': 'could not read /seasons/types - check '
                         'TVDB_API_KEY and TVDB_PIN',
            }), 503
        return jsonify({
            'status': 'ok',
            'seasonTypes': [
                {'id': t.get('id'),
                 'name': t.get('name'),
                 'type': t.get('type'),
                 'registered': t.get('type') in
                 [v['seasonType'] for v in registered.values()]}
                for t in types if isinstance(t, dict)
            ],
        })

    @app.errorhandler(400)
    def bad_request(err):
        return jsonify({'error': 'bad request'}), 400

    @app.errorhandler(404)
    def not_found(err):
        return jsonify({'error': 'not found'}), 404

    @app.errorhandler(500)
    def server_error(err):
        log.exception('unhandled error')
        return jsonify({'error': 'internal error'}), 500

    # Try the credentials now rather than guessing about them. A warning
    # that TVDB_PIN is unset is misleading on a licensed key, which works
    # without one; and a key that is wrong is better discovered at boot
    # than on the first library scan.
    if not config.api_key:
        log.warning('TVDB_API_KEY is not set - upstream requests will fail')
    elif tvdb.login():
        log.info('TheTVDB credentials accepted (PIN %s)',
                 'supplied' if config.pin else 'not needed')
    elif not config.pin:
        log.error('TheTVDB rejected the API key and no TVDB_PIN is set - a '
                  'user-supported project key needs each subscriber PIN')
    else:
        log.error('TheTVDB rejected the API key and PIN')

    log.info('registered %d provider(s): %s', len(registered),
             ', '.join(sorted(registered)))
    return app
