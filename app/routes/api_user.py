from flask import Blueprint, request, session
from ..services.user_service import UserService
from ..utils.api_response import success, error

user_bp = Blueprint('user_api', __name__)
user_service = UserService()

@user_bp.route('/dashboard', methods=['GET'])
def get_dashboard():
    """
    Endpoint for retrieving the user's dashboard data.
    Requires: User session ('user_id').
    Returns: JSON containing saved 'trips' and guide 'bookings'.
    """
    user_id = session.get('user_id')
    if not user_id:
        return error("UNAUTHORIZED", "Unauthorized", 401)
    
    data = user_service.get_dashboard_data(user_id)
    return success(data, status_code=200)

@user_bp.route('/save-trip', methods=['POST'])
def save_trip():
    """
    Endpoint to persist the current session's travel itinerary to the user's account history.
    Requires: User session ('user_id') and active trip in session ('trip').
    The trip's conversation is stored alongside it so the user can revisit their
    chat when they reopen the saved trip.
    Returns: Success message and generated Trip ID.
    """
    user_id = session.get('user_id')
    trip_data = session.get('trip')

    if not user_id or not trip_data:
        return error("NO_ACTIVE_TRIP", "Unauthorized or no active trip to save", 400)

    chat_history = session.get('chat_history', [])
    trip_id = user_service.save_trip(user_id, trip_data, chat_history)
    return success({"trip_id": trip_id}, "Trip saved successfully", 201)


@user_bp.route('/open-trip', methods=['POST'])
def open_trip():
    """
    Loads a saved trip back into the session so the user can view it and chat
    about it. Requires: user session + JSON {'trip_id': '...'}.
    Returns: the saved trip itinerary.
    """
    user_id = session.get('user_id')
    if not user_id:
        return error("UNAUTHORIZED", "Unauthorized", 401)

    trip_id = (request.get_json(silent=True) or {}).get('trip_id')
    if not trip_id:
        return error("MISSING_TRIP_ID", "trip_id is required", 400)

    record = user_service.get_trip(user_id, trip_id)
    if not record or not record.get("itinerary"):
        return error("TRIP_NOT_FOUND", "Saved trip not found", 404)

    itinerary = record["itinerary"]
    chat_history = record.get("chat_history", [])

    session['trip'] = itinerary
    session['chat_history'] = chat_history
    return success({
        "trip": itinerary,
        "trip_id": record.get("trip_id"),
        "chat_history": chat_history,
    }, status_code=200)


@user_bp.route('/delete-trip', methods=['POST'])
def delete_trip():
    """Deletes a saved trip owned by the logged-in user."""
    user_id = session.get('user_id')
    if not user_id:
        return error("UNAUTHORIZED", "Unauthorized", 401)

    trip_id = (request.get_json(silent=True) or {}).get('trip_id')
    if not trip_id:
        return error("MISSING_TRIP_ID", "trip_id is required", 400)

    if not user_service.delete_trip(user_id, trip_id):
        return error("TRIP_NOT_FOUND", "Saved trip not found", 404)
    return success({"trip_id": trip_id}, "Trip deleted", 200)


@user_bp.route('/update-trip-chat', methods=['POST'])
def update_trip_chat():
    """Persists ongoing chat for a saved trip the user is viewing."""
    user_id = session.get('user_id')
    if not user_id:
        return error("UNAUTHORIZED", "Unauthorized", 401)

    payload = request.get_json(silent=True) or {}
    trip_id = payload.get('trip_id')
    chat_history = payload.get('chat_history')
    if not trip_id or not isinstance(chat_history, list):
        return error("INVALID_PAYLOAD", "trip_id and chat_history are required", 400)

    if not user_service.update_trip_chat(user_id, trip_id, chat_history):
        return error("TRIP_NOT_FOUND", "Saved trip not found", 404)
    return success({"trip_id": trip_id}, "Chat saved", 200)
