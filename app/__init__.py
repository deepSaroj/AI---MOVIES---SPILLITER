import os
from pathlib import Path

from flask import Flask

from config import Config


def create_app(config_object=None):
    app = Flask(__name__)
    app.config.from_object(config_object or Config)

    Path(app.config["UPLOAD_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.config["OUTPUT_FOLDER"]).mkdir(parents=True, exist_ok=True)
    Path(app.instance_path).mkdir(parents=True, exist_ok=True)

    from .extensions import csrf, db, limiter, login_manager, migrate
    db.init_app(app)
    migrate.init_app(app, db)
    login_manager.init_app(app)
    csrf.init_app(app)
    if limiter is not None:
        limiter.init_app(app)

    from .models import User

    @login_manager.user_loader
    def load_user(user_id):
        return db.session.get(User, int(user_id))

    from .auth.routes import auth_bp
    from .main.routes import main_bp
    from .videos.routes import videos_bp
    from .api.routes import api_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(videos_bp)
    app.register_blueprint(api_bp)

    @app.after_request
    def security_headers(resp):
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "SAMEORIGIN")
        resp.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        return resp

    @app.errorhandler(404)
    def not_found(_e):
        from flask import render_template
        return render_template("errors/404.html"), 404

    @app.errorhandler(413)
    def too_large(_e):
        from flask import flash, redirect, url_for
        flash("That file is larger than the server upload limit.", "danger")
        return redirect(url_for("videos.workspace"))

    @app.errorhandler(500)
    def server_error(_e):
        from flask import render_template
        return render_template("errors/500.html"), 500

   # with app.app_context():
 #       db.create_all()  # dev convenience; production uses Flask-Migrate (see README)
    return app
