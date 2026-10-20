# AI Movie Splitter

Split your own or otherwise authorized videos into perfectly timed clips —
1, 5, 10, 15, 30 minutes or a custom duration — using a real FFmpeg engine.

**Stack:** Flask 3 · Flask-SQLAlchemy · Flask-Login · Flask-WTF (CSRF) ·
Flask-Migrate · FFmpeg/FFprobe · SQLite (dev) / PostgreSQL (prod) ·
Bootstrap 5 glassmorphism UI · background thread runner (Celery-ready).

> Only split videos you own or are authorized to use. Streaming/watch pages
> (YouTube, Netflix, …) are **not** downloadable sources and are refused with
> an explanation — upload the file instead. No DRM/paywall bypass, ever.

## Features
- Drag-and-drop upload with server-side FFprobe content validation (browser
  filename/MIME is never trusted; files are stored under generated names)
- Direct authorized video-URL fetching with full SSRF protection (private /
  loopback / cloud-metadata IPs blocked, every redirect re-validated after DNS)
- Real FFmpeg splitting: stream-copy by default, optional re-encode; the final
  clip always keeps the remaining duration (65 min @ 10 min → 7 clips)
- Background jobs with real per-clip progress, cancellation, retry
- Per-clip preview + download, Download-All ZIP (with `timestamps.txt`),
  copy-timestamps, delete clip / delete job
- Accounts: register/login/logout, hashed passwords, change password,
  per-user job history — nobody can open another user's job or clip
- JSON API under `/api/...` mirroring every web flow

## Local setup — macOS (MacBook Air M2 friendly)

```bash
# 1. Check tools
python3 --version        # 3.10+ recommended
git --version

# 2. FFmpeg via Homebrew
brew install ffmpeg      # provides ffmpeg + ffprobe

# 3. Clone / enter the project and create a venv
cd ai-movie-splitter
python3 -m venv .venv
source .venv/bin/activate

# 4. Install dependencies
pip install -r requirements.txt

# 5. Environment file
cp .env.example .env     # set a real SECRET_KEY

# 6. Database (dev works out of the box via db.create_all; for migrations:)
flask --app run db init        # once
flask --app run db migrate -m "initial"
flask --app run db upgrade

# 7. Run
python run.py            # http://127.0.0.1:5000

# 8. Tests
python -m pytest -q      # 24 tests: auth, SSRF, upload validation,
                         # duration maths, REAL splitting, downloads, cancel

# 9. Make a sample video (no movie download needed)
python scripts/make_sample.py 65 sample_65s.mp4
```

### Windows (equivalent)
```bat
winget install Gyan.FFmpeg
py -m venv .venv && .venv\Scripts\activate
pip install -r requirements.txt
copy .env.example .env
py run.py
```

### Troubleshooting
| Problem | Fix |
|---|---|
| `ffmpeg: command not found` | `brew install ffmpeg` (Mac) / `winget install Gyan.FFmpeg` (Win), restart terminal |
| `externally-managed-environment` on pip | You skipped the venv — activate `.venv` first |
| Upload rejected as "not a video" | The file failed FFprobe content validation; it may be corrupt or mislabelled |
| Job stuck at Queued | The dev server was restarted mid-job; open the job and use Retry |
| Port 5000 in use (macOS AirPlay) | Run on another port: `flask --app run run --port 5001` or disable AirPlay Receiver |

## How splitting works
`app/services/video_processor.calculate_clips(total, clip)` returns exact
`[start, end)` ranges; `split_video()` runs one FFmpeg process per clip
(`-ss` before `-i`, `-c copy`, no shell — arguments are a list, so no command
injection). Progress = clips finished / total clips (real data, never faked).
If a stream-copy clip fails (keyframe/codec edge case), it is retried once
with re-encoding. Videos without audio are handled naturally by stream copy.

## API (all require login except register/login)
```
POST   /api/auth/register        POST /api/auth/login      POST /api/auth/logout
POST   /api/videos/upload        POST /api/videos/from-url
POST   /api/videos/<job_id>/split
GET    /api/jobs                 GET  /api/jobs/<job_id>
POST   /api/jobs/<job_id>/cancel GET  /api/jobs/<job_id>/clips
GET    /api/clips/<clip_id>/download
GET    /api/jobs/<job_id>/download-all
DELETE /api/jobs/<job_id>
```

## Project layout
See the folder tree in the repo root: `app/` (auth / main / videos / api
blueprints + `services/`), `templates/`, `static/`, `tests/`, `scripts/`.

Deployment: see **DEPLOYMENT.md**. Security notes: see DEPLOYMENT.md §Security.
