import io
import shutil
import zipfile
from pathlib import Path

import requests
from flask import (Blueprint, abort, current_app, flash, redirect, render_template,
                   request, send_file, url_for)
from flask_login import current_user, login_required
from werkzeug.utils import secure_filename

from ..extensions import db
from ..models import GeneratedClip, VideoJob
from ..services import jobs as job_runner
from ..services import storage, url_validator, video_probe, video_processor

videos_bp = Blueprint("videos", __name__)

DURATION_PRESETS = [60, 300, 600, 900, 1800]


def get_owned_job(job_id):
    job = VideoJob.query.filter_by(id=job_id, user_id=current_user.id).first()
    if job is None:
        abort(404)
    return job


def _ext_ok(filename):
    return ("." in (filename or "")
            and filename.rsplit(".", 1)[-1].lower() in current_app.config["ALLOWED_EXTENSIONS"])


def _probe_or_reject(path):
    """Content validation: the file must really be a video (FFprobe), whatever
    its name/MIME claimed. Returns probe dict or raises ValueError(message)."""
    try:
        return video_probe.probe_video(path, current_app.config["FFPROBE_BIN"])
    except video_probe.ProbeError as exc:
        raise ValueError(str(exc)) from exc


def _create_job_from_file(path, stored_name, display_name, source_type, source_ref=None):
    info = _probe_or_reject(path)
    job = VideoJob(
        user_id=current_user.id,
        original_filename=display_name,
        stored_filename=stored_name,
        source_type=source_type,
        source_reference=source_ref,
        title=Path(display_name).stem,
        original_duration=info["duration"],
        has_audio=info["has_audio"],
        status="uploaded",
    )
    db.session.add(job)
    db.session.commit()
    # Best-effort thumbnail next to the outputs for this job
    out_dir = storage.job_output_dir(current_app.config["OUTPUT_FOLDER"], current_user.id, job.id)
    video_processor.make_thumbnail(path, out_dir / "thumb.jpg", current_app.config["FFMPEG_BIN"])
    return job


@videos_bp.route("/workspace")
@login_required
def workspace():
    return render_template("workspace.html", presets=DURATION_PRESETS)


@videos_bp.route("/videos/upload", methods=["POST"])
@login_required
def upload():
    file = request.files.get("video")
    if file is None or not file.filename:
        flash("Please choose a video file to upload.", "danger")
        return redirect(url_for("videos.workspace"))
    if not _ext_ok(file.filename):
        flash("Unsupported file type. Allowed: MP4, MOV, MKV, AVI, WebM.", "danger")
        return redirect(url_for("videos.workspace"))
    display = secure_filename(file.filename)
    stored_name, path = storage.save_upload(file, current_app.config["UPLOAD_FOLDER"])
    try:
        job = _create_job_from_file(path, stored_name, display, "upload")
    except ValueError as exc:
        Path(path).unlink(missing_ok=True)
        flash(str(exc), "danger")
        return redirect(url_for("videos.workspace"))
    flash("Video uploaded and verified. Now choose your clip duration.", "success")
    return redirect(url_for("videos.job_detail", job_id=job.id))


@videos_bp.route("/videos/from-url", methods=["POST"])
@login_required
def from_url():
    url = (request.form.get("url") or "").strip()
    try:
        meta = url_validator.validate_remote_video_url(url)
    except url_validator.URLValidationError as exc:
        flash(str(exc), "danger")
        return redirect(url_for("videos.workspace"))
    if meta["content_length"] and meta["content_length"] > current_app.config["MAX_REMOTE_MB"] * 1024 * 1024:
        flash("That remote file is larger than the allowed download limit.", "danger")
        return redirect(url_for("videos.workspace"))

    final_url = meta["final_url"]
    ext = Path(final_url.split("?")[0]).suffix.lower() or ".mp4"
    if ext.lstrip(".") not in current_app.config["ALLOWED_EXTENSIONS"]:
        ext = ".mp4"
    stored_name = f"{__import__('uuid').uuid4().hex}{ext}"
    dest = Path(current_app.config["UPLOAD_FOLDER"]) / stored_name
    cap = current_app.config["MAX_REMOTE_MB"] * 1024 * 1024
    try:
        with requests.get(final_url, stream=True, timeout=60) as resp:
            resp.raise_for_status()
            written = 0
            with open(dest, "wb") as fh:
                for chunk in resp.iter_content(chunk_size=1024 * 256):
                    written += len(chunk)
                    if written > cap:
                        fh.close()
                        dest.unlink(missing_ok=True)
                        flash("Download exceeded the size limit and was stopped.", "danger")
                        return redirect(url_for("videos.workspace"))
                    fh.write(chunk)
    except requests.RequestException as exc:
        dest.unlink(missing_ok=True)
        flash(f"Could not download the video: {exc}", "danger")
        return redirect(url_for("videos.workspace"))

    display = Path(final_url.split("?")[0]).name or "remote-video"
    try:
        job = _create_job_from_file(dest, stored_name, display, "url", source_ref=url)
    except ValueError as exc:
        dest.unlink(missing_ok=True)
        flash(str(exc), "danger")
        return redirect(url_for("videos.workspace"))
    flash("Video fetched and verified. Now choose your clip duration.", "success")
    return redirect(url_for("videos.job_detail", job_id=job.id))


@videos_bp.route("/jobs/<int:job_id>")
@login_required
def job_detail(job_id):
    job = get_owned_job(job_id)
    est = 0
    if job.original_duration and job.selected_clip_duration:
        est = len(video_processor.calculate_clips(job.original_duration, job.selected_clip_duration))
    return render_template("job_detail.html", job=job, presets=DURATION_PRESETS,
                           estimated_clips=est, fmt_ts=video_processor.format_ts)


@videos_bp.route("/jobs/<int:job_id>/thumbnail")
@login_required
def thumbnail(job_id):
    job = get_owned_job(job_id)
    thumb = (Path(current_app.config["OUTPUT_FOLDER"]) / f"user_{current_user.id}"
             / f"job_{job.id}" / "thumb.jpg")
    if not thumb.exists():
        abort(404)
    return send_file(thumb, mimetype="image/jpeg")


@videos_bp.route("/jobs/<int:job_id>/split", methods=["POST"])
@login_required
def split(job_id):
    job = get_owned_job(job_id)
    if job.status in ("queued", "processing"):
        flash("This job is already processing.", "warning")
        return redirect(url_for("videos.job_detail", job_id=job.id))
    preset = request.form.get("clip_duration", type=int)
    custom = request.form.get("custom_duration", type=int)
    custom_unit = request.form.get("custom_unit", "seconds")
    duration = custom * 60 if (custom and custom_unit == "minutes") else (custom or preset)
    if not duration or duration < 5:
        flash("Please choose a clip duration of at least 5 seconds.", "danger")
        return redirect(url_for("videos.job_detail", job_id=job.id))
    if job.original_duration and duration >= job.original_duration:
        flash("Clip duration must be shorter than the video itself.", "danger")
        return redirect(url_for("videos.job_detail", job_id=job.id))
    job.selected_clip_duration = duration
    job.output_format = "webm" if request.form.get("output_format") == "webm" else "mp4"
    prefix = (request.form.get("name_prefix") or "clip").strip()
    job.name_prefix = "".join(c for c in prefix if c.isalnum() or c in "-_")[:40] or "clip"
    job.reencode = request.form.get("reencode") == "1"
    # Clear old clips on a re-split
    for clip in list(job.clips):
        db.session.delete(clip)
    job.error_message = None
    db.session.commit()
    job_runner.submit_split(current_app._get_current_object(), job.id)
    flash("Splitting started. Keep this page open or check back from your dashboard.", "info")
    return redirect(url_for("videos.job_detail", job_id=job.id))


@videos_bp.route("/jobs/<int:job_id>/cancel", methods=["POST"])
@login_required
def cancel(job_id):
    job = get_owned_job(job_id)
    if job.status in ("queued", "processing"):
        job.status = "cancelled"
        db.session.commit()
        job_runner.request_cancel(job.id)
        flash("Processing cancelled.", "warning")
    return redirect(url_for("videos.job_detail", job_id=job.id))


@videos_bp.route("/jobs/<int:job_id>/retry", methods=["POST"])
@login_required
def retry(job_id):
    job = get_owned_job(job_id)
    if job.status in ("failed", "cancelled") and job.selected_clip_duration:
        job_runner.clear_cancel(job.id)
        job_runner.submit_split(current_app._get_current_object(), job.id)
        flash("Processing restarted.", "info")
    return redirect(url_for("videos.job_detail", job_id=job.id))


@videos_bp.route("/jobs/<int:job_id>/delete", methods=["POST"])
@login_required
def delete_job(job_id):
    job = get_owned_job(job_id)
    out_dir = Path(current_app.config["OUTPUT_FOLDER"]) / f"user_{current_user.id}" / f"job_{job.id}"
    src = Path(current_app.config["UPLOAD_FOLDER"]) / (job.stored_filename or "")
    db.session.delete(job)
    db.session.commit()
    shutil.rmtree(out_dir, ignore_errors=True)
    src.unlink(missing_ok=True)
    flash("Job and its files deleted.", "info")
    return redirect(url_for("main.dashboard"))


def _owned_clip(clip_id):
    clip = (GeneratedClip.query.join(VideoJob)
            .filter(GeneratedClip.id == clip_id, VideoJob.user_id == current_user.id).first())
    if clip is None:
        abort(404)
    return clip


def _clip_path(clip):
    return (Path(current_app.config["OUTPUT_FOLDER"]) / f"user_{current_user.id}"
            / f"job_{clip.job_id}" / clip.filename)


@videos_bp.route("/clips/<int:clip_id>/download")
@login_required
def download_clip(clip_id):
    clip = _owned_clip(clip_id)
    path = _clip_path(clip)
    if not path.exists():
        abort(404)
    return send_file(path, as_attachment=True, download_name=clip.filename)


@videos_bp.route("/clips/<int:clip_id>/stream")
@login_required
def stream_clip(clip_id):
    clip = _owned_clip(clip_id)
    path = _clip_path(clip)
    if not path.exists():
        abort(404)
    return send_file(path, as_attachment=False)


@videos_bp.route("/clips/<int:clip_id>/delete", methods=["POST"])
@login_required
def delete_clip(clip_id):
    clip = _owned_clip(clip_id)
    job_id = clip.job_id
    _clip_path(clip).unlink(missing_ok=True)
    db.session.delete(clip)
    db.session.commit()
    flash("Clip deleted.", "info")
    return redirect(url_for("videos.job_detail", job_id=job_id))


@videos_bp.route("/jobs/<int:job_id>/download-all")
@login_required
def download_all(job_id):
    job = get_owned_job(job_id)
    if not job.clips:
        flash("No clips to download yet.", "warning")
        return redirect(url_for("videos.job_detail", job_id=job.id))
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        for clip in job.clips:
            path = _clip_path(clip)
            if path.exists():
                zf.write(path, arcname=clip.filename)
        lines = [f"{c.clip_number:02d}. {video_processor.format_ts(c.start_time)} - "
                 f"{video_processor.format_ts(c.end_time)}  ({clip.filename})"
                 for c in job.clips for clip in [c]]
        zf.writestr("timestamps.txt", "\n".join(lines))
    buffer.seek(0)
    return send_file(buffer, as_attachment=True,
                     download_name=f"{job.name_prefix}_clips_job{job.id}.zip",
                     mimetype="application/zip")
