# wtpm-web

- Deployable web version of the Written Text Pattern Machine: a German text becomes a pattern, played in the browser with Strudel.
- Analysis and composition are copied from the private `written-text-pattern-machine` (commit `f900fde`).
- License: AGPL-3.0-or-later (Strudel is AGPL-3.0); see `LICENSE`.

## Samples

- Every sample is a Dirt-Sample at a pinned commit (`DIRT_COMMIT` in `src/wtpm/manifest.py`); the browser loads it from GitHub, nothing is hosted here.
- `src/wtpm/samples.json` lists each usable sample with its role, length, Strudel sound name (`<folder>_<file stem>`, one file per name) and file; the bass is the Strudel synth `sawtooth`.
- Rebuild it from the local samplebank roles (`~/tidal/samples/samplebank.json` and its analysis cache): `uv run python -m wtpm.manifest`. Samples missing at the pinned commit are listed under `missing`.
- The composer draws only from this manifest; the same text and sample seed draw the same samples.

## Development

- `uv sync`
- `uv run pytest`
