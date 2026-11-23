<div align="center">

# tvdb-provider

**A Plex metadata provider for TheTVDB, including its DVD, absolute and other episode orders.**

Plex stops using TheTVDB on 3 December 2026. This brings it back as a custom metadata provider (PMS 1.43.0 and later), using your own TheTVDB API key.

[![GitHub last commit](https://img.shields.io/github/last-commit/o51r15/TheTVDB-Provider)](https://github.com/o51r15/TheTVDB-Provider)
[![Build](https://img.shields.io/github/actions/workflow/status/o51r15/TheTVDB-Provider/build.yml?label=build)](https://github.com/o51r15/TheTVDB-Provider/actions)
[![GHCR](https://img.shields.io/badge/ghcr.io-tvdb--provider-blue?logo=docker&logoColor=white)](https://github.com/o51r15/TheTVDB-Provider/pkgs/container/tvdb-provider)
[![Plex](https://img.shields.io/badge/plex-1.43%2B-e5a00d.svg)](https://www.plex.tv/)
[![Python](https://img.shields.io/badge/python-3.9%2B-3776ab.svg?logo=python&logoColor=white)](https://www.python.org/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)

</div>

---

## Why

After 3 December, Plex's built-in TheTVDB agent stops working and shows that use it stop getting new episodes. Most libraries won't notice, since aired order is also available from TMDB. DVD and absolute order are different. In Plex they only ever came from TheTVDB, and Plex hasn't said when its TMDB replacement (episode groups) will ship or whether it will cover the same orders. Anime and DVD-order collections are the libraries that lose out.

TheTVDB's API isn't going away. Plex's licence to it is. With your own key the data is still there, and this provider serves it to Plex.

## What it does

Plex sends a match request with whatever it knows about a show: title, year, filename, sometimes an id. The provider looks the show up on TheTVDB v4 and returns the show, its seasons and episodes, with titles, summaries, air dates, runtimes, cast, genres, posters, backgrounds and episode stills.

Each show also tells Plex which TheTVDB episode orders it has. Plex lists them under the show's **Edit → Advanced → Episode ordering**, the same place the built-in agent put them, and you pick one per show.

Firefly is a good test, because its orders differ:

| Episode ordering | Season 1 starts with | What you get |
|---|---|---|
| TheTVDB (Aired Order) | The Train Job | 14 episodes, 6 specials in season 0 |
| TheTVDB (DVD Order) | Serenity | 14 episodes, 3 specials in season 0 |
| TheTVDB (Absolute Order) | Serenity | One run of 15. TheTVDB counts the 2005 film as number 15 |

The menu for each show only lists the orders that have episodes. TheTVDB sometimes has an order that stops short of the show, and if you pick one of those, the episodes it's missing come up without metadata. Set `TVDB_FULL_ORDERS_ONLY=true` to only list orders that include every episode released so far.

## Features

- Per-show episode ordering through Plex's own menu: aired, DVD, absolute, alternate, regional, alternate DVD and alternate 2, whichever the show has
- Season types and artwork types read from TheTVDB's live lists, not a hardcoded table
- Posters ranked by your language first, then by TheTVDB's community score. Textless art is preferred over the wrong language
- Season posters matched to the order you picked
- Translations preferred, so a Japanese show comes through in English rather than romaji
- `{tvdb-121361}` in a folder name pins a show that keeps matching wrong. `{imdb-tt…}` and `{tmdb-…}` work too, which helps with Sonarr folders that don't carry a TVDB id
- Caching in tiers: an hour for most things, a day for episode lists, a week for reference data
- When TheTVDB is down or your key fails, Plex gets a 503 rather than an empty answer. Plex trusts an empty answer and quietly switches the library back to its built-in agent
- A self-test endpoint that walks through login, search, episodes and the mapped output, and tells you which step broke
- Docker images on GHCR, non-root, with a healthcheck

## Upgrading from 1.0.0

1.0.0 got this part wrong. We believed a provider couldn't add anything to Plex's Episode ordering menu, so 1.0.0 registered one provider per order (`/aired`, `/dvd`, `/absolute`, `/alternate`) and you picked the order by picking the agent. Plex's provider docs describe exactly the per-show menu we said wasn't possible, and we missed it.

1.0.1 replaces all of those with a single provider at `/tvdb`. `TVDB_ORDER_PROVIDERS` and `TVDB_ORDER_OVERRIDES` are gone too, since the order is now set per show in Plex.

The new provider has a new identifier, so Plex treats it as a different agent and shows need to match again. I'd try it on a small test library before moving a big one.

If you'd rather keep the 1.0.0 behaviour, pin the image to `ghcr.io/o51r15/tvdb-provider:1.0.0`.

## Quick start

### Docker Compose

```bash
# 1. Get the compose file
mkdir -p ~/tvdb-provider
curl -o ~/tvdb-provider/docker-compose.yml \
  https://raw.githubusercontent.com/o51r15/TheTVDB-Provider/main/docker-compose.yml

# 2. Add your TheTVDB key
cd ~/tvdb-provider
echo 'TVDB_API_KEY=your-key-here' > .env
echo 'TVDB_PIN=' >> .env            # your subscriber PIN, if your key needs one
echo 'TZ=America/New_York' >> .env

# 3. Start it
docker compose up -d
```

Check it: **http://your-server:8081/tvdb** should return a `MediaProvider` document. **http://your-server:8081/orders** makes an authenticated call to TheTVDB, so if it answers, your key and PIN work.

To update: `docker compose pull && docker compose up -d`

> **Keep it on your LAN.** Plex sends custom providers unauthenticated requests. Plex itself says that's fine for local hosting and advises against a public provider for now.

### Compose file

```yaml
services:
  tvdb-provider:
    image: ghcr.io/o51r15/tvdb-provider:latest   # or pin a version, e.g. :1.0.1
    container_name: tvdb-provider
    restart: unless-stopped
    ports:
      - "8081:8081"        # 8081 so it can sit next to another provider on 8080
    environment:
      - TZ=America/New_York
    env_file:
      - .env
```

### From source

```bash
git clone https://github.com/o51r15/TheTVDB-Provider.git && cd TheTVDB-Provider
pip install -r requirements.txt
cp .env.example .env                        # add your TVDB_API_KEY
TVDB_API_KEY=... python3 wsgi.py            # dev
gunicorn --bind 0.0.0.0:8081 --workers 1 --threads 8 wsgi:app
```

Run one worker. The cache lives in process memory, so a second worker means a second cache, double the calls to TheTVDB, and a `/health` that reports whichever worker answered. Threads handle the concurrency fine.

## Plex setup

1. **Settings → Metadata Agents → Add Provider**, and enter `http://your-server:8081/tvdb`
2. **Add Agent**, give it a name, and set the provider you just added as **Primary**
3. Create a **TV Shows** library, or edit one, and pick that agent under **Advanced**
4. To change a show's order: open the show, **Edit → Advanced → Episode ordering**, pick one, save, then **Refresh Metadata**

A few things worth knowing:

- **Your files still need to be numbered for the order you pick.** Plex matches files by the `S01E03` in the filename, and a provider can't change that. If your files are numbered in aired order and you switch the show to DVD, the DVD titles land on the aired-order files.
- **A refresh doesn't re-match.** Items that failed to match stay unmatched until a new scan or a manual **Fix Match**. Fix Match one show to check things before doing a whole library.
- **Artwork changes need a Refresh Metadata.** Plex keeps the posters it already has.
- **So do changes to the Episode ordering menu.** Plex stores each show's list of orders, so turning `TVDB_FULL_ORDERS_ONLY` on or off, or TheTVDB adding an order, only shows up after a Refresh Metadata on that show.
- **If the new agent isn't in the dropdown,** hard-refresh Plex Web (`Ctrl+Shift+R`). The list is cached in the browser.

## Configuration

Everything is an environment variable. The provider API has no settings page in Plex.

| Variable | Default | What it does |
|---|---|---|
| `TVDB_API_KEY` | | **Required.** A v4 key from [your API page](https://www.thetvdb.com/api-information) |
| `TVDB_PIN` | | Your subscriber PIN. Needed with a user-supported key, not with a licensed one |
| `TVDB_LANGUAGE` | `eng` | Language for translations and artwork |
| `TVDB_ORDER_FALLBACK` | `true` | If a show has no aired-order episodes, serve its default order instead of nothing |
| `TVDB_FULL_ORDERS_ONLY` | `false` | `true` only lists an order (DVD, absolute and so on) if it has every released episode. With `false`, partial orders are listed too, and episodes they're missing lose their metadata when picked |
| `TVDB_EPISODE_CACHE_TTL` | `86400` | Episode lists are the slowest call and rarely change |
| `TVDB_MATCH_BY_ID_HINT` | `true` | Use `{tvdb-…}`, `{imdb-…}` and `{tmdb-…}` from folder and file names |

The rest are on the **[Configuration](https://github.com/o51r15/TheTVDB-Provider/wiki/Configuration)** wiki page.

## Endpoints

The provider lives at `/tvdb`: the `MediaProvider` manifest at the root, `POST /library/metadata/matches`, and `/library/metadata/<ratingKey>` with `/children`, `/grandchildren`, `/images` and `/extras`. There's also `/tvdb/selftest?q=<show>`, plus `/health` (cache counters, nothing secret) and `/orders` (TheTVDB's season types) at the top level.

Plex asks for the show with `episodeOrder=tvdbDvd` (or `tvdbAiring`, `tvdbAbsolute` and so on), then fetches seasons and episodes by key alone. So the order is in the key: `season-78874-dvd-1`, `ep-297999-dvd`.

More on the **[Endpoints](https://github.com/o51r15/TheTVDB-Provider/wiki/Endpoints)** page.

## Notes on Plex's provider API

Some of how Plex talks to providers isn't documented, and I found most of it by having things break: paging that arrives as query parameters, nested containers that have to be objects and not arrays, hint fields that change name depending on library type, and a scanner no provider can influence. Those are written up in **[Plex provider API notes](https://github.com/o51r15/TheTVDB-Provider/wiki/Plex-Provider-API-Notes)**.

## Docker images

| Tag | Built | Changes? |
|---|---|---|
| `ghcr.io/o51r15/tvdb-provider:dev` | On every push to `main` | Yes, follows the latest commit |
| `ghcr.io/o51r15/tvdb-provider:latest` | On tagged releases | Yes, follows the newest release |
| `ghcr.io/o51r15/tvdb-provider:1.0.1` | For that release | No. Pin to this |

Image tags have no `v` in front, even though git tags do: `git tag v1.0.1` builds `:1.0.1`. `:dev` is where changes land first and can break.

## Tests

```bash
python3 tests/test_provider.py
```

38 tests. TheTVDB is stubbed, so no key is needed. Each one was written for a bug that actually happened: the config fallbacks, the many names Plex uses for the same hint, id hints, artwork language ranking, the cache, and how episode orders are listed, requested and carried in keys.

## Documentation

- **[Configuration](https://github.com/o51r15/TheTVDB-Provider/wiki/Configuration)**: every environment variable
- **[Endpoints](https://github.com/o51r15/TheTVDB-Provider/wiki/Endpoints)**: the HTTP side
- **[Episode Ordering](https://github.com/o51r15/TheTVDB-Provider/wiki/Episode-Ordering)**: TheTVDB's season types, how they get into Plex's menu, and what 1.0.0 got wrong
- **[Plex Provider API Notes](https://github.com/o51r15/TheTVDB-Provider/wiki/Plex-Provider-API-Notes)**: undocumented behaviour, found the hard way
- **[Troubleshooting](https://github.com/o51r15/TheTVDB-Provider/wiki/Troubleshooting)**: start here when nothing matches

## Requirements

- **Plex Media Server 1.43.0 or later.** Custom metadata providers don't exist before that
- **A TheTVDB v4 API key** from [thetvdb.com/api-information](https://www.thetvdb.com/api-information). Keys are issued per project, not per user. A user-supported key also needs each user's subscriber PIN. A licensed key doesn't. If your key requires payment you'll be invoiced, and it expires after 7 days unpaid
- **Docker**, or **Python 3.9+** to run from source
- Plex has to be able to reach the service over the network

## Tech stack

Python 3.9+ (`python:3.15-slim` in the image), Flask, gunicorn, `requests`, an in-process cache, and GitHub Actions publishing to GHCR.

## Links

- [Plex metadata providers API](https://developer.plex.tv/pms/), the spec this follows
- [Custom metadata providers announcement](https://forums.plex.tv/t/announcement-custom-metadata-providers/934384)
- [TheTVDB v4 API](https://github.com/thetvdb/v4-api)
- [Issues](https://github.com/o51r15/TheTVDB-Provider/issues)

## Contributing

Bug reports are the most useful thing you can send, and so are corrections to the API notes. [CONTRIBUTING.md](CONTRIBUTING.md) covers what to put in an issue and how to run the tests. [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) applies here.

## License

[MIT](LICENSE). This is an independent project, not affiliated with Plex or TheTVDB. TheTVDB data is under their terms, and you supply your own API key.
