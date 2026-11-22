# Security

## Reporting

Open a [private security advisory](https://github.com/o51r15/TheTVDB-Provider/security/advisories/new),
or a normal issue if the problem is not sensitive.

## Keep it on your LAN

Plex sends custom metadata providers **unauthenticated** requests. There is no
provider-side auth in the API yet, and Plex's own guidance is that this is
"fine for development or local-only hosting" and to wait before publishing a
public API.

So this service has no authentication of its own. Anyone who can reach port
8081 can query it, which means anyone who can reach it can spend your TheTVDB
API quota. Do not publish it through a reverse proxy, tunnel or port forward.

## Your API key

`TVDB_API_KEY` and `TVDB_PIN` are read from the environment and are never
logged, echoed in a response, or written to disk by this service. `/health`
reports only whether each is *set*.

Keep them in a `.env` file outside the repository. The shipped `.gitignore`
excludes `.env`, but the safest arrangement is to keep the real file in a
separate deployment directory entirely, so a stray `git add` cannot reach it.

TheTVDB v4 keys are issued per project. If your key is user-supported it is
paired with each end user's own subscriber PIN; a licensed key works without
one. If a key requires payment you are invoiced, and an unpaid key expires
after 7 days — the provider logs a clear authentication failure at startup
when that happens, rather than failing quietly during a library scan.

## Scope

This service makes outbound HTTPS calls to TheTVDB only. It does not read your
media files, does not write to your library, and stores nothing on disk: the
cache is in process memory and is lost on restart.
