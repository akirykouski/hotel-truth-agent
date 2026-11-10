# Сборка в два этапа: зависимости ставятся в venv на первом, в рабочий образ попадают только venv и код (без uv и кэшей).
FROM python:3.12.8-slim-bookworm AS build
COPY --from=ghcr.io/astral-sh/uv:0.8.14 /uv /bin/uv
RUN uv venv /opt/venv
COPY requirements.txt .
RUN VIRTUAL_ENV=/opt/venv uv pip install --no-cache -r requirements.txt

FROM python:3.12.8-slim-bookworm
# не root: uid 10001; data/cache и registry/custom создаются здесь, чтобы именованные тома унаследовали владельца
RUN useradd --create-home --uid 10001 app
WORKDIR /app
COPY --from=build /opt/venv /opt/venv
COPY --chown=app:app app app
COPY --chown=app:app registry registry
COPY --chown=app:app data data
COPY --chown=app:app scripts scripts
COPY --chown=app:app tests tests
RUN mkdir -p data/cache registry/custom && chown app:app /app data/cache registry/custom
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1
USER app
EXPOSE 8080 8001
HEALTHCHECK --interval=10s --timeout=6s --start-period=300s --start-interval=5s --retries=3 \
  CMD python -c "import urllib.request as u; u.urlopen('http://localhost:8080/health', timeout=5)"
CMD ["uvicorn", "app.api:app", "--host", "0.0.0.0", "--port", "8080"]
