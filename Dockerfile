FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY tvdb_provider/ ./tvdb_provider/
COPY wsgi.py .

RUN useradd --create-home --uid 1000 tvdb
USER tvdb

# 8081, so this can run alongside the ThePornDB provider on 8080.
EXPOSE 8081

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8081/health',timeout=3).status==200 else 1)"

# One worker, many threads - deliberately.
#
# The response cache and the single-flight lock live in process memory, so
# a second worker means a second cache: the same episode list gets fetched
# twice, coalescing only works within one worker, and /health reports
# whichever process happened to answer (it read upstreamCalls=0 moments
# after another worker had served a full show).
#
# This is pure I/O waiting on one upstream for a single Plex server, so
# threads cover the concurrency and a shared cache is worth far more than
# a second process.
CMD ["gunicorn", "--bind", "0.0.0.0:8081", "--workers", "1", "--threads", "8", \
     "--access-logfile", "-", "wsgi:app"]
