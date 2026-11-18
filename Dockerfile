FROM python:3.12-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY src ./src
ENV PYTHONUNBUFFERED=1 BRIEF_CACHE_DIR=/tmp/ticker-agent-cache
EXPOSE 8000
# Hosting platforms pass the port in $PORT; default to 8000 locally.
CMD ["sh", "-c", "uvicorn ticker_agent.app:app --app-dir src --host 0.0.0.0 --port ${PORT:-8000}"]
