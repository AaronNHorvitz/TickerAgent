FROM python:3.12-slim
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PIP_NO_CACHE_DIR=1 \
    BRIEF_CACHE_DIR=/tmp/ticker-agent-cache
COPY requirements.txt .
RUN pip install -r requirements.txt
COPY src ./src
# Run as an unprivileged user; the only writable path needed is the cache in /tmp.
RUN useradd --create-home --uid 10001 app
USER app
EXPOSE 8000
# Hosting platforms pass the port in $PORT; default to 8000 locally.
CMD ["sh", "-c", "exec uvicorn ticker_agent.app:app --app-dir src --host 0.0.0.0 --port ${PORT:-8000}"]
