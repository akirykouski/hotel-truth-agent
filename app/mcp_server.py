"""MCP-сервер: слой знаний об отелях для любого агента (Claude, другие ассистенты, агент трека «О!дин запрос»).

  python -m app.mcp_server          # stdio, для Claude Desktop / Claude Code
  python -m app.mcp_server --http   # streamable HTTP на :8001/mcp

Роли. Читающие инструменты открыты всем. Изменяющие (add_characteristic, answer_question) регистрируются только
если задан MCP_ADMIN_TOKEN, и каждый требует этот токен аргументом `token`. Без переменной сервер только для чтения.
ask_hotelier (вопрос отельеру в очередь) остаётся открытым: это действие гостя, как кнопка «Спросить у отеля».
"""
import hmac
import os
import sys

from mcp.server.fastmcp import FastMCP

from app import actions, hotelier, region

mcp = FastMCP("ostrovok-hotel-facts", instructions=(
    f"Проверяемые факты об отелях {region.META['label_of']}: вид на море по этажам, закат по месяцам, путь до пляжа с подъёмом, "
    "шум ночью, что открыто ночью, для детей, питомцы и др. У каждого факта есть источник, уверенность и дата. "
    "Ищите search_hotels, детали — hotel_facts, новые характеристики — add_characteristic."), port=8001)

for fn in (actions.search_hotels, actions.hotel_facts, actions.find_hotel, actions.compare_hotels,
           actions.list_characteristics, actions.compute_tool, actions.ask_hotelier,
           actions.hotelier_inbox, actions.room_advice):
    mcp.tool()(fn)

ADMIN_TOKEN = os.getenv("MCP_ADMIN_TOKEN") or ""


def _check(token):
    if not ADMIN_TOKEN or not hmac.compare_digest(str(token).encode(), ADMIN_TOKEN.encode()):
        raise PermissionError("нужен MCP_ADMIN_TOKEN: изменяющие инструменты только для команды Островка")


if ADMIN_TOKEN:
    @mcp.tool()
    def add_characteristic(description: str, token: str):
        """Добавить новую характеристику по описанию словами (черновик до одобрения админом). Нужен token = MCP_ADMIN_TOKEN."""
        _check(token)
        return actions.add_characteristic(description)

    @mcp.tool()
    def answer_question(question_id: int, answer: str, token: str):
        """Записать ответ отельера на вопрос системы (становится фактом с источником «отельер»). Нужен token = MCP_ADMIN_TOKEN."""
        _check(token)
        return hotelier.answer(int(question_id), answer, by="mcp-admin")


if __name__ == "__main__":
    mcp.run("streamable-http" if "--http" in sys.argv else "stdio")
