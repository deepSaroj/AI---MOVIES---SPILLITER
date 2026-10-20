import os
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent


def _db_uri():
    url = os.environ.get("DATABASE_URL", "")
    if url:
        # Render/Heroku style postgres:// -> postgresql://
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        return url
    return f"sqlite:///{BASE_DIR / 'instance' / 'app.db'}"


class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-change-me")
    SQLALCHEMY_DATABASE_URI = _db_uri()
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    # Uploads
    MAX_CONTENT_LENGTH = int(os.environ.get("MAX_UPLOAD_MB", "2048")) * 1024 * 1024
    UPLOAD_FOLDER = str(Path(os.environ.get("UPLOAD_FOLDER", BASE_DIR / "uploads")))
    OUTPUT_FOLDER = str(Path(os.environ.get("OUTPUT_FOLDER", BASE_DIR / "outputs")))
    ALLOWED_EXTENSIONS = {"mp4", "mov", "mkv", "avi", "webm", "m4v"}
    # Remote download cap (MB) for the from-URL flow
    MAX_REMOTE_MB = int(os.environ.get("MAX_REMOTE_MB", "1024"))
    # Retention: delete job files older than this many days (0 = never auto-delete)
    RETENTION_DAYS = int(os.environ.get("RETENTION_DAYS", "7"))
    # Processing
    REENCODE_DEFAULT = os.environ.get("REENCODE_DEFAULT", "0") == "1"
    FFMPEG_BIN = os.environ.get("FFMPEG_BIN", "ffmpeg")
    FFPROBE_BIN = os.environ.get("FFPROBE_BIN", "ffprobe")
    # Session security
    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    SESSION_COOKIE_SECURE = os.environ.get("SESSION_COOKIE_SECURE", "0") == "1"
    REMEMBER_COOKIE_HTTPONLY = True
    WTF_CSRF_TIME_LIMIT = None


class TestConfig(Config):
    TESTING = True
    SECRET_KEY = "test-secret"
    SQLALCHEMY_DATABASE_URI = "sqlite://"
    WTF_CSRF_ENABLED = False
    MAX_CONTENT_LENGTH = 64 * 1024 * 1024
