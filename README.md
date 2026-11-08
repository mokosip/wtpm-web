# wtpm-web

- Deployable web version of the Written Text Pattern Machine: a German text becomes a pattern, played in the browser with Strudel.
- Analysis and composition are copied from the private `written-text-pattern-machine` (commit `f900fde`).
- License: AGPL-3.0-or-later (Strudel is AGPL-3.0); see `LICENSE`.

## Samples

- Every sample is a Dirt-Sample at a pinned commit (`DIRT_COMMIT` in `src/wtpm/manifest.py`); the browser loads it from GitHub, nothing is hosted here.
- `src/wtpm/samples.json` lists each usable sample with its role, length, Strudel sound name (`<folder>_<file stem>`, one file per name) and file; the bass is the Strudel synth `sawtooth`.
- Rebuild it from the local samplebank roles (`~/tidal/samples/samplebank.json` and its analysis cache): `uv run python -m wtpm.manifest`. Samples missing at the pinned commit are listed under `missing`.
- The composer draws only from this manifest; the same text and sample seed draw the same samples.

## Strudel export

- `render_strudel(score)` (`src/wtpm/strudel.py`) gives `cps`, `bars` and one voice per layer part: `s("…").note("…").gain("…").clip("…")` over `bars × 16` slots (`~` = rest); simultaneous notes of a layer go to separate voices. The page plays `setcps(cps)` and `stack(voices).slow(bars)`.
- Pitch: Strudel plays a sample at its own pitch for `note` 36 and a synth `note` as MIDI, so samples get `note + 36` and the bass synth `note + 60` (SuperDirt: note 0 = original sample / middle C).
- Level: SuperDirt sounds at `gain⁴`, Strudel at `gain`, so the export writes `gain⁴`.
- Length: Strudel's `clip` multiplies the event (one sixteenth) like SuperDirt's `legato`.
- Bass: Strudel synth `sawtooth` with `.lpf(600)`.
- Echo notes get their own voices with `room`, `size`, `delay`, `delaytime`, `delayfeedback` and `.orbit(1)`, because Strudel shares effects per orbit.
- Checked in the browser with `@strudel/web` 1.3.0: for the Pilger text every score event comes back as one Strudel event at the same sixteenth with the same sound, note, gain, length and room.

## Page and server

- Only `/sound` (also `/`): text in, `POST /api/sonify {text, sample_seed}` → `{analysis, score, strudel}`; German only (`de_dep_news_trf`); at most 2000 characters (413 above), empty text 400.
- `GET /api/samples` gives the Strudel sample map (`base` + sound name → file); the page loads it once with `initStrudel({prebake: () => samples(map, base)})` from `@strudel/web` 1.3.0 (pinned on unpkg).
- Play evaluates `setcps(…)` + `stack(…).slow(bars)`; stop is `hush()`. Muting a pad or turning the tempo knob evaluates the code again without those voices or with the new `cps`. The dice and the SEED field draw new samples.
- No Merkliste, no sample banks, no analysis view, no SuperDirt, no Tidal download.
- Run locally: `PORT=8100 uv run python -m wtpm.server` (`HOST` defaults to 127.0.0.1).

## Development

- `uv sync`
- `uv run pytest`
