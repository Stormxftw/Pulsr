# ARTWORK SCOPE — reviewed admission-pattern mirror

This is a deliberately reduced artwork set, not the full Simple Icons release.
Exclude an entire icon when its unchanged slug, title or upstream source URL
matches either regex below (case-insensitive). Do not rename, encode or split
artwork names. Each absent slug and its reason is recorded in BRANDS-LICENSE.md
and the build report. The full shipped tree, including this policy, still passes
through the actual plugin scanner; no scanner ignore rules or guard changes apply.

Literal pattern mirror from Hermes `tools/skills_guard.py` (reviewed checkout):

- `tunnel_service` (lines 329–330): `\bngrok\b|\blocaltunnel\b|\bserveo\b|\bcloudflared\b`
- `crypto_mining` (line 406): `xmrig|stratum\+tcp|monero|coinhive|cryptonight`

`scripts/build-brands.py` reads this literal list when HERMES_SOURCE is absent.
When HERMES_SOURCE is set it reads those two tuples from the scanner's AST without
executing that checkout. Missing patterns fail closed, not silently fall back.
The mirror parity test compares the entire regex text with the real scanner when
importable; the scope/exclusion tests always run. Other admission checks still
apply: this two-category artwork policy does not attempt to replace the scanner.

The policy is kept as readable documentation rather than a service reference in
runtime code. Scanner prose cautions remain visible for review; literal artwork
records matching these categories are not shipped in brands.json.
