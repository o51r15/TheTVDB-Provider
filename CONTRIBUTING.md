# Contributing

Bug reports and corrections are the most useful thing you can send. Most of
what this provider knows about Plex's API was learned from failures against a
live server, so if you hit behaviour the
[API notes](https://github.com/o51r15/TheTVDB-Provider/wiki/Plex-Provider-API-Notes)
get wrong, I'd rather know than not.

## Before opening an issue

Run the self-test for the order that's misbehaving:

```bash
curl -s http://your-server:8081/dvd/selftest | python3 -m json.tool
curl -s http://your-server:8081/health | python3 -m json.tool
```

Neither contains credentials — `/health` reports only whether `TVDB_API_KEY`
and `TVDB_PIN` are *set* — so both are safe to paste.

Include those, your Plex version, and the library's agent. For a matching
problem, set `TVDB_LOG_LEVEL=DEBUG` and include the line showing the hint Plex
actually sent; it is usually not the folder name you'd expect.

[Troubleshooting](https://github.com/o51r15/TheTVDB-Provider/wiki/Troubleshooting)
covers the common cases first.

## Development setup

```bash
git clone https://github.com/o51r15/TheTVDB-Provider.git
cd TheTVDB-Provider
pip install -r requirements.txt
cp .env.example .env          # add your TVDB_API_KEY
python3 wsgi.py               # dev server on 8081
```

You need your own TheTVDB v4 key. Keys are per project, not per user, so
there is no shared development key to hand out.

## Tests

```bash
python3 tests/test_provider.py
```

Upstream is stubbed, so no API key is needed to run them.

**Every test in here was written against a bug that actually happened.** That
is the bar for new ones too: if you're fixing something, add the test that
would have caught it, and make sure it fails before your fix and passes after.
A test that only restates what the code already says isn't worth the
maintenance.

Please don't add a test framework. The suite is plain `unittest` so it runs
anywhere with nothing installed.

## Things worth knowing before you change behaviour

These are the constraints that shaped the design. Changing them is fine, but
know what you're trading:

- **Never turn an upstream failure into an empty success.** Plex reads an
  empty `200` as authoritative and writes permanent `local://` stubs. Return
  `503` or `404` instead.
- **One gunicorn worker, many threads.** The cache and single-flight are
  in-process; a second worker is a second cache. The `Dockerfile` explains
  this at the point where it matters.
- **Credentials never get logged, echoed, or written to disk.** If a change
  would put `TVDB_API_KEY` or `TVDB_PIN` into a response or a log line at any
  level, it doesn't go in.
- **Season types come from TheTVDB, not from a hardcoded list.** `/orders`
  reads them live. Don't reintroduce a static table.

## Style

Plain Python, standard library where it will do, no new runtime dependencies
without a reason that's worth stating in the PR.

Docstrings explain *why* a thing is the way it is, especially when it looks
wrong. Half the non-obvious code here exists because Plex does something
undocumented, and the comment saying so is the point.

Keep commits focused — one logical change each — and write the subject in the
imperative: "Fix season poster lookup for absolute order", not "fixed stuff".

## Pull requests

Open against `main`. CI builds the image and runs the tests on every push.

Say what broke and how you reproduced it. A PR that fixes a real symptom with
three lines beats a refactor, every time.

## Scope

This provider does one thing: serve TheTVDB metadata to Plex, with episode
ordering expressed as the agent. Things that are out of scope:

- Other metadata sources
- Anything that writes to your Plex library or touches media files
- Renaming tools — Plex's scanner can't be influenced by a provider, so this
  can't help there
- Provider-side authentication, until Plex's API actually supports it

## License

Contributions are accepted under the [MIT License](LICENSE), same as the rest
of the project.
