"""JSON API mirroring the web flows (same auth + ownership rules).

CSRF: browser calls must send the X-CSRFToken header (token is in the page
<meta name="csrf-token">). All endpoints require login except register/login.
"""
import uuid
from pathlib import Path

from flask import Blueprint, current_app, jsonify, request, send_file
from flask_login import current_user, login_required, login_user, logout_user
from werkzeug.utils import secure_filename

from ..extensions import csrf, db
from ..models import GeneratedClip, User, VideoJob
from ..services import jobs as job_runner
from ..services import storage, url_validator
from ..videos.routes import (_create_job_from_file, _ext_ok, _clip_path,
                             get_owned_job)

api_bp = Blueprint("api", __name__, url_prefix="/api")


def err(message, status=400):
    return jsonify({"ok": False, "error": message}), status


@api_bp.route("/auth/register", methods=["POST"])
@csrf.exempt
def api_register():
    data = request.get_json(silent=True) or request.form
    username = (data.get("username") or "").strip()
    email = (data.get("email") or "").strip().lower()
    password = data.get("password") or ""
    if len(username) < 3 or "@" not in email or len(password) < 8:
        return err("username (>=3), valid email and password (>=8) are required.")
    if User.query.filter((User.email == email) | (User.username == username)).first():
        return err("Username or email already exists.", 409)
    user = User(username=username, email=email)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return jsonify({"ok": True, "user": {"id": user.id, "username": user.username,
                                          "email": user.email}}), 201


@api_bp.route("/auth/login", methods=["POST"])
@csrf.exempt
def api_login():
    data = request.get_json(silent=True) or request.form
    user = User.query.filter_by(email=(data.get("email") or "").strip().lower()).first()
    if not user or not user.check_password(data.get("password") or ""):
        return err("Invalid email or password.", 401)
    login_user(user, remember=True)
    return jsonify({"ok": True, "user": {"id": user.id, "username": user.username}})


@api_bp.route("/auth/logout", methods=["POST"])
@login_required
def api_logout():
    logout_user()
    return jsonify({"ok": True})


@api_bp.route("/videos/upload", methods=["POST"])
@login_required
def api_upload():
    file = request.files.get("video")
    if file is None or not file.filename:
        return err("No video file provided (form field: video).")
    if not _ext_ok(file.filename):
        return err("Unsupported file type. Allowed: MP4, MOV, MKV, AVI, WebM.")
    display = secure_filename(file.filename)
    stored_name, path = storage.save_upload(file, current_app.config["UPLOAD_FOLDER"])
    try:
        job = _create_job_from_file(path, stored_name, display, "upload")
    except ValueError as exc:
        Path(path).unlink(missing_ok=True)
        return err(str(exc), 422)
    return jsonify({"ok": True, "job": job.to_dict()}), 201


@api_bp.route("/videos/from-url", methods=["POST"])
@login_required
def api_from_url():
    data = request.get_json(silent=True) or request.form
    url = (data.get("url") or "").strip()
    try:
        meta = url_validator.validate_remote_video_url(url)
    except url_validator.URLValidationError as exc:
        return err(str(exc), 422)
    return jsonify({"ok": True, "eligible": True, "meta": meta,
                    "note": "URL is a direct video file. POST the same URL via the web "
                            "workspace to download and create the job."})


@api_bp.route("/videos/<int:job_id>/split", methods=["POST"])
@login_required
def api_split(job_id):
    job = get_owned_job(job_id)
    data = request.get_json(silent=True) or request.form
    duration = data.get("clip_duration", type=int) if hasattr(data, "get") else None
    try:
        duration = int(data.get("clip_duration"))
    except (TypeError, ValueError):
        return err("clip_duration (seconds) is required.")
    if duration < 5:
        return err("clip_duration must be at least 5 seconds.")
    job.selected_clip_duration = duration
    fmt = data.get("output_format", "mp4")
    job.output_format = "webm" if fmt == "webm" else "mp4"
    prefix = str(data.get("name_prefix", "clip"))
    job.name_prefix = "".join(c for c in prefix if c.isalnum() or c in "-_")[:40] or "clip"
    db.session.commit()
    job_runner.submit_split(current_app._get_current_object(), job.id)
    return jsonify({"ok": True, "job": job.to_dict()})


@api_bp.route("/jobs/<int:job_id>")
@login_required
def api_job(job_id):
    return jsonify({"ok": True, "job": get_owned_job(job_id).to_dict()})


@api_bp.route("/jobs")
@login_required
def api_jobs():
    jobs = (VideoJob.query.filter_by(user_id=current_user.id)
            .order_by(VideoJob.created_at.desc()).all())
    return jsonify({"ok": True, "jobs": [j.to_dict() for j in jobs]})


@api_bp.route("/jobs/<int:job_id>/cancel", methods=["POST"])
@login_required
def api_cancel(job_id):
    job = get_owned_job(job_id)
    if job.status in ("queued", "processing"):
        job.status = "cancelled"
        db.session.commit()
        job_runner.request_cancel(job.id)
    return jsonify({"ok": True, "job": job.to_dict()})


@api_bp.route("/jobs/<int:job_id>/clips")
@login_required
def api_clips(job_id):
    job = get_owned_job(job_id)
    return jsonify({"ok": True, "clips": [c.to_dict() for c in job.clips]})


@api_bp.route("/clips/<int:clip_id>/download")
@login_required
def api_download_clip(clip_id):
    clip = (GeneratedClip.query.join(VideoJob)
            .filter(GeneratedClip.id == clip_id, VideoJob.user_id == current_user.id).first())
    if clip is None:
        return err("Clip not found.", 404)
    path = _clip_path(clip)
    if not path.exists():
        return err("Clip file is missing.", 404)
    return send_file(path, as_attachment=True, download_name=clip.filename)


@api_bp.route("/jobs/<int:job_id>/download-all")
@login_required
def api_download_all(job_id):
    from ..videos.routes import download_all as web_download_all
    return web_download_all(job_id)


@api_bp.route("/jobs/<int:job_id>", methods=["DELETE"])
@login_required
def api_delete_job(job_id):
    from ..videos.routes import delete_job as _unused  # noqa: F401 (keeps parity obvious)
    import shutil
    job = get_owned_job(job_id)
    out_dir = Path(current_app.config["OUTPUT_FOLDER"]) / f"user_{current_user.id}" / f"job_{job.id}"
    src = Path(current_app.config["UPLOAD_FOLDER"]) / (job.stored_filename or "")
    db.session.delete(job)
    db.session.commit()
    shutil.rmtree(out_dir, ignore_errors=True)
    src.unlink(missing_ok=True)
    return jsonify({"ok": True})
