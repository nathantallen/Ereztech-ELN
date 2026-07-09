import os

from flask import Flask

from .extensions import db, login_manager


def create_app():
    app = Flask(__name__)
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get(
        "DATABASE_URL", "postgresql+psycopg2://erezops:erezops@localhost:5432/erezops"
    )
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    db.init_app(app)
    login_manager.init_app(app)

    from .auth import bp as auth_bp
    from .main import bp as main_bp
    from .runs import bp as runs_bp
    from .reactors import bp as reactors_bp
    from .rd import bp as rd_bp
    from .admin import bp as admin_bp
    from .docroots import bp as docroots_bp
    from .settings import bp as settings_bp
    from .sap import bp as sap_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(main_bp)
    app.register_blueprint(runs_bp)
    app.register_blueprint(reactors_bp)
    app.register_blueprint(rd_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(docroots_bp)
    app.register_blueprint(settings_bp)
    app.register_blueprint(sap_bp)

    from . import models  # noqa: F401  (register models with SQLAlchemy)

    @app.context_processor
    def inject_ui_helpers():
        from .models import Role, RunStatus
        from .permissions import can_edit_production, is_admin

        try:
            status_colors = {
                s.name: s.color
                for s in RunStatus.query.order_by(RunStatus.position, RunStatus.id)
            }
            role_colors = {r.name: r.color for r in Role.query}
        except Exception:  # first boot, before tables exist
            status_colors, role_colors = {}, {}
        return dict(
            is_admin=is_admin(),
            can_edit_prod=can_edit_production(),
            status_colors=status_colors,
            role_colors=role_colors,
        )

    return app
