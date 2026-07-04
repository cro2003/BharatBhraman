import os

from app import create_app

app = create_app()

if __name__ == "__main__":
    debug = os.environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
    port = int(os.environ.get("PORT", 5000))
    app.run(debug=debug, port=port)
