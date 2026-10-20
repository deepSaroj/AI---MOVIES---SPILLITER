from flask import Blueprint, render_template
from flask_login import current_user, login_required

from ..models import VideoJob

main_bp = Blueprint("main", __name__)


@main_bp.route("/")
def index():
    return render_template("index.html")


@main_bp.route("/privacy")
def privacy():
    return render_template("privacy.html")


@main_bp.route("/terms")
def terms():
    return render_template("terms.html")


@main_bp.route("/dashboard")
@login_required
def dashboard():
    jobs = (VideoJob.query.filter_by(user_id=current_user.id)
            .order_by(VideoJob.created_at.desc()).all())
    stats = {
        "total": len(jobs),
        "completed": sum(1 for j in jobs if j.status == "completed"),
        "processing": sum(1 for j in jobs if j.status in ("queued", "processing")),
        "clips": sum(len(j.clips) for j in jobs),
    }
    return render_template("dashboard.html", jobs=jobs[:10], stats=stats)
