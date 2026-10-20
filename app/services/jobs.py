"""Background job runner (local-dev friendly, no paid services).

Default: a thread pool inside the Flask process (JOB_RUNNER=thread).
Production option: set JOB_RUNNER=celery and run a Celery worker with Redis —
the same run_split_job() function is the Celery task body (see DEPLOYMENT.md).

Cancellation is cooperative: a per-job flag is checked between clips, and the
DB status is also honoured so a cancel from another process still stops work
at the next clip boundary.
"""
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

_executor = ThreadPoolExecutor(max_workers=2, thread_name_prefix="splitter")
_cancel_flags = {}
_lock = threading.Lock()


def request_cancel(job_id):
    with _lock:
        _cancel_flags[job_id] = True


def clear_cancel(job_id):
    with _lock:
        _cancel_flags.pop(job_id, None)


def _is_cancelled(app, job_id):
    with _lock:
        if _cancel_flags.get(job_id):
            return True
    # Also respect DB state (e.g. cancel written by another process/worker)
    from ..extensions import db
    from ..models import VideoJob
    with app.app_context():
        job = db.session.get(VideoJob, job_id)
        return bool(job and job.status == "cancelled")


def run_split_job(app, job_id):
    """Execute the split for one job. Runs inside the worker thread."""
    from ..extensions import db
    from ..models import GeneratedClip, VideoJob
    from . import video_processor

    with app.app_context():
        job = db.session.get(VideoJob, job_id)
        if job is None or job.status == "cancelled":
            return
        job.status = "processing"
        job.progress = 0
        job.error_message = None
        db.session.commit()

        src = Path(app.config["UPLOAD_FOLDER"]) / (job.stored_filename or "")
        out_dir = Path(app.config["OUTPUT_FOLDER"]) / f"user_{job.user_id}" / f"job_{job.id}"
        out_dir.mkdir(parents=True, exist_ok=True)

        def on_progress(pct):
            j = db.session.get(VideoJob, job_id)
            if j:
                j.progress = pct
                db.session.commit()

        try:
            if not src.exists():
                raise video_processor.SplitError("Source file is missing on the server.")
            results = video_processor.split_video(
                src, out_dir, job.original_duration, job.selected_clip_duration,
                prefix=job.name_prefix, output_format=job.output_format,
                reencode=job.reencode, ffmpeg_bin=app.config["FFMPEG_BIN"],
                progress_cb=on_progress,
                is_cancelled=lambda: _is_cancelled(app, job_id),
            )
        except video_processor.SplitError as exc:
            j = db.session.get(VideoJob, job_id)
            if str(exc) == "cancelled" or (j and j.status == "cancelled"):
                if j:
                    j.status = "cancelled"
                    db.session.commit()
                return
            if j:
                j.status = "failed"
                j.error_message = str(exc)
                db.session.commit()
            return
        except Exception as exc:  # never crash the worker silently
            j = db.session.get(VideoJob, job_id)
            if j:
                j.status = "failed"
                j.error_message = f"Processing failed: {exc}"
                db.session.commit()
            return

        j = db.session.get(VideoJob, job_id)
        if j is None or j.status == "cancelled":
            return
        for r in results:
            db.session.add(GeneratedClip(
                job_id=j.id, clip_number=r["clip_number"], filename=r["filename"],
                start_time=r["start_time"], end_time=r["end_time"],
                duration=r["duration"], file_size=r["file_size"],
            ))
        j.status = "completed"
        j.progress = 100
        j.completed_at = datetime.now(timezone.utc)
        db.session.commit()
        clear_cancel(job_id)


def submit_split(app, job_id):
    """Queue a job for background processing."""
    from ..extensions import db
    from ..models import VideoJob
    with app.app_context():
        job = db.session.get(VideoJob, job_id)
        if job:
            job.status = "queued"
            db.session.commit()
    _executor.submit(run_split_job, app, job_id)
