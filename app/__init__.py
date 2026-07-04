import logging
import os
import time

from dotenv import load_dotenv
from flask import Flask, request, g
from flask_session import Session
from werkzeug.middleware.proxy_fix import ProxyFix

from .database.connection import client as mongo_client, DB_NAME
from .database.telemetry import log_api_request

load_dotenv()

logging.basicConfig(
    level=os.environ.get("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


def create_app() -> Flask:
    """
    Application factory that initializes and configures the Flask instance.
    Configures:
    1. Template and Static folders.
    2. MongoDB-backed thread-safe sessions.
    3. Blueprints for all modular APIs.
    4. Middleware for technical telemetry and performance tracking.
    
    :return: A configured Flask application object.
    """
    app = Flask(__name__,
                template_folder='../templates',
                static_folder='../static')

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

    secret_key = os.environ.get('SECRET_KEY')
    if not secret_key:
        raise RuntimeError(
            "SECRET_KEY environment variable is required (see .env.example). "
            "Refusing to start with an insecure default."
        )
    app.secret_key = secret_key

    app.config['SESSION_TYPE'] = 'mongodb'
    app.config['SESSION_MONGODB'] = mongo_client
    app.config['SESSION_MONGODB_DB'] = DB_NAME
    app.config['SESSION_MONGODB_COLLECT'] = 'sessions'
    app.config['PERMANENT_SESSION_LIFETIME'] = int(os.environ.get('SESSION_LIFETIME_SECONDS', 1800))

    app.config['SESSION_COOKIE_HTTPONLY'] = True
    app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
    app.config['SESSION_COOKIE_SECURE'] = (
        os.environ.get('SESSION_COOKIE_SECURE', 'false').lower() in ('1', 'true', 'yes')
    )
    Session(app)

    from .routes.api_telemetry import telemetry_bp
    from .routes.core import core_bp
    from .routes.api_travel import travel_bp
    from .routes.api_guides import guides_bp
    from .routes.api_auth import auth_bp
    from .routes.api_user import user_bp
    from .routes.api_i18n import i18n_bp

    app.register_blueprint(telemetry_bp, url_prefix='/api/portfolio')
    app.register_blueprint(core_bp)
    app.register_blueprint(travel_bp, url_prefix='/api/travel')
    app.register_blueprint(guides_bp, url_prefix='/api/guides')
    app.register_blueprint(auth_bp, url_prefix='/api/auth')
    app.register_blueprint(user_bp, url_prefix='/api/user')
    app.register_blueprint(i18n_bp, url_prefix='/api/i18n')

    @app.before_request
    def start_timer():
        """Middleware to record the precise start time of every incoming request."""
        g.start_time = time.time()

    @app.after_request
    def log_request(response):
        """Middleware to calculate performance metrics and log technical telemetry after each request."""
        if hasattr(g, 'start_time'):
            diff = float(time.time() - g.start_time) * 1000
            if not request.path.startswith('/static'):
                log_api_request(
                    project_name="BharatBhraman",
                    endpoint=request.endpoint or request.path,
                    method=request.method,
                    status_code=response.status_code,
                    response_time_ms=int(diff)
                )
        return response

    return app


if __name__ == '__main__':
    app = create_app()
    debug = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    app.run(debug=debug)
