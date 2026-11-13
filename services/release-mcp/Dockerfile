FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 app

# No database access and no secrets in this image; the server reaches data only through the Release API.
USER app
CMD ["python", "-m", "release_mcp"]
