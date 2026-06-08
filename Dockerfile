FROM python:3.12-slim

WORKDIR /app

COPY requirements-deploy.txt requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

RUN mkdir -p /data

ENV FLASK_ENV=production
ENV DATABASE_URL=sqlite:////data/attendance.db
ENV FLASK_PORT=8080

EXPOSE 8080

# Single worker + threads: fits the 256MB Fly machine (2 workers OOM'd) and
# avoids two processes racing on db.create_all()/migrations against SQLite.
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", "--worker-class", "gthread", "--timeout", "120", "run:app"]
