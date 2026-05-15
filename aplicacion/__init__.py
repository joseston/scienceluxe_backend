
import logging
import sys

from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from config import Config

db = SQLAlchemy()
migrate = Migrate()


def _configure_logging(app: Flask) -> None:
    root_logger = logging.getLogger()
    if not root_logger.handlers:
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s %(levelname)s %(name)s: %(message)s',
            stream=sys.stdout,
        )
    else:
        root_logger.setLevel(logging.INFO)
        for handler in root_logger.handlers:
            handler.setLevel(logging.INFO)

    app.logger.setLevel(logging.INFO)
    logging.getLogger('werkzeug').setLevel(logging.INFO)

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)
    _configure_logging(app)

    # Copiar DB_SCHEMA a config para que Alembic pueda ubicar version_table_schema.
    if hasattr(config_class, 'DB_SCHEMA'):
        app.config['DB_SCHEMA'] = getattr(config_class, 'DB_SCHEMA')

    db.init_app(app)
    migrate.init_app(
        app,
        db,
        # Evita colisiones con otras apps que ya tengan una tabla 'alembic_version'
        # en la misma BD (caso típico en Supabase).
        configure_args={"version_table": "alembic_version_scienceluxe_backend"},
    )

    from aplicacion import models
    from aplicacion.endpoints.proceso0 import proceso0_bp
    from aplicacion.endpoints.proceso1 import proceso1_bp
    from aplicacion.endpoints.proceso2 import proceso2_bp
    from aplicacion.endpoints.proceso3 import proceso3_bp
    from aplicacion.endpoints.proceso4 import proceso4_bp
    from aplicacion.endpoints.proceso5 import proceso5_bp
    from aplicacion.endpoints.proceso1_corto import proceso1_corto_bp
    from aplicacion.endpoints.proceso2_corto import proceso2_corto_bp
    from aplicacion.endpoints.proceso3_corto import proceso3_corto_bp
    from aplicacion.endpoints.proceso4_corto import proceso4_corto_bp
    from aplicacion.endpoints.clip_library import clip_library_bp
    from aplicacion.endpoints.videos import videos_bp

    app.register_blueprint(proceso0_bp, url_prefix='/api/proceso0')
    app.register_blueprint(proceso1_bp, url_prefix='/api/proceso1')
    app.register_blueprint(proceso2_bp, url_prefix='/api/proceso2')
    app.register_blueprint(proceso3_bp, url_prefix='/api/proceso3')
    app.register_blueprint(proceso4_bp, url_prefix='/api/proceso4')
    app.register_blueprint(proceso5_bp, url_prefix='/api/proceso5')
    app.register_blueprint(proceso1_corto_bp, url_prefix='/api/proceso1-corto')
    app.register_blueprint(proceso2_corto_bp, url_prefix='/api/proceso2-corto')
    app.register_blueprint(proceso3_corto_bp, url_prefix='/api/proceso3-corto')
    app.register_blueprint(proceso4_corto_bp, url_prefix='/api/proceso4-corto')
    app.register_blueprint(clip_library_bp, url_prefix='/api/clip-library')
    app.register_blueprint(videos_bp, url_prefix='/api/videos')

    @app.after_request
    def add_cors_headers(response):
        response.headers['Access-Control-Allow-Origin'] = '*'
        response.headers['Access-Control-Allow-Headers'] = 'Content-Type, Authorization'
        response.headers['Access-Control-Allow-Methods'] = 'GET, POST, PATCH, PUT, DELETE, OPTIONS'
        return response

    # Register blueprints or routes here if needed
    # from aplicacion.routes import main
    # app.register_blueprint(main)

    @app.route('/')
    def index():
        return "Scienceluxe Backend is Running!"

    @app.route('/health')
    def health():
        return {'status': 'ok'}

    return app
