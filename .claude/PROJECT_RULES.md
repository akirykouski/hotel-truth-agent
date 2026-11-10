# Project rules — ostrovok-agent
## What this is
FastAPI прототип хакатона Островка: проверяемые факты об отелях центра Сочи, чат/поиск, MCP-сервер. См. README.md.
## Must-know / gotchas
- Изменяющие эндпоинты закрыты ролями (`app/auth.py`): новый POST/DELETE, меняющий общее состояние, обязан получить `Depends(require_admin)` или `authorize_hotel`. «Кто» только из токена.
- `app` и `mcp` в Docker делят тома `cache` и `registry-custom`; рабочая база SQLite в WAL.
- `app/search.py` и гостевая выдача в `app/web/front/app.js` правят другие сессии; `bench/` не трогать.
## How to run / test / build
- Гейт без rtk: `LLM_PROVIDER=none .venv/bin/python tests/{smoke,front_queries,sense_check,taste_check,auth_check}.py`
## Conventions
- Код, комментарии, UI по-русски, коротко.
## Safety rails
- Не пушить; `data/cache/` не коммитить.
