"""TheTVDB records -> Plex metadata documents.

Every coercion in here exists because of something Plex does that is not
in its documentation. The three that cost the most time on the ThePornDB
provider, carried over:

* **Hint keys are not consistent.** The same field arrives as `title` or
  `name`, `filename` or `file`, depending on library type. Reading one
  spelling only makes every lookup answer an empty container, and Plex
  then logs 'Primary provider failed to return a result, skipping item'
  and silently reverts the library to its built-in agent.
* **Nested containers must be objects**, never arrays.
* **Values are not reliably strings.** A field that is usually text
  arrives as a number or None often enough that `.strip()` on it is a
  500; text_of/date_of exist so no caller has to care.
"""
import re

from .config import config

# Plex's own spellings, in the order they are preferred.
TITLE_KEYS = ('title', 'name', 'showTitle', 'parentTitle')
FILE_KEYS = ('filename', 'file', 'path', 'originalFilename')
YEAR_KEYS = ('year', 'releaseYear', 'originallyAvailableAt')
GUID_KEYS = ('guid', 'guids')

# {tvdb-121361} in a folder or file name, and the bare tvdb-121361 form
# Plex itself writes into the Fix Match field.
ID_HINT_RE = re.compile(r'\{?\s*tvdb[-_: ]+(\d+)\s*\}?', re.I)
IMDB_HINT_RE = re.compile(r'\{?\s*imdb[-_: ]+(tt\d+)\s*\}?', re.I)
TMDB_HINT_RE = re.compile(r'\{?\s*tmdb[-_: ]+(\d+)\s*\}?', re.I)
YEAR_RE = re.compile(r'(?<!\d)(19\d{2}|20\d{2})(?!\d)')
RATING_KEY_SAFE_RE = re.compile(r'[^a-zA-Z0-9_-]')

SHOW, SEASON, EPISODE = 2, 3, 4


# ------------------------------------------------------------------ coercion

def text_of(value):
    """Whatever came back, as a string. Never raises."""
    if isinstance(value, str):
        return value
    if value is None:
        return ''
    return '%s' % value


def date_of(record):
    """An ISO date string, or ''.

    TheTVDB uses several field names depending on the record type, and any
    of them can be null on an unaired episode.
    """
    if not hasattr(record, 'get'):
        return ''
    for key in ('aired', 'firstAired', 'first_air_time', 'date',
                'firstAiredDate'):
        value = record.get(key)
        if isinstance(value, str) and value:
            return value[:10]
    return ''


def year_of(record):
    date = date_of(record)
    if date[:4].isdigit():
        return int(date[:4])
    raw = text_of(record.get('year') if hasattr(record, 'get') else '')
    return int(raw) if raw.isdigit() else None


def safe_rating_key(value):
    """Plex accepts only [a-zA-Z0-9_-] in a ratingKey.

    Anything else and the GUID it builds from the key is rejected, which
    surfaces as the item simply never matching, with nothing in the log to
    say why.
    """
    return RATING_KEY_SAFE_RE.sub('-', text_of(value))


def hint(hints, keys):
    """First populated value among Plex's several spellings."""
    if not hasattr(hints, 'get'):
        return ''
    for key in keys:
        value = hints.get(key)
        if value not in (None, '', [], {}):
            return value
    return ''


# -------------------------------------------------------------------- lookups

def extract_tvdb_id(text):
    found = ID_HINT_RE.search(text_of(text))
    return found.group(1) if found else None


def extract_remote_id(text):
    """An IMDb or TMDB id from a hint, for /search/remoteid.

    Worth trying because Sonarr-managed folders routinely carry
    {imdb-tt0903747} or {tmdb-1396} but no TVDB id, and TheTVDB can
    resolve either to its own series.
    """
    text = text_of(text)
    found = IMDB_HINT_RE.search(text)
    if found:
        return found.group(1)
    found = TMDB_HINT_RE.search(text)
    if found:
        return found.group(1)
    return None


def guid_tvdb_id(hints, identifier):
    """A series id out of an explicit guid hint, if it is one of ours."""
    raw = hint(hints, GUID_KEYS)
    candidates = raw if isinstance(raw, (list, tuple)) else [raw]
    for item in candidates:
        value = text_of(item.get('id') if hasattr(item, 'get') else item)
        if value.startswith(identifier + '://'):
            tail = value.rsplit('/', 1)[-1]
            # show-121361 / season-121361-3 / ep-9123456
            digits = re.findall(r'\d+', tail)
            if digits:
                return digits[0]
        found = extract_tvdb_id(value)
        if found:
            return found
    return None


def clean_title(text):
    """A searchable show title out of a title or filename hint."""
    text = text_of(text)
    if config.strip_path:
        text = re.split(r'[\\/]', text)[-1]
    text = re.sub(r'\.(mkv|mp4|avi|m4v|ts|mov|wmv|flv|mpg)$', '', text,
                  flags=re.I)
    # Drop id hints so they are not searched for as words.
    text = ID_HINT_RE.sub(' ', text)
    text = IMDB_HINT_RE.sub(' ', text)
    text = TMDB_HINT_RE.sub(' ', text)
    text = re.sub(r'\((19\d{2}|20\d{2})\)', ' ', text)
    text = re.sub(r'[._]+', ' ', text)
    # Season/episode markers, so a filename hint does not search for S03E07
    text = re.sub(r'\bS\d{1,2}\s*E\d{1,3}\b', ' ', text, flags=re.I)
    text = re.sub(r'\bseason\s*\d{1,2}\b', ' ', text, flags=re.I)
    return re.sub(r'\s{2,}', ' ', text).strip(' -')


def hint_year(hints):
    for key in YEAR_KEYS:
        found = YEAR_RE.search(text_of(hints.get(key)
                                       if hasattr(hints, 'get') else ''))
        if found:
            return found.group(1)
    # Search the RAW title, not the cleaned one: clean_title strips
    # '(2002)' on purpose, so cleaning first threw away the only year most
    # folder names carry and every match went out without one.
    for keys in (TITLE_KEYS, FILE_KEYS):
        raw = text_of(hint(hints, keys))
        for pattern in (ID_HINT_RE, IMDB_HINT_RE, TMDB_HINT_RE):
            raw = pattern.sub(' ', raw)
        found = YEAR_RE.search(raw)
        if found:
            return found.group(1)
    return None


# ------------------------------------------------------------------- imagery

def _image_url(value):
    """TheTVDB image fields are sometimes a URL, sometimes an object."""
    if isinstance(value, str) and value:
        return value
    if isinstance(value, dict):
        for key in ('image', 'url', 'fileName', 'thumbnail'):
            if isinstance(value.get(key), str) and value[key]:
                return value[key]
    return None


# TheTVDB artwork type ids -> Plex image types, read from /artwork/types
# rather than assumed. Getting these wrong is not a cosmetic problem: an
# earlier guess had 1 ('series Banner') and 7 ('season Poster') both
# mapped to 'background', so season posters were served as backdrops.
#
#   1 series Banner      2 series Poster      3 series Background
#   5 series Icon        6 season Banner      7 season Poster
#   8 season Background 10 season Icon       11 episode 16:9 Screencap
#  12 episode 4:3 Screencap                  13 actor Photo
#  14 movie Poster      15 movie Background  16 movie Banner
#  20/21 Cinemagraph    22/24 ClearArt       23/25 ClearLogo
ART_TYPE_MAP = {
    1: 'banner', 6: 'banner', 16: 'banner',
    2: 'coverPoster', 7: 'coverPoster', 14: 'coverPoster', 27: 'coverPoster',
    3: 'background', 8: 'background', 15: 'background',
    11: 'snapshot', 12: 'snapshot',
}
# Icons, cinemagraphs, clear art/logo and actor photos have no slot in a
# Plex Image array, so they are dropped rather than mislabelled as a
# poster - which is what a permissive default did.
ART_TYPE_SKIP = {5, 10, 13, 18, 19, 20, 21, 22, 23, 24, 25, 26}

# Poster first: Plex takes the first entry of a type as the primary.
TYPE_ORDER = {'coverPoster': 0, 'background': 1, 'snapshot': 2, 'banner': 3}


def _lang_rank(lang, prefer):
    """Lower is better. Textless art outranks a wrong-language poster.

    Michael's first test library pulled Arabic and Bulgarian posters for
    shows that had 27 English ones, because the base record's `image` was
    emitted first with no language check at all and Plex takes the first
    poster it is given.
    """
    if lang in prefer:
        return prefer.index(lang)
    if not lang:
        # Language-neutral (textless) art is always acceptable.
        return len(prefer)
    return len(prefer) + 1


def images_for(record, title=''):
    """A Plex Image array, best-language-first.

    Entries whose language is neither wanted nor neutral are dropped when
    TVDB_ARTWORK_LANGUAGE_FILTER is on - unless that would leave a type
    with no art at all, in which case the best available is kept. A show
    with only Japanese posters should still have a poster.
    """
    prefer = [config.language] + [l for l in config.language_fallbacks
                                  if l != config.language]
    wrong = len(prefer) + 1
    cand = []
    seen = set()

    def add(kind, url, lang, score=0):
        if not url or not kind or url in seen:
            return
        seen.add(url)
        cand.append({
            'type': kind, 'url': url, 'alt': title,
            '_lang': _lang_rank(lang, prefer),
            '_score': score if isinstance(score, (int, float)) else 0,
        })

    artworks = record.get('artworks')
    if isinstance(artworks, list):
        for art in artworks:
            if not isinstance(art, dict):
                continue
            art_type = art.get('type')
            if art_type in ART_TYPE_SKIP:
                continue
            kind = ART_TYPE_MAP.get(art_type)
            if not kind:
                continue
            add(kind, _image_url(art.get('image')) or _image_url(art),
                art.get('language'), art.get('score'))

    # The base record's single image carries no language, so it ranks with
    # textless art - behind a real match, ahead of a wrong-language one.
    add('coverPoster', _image_url(record.get('image')), None)
    add('coverPoster', _image_url(record.get('poster')), None)
    add('background', _image_url(record.get('fanart')), None)

    if config.artwork_language_filter:
        kept = [c for c in cand if c['_lang'] < wrong]
        # Keep a last-resort entry for any type the filter emptied.
        for kind in {c['type'] for c in cand}:
            if not any(c['type'] == kind for c in kept):
                rest = [c for c in cand if c['type'] == kind]
                rest.sort(key=lambda c: (c['_lang'], -c['_score']))
                kept.append(rest[0])
        cand = kept

    cand.sort(key=lambda c: (TYPE_ORDER.get(c['type'], 9), c['_lang'],
                             -c['_score']))
    return [{'type': c['type'], 'url': c['url'], 'alt': c['alt']}
            for c in cand]


# ---------------------------------------------------------------- translation

def translated(record, translations, field):
    """Prefer a translation for name/overview, else the base record.

    TheTVDB returns the series' original-language text on the base record,
    so a library set to English on a Japanese show gets romaji unless the
    translation is fetched and preferred.
    """
    if isinstance(translations, dict):
        value = translations.get(field)
        if isinstance(value, str) and value.strip():
            return value
    value = record.get(field) if hasattr(record, 'get') else None
    return text_of(value)


def people_from(record):
    """Plex Role entries from an extended record's characters array."""
    if not config.include_cast:
        return []
    chars = record.get('characters')
    if not isinstance(chars, list):
        return []
    roles = []
    for order, char in enumerate(chars, 1):
        if not isinstance(char, dict):
            continue
        name = text_of(char.get('personName')).strip()
        if not name:
            continue
        people_type = char.get('peopleType')
        if people_type and people_type != 'Actor' and not config.include_crew:
            continue
        entry = {'tag': name, 'order': order}
        role = text_of(char.get('name')).strip()
        if role:
            entry['role'] = role
        thumb = _image_url(char.get('image'))
        if thumb:
            entry['thumb'] = thumb
        roles.append(entry)
        if len(roles) >= config.max_cast:
            break
    return roles


def tags_from(record, key, limit=None):
    """A Plex tag array (Genre, Country, ...) from a TVDB list field."""
    values = record.get(key)
    if not isinstance(values, list):
        return []
    out = []
    for item in values:
        name = item.get('name') if isinstance(item, dict) else item
        name = text_of(name).strip()
        if name and {'tag': name} not in out:
            out.append({'tag': name})
        if limit and len(out) >= limit:
            break
    return out
