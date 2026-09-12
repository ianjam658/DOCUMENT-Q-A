from functools import wraps
from flask import request, jsonify, current_app


def require_api_key(f):
    """Protects an endpoint with a shared-secret API key sent as the
    X-API-Key header. Swap this for per-customer keys stored in the DB
    once you have real paying customers to manage."""

    @wraps(f)
    def decorated(*args, **kwargs):
        expected = current_app.config["API_SECRET_KEY"]
        provided = request.headers.get("X-API-Key")
        if not provided or provided != expected:
            return jsonify({"error": "Unauthorized — missing or invalid X-API-Key header"}), 401
        return f(*args, **kwargs)

    return decorated
