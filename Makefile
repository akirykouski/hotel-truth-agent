.PHONY: up down seed secrets auth-test eval-sea demo demo-test reset run test front-test semantic-test precompute mcp taste-test taste-seed taste-demo geoip
demo:            ## запуск в Docker: http://localhost:8080
	docker compose up --build
demo-test:       ## smoke-тесты в контейнере (профиль test)
	docker compose --profile test run --rm --build test
reset:           ## остановить Docker и сбросить демо к исходному состоянию
	docker compose down -v
run:             ## запуск локально
	uvicorn app.api:app --port 8080
test:
	python tests/smoke.py
auth-test:       ## роли на сервере: гость / отельер своего отеля / админ; без LLM
	LLM_PROVIDER=none python tests/auth_check.py
front-test:      ## разбор запросов главной (плитки, примеры, варианты); без LLM
	LLM_PROVIDER=none python tests/front_queries.py
semantic-test:   ## смысл запроса: отрицание, уточнения, другой город, дата цен; без LLM
	LLM_PROVIDER=none python tests/semantic_queries.py
precompute:      ## пересчитать все факты (≈40 с) и демо-ответы отельеров
	python scripts/precompute.py && python scripts/seed_demo.py
mcp:
	python -m app.mcp_server
taste-test:      ## кластеры вкуса: ограничения, режимы, API (временная база)
	python tests/taste_check.py
taste-demo:      ## запуск с демо кластеров вкуса: http://localhost:8080/?cluster=1 (после make taste-seed)
	TASTE_DEMO=1 uvicorn app.api:app --port 8080
taste-seed:      ## засеять 600 синтетических посетителей и обучить кластеры; потом make taste-demo
	python scripts/seed_synthetic.py --replay
geoip:           ## скачать гео по IP (db-ip lite, ~140 МБ) в data/cache/geoip
	python scripts/fetch_geoip.py
eval-sea:        ## оценка «вид на море» против независимой разметки (data/eval/sea_view_gold.json), детерминированно
	python scripts/eval_sea_view.py
up:              ## то же, что demo, в фоне: http://localhost:8080
	docker compose up --build -d
down:            ## остановить контейнеры (данные демо остаются в томах)
	docker compose down
seed:            ## демо-данные в образе; при старте app копирует их в том cache. Сброс к исходным и запуск заново
	docker compose down -v && docker compose up --build -d
secrets:         ## зашифровать .env для жюри в secrets.env.age (публичный ключ организаторов, age)
	@test -s .env || (echo "нет .env: cp .env.example .env и впишите ключ"; exit 1)
	age -r age1932fu7f70rwyfhaxflyfszz4gf6avxwc95wc0yjwm6zns9tspycqpgdnc0 -o secrets.env.age .env
	@echo "готово: secrets.env.age ($$(wc -c < secrets.env.age) байт); .env в git не попадает"
