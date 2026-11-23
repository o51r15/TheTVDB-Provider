<!--
Thanks for sending this. Delete any section that doesn't apply —
a three-line fix doesn't need a filled-in form.
-->

## What this changes

<!-- One or two sentences. What was wrong, or what's new. -->

## The symptom it fixes

<!--
For a bug fix: what you actually saw. The Plex-side behaviour, a log line,
a wrong response — whatever made you go looking. Skip for a new feature.
-->

## How you reproduced it

<!--
Enough that I can see it too: the series id, the order, the endpoint,
the Plex version. `/selftest` and `/health` output are safe to paste —
neither contains credentials.
-->

## Checklist

- [ ] `python3 tests/test_provider.py` passes
- [ ] A test was added that fails without this change, if it's a bug fix
- [ ] No new runtime dependency, or the PR says why one is needed
- [ ] `TVDB_API_KEY` / `TVDB_PIN` still never reach a log line or a response
- [ ] An upstream failure still returns 5xx or 404, never an empty 200
- [ ] Docs updated if behaviour or configuration changed — the wiki is a
      separate repository, so note here what needs changing there

## Anything else

<!--
Trade-offs you made, things you weren't sure about, anything you'd like
a second opinion on. "I don't love this but it works" is a useful thing
to say.
-->
