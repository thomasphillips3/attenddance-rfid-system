FROM python:3.12-slim

WORKDIR /app

# The studio is in Michigan (Eastern) and holds classes in the evening. Fly runs
# UTC by default, so naive date.today()/datetime.now() would attribute an 8pm+ ET
# class's attendance and late-evening payments to the NEXT calendar day. Install
# tzdata and set the container timezone so business dates are local. (utcnow()
# stays UTC for system/audit timestamps.) Keep this in sync with config TIMEZONE.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*
ENV TZ=America/New_York

COPY requirements-deploy.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data

ENV FLASK_ENV=production
ENV DATABASE_URL=sqlite:////data/attendance.db
ENV FLASK_PORT=8080
# Unbuffered stdout/stderr so logs flush to `fly logs` immediately instead of
# being block-buffered under Docker (and lost if the process is killed before a
# flush). Complements the module-level logging config in run.py.
ENV PYTHONUNBUFFERED=1

EXPOSE 8080

# Single worker + threads: fits the 256MB Fly machine (2 workers OOM'd) and
# avoids two processes racing on db.create_all()/migrations against SQLite.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--worker-class", "gthread", "--timeout", "120", "run:app"]
