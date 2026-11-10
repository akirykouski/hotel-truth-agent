# O!Pravda: the truth about a hotel

**1st place among 800+ teams at the Ostrovok hackathon (October 2026)**, track "One step to the perfect hotel".

A hotel-search agent that works out what a hotel card does not say, and checks what it does say. For hotels in Sochi it computes whether the sea is visible from a given side and floor, whether the sunset is visible in a given month, how long the walk to the beach really is (slope included), and how quiet the night is. Then it answers a guest's free-text request: which hotel, which room to ask for, and what to request when booking.

**Core rule: the LLM never guesses facts.** It parses the request, writes recipes for new hotel characteristics and maps hotelier answers to fields. Every number comes from deterministic code over open data, and chat answers are checked against tool outputs.

## How it works

- **Geodata engine.** Sea view and sunset: ray casting over the Copernicus GLO-30 elevation model and OSM buildings, per building side and floor, with 24 Monte Carlo runs over noisy heights for a confidence score (`app/tools/view.py`). Walk to the beach: OSM pedestrian graph with terrain and Tobler's hiking function (`app/tools/walk.py`). Night noise per building side (`app/tools/noise.py`).
- **Truth engine.** Every fact stores value, source, method, confidence, date and evidence. A Dawid-Skene style EM estimates how reliable each source is (hotel card, reviews, photos, hotelier, geodata) per class of characteristic, flags conflicts and says who it believed and why (`app/truth.py`).
- **Self-extending registry.** Characteristics live in `registry/*.yaml`. For a new one described in words, `app/compiler.py` picks tools from the catalog, tests the recipe on 5 hotels and lets the LLM repair it on failure.
- **Hotelier dialogue.** The system asks hoteliers at most 3 questions per hotel, ranked by information value, and only where data is missing or sources disagree. A free-text answer becomes a fact only after the hotelier confirms the system's reading.
- **Agent surface.** FastAPI web app plus an MCP server, so any MCP client can search and query hotels.

Stack: Python, FastAPI, SQLite, MCP, Claude / any OpenAI-compatible LLM, Leaflet, Docker.

## Data in this public copy

This repository contains the code, docs, demo video, deck and the open datasets (OSM extracts, Copernicus DEM, Open-Meteo climate). **The Ostrovok hotel listings, reviews and derived facts used during the hackathon are not included**: they were provided for the event and are not ours to republish. To run the demo, build a region from your own hotel source (`HOTELS_SRC_DIR`, see the "new region in one command" section of [README.ru.md](README.ru.md)).

## Docs and demo

- Full documentation (Russian): [README.ru.md](README.ru.md)
- Deck: [docs/deck/deck.pdf](docs/deck/deck.pdf)
- 3.5-minute demo: [docs/demo.mp4](docs/demo.mp4)
- Sea-view accuracy: [docs/accuracy.md](docs/accuracy.md)

## Team

Arseniy Kirykouski, Maksim Okulov, Kirill Kulikov, Valentina Shvetsova.
