from flask import Blueprint, current_app, jsonify, render_template, request

from hainan_cycling.catalog.repository import (
    AttractionNotFoundError,
    delete_attraction,
    list_attractions,
    set_attraction_status,
)

web = Blueprint("web", __name__)


@web.get("/")
def index():
    return render_template("index.html")


@web.get("/api/attractions")
def attractions():
    status = request.args.get("status", "approved")
    try:
        items = list_attractions(status=status)
    except (OSError, ValueError):
        current_app.logger.exception("Unable to load attraction catalog")
        return jsonify({"error": "Unable to load attraction catalog"}), 500

    return jsonify([item.model_dump(mode="json") for item in items])


@web.post("/api/attractions/<attraction_id>/status")
def update_attraction_status(attraction_id: str):
    payload = request.get_json(silent=True) or {}
    status = payload.get("status")
    if not isinstance(status, str):
        return jsonify({"error": "A status string is required"}), 400

    try:
        item = set_attraction_status(attraction_id, status)
    except AttractionNotFoundError:
        return jsonify({"error": "Attraction not found"}), 404
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except OSError:
        current_app.logger.exception("Unable to write attraction catalog")
        return jsonify({"error": "Unable to write attraction catalog"}), 500

    return jsonify(item.model_dump(mode="json"))


@web.delete("/api/attractions/<attraction_id>")
def remove_attraction(attraction_id: str):
    try:
        delete_attraction(attraction_id)
    except AttractionNotFoundError:
        return jsonify({"error": "Attraction not found"}), 404
    except ValueError as error:
        return jsonify({"error": str(error)}), 400
    except OSError:
        current_app.logger.exception("Unable to write attraction catalog")
        return jsonify({"error": "Unable to write attraction catalog"}), 500

    return "", 204
