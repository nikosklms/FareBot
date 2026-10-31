FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    # Fewer malloc pools for the page-parsing threads: measured ~170 MB instead of ~200 MB after big searches.
    MALLOC_ARENA_MAX=2 \
    FAREBOT_DB_PATH=/data/farebot.db

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
# The bot runs as a normal user and can only write to /data (database, its backups and the lock file).
# uid 1000 matches the first user on most Linux machines, so a ./data bind mount stays writable.
RUN useradd --uid 1000 --no-create-home farebot && mkdir /data && chown farebot /data
USER farebot
VOLUME /data

# Ctrl+C / docker stop send SIGTERM; the bot stops running searches and tells users before exiting.
CMD ["python", "main.py"]
