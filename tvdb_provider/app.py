"""Plex custom metadata provider for TheTVDB.

Plex is removing TheTVDB as a metadata source on 2026-12-03, and DVD and
absolute episode ordering exist in Plex only through it.

One provider, at /tvdb. Each show lists the TheTVDB orders it has, and
Plex shows them in that show's Episode ordering setting. Up to v1.0.0
there was one provider per order instead (/aired, /dvd, ...); those are
gone.

Implements the provider contract documented at
https://developer.plex.tv/pms/  (API Info -> Metadata Providers).
"""
import logging

from flask import Flask, jsonify

from .config import config
from . import series, tvdb

log = logging.getLogger(__name__)

PATH = '/tvdb'


def create_app():
    logging.basicConfig(
        level=getattr(logging, config.log_level.upper(), logging.INFO),
        format='%(asctime)s %(levelname)s %(name)s: %(message)s')

    app = Flask(__name__)
    app.register_blueprint(
        series.make_tv_provider('tvdb', config.identifier, config.title),
        url_prefix=PATH)

    @app.route('/health')
    def health():
        return jsonify({
            'status': 'ok',
            'apiKeyConfigured': bool(config.api_key),
            'pinConfigured': bool(config.pin),
            'language': config.language,
            'provider': {'path': PATH, 'identifier': config.identifier,
                         'title': config.title, 'version': config.version},
            'orderFallback': config.order_fallback,
            'cache': tvdb.cache_stats(),
            'selftest': '%s/selftest?q=<show>' % PATH,
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
                 'type': t.get('type')}
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

    log.info('provider %s registered at %s', config.identifier, PATH)
    return app
