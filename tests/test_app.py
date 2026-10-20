import io
import time
from pathlib import Path

import pytest

from app.extensions import db
from app.models import GeneratedClip, User, VideoJob
from app.services import url_validator, video_processor
from tests.conftest import make_user

# ---------- Duration maths ----------

def test_calculate_clips_spec_example():
    clips = video_processor.calculate_clips(65 * 60, 10 * 60)
    assert len(clips) == 7
    assert clips[0] == (0.0, 600.0)
    assert clips[-1] == (3600.0, 3900.0)  # final partial clip keeps the remainder


def test_calculate_clips_exact_multiple_and_single():
    assert video_processor.calculate_clips(600, 600) == [(0.0, 600.0)]
    assert len(video_processor.calculate_clips(65, 10)) == 7
    assert video_processor.calculate_clips(65, 10)[-1] == (60.0, 65.0)


def test_calculate_clips_rejects_bad_input():
    with pytest.raises(ValueError):
        video_processor.calculate_clips(0, 10)
    with pytest.raises(ValueError):
        video_processor.calculate_clips(100, 0)


# ---------- URL validation / SSRF ----------

@pytest.mark.parametrize("url", [
    "http://127.0.0.1/movie.mp4",
    "http://localhost/movie.mp4",
    "http://169.254.169.254/latest/meta-data/",
    "http://10.0.0.5/movie.mp4",
    "http://192.168.1.10/movie.mp4",
    "ftp://example.com/movie.mp4",
    "file:///etc/passwd",
])
def test_ssrf_blocked(url):
    with pytest.raises(url_validator.URLValidationError):
        url_validator.assert_public_url(url)


def test_youtube_is_page_only_and_honest():
    with pytest.raises(url_validator.URLValidationError) as exc:
        url_validator.validate_remote_video_url("https://www.youtube.com/watch?v=abc123")
    assert "not" in str(exc.value).lower() and "upload" in str(exc.value).lower()


# ---------- Auth ----------

def test_register_and_login(client):
    resp = make_user(client)
    assert resp.status_code in (302, 200)
    client.get("/logout")
    resp = client.post("/login", data={"email": "deepak@example.com",
                                       "password": "password123"})
    assert resp.status_code == 302
    assert client.get("/dashboard").status_code == 200


def test_password_is_hashed(client):
    make_user(client)
    user = User.query.filter_by(email="deepak@example.com").first()
    assert user.password_hash != "password123"
    assert user.check_password("password123")
    assert not user.check_password("wrong-password")


def test_dashboard_requires_login(client):
    assert client.get("/dashboard").status_code == 302


def test_api_register_login(client):
    resp = client.post("/api/auth/register", json={
        "username": "apiuser", "email": "api@example.com", "password": "password123"})
    assert resp.status_code == 201
    client.post("/api/auth/logout")
    resp = client.post("/api/auth/login", json={
        "email": "api@example.com", "password": "bad"})
    assert resp.status_code == 401
    resp = client.post("/api/auth/login", json={
        "email": "api@example.com", "password": "password123"})
    assert resp.status_code == 200


# ---------- Upload validation ----------

def upload(client, path, name=None):
    data = {"video": (io.BytesIO(Path(path).read_bytes()), name or Path(path).name)}
    return client.post("/videos/upload", data=data, content_type="multipart/form-data")


def test_upload_rejects_fake_video(auth_client):
    resp = auth_client.post("/videos/upload", data={
        "video": (io.BytesIO(b"this is not a video"), "fake.mp4")},
        content_type="multipart/form-data")
    assert resp.status_code == 302  # back to workspace with an error flash
    assert VideoJob.query.count() == 0


def test_upload_rejects_bad_extension(auth_client, sample_video):
    resp = upload(auth_client, sample_video, name="movie.exe")
    assert resp.status_code == 302
    assert VideoJob.query.count() == 0


def test_upload_valid_video_creates_job(auth_client, sample_video):
    resp = upload(auth_client, sample_video)
    assert resp.status_code == 302
    job = VideoJob.query.first()
    assert job is not None and job.status == "uploaded"
    assert 64.0 < job.original_duration < 66.0
    assert job.has_audio is True


def test_upload_silent_video_has_no_audio(auth_client, silent_video):
    upload(auth_client, silent_video)
    job = VideoJob.query.first()
    assert job.has_audio is False


# ---------- Real splitting ----------

def wait_for_job(job_id, timeout=120):
    deadline = time.time() + timeout
    while time.time() < deadline:
        job = db.session.get(VideoJob, job_id)
        db.session.refresh(job)
        if job.status in ("completed", "failed", "cancelled"):
            return job
        time.sleep(0.5)
    raise AssertionError("job did not finish in time")


def test_real_split_with_final_partial_clip(app, auth_client, sample_video):
    upload(auth_client, sample_video)
    job = VideoJob.query.first()
    resp = auth_client.post(f"/jobs/{job.id}/split", data={
        "clip_duration": 10, "output_format": "mp4", "name_prefix": "part"})
    assert resp.status_code == 302
    job = wait_for_job(job.id)
    assert job.status == "completed", job.error_message
    assert job.progress == 100
    clips = GeneratedClip.query.filter_by(job_id=job.id).order_by(GeneratedClip.clip_number).all()
    assert len(clips) == 7  # 65s @ 10s -> 6 full + 1 partial (5s)
    assert clips[-1].start_time == 60.0 and clips[-1].end_time == 65.0
    for c in clips:
        assert c.file_size and c.file_size > 0
    # On-disk clips are real, probe-able videos
    from app.services import video_probe
    out_dir = Path(app.config["OUTPUT_FOLDER"]) / f"user_{job.user_id}" / f"job_{job.id}"
    info = video_probe.probe_video(out_dir / clips[-1].filename)
    assert 4.0 < info["duration"] < 6.5


def test_download_permissions(app, auth_client, sample_video):
    upload(auth_client, sample_video)
    job = VideoJob.query.first()
    auth_client.post(f"/jobs/{job.id}/split", data={"clip_duration": 30})
    job = wait_for_job(job.id)
    clip = GeneratedClip.query.filter_by(job_id=job.id).first()
    # Owner can download
    assert auth_client.get(f"/clips/{clip.id}/download").status_code == 200
    assert auth_client.get(f"/jobs/{job.id}/download-all").status_code == 200
    # A second user cannot (Flask test clients share a cookie jar, so log the
    # shared session out first, then register the second user for real)
    other = app.test_client()
    other.get("/logout")
    make_user(other, username="other", email="other@example.com")
    assert b"other" in other.get("/dashboard").data
    assert other.get(f"/clips/{clip.id}/download").status_code == 404
    assert other.get(f"/jobs/{job.id}").status_code == 404
    assert other.get(f"/jobs/{job.id}/download-all").status_code == 404
    assert other.get(f"/api/jobs/{job.id}").status_code == 404


def test_job_cancellation(app, auth_client, sample_video):
    upload(auth_client, sample_video)
    job = VideoJob.query.first()
    auth_client.post(f"/api/jobs/{job.id}/cancel")  # not processing yet: no-op, stays uploaded
    job = db.session.get(VideoJob, job.id)
    assert job.status == "uploaded"
    # Cooperative cancel: raise the cancel flag, then start the job — the worker
    # must honour it at the first clip boundary and end as 'cancelled',
    # never 'completed'. (Deterministic; a fast stream-copy split could
    # otherwise finish before a mid-flight cancel lands.)
    from app.services import jobs as runner
    runner.request_cancel(job.id)
    auth_client.post(f"/jobs/{job.id}/split", data={"clip_duration": 5})
    job = wait_for_job(job.id, timeout=60)
    assert job.status == "cancelled"
    assert GeneratedClip.query.filter_by(job_id=job.id).count() == 0
    runner.clear_cancel(job.id)


def test_job_persists_in_db(auth_client, sample_video):
    upload(auth_client, sample_video)
    job_id = VideoJob.query.first().id
    db.session.remove()
    again = db.session.get(VideoJob, job_id)
    assert again is not None and again.original_filename.endswith(".mp4")


def test_public_pages(client):
    for path in ("/", "/privacy", "/terms", "/login", "/register"):
        assert client.get(path).status_code == 200, path
    assert b"Split Videos. Create Clips. Save Time." in client.get("/").data
    assert b"Paste an authorized video URL here" in client.get("/").data
