"""Disk storage helpers. Files live on disk (never in DB rows).

Local dev: uploads/ and outputs/ folders.
Production: point UPLOAD_FOLDER / OUTPUT_FOLDER at a persistent disk, or swap
save_stream() for an S3/GCS implementation (same interface).
"""
import uuid
from pathlib import Path

from werkzeug.utils import secure_filename


def generated_name(original_filename):
    ext = Path(original_filename or "").suffix.lower()
    return f"{uuid.uuid4().hex}{ext}"


def save_upload(file_storage, upload_folder):
    """Save an uploaded file under a generated name; return (stored_name, path)."""
    folder = Path(upload_folder)
    folder.mkdir(parents=True, exist_ok=True)
    name = generated_name(secure_filename(file_storage.filename or "video"))
    path = folder / name
    file_storage.save(path)
    return name, path


def job_output_dir(output_folder, user_id, job_id):
    path = Path(output_folder) / f"user_{user_id}" / f"job_{job_id}"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_join(base, *parts):
    """Path-traversal-safe join: result must stay inside base."""
    base = Path(base).resolve()
    target = (base / Path(*parts)).resolve()
    if base != target and base not in target.parents:
        raise ValueError("Invalid path.")
    return target
