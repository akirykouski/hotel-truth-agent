# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users
Primary audience for this build: the Ostrovok hackathon jury (product and design people) on 29.10.2026, watching a ~3-minute live demo. The surface must read as a real Ostrovok feature a traveller would use. Secondary, implied by the demo story: travellers choosing a hotel in central Sochi who care about facts the hotel card does not state (sea view by floor, sunset by month, walk to the beach with slope, night noise).

## Product Purpose
«О!Правда об отеле» computes what is missing from a hotel card from open data (OSM, DEM, climate, reviews) and answers natural-language searches with an explanation of why each hotel fits and where it falls short. Every fact carries source, confidence and date; conflicts between sources are visible. Success for the demo: the jury sees search, honest per-condition evidence, the wait turned into «О!ркада» mini-games, and recommendations visibly adapted to how the visitor handles their device.

## Positioning
The LLM never guesses facts: it parses the query and writes recipes; deterministic code computes every number from open data, with stability-based confidence (24 perturbed runs). Results are bucketed (подходит / возможно / не подходит) instead of a single opaque score. The wait screen doubles as a device-proficiency probe (timings and geometry only, never text) that reranks results within a bucket, with visible reasons and an opt-out.

## Operating Context
Demo runs locally (FastAPI, `uvicorn app.api:app --port 8010 --reload`), no LLM key required. `/` redirects to the role picker `/choose-role`: travellers go to the front at `/ui` (`app/web/front/`), hoteliers to `/hotelier`, the Ostrovok team to `/backoffice` (overview, city profile, search, hotel facts, characteristics, metrics, questions, refresh, regions). `/admin` was merged into it. `?slow=1` adds a client delay so the arcade opens during search. Region: central Sochi, 229 hotels.

## Capabilities and Constraints
- Vanilla HTML/CSS/JS, no build step; Leaflet 1.9.4 from cdnjs is the only library.
- 10 mini-games (`app/web/waitgames/games/*.js`), each under 30 s, Russian copy, Ostrovok references; registered via `Arcade.register` with a ctx telemetry API. Game ids and the ctx contract (top of `arcade.js`) must be preserved.
- Device profile (`sense.js`) and server policy (`app/sense.py`) are product logic; design must not change their meaning. Score hidden when confidence < 0.15.
- Must work at 390px mobile and 1440px desktop.

## Brand Commitments
Ostrovok.ru identity is binding: blue #0B4EC2, acid lime #ACEF81, warm grey #F2F1F0, ink #292F37, accents purple #855CA6 and red #CB1B00; fonts PT Root UI and Spoof (from nof.fastrovok.net); wordmark OSTR[pin]VOK.RU; light theme only (ostrovok.ru has no dark theme); blog-style 3D objects on lime. Promo code «ЛЕЖАТЬ». All copy in Russian.

## Evidence on Hand
- Real data: `data/hotels.json` (229 hotels), `data/facts.sqlite` (3 155 facts), metrics in README («Уверенность и метрики»).
- Gemini-generated 3D assets: `app/web/front/assets/*.webp` (hero, 8 condition icons, empty state, arcade, profile), `app/web/waitgames/covers/*.webp` (10 game covers).
- Marketer brief for the games: `docs/arcade_brief.md`.
- No real user testimonials, no real booking/pricing integration: never fabricate them.

## Product Principles
1. Facts over vibes: every claim shows its source and confidence.
2. Honest about gaps: unknowns and conflicts are shown, never hidden.
3. The wait is part of the product, not dead time.
4. Adaptation is visible and reversible: say why the list changed, allow opt-out.
5. Feels native to Ostrovok, not a bolt-on.

## Accessibility & Inclusion
Touch targets ≥ 44px; respect prefers-reduced-motion; the "careful" segment gets larger, calmer layouts.
