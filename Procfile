web: gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 300
# Production queue option (only if JOB_RUNNER=celery and Redis is configured):
# worker: celery -A app.services.jobs worker --loglevel=info
