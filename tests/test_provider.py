"""Config, mapping and client tests.

Each test here corresponds to something that actually broke, either in
this provider or in the ThePornDB one it is modelled on. Run directly:

    python3 tests/test_provider.py
"""
import importlib
import os
import sys
import unittest

# Defaults left alone so the TTL-tier assertions mean something; the
# cache tests use their own Cache instance rather than the module's.
os.environ.update({'TVDB_API_KEY': 'k'})
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                '..'))

from tvdb_provider import cache_core, mapping, tvdb  # noqa: E402
from tvdb_provider import config as config_mod  # noqa: E402


def reload_config(**env):
    """Re-import config under a given environment.

    Settings are evaluated at class-definition time, so changing one means
    reloading the module.
    """
    saved = {k: os.environ.get(k) for k in env}
    os.environ.update({k: v for k, v in env.items() if v is not None})
    for k, v in env.items():
        if v is None:
            os.environ.pop(k, None)
    try:
        return importlib.reload(config_mod)
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


class ConfigTest(unittest.TestCase):
    def test_one_truthy_definition(self):
        # tv.py in the ThePornDB provider had two that disagreed about
        # 'True', so includeChildren was honoured on one route and ignored
        # on another, and a season without children binds nothing.
        for value in ('1', 'true', 'TRUE', 'True', 'yes', 'on', ' on '):
            self.assertTrue(config_mod.truthy(value), value)
        for value in ('0', 'false', 'no', 'off', '', 'maybe', None):
            self.assertFalse(config_mod.truthy(value), value)

    def test_bad_int_falls_back_instead_of_crashing(self):
        # These were int(_str(...)) at class-definition time, so one
        # non-numeric value killed the container at import with a bare
        # ValueError naming no variable.
        cfg = reload_config(TVDB_TIMEOUT='not-a-number')
        self.assertEqual(cfg.config.timeout, 30)
        reload_config(TVDB_TIMEOUT=None)



class CoercionTest(unittest.TestCase):
    def test_text_of_never_raises(self):
        # A field that is usually text arrives as a number or None often
        # enough that .strip() on it is a 500.
        self.assertEqual(mapping.text_of('x'), 'x')
        self.assertEqual(mapping.text_of(None), '')
        self.assertEqual(mapping.text_of(7), '7')
        self.assertEqual(mapping.text_of(0), '0')

    def test_date_of_tries_every_tvdb_spelling(self):
        self.assertEqual(mapping.date_of({'aired': '2002-09-20'}),
                         '2002-09-20')
        self.assertEqual(mapping.date_of({'firstAired': '2002-09-20'}),
                         '2002-09-20')
        # Truncates a datetime, and survives a null on an unaired episode.
        self.assertEqual(mapping.date_of({'aired': '2002-09-20T01:00:00Z'}),
                         '2002-09-20')
        self.assertEqual(mapping.date_of({'aired': None}), '')
        self.assertEqual(mapping.date_of({}), '')
        self.assertEqual(mapping.date_of(None), '')

    def test_safe_rating_key(self):
        # Plex accepts only [a-zA-Z0-9_-]; anything else and the GUID it
        # builds is rejected, which shows up as the item never matching
        # with nothing in the log to say why.
        self.assertEqual(mapping.safe_rating_key('78874'), '78874')
        self.assertEqual(mapping.safe_rating_key('a b/c'), 'a-b-c')
        self.assertEqual(mapping.safe_rating_key(78874), '78874')


class HintTest(unittest.TestCase):
    def test_hint_reads_every_spelling(self):
        # The same field arrives as title or name, filename or file,
        # depending on library type. Reading one spelling only makes every
        # lookup answer an empty container, and Plex then reverts the
        # library to its built-in agent.
        self.assertEqual(mapping.hint({'title': 'A'}, mapping.TITLE_KEYS), 'A')
        self.assertEqual(mapping.hint({'name': 'B'}, mapping.TITLE_KEYS), 'B')
        self.assertEqual(mapping.hint({'file': '/x/y.mkv'},
                                      mapping.FILE_KEYS), '/x/y.mkv')
        self.assertEqual(mapping.hint({'filename': 'z.mkv'},
                                      mapping.FILE_KEYS), 'z.mkv')
        self.assertEqual(mapping.hint({}, mapping.TITLE_KEYS), '')
        self.assertEqual(mapping.hint(None, mapping.TITLE_KEYS), '')

    def test_hint_skips_empty_values(self):
        self.assertEqual(
            mapping.hint({'title': '', 'name': 'real'}, mapping.TITLE_KEYS),
            'real')

    def test_extract_tvdb_id(self):
        for text in ('Firefly (2002) {tvdb-78874}', '{tvdb-78874}',
                     'tvdb-78874', 'Show {tvdb_78874}'):
            self.assertEqual(mapping.extract_tvdb_id(text), '78874', text)
        self.assertIsNone(mapping.extract_tvdb_id('Firefly (2002)'))

    def test_extract_remote_id(self):
        # Sonarr-managed folders routinely carry an IMDb or TMDB id and no
        # TVDB one; TheTVDB resolves either via /search/remoteid.
        self.assertEqual(mapping.extract_remote_id('X {imdb-tt0303461}'),
                         'tt0303461')
        self.assertEqual(mapping.extract_remote_id('X {tmdb-1437}'), '1437')
        self.assertIsNone(mapping.extract_remote_id('X'))

    def test_guid_tvdb_id(self):
        ident = 'tv.plex.agents.custom.tvdb.dvd'
        self.assertEqual(
            mapping.guid_tvdb_id({'guid': ident + '://show/show-78874'},
                                 ident), '78874')
        self.assertEqual(
            mapping.guid_tvdb_id({'guid': ident + '://season/season-78874-3'},
                                 ident), '78874')
        self.assertIsNone(mapping.guid_tvdb_id({'guid': 'other://x/1'},
                                               ident))

    def test_clean_title(self):
        cases = {
            '/data/TV/Firefly (2002)/Firefly - S01E01.mkv': 'Firefly',
            'Firefly (2002) {tvdb-78874}': 'Firefly',
            'Breaking.Bad.S02E05.mkv': 'Breaking Bad',
            'Season 3': '',
            'Firefly': 'Firefly',
        }
        for raw, want in cases.items():
            self.assertEqual(mapping.clean_title(raw), want, raw)

    def test_hint_year(self):
        self.assertEqual(mapping.hint_year({'year': '2002'}), '2002')
        self.assertEqual(mapping.hint_year({'title': 'Firefly (2002)'}),
                         '2002')
        self.assertEqual(
            mapping.hint_year({'originallyAvailableAt': '2002-09-20'}),
            '2002')
        self.assertIsNone(mapping.hint_year({'title': 'Firefly'}))


class ImageTest(unittest.TestCase):
    def test_image_url_accepts_string_or_object(self):
        # TheTVDB image fields are sometimes a URL and sometimes an object.
        self.assertEqual(mapping._image_url('http://x/a.jpg'),
                         'http://x/a.jpg')
        self.assertEqual(mapping._image_url({'image': 'http://x/b.jpg'}),
                         'http://x/b.jpg')
        self.assertIsNone(mapping._image_url(None))
        self.assertIsNone(mapping._image_url({}))

    def test_images_for_dedupes(self):
        record = {'image': 'http://x/a.jpg', 'poster': 'http://x/a.jpg',
                  'fanart': 'http://x/bg.jpg'}
        urls = [i['url'] for i in mapping.images_for(record, 'T')]
        self.assertEqual(urls, ['http://x/a.jpg', 'http://x/bg.jpg'])

    def test_people_respects_cap(self):
        chars = [{'personName': 'P%d' % n, 'name': 'R%d' % n,
                  'peopleType': 'Actor'} for n in range(5)]
        # reload_config restores the environment on the way out, so the
        # assertion has to happen while the override is live.
        os.environ['TVDB_MAX_CAST'] = '2'
        try:
            importlib.reload(config_mod)
            importlib.reload(mapping)
            self.assertEqual(config_mod.config.max_cast, 2)
            self.assertEqual(
                len(mapping.people_from({'characters': chars})), 2)
        finally:
            os.environ.pop('TVDB_MAX_CAST', None)
            importlib.reload(config_mod)
            importlib.reload(mapping)
        self.assertEqual(len(mapping.people_from({'characters': chars})), 5)

    def test_people_skips_unnamed(self):
        chars = [{'name': 'Role only'}, {'personName': 'Real Person'}]
        roles = mapping.people_from({'characters': chars})
        self.assertEqual([r['tag'] for r in roles], ['Real Person'])

    def test_tags_from_dedupes(self):
        record = {'genres': [{'name': 'Drama'}, {'name': 'Drama'},
                             {'name': 'Sci-Fi'}]}
        self.assertEqual(mapping.tags_from(record, 'genres'),
                         [{'tag': 'Drama'}, {'tag': 'Sci-Fi'}])
        self.assertEqual(mapping.tags_from({}, 'genres'), [])


class CacheTest(unittest.TestCase):
    def setUp(self):
        tvdb.cache_clear()
        self.cache = cache_core.Cache(max_entries=5)

    def test_cache_is_bounded(self):
        # A plain dict grew for the life of the process: an entry was only
        # ever dropped when that exact key was requested again after
        # expiry.
        for n in range(20):
            self.cache.put(('path%d' % n, ()), {'n': n})
        self.assertLessEqual(self.cache.stats()['entries'], 5)
        self.assertGreater(self.cache.stats()['evictions'], 0)

    def test_expired_entry_is_a_miss(self):
        self.cache.put(('p', ()), {'v': 1})
        self.assertIs(self.cache.get(('p', ()), ttl=-1), cache_core.MISSING)

    def test_absent_and_negative_are_distinguishable(self):
        # 'nothing cached' and 'cached knowledge that upstream has
        # nothing' must not look alike, or a known-missing record is
        # re-fetched on every retry.
        self.assertIs(self.cache.get(('nope', ()), ttl=60),
                      cache_core.MISSING)
        self.cache.put(('nope', ()), cache_core.NEGATIVE)
        self.assertIs(self.cache.get(('nope', ()), ttl=60),
                      cache_core.NEGATIVE)

    def test_counters_track_hits_and_misses(self):
        self.cache.put(('k', ()), 'v')
        self.cache.get(('k', ()), ttl=60)
        self.cache.get(('absent', ()), ttl=60)
        stats = self.cache.stats()
        self.assertEqual(stats['hits'], 1)
        self.assertEqual(stats['misses'], 1)
        self.assertEqual(stats['hitRate'], 0.5)

    def test_hit_rate_is_none_before_any_traffic(self):
        self.assertIsNone(self.cache.stats()['hitRate'])

    def test_key_lock_is_stable_per_key(self):
        # Single-flight depends on the same key yielding the same lock.
        self.assertIs(self.cache.key_lock(('a', ())),
                      self.cache.key_lock(('a', ())))
        self.assertIsNot(self.cache.key_lock(('a', ())),
                         self.cache.key_lock(('b', ())))

    def test_ttl_tiers_are_distinct(self):
        # Episode lists are dozens of paged calls and barely change;
        # reference data changes less still.
        stats = tvdb.cache_stats()
        self.assertLess(stats['ttl'], stats['episodeTtl'])
        self.assertLess(stats['episodeTtl'], stats['staticTtl'])
        self.assertLess(stats['negativeTtl'], stats['ttl'])

    def test_episode_rows_handles_both_shapes(self):
        # /series/{id}/episodes/{type} answers {"series":…, "episodes":[…]},
        # while flatter endpoints answer a bare list.
        self.assertEqual(tvdb._episode_rows([{'id': 1}]), [{'id': 1}])
        self.assertEqual(tvdb._episode_rows({'episodes': [{'id': 2}]}),
                         [{'id': 2}])
        self.assertEqual(tvdb._episode_rows({'series': {}}), [])
        self.assertEqual(tvdb._episode_rows(None), [])


class EpisodeOrderTest(unittest.TestCase):
    """SeasonType on the show, episodeOrder honoured.

    Two episodes whose positions swap between aired and DVD order, the
    Firefly shape, so a wrong order is visible in the numbering.
    """
    SERIES = {
        'id': 78874, 'name': 'Firefly', 'firstAired': '2002-09-20',
        'seasons': [
            {'id': 1, 'number': 1,
             'type': {'id': 1, 'type': 'official', 'name': 'Aired Order'}},
            {'id': 2, 'number': 1,
             'type': {'id': 2, 'type': 'dvd', 'name': 'DVD Order'}},
            # Season rows with no episodes behind them, as AEW Dynamite has
            # for DVD order on TheTVDB.
            {'id': 3, 'number': 1,
             'type': {'id': 3, 'type': 'absolute',
                      'name': 'Absolute Order'}},
        ],
    }
    EPISODES = {
        'official': [
            {'id': 10, 'seriesId': 78874, 'seasonNumber': 1, 'number': 1,
             'name': 'The Train Job'},
            {'id': 20, 'seriesId': 78874, 'seasonNumber': 1, 'number': 2,
             'name': 'Serenity'},
        ],
        'dvd': [
            {'id': 20, 'seriesId': 78874, 'seasonNumber': 1, 'number': 1,
             'name': 'Serenity'},
            {'id': 10, 'seriesId': 78874, 'seasonNumber': 1, 'number': 2,
             'name': 'The Train Job'},
        ],
    }

    @classmethod
    def setUpClass(cls):
        cls.saved = {}
        aired = {e['id']: e for e in cls.EPISODES['official']}
        stubs = {
            'login': lambda: True,
            'series': lambda sid: cls.SERIES if str(sid) == '78874' else None,
            'series_extended': lambda sid, short=False:
                cls.SERIES if str(sid) == '78874' else None,
            'series_translation': lambda sid, lang: None,
            'series_episodes': lambda sid, kind='default', lang=None,
                page=None: list(cls.EPISODES.get(kind, [])),
            'episode': lambda eid: aired.get(int(eid)),
            'episode_extended': lambda eid: aired.get(int(eid)),
            'episode_translation': lambda eid, lang: None,
        }
        for fn, stub in stubs.items():
            cls.saved[fn] = getattr(tvdb, fn)
            setattr(tvdb, fn, stub)
        from tvdb_provider import app as app_mod
        cls.client = app_mod.create_app().test_client()

    @classmethod
    def tearDownClass(cls):
        for fn, original in cls.saved.items():
            setattr(tvdb, fn, original)

    def get(self, path):
        response = self.client.get('/tvdb' + path)
        self.assertEqual(response.status_code, 200, path)
        return response.get_json()['MediaContainer']['Metadata']

    def test_show_lists_orders_in_plex_form_aired_first(self):
        show = self.get('/library/metadata/show-78874')[0]
        self.assertEqual(
            [(t['id'], t['tag'], t['title']) for t in show['SeasonType']],
            [('tvdbAiring', 'Aired', 'TheTVDB (Aired Order)'),
             ('tvdbDvd', 'DVD', 'TheTVDB (DVD Order)')])

    def test_order_with_seasons_but_no_episodes_is_not_offered(self):
        # Offering it let Plex pick it, and the show came back with no
        # seasons at all.
        show = self.get('/library/metadata/show-78874')[0]
        self.assertNotIn('tvdbAbsolute',
                         [t['id'] for t in show['SeasonType']])

    def test_no_order_defaults_to_aired(self):
        eps = self.get('/library/metadata/season-78874-official-1/children')
        self.assertEqual([e['title'] for e in eps],
                         ['The Train Job', 'Serenity'])

    def test_both_parameter_spellings_switch_order(self):
        for name in ('episodeOrder', 'episodeOrdering'):
            seasons = self.get('/library/metadata/show-78874/children?'
                               '%s=tvdbDvd' % name)
            self.assertEqual(seasons[0]['ratingKey'], 'season-78874-dvd-1')

    def test_order_survives_in_keys_down_the_tree(self):
        show = self.get('/library/metadata/show-78874?includeChildren=1'
                        '&episodeOrder=tvdbDvd')[0]
        season = show['Children']['Metadata'][0]
        eps = self.get('/library/metadata/%s/children' % season['ratingKey'])
        self.assertEqual([(e['index'], e['title'], e['ratingKey'])
                          for e in eps],
                         [(1, 'Serenity', 'ep-20-dvd'),
                          (2, 'The Train Job', 'ep-10-dvd')])
        self.assertEqual(eps[0]['parentRatingKey'], 'season-78874-dvd-1')

    def test_single_episode_is_renumbered_for_its_order(self):
        # The episode record carries aired numbering; served in DVD order
        # it must take the DVD position or Plex files it in the wrong slot.
        ep = self.get('/library/metadata/ep-10-dvd')[0]
        self.assertEqual((ep['parentIndex'], ep['index']), (1, 2))
        ep = self.get('/library/metadata/ep-10-official')[0]
        self.assertEqual((ep['parentIndex'], ep['index']), (1, 1))

    def test_order_the_show_lacks_returns_no_seasons(self):
        self.assertEqual(self.get('/library/metadata/show-78874/children?'
                                  'episodeOrder=tvdbAbsolute'), [])
        show = self.get('/library/metadata/show-78874?includeChildren=1'
                        '&episodeOrder=tvdbAbsolute')[0]
        self.assertEqual(show['Children']['size'], 0)

    def test_season_match_honours_order_in_hints(self):
        response = self.client.post('/tvdb/library/metadata/matches', json={
            'type': 3, 'parentGuid': 'tvdb-78874', 'index': 1,
            'includeChildren': 1, 'episodeOrder': 'tvdbDvd'})
        season = response.get_json()['MediaContainer']['Metadata'][0]
        self.assertEqual(season['ratingKey'], 'season-78874-dvd-1')
        self.assertEqual(season['Children']['Metadata'][0]['title'],
                         'Serenity')

    def test_per_order_providers_are_gone(self):
        # v1.0.0 registered /aired, /dvd, /absolute and /alternate. 1.0.1
        # is one provider at /tvdb, and the old paths must not answer.
        for path in ('/aired', '/dvd', '/absolute', '/alternate', '/test'):
            self.assertEqual(self.client.get(path).status_code, 404, path)

    def test_key_without_order_serves_aired(self):
        # v1.0.0's season key carried no order. It still parses, and gets
        # aired order rather than a 404.
        eps = self.get('/library/metadata/season-78874-1/children')
        self.assertEqual([e['title'] for e in eps],
                         ['The Train Job', 'Serenity'])

if __name__ == '__main__':
    unittest.main(verbosity=2)
