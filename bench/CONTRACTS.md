# Feature contracts measured by the benchmark

`bench/run.py` (deterministic) and `bench/llm_track.py` (LLM, 12 guest scenarios) are the frozen yardstick.
Feature branches must not edit `bench/`. Each feature exposes the interface below; the benchmark calls it and
scores "absent" if it is missing. Baseline numbers: `bench/results/baseline*.json`.

All runs use a throwaway copy of the checkout's `data/facts.sqlite`, `LLM_PROVIDER=none` unless noted.

## 1. Truth Engine — `t2_fraud`, `t3_heldout`
- No new required API. `store.resolve(hotel_id, spec, fs=None)` keeps its return keys
  (`status, value, summary, source, source_label, confidence, facts, conflicts`).
- Physical characteristics (`sea_view, night_quiet, beach_walk, sunset`): a hotelier claim (conf 0.9) that
  contradicts a confident computation must NOT flip the value; the conflict must be flagged.
- Policy characteristics (`pets, night_checkin`): the hotelier stays the authority.
- Scored: `physics_holds_mean` ↑, `policy_hotelier_wins_mean` stays 1.0, held-out `agree` ↑ / `ece` ↓,
  `sea_view_conf_eq_1` ↓ (calibrated, not 1.0 by default).

## 2. Window Simulator — `f2_window`
`app/tools/window.py: render(hotel_id, facade=None, floor=None, month=7) -> dict`
- `facade` = direction label as in sea_view facts (e.g. "ЮЗ"); default = best sea facade. `floor` default = top.
- returns `{"facade", "floor", "sea_fraction": 0..1 share of the facade's view fan with sea visible (nominal run),
  "sea_p": 0..1 Monte-Carlo probability the view qualifies, "sun": {"az", "alt", "visible", "over_sea"},
  "panorama": [{"az", "obstruction_deg", "kind"}], "svg": "<svg ...>"}`
- Scored: consistency with the `sea_view` geo fact (sea at `from_floor` on that facade; none when has=False).

## 3. Room Resolver — `f3_rooms`
`app/rooms.py: resolve_rooms(hotel_id) -> list[dict]`, one per room category in the card:
`{"room": exact card name, "claims_sea_view": bool, "sea_view_p": 0..1, "ask": {"side": str|None, "min_floor": int|None},
"special_request": str (Russian, ready to paste into the booking), "hidden_view": bool, "evidence": [...]}`
- Scored: card-named sea-view categories consistent with geometry; agreement with guests who stayed in that
  category and praised the view (review `room` field); count of special requests and hidden-view categories.

## 4. Grounded answers — `f4_grounding` + LLM track
`app/grounding.py: verify(text, trace) -> {"claims": [...], "unsupported": int, "total": int}`
- `trace` items: `{"tool", "input", "output"}`. Fabricated numbers must be caught; a true answer must pass.
- LLM track (independent oracle, not this module): `grounded_rate` ↑, `constraint_coverage` ↑.

## 5. Draft gate — `f5_draft`
- `compiler.add(text)` returns `{"ok", "id", "status": "draft", "eval": {...auto-eval report...}}`.
- Drafts are invisible to public search (`search.parse_rules` / `search.parse`) until `registry.approve(char_id)`.
- Scored: `gate_works`, `has_eval_report`.

## 6. Photos as a sensor — `f6_photos`
- `data/photo_labels.json` (frozen labels, `{hotel_id: [{url, labels: {...}}]}`) and facts with `source='photos'`
  in `data/facts.sqlite` (at least for `sea_view`, key `has`).
- Scored: number of photo facts, agreement with the geo computation.

## 7. Relaxation frontier — `f7_relax`
- `search.search(...)` result has `"relaxations": [{"drop": str, "gain": int, "best": hotel brief, ...}]`
  whenever `counts["match"] < 10`. `gain` = extra matches if that constraint is dropped.

## 8. Night timeline — `f8_timeline`
`app/tools/noise.py: timeline(hotel_id, month=7) -> {"facades": [{"dir", "hours": {0..23: dB}}], ...}`
- Mean of hours 23–06 on the quietest facade within 4 dB of the `night_quiet` fact `night_db_quiet`.

## 9. Change radar — `f9_radar`
`app/radar.py: scan(hotels=None, now=None) -> [{"hotel_id", "kind", "severity", "evidence", "char_id"}]`
- `hotels` = list of hotel dicts (same shape as `data/hotels.json`) to scan instead of the dataset.
- Scored: a synthetic spike of 6 recent construction-noise reviews is caught; alert rate on real data stays sane.

## 10. New region — `f10_region`
- `data/regions/<name>/` with its own hotels/OSM/DEM/climate + `facts.sqlite`. Env `REGION=<name>` makes
  `geodata.load()` and `store` use that region (store seed `data/regions/<name>/facts.sqlite`, runtime copy under
  `data/regions/<name>/cache/`). Without `REGION` nothing changes.
- Scored: hotels loaded and share with a computed `sea_view`.
