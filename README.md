<div align="center">

# tvdb-provider

**Plex metadata provider for TheTVDB — and the episode orderings Plex is removing on 3 December 2026.**

An HTTP service built against the custom metadata provider API that Plex shipped in PMS 1.43.0. Each TheTVDB season type is registered as its own provider, so choosing the agent is how you choose the order — which is the control Plex is taking away.

[![GitHub last commit](https://img.shields.io/github/last-commit/o51r15/TheTVDB-Provider)](https://github.com/o51r15/TheTVDB-Provider)
[![Build](https://img.shields.io/github/actions/workflow/status/o51r15/TheTVDB-Provider/build.yml?label=build)](https://github.com/o51r15/TheTVDB-Provider/actions)
[![GHCR](https://img.shields.io/badge/ghcr.io-tvdb--provider-blue?logo=docker&logoColor=white)](https://github.com/o51r15/TheTVDB-Provider/pkgs/container/tvdb-provider)
[![Plex](https://img.shields.io/badge/plex-1.43%2B-e5a00d.svg)](https://www.plex.tv/)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab.svg?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

---

> **Why this exists** — On **3 December 2026** TheTVDB stops being a metadata source in Plex, after Plex and TheTVDB's owner failed to agree new terms. Nothing is deleted and finished shows mostly carry on, but the legacy agent stops working and TheTVDB-ordered shows stop receiving new episodes. The part that hurts is narrower than "a database went away": **DVD and absolute ordering exist in Plex only through TheTVDB.** TMDB episode groups are the stated replacement, with no ship date and no promise they reproduce every TheTVDB order — Plex's own advice to anyone depending on alternate ordering is to keep using TheTVDB, which is the thing being switched off. Anime and DVD-order collections are the casualties, not aired-order libraries. TheTVDB's API is not going anywhere; only Plex's licence to it lapsed. With your own key the data is still there, and this serves it back.

## What It Does

Plex sends a match request with whatever it knows — title, year, filename, sometimes an id hint. tvdb-provider resolves it against TheTVDB v4 and returns a fully populated show, season and episode hierarchy: real titles, summaries, air dates, runtimes, cast with headshots, genres, and language-ranked posters, backgrounds and episode stills.

The ordering is the point. A provider cannot add an entry to Plex's episode-ordering dropdown — the contract exposes only `metadata` and `match` — so each season type is registered as a **separate provider with its own identifier** instead. Four agents appear in Plex, and picking one picks the order.

Firefly, the canonical case, served three ways from the same records:

| Agent | S01E01 is | Episodes |
|---|---|---|
| **TheTVDB (Aired Order)** | The Train Job | 20 — Fox aired the pilot third |
| **TheTVDB (DVD Order)** | Serenity | 17 |
| **TheTVDB (Absolute Order)** | Serenity | 15, continuous, no specials |

## Features

- **Ordering as agent selection** — aired, DVD, absolute and alternate each registered as their own provider; `/orders` lists what TheTVDB currently offers and which are live
- **Per-series overrides** — `TVDB_ORDER_OVERRIDES=78874:dvd,81797:absolute` so **one** library can hold aired-order shows and absolute-order anime at once, rather than needing a library per order
- **Season types read, not assumed** — pulled from `/seasons/types`; there are seven, including `altdvd` and `alttwo`, which a hardcoded list misses
- **Order fallback** — a series with no episodes in the requested order serves its default rather than appearing empty, because Plex treats an empty container as final rather than something to retry
- **Language-ranked artwork** — posters sorted by requested language then TheTVDB community score, textless art preferred over the wrong language, and a last-resort kept so a show is never left with no poster
- **Correct artwork types** — mapped from the live `/artwork/types`; season posters are posters, banners are banners, and icons and clear-art are dropped rather than mislabelled
- **Per-season posters** — matched by `seasonId`, and read from the season rows belonging to the order being served
- **Translations preferred** — a Japanese show reads in English rather than romaji, with configurable fallbacks
- **Id-hint matching** — `{tvdb-121361}` in a folder name pins a stubborn show; `{imdb-tt…}` and `{tmdb-…}` resolve through `/search/remoteid`, which covers Sonarr-managed folders carrying no TVDB id
- **Tiered caching** — 1 hour general, 1 day for episode lists, 1 week for reference data, 5 minutes for known-absent records; 36 Plex requests cost 4 upstream calls at an 88% hit rate
- **Single-flight** — concurrent requests for the same uncached record collapse into one upstream call
- **Honest failures** — an auth or upstream failure answers 503, never an empty 200, because Plex believes an empty container and silently reverts the library to its built-in agent
- **Self-check endpoint** — `/aired/selftest?q=<show>` walks login → season types → search → series → episodes → mapped documents and names the step that broke
- **27 tests** — each written against a bug that actually occurred
- **Docker-native** — GHCR images, non-root container, healthcheck, CI-built `:dev` and `:latest`

## Quick Start

### Docker Compose (recommended)

```bash
# 1. Create your compose file
mkdir -p ~/tvdb-provider
curl -o ~/tvdb-provider/docker-compose.yml \
  https://raw.githubusercontent.com/o51r15/TheTVDB-Provider/main/docker-compose.yml

# 2. Add your TheTVDB key
cd ~/tvdb-provider
echo 'TVDB_API_KEY=your-key-here' > .env
echo 'TVDB_PIN=' >> .env            # subscriber PIN, if your key needs one
echo 'TZ=America/New_York' >> .env

# 3. Run
docker compose up -d
```

Verify: **http://your-server:8081/aired** — a `MediaProvider` document comes back when it's working. **http://your-server:8081/orders** proves the key and PIN work, since it is an authenticated call needing no series id.

> **Updating:** `docker compose pull && docker compose up -d`

> **Security:** Plex sends custom providers **unauthenticated** requests — provider auth is not implemented yet. Plex calls this "fine for development or local-only hosting" and advises waiting before publishing a public API. Keep this on your LAN.

### Docker Compose File

```yaml
services:
  tvdb-provider:
    image: ghcr.io/o51r15/tvdb-provider:dev   # :latest for tagged releases
    container_name: tvdb-provider
    restart: unless-stopped
    ports:
      - "8081:8081"        # 8081 so it sits beside other providers on 8080
    environment:
      - TZ=America/New_York
    env_file:
      - .env
```

### From Source

```bash
git clone https://github.com/o51r15/TheTVDB-Provider.git && cd TheTVDB-Provider
pip install -r requirements.txt
cp .env.example .env                        # add your TVDB_API_KEY
TVDB_API_KEY=... python3 wsgi.py            # dev
gunicorn --bind 0.0.0.0:8081 --workers 1 --threads 8 wsgi:app
```

> **One worker, deliberately.** The cache and the single-flight lock live in process memory, so a second worker is a second cache: the same episode list gets fetched twice and `/health` reports whichever process answered. This is pure I/O against one upstream for one Plex server, so threads cover the concurrency.

## Providers

One container, one provider per order. Register whichever you need.

| Path | Season type | Agent name in Plex | Default |
|---|---|---|---|
| **`/aired`** | `official` | TheTVDB (Aired Order) | **On** |
| **`/dvd`** | `dvd` | TheTVDB (DVD Order) | **On** |
| **`/absolute`** | `absolute` | TheTVDB (Absolute Order) | **On** |
| **`/alternate`** | `alternate` | TheTVDB (Alternate Order) | **On** |
| `/regional` | `regional` | TheTVDB (Regional Order) | Off |
| `/altdvd` | `altdvd` | TheTVDB (Alternate DVD Order) | Off |
| `/alttwo` | `alttwo` | TheTVDB (Alternate Order 2) | Off |
| `/default` | `default` | TheTVDB (Series Default Order) | Off |

Set `TVDB_ORDER_PROVIDERS` to change the set. `GET /orders` shows what TheTVDB offers and which are registered.

## Plex Setup

1. **Settings → Metadata Agents → Add Provider** → `http://your-server:8081/absolute`
2. **Add Agent** — name it, then set the provider you just added as **Primary**
3. Create a **TV Shows** library and pick that agent in the library's **Advanced** pane

Repeat per order you want available. Each path is a distinct provider with its own identifier, so all of them coexist as separate agents.

> **Mixed libraries don't need separate agents.** Because Plex binds one agent per library, per-show ordering lives in this provider instead: `TVDB_ORDER_OVERRIDES=78874:dvd` makes that one series serve DVD order inside an otherwise aired-order library.

> **A refresh never re-matches.** Items that failed to match are stored as `local://` stubs and stay that way forever. Only a fresh scan of a file Plex has not seen, or a manual **Fix Match**, creates a new binding. Fix Match one item to verify before touching a whole library.

> **Artwork changes need a Refresh Metadata.** Plex caches the posters it already pulled; a provider-side change does not re-fetch art on its own.

> **If a new agent doesn't appear in the dropdown,** hard-refresh Plex Web (`Ctrl+Shift+R`). The agent list is cached client-side; `GET /system/agents?mediaType=2` on the server is the source of truth.

## Configuration

Everything is environment variables — the provider API has no Plex-side preferences UI.

| Variable | Default | What it does |
|---|---|---|
| `TVDB_API_KEY` | — | **Required.** A v4 key from [your API page](https://www.thetvdb.com/api-information) |
| `TVDB_PIN` | — | Your subscriber PIN. Needed for a user-supported key; a licensed key works without one |
| `TVDB_ORDER_PROVIDERS` | `official,dvd,absolute,alternate` | Which orders to expose as agents |
| `TVDB_ORDER_OVERRIDES` | — | Per-series order, e.g. `78874:dvd,81797:absolute` |
| `TVDB_ORDER_FALLBACK` | `true` | Serve the default order when the requested one is empty |
| `TVDB_LANGUAGE` | `eng` | Preferred translation and artwork language |
| `TVDB_EPISODE_CACHE_TTL` | `86400` | Episode lists are the expensive call and the least volatile |
| `TVDB_MATCH_BY_ID_HINT` | `true` | Honour `{tvdb-…}`, `{imdb-…}` and `{tmdb-…}` in names |

**[Full configuration reference →](https://github.com/o51r15/TheTVDB-Provider/wiki/Configuration)** — every variable, with defaults and why it exists.

## Endpoints

Each provider path exposes the same surface: the `MediaProvider` manifest at
the root, `POST /library/metadata/matches`, and
`/library/metadata/<ratingKey>` with `/children`, `/grandchildren`,
`/images` and `/extras`. There is a `/selftest` per provider, plus a global
`/health` with cache counters and `/orders`.

**[Full endpoint reference →](https://github.com/o51r15/TheTVDB-Provider/wiki/Endpoints)**

## Notes on Plex's Provider API

Plex's provider API has undocumented behaviour that costs real debugging time —
paging arriving as query parameters, nested containers that must be objects
rather than arrays, inconsistent hint key names, and the fact that a provider
cannot influence scanning at all.

**[Plex provider API notes →](https://github.com/o51r15/TheTVDB-Provider/wiki/Plex-Provider-API-Notes)** — each entry recorded from a real failure.

## Docker Images

| Tag | When it's built | Moves? |
|---|---|---|
| `ghcr.io/o51r15/tvdb-provider:dev` | Every push to `main` | Yes — latest commit |
| `ghcr.io/o51r15/tvdb-provider:latest` | Tagged releases only | Yes — newest release |
| `ghcr.io/o51r15/tvdb-provider:1.0` | Tagged releases | Yes — newest 1.0.x |
| `ghcr.io/o51r15/tvdb-provider:1.0.0` | The release itself | No — pin to this |

Note the image tags carry **no `v` prefix** even though the git tags do:
`git tag v1.0.0` produces `:1.0.0`. Pin to the exact version in production;
`:dev` is the development stream and will break.

Cut a release with `git tag -a v1.0.0 -m v1.0.0 && git push origin v1.0.0`.

## Tests

```bash
python3 tests/test_provider.py     # 27
```

Upstream is stubbed, so no key is needed. They cover the config fallbacks, the
order-override parser, hint-key resolution across every spelling Plex uses,
id-hint extraction, artwork language ranking, and the cache's negative
entries, bounds, counters and single-flight locking.

## Documentation

- **[Configuration](https://github.com/o51r15/TheTVDB-Provider/wiki/Configuration)** — every environment variable
- **[Endpoints](https://github.com/o51r15/TheTVDB-Provider/wiki/Endpoints)** — the HTTP surface each provider path exposes
- **[Episode Ordering](https://github.com/o51r15/TheTVDB-Provider/wiki/Episode-Ordering)** — the season types, what Plex is losing, and how overrides work
- **[Plex Provider API Notes](https://github.com/o51r15/TheTVDB-Provider/wiki/Plex-Provider-API-Notes)** — undocumented behaviour, each recorded from a real failure
- **[Troubleshooting](https://github.com/o51r15/TheTVDB-Provider/wiki/Troubleshooting)** — start here when nothing matches

## Requirements

- **Plex Media Server 1.43.0+** — the release that introduced custom metadata providers; there is no way to register one on an earlier server
- **A TheTVDB v4 API key** — from [thetvdb.com/api-information](https://www.thetvdb.com/api-information). Keys are issued **per project, not per user**: a user-supported key is paired with each end user's own subscriber PIN, while a licensed key works without one. If your key requires payment you are invoiced, and it expires after 7 days unpaid
- **Docker**, or **Python 3.9+** to run from source
- Network reachability from the Plex server to this service

## Tech Stack

Python 3.9+ (`python:3.12-slim` in the image), Flask blueprints registered once
per season type, gunicorn, `requests` with a thread-local session, an
in-process tiered TTL cache with negative entries and per-key single-flight,
GitHub Actions → GHCR

## Links

- [Plex Metadata Providers API](https://developer.plex.tv/pms/) — the spec this implements
- [Custom Metadata Providers announcement](https://forums.plex.tv/t/announcement-custom-metadata-providers/934384)
- [TheTVDB v4 API](https://github.com/thetvdb/v4-api) — the metadata source
- [Issues](https://github.com/o51r15/TheTVDB-Provider/issues) — bugs and feature requests

## License

[MIT](LICENSE). This is an independent project and is not affiliated with
Plex or TheTVDB. TheTVDB data is subject to their own terms; you supply your
own API key.
