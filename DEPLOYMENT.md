# Deployment Guide — AI Movie Splitter

Honest limits first: **no free tier gives permanent hosting + permanent file
storage + unlimited video processing.** Verify the provider's current limits
before relying on them; the notes below are patterns, not promises.

## 1. Push to GitHub
```bash
git init && git add . && git commit -m "AI Movie Splitter"
git branch -M main
git remote add origin https://github.com/<you>/ai-movie-splitter.git
git push -u origin main
```
`.gitignore` already excludes `.env`, databases, uploads and outputs. Never
commit real secrets.

## 2. Environment variables (set in the host dashboard, not in code)
`SECRET_KEY` (long random), `DATABASE_URL` (PostgreSQL), `SESSION_COOKIE_SECURE=1`,
`MAX_UPLOAD_MB`, `MAX_REMOTE_MB`, `RETENTION_DAYS`, `JOB_RUNNER` (`thread` or `celery`),
`REDIS_URL` (only for Celery).

## 3. FFmpeg in production
- **Docker (recommended):** the included `Dockerfile` installs FFmpeg via apt.
- **Render:** use the Docker deploy path, or a build command that installs
  FFmpeg; the plain Python environment does not guarantee FFmpeg is present.
- Verify after deploy: open a shell and run `ffmpeg -version`.

## 4. Web server
Gunicorn: `gunicorn run:app --workers 2 --threads 4 --timeout 300`
(see `Procfile`). Long timeouts matter because uploads are large.

## 5. PostgreSQL
Create a Postgres database and set `DATABASE_URL`. Render's free Postgres is
time-limited (it expires); for a durable free database use an external
provider such as Neon. Run migrations once: `flask --app run db upgrade`.

## 6. Background workers
- **Default (`JOB_RUNNER=thread`):** an in-process thread pool. Fine for a
  demo/single instance. Jobs do not survive a restart — users can Retry.
- **Production (`JOB_RUNNER=celery`):** provision Redis, run
  `celery -A app.services.jobs worker` as a separate service, and dispatch
  `run_split_job` as a task. Cancellation stays cooperative (flag checked
  between clips).

## 7. File storage (important)
Free/ephemeral host filesystems **delete uploads and outputs on restart**.
For production, either attach a persistent disk and point `UPLOAD_FOLDER` /
`OUTPUT_FOLDER` at it, or move storage to S3-compatible object storage
(`app/services/storage.py` is the single seam to change). Keep
`RETENTION_DAYS` set so old jobs are cleaned up.

## 8. Logs & monitoring
Follow the host's log stream; failed jobs store their FFmpeg error in
`video_jobs.error_message` (visible on the job page) — check there first.

## Security summary
- Passwords: Werkzeug hashing only, never plain text.
- Sessions: HTTP-only cookies, SameSite=Lax, Secure in production; CSRF on
  every form (Flask-WTF) and rate limiting on auth (Flask-Limiter).
- Uploads: extension allowlist **plus** FFprobe content validation,
  generated filenames, size caps (`MAX_CONTENT_LENGTH` → HTTP 413 page).
- URLs: scheme allowlist, DNS resolution with *all* IPs checked against
  private/loopback/link-local/reserved ranges (blocks cloud metadata
  169.254.169.254), manual redirect walk re-validated per hop, streamed
  download with a hard byte cap.
- FFmpeg: subprocess argument lists only — no shell, no string interpolation.
- Authorization: every job/clip query is scoped to `current_user.id`;
  other users receive 404 (verified by tests).
- Downloads: login-required and ownership-checked; ZIPs are generated
  per-request for the owner only.
