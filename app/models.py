from datetime import datetime, timezone

from flask_login import UserMixin
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow():
    return datetime.now(timezone.utc)


class User(UserMixin, db.Model):
    __tablename__ = "users"
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False, index=True)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    jobs = db.relationship("VideoJob", back_populates="user", cascade="all, delete-orphan")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)


class VideoJob(db.Model):
    __tablename__ = "video_jobs"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    original_filename = db.Column(db.String(255), nullable=False)
    stored_filename = db.Column(db.String(255), nullable=True)  # server-generated name on disk
    source_type = db.Column(db.String(20), nullable=False, default="upload")  # upload | url
    source_reference = db.Column(db.String(1024), nullable=True)  # original URL (display only)
    title = db.Column(db.String(255), nullable=True)
    original_duration = db.Column(db.Float, nullable=True)  # seconds
    has_audio = db.Column(db.Boolean, nullable=True)
    selected_clip_duration = db.Column(db.Integer, nullable=True)  # seconds
    output_format = db.Column(db.String(10), nullable=False, default="mp4")
    name_prefix = db.Column(db.String(80), nullable=False, default="clip")
    reencode = db.Column(db.Boolean, nullable=False, default=False)
    status = db.Column(db.String(20), nullable=False, default="uploaded", index=True)
    # uploaded | queued | processing | completed | failed | cancelled
    progress = db.Column(db.Integer, nullable=False, default=0)  # 0-100, real per-clip progress
    error_message = db.Column(db.Text, nullable=True)
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)
    completed_at = db.Column(db.DateTime, nullable=True)

    user = db.relationship("User", back_populates="jobs")
    clips = db.relationship(
        "GeneratedClip", back_populates="job", cascade="all, delete-orphan",
        order_by="GeneratedClip.clip_number",
    )

    def to_dict(self):
        return {
            "id": self.id,
            "original_filename": self.original_filename,
            "source_type": self.source_type,
            "title": self.title,
            "original_duration": self.original_duration,
            "selected_clip_duration": self.selected_clip_duration,
            "output_format": self.output_format,
            "status": self.status,
            "progress": self.progress,
            "error_message": self.error_message,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "clip_count": len(self.clips),
        }


class GeneratedClip(db.Model):
    __tablename__ = "generated_clips"
    id = db.Column(db.Integer, primary_key=True)
    job_id = db.Column(db.Integer, db.ForeignKey("video_jobs.id"), nullable=False, index=True)
    clip_number = db.Column(db.Integer, nullable=False)
    filename = db.Column(db.String(255), nullable=False)  # server-generated name on disk
    start_time = db.Column(db.Float, nullable=False)  # seconds
    end_time = db.Column(db.Float, nullable=False)
    duration = db.Column(db.Float, nullable=False)
    file_size = db.Column(db.Integer, nullable=True)  # bytes
    created_at = db.Column(db.DateTime, default=utcnow, nullable=False)

    job = db.relationship("VideoJob", back_populates="clips")

    def to_dict(self):
        return {
            "id": self.id,
            "job_id": self.job_id,
            "clip_number": self.clip_number,
            "filename": self.filename,
            "start_time": self.start_time,
            "end_time": self.end_time,
            "duration": self.duration,
            "file_size": self.file_size,
        }
