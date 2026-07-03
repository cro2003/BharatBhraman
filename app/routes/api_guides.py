from flask import Blueprint, request, session
from ..services.guide_service import GuideService
from ..utils.api_response import success, error

guides_bp = Blueprint('guides_api', __name__)
guide_service = GuideService()

@guides_bp.route('/register', methods=['POST'])
def register_guide():
    """
    Endpoint for travel guide registration.
    Accepts JSON or form data.
    """
    payload = request.get_json(silent=True) or request.form
    languages_raw = payload.get('languages') or payload.get('Language', '')
    if isinstance(languages_raw, str):
        languages = [item.strip() for item in languages_raw.split(',') if item.strip()]
    else:
        languages = list(languages_raw or [])

    try:
        hourly_rate = float(payload.get('hourly_rate') or payload.get('price', 0) or 0)
    except (TypeError, ValueError):
        return error("INVALID_GUIDE_PAYLOAD", "hourly_rate must be a number", 400)

    guide_data = {
        "name": payload.get('name') or payload.get('first'),
        "age": payload.get('age') or payload.get('Age'),
        "gender": payload.get('gender'),
        "languages": languages,
        "email": payload.get('email'),
        "phone": payload.get('phone') or payload.get('mobile'),
        "cities_covered": [payload.get('city')],
        "hourly_rate": hourly_rate
    }

    if not guide_data["name"] or not guide_data["email"] or not guide_data["cities_covered"][0]:
        return error("INVALID_GUIDE_PAYLOAD", "Missing required guide registration fields", 400)

    guide_id = guide_service.register_guide(guide_data)
    return success({"guide_id": guide_id}, "Guide registered successfully", 201)

@guides_bp.route('/search', methods=['GET'])
def search_guides():
    """
    Endpoint to search for available guides in a specific city.
    Query Params: ?city=Mumbai&lang=English
    """
    city = request.args.get('city')
    lang = request.args.get('lang')
    if not city:
        return error("MISSING_CITY", "City is required", 400)
    results = guide_service.search_guides(city, lang)
    return success(results, status_code=200)

@guides_bp.route('/book', methods=['POST'])
def book_guide():
    """
    Endpoint to initiate a guide booking (requires login).
    Expects JSON: {'guide_id': '...', 'date': 'YYYY-MM-DD', 'hours': 2}
    """
    user_id = session.get('user_id')
    if not user_id:
        return error("UNAUTHORIZED", "Please log in to book a guide", 401)

    payload = request.get_json(silent=True) or {}
    guide_id = payload.get('guide_id')
    date = payload.get('date')
    if not guide_id or not date:
        return error("MISSING_BOOKING_FIELDS", "guide_id and date are required", 400)

    try:
        hours = float(payload.get('hours', 1) or 1)
    except (TypeError, ValueError):
        return error("INVALID_HOURS", "hours must be a number", 400)
    if hours <= 0:
        return error("INVALID_HOURS", "hours must be greater than zero", 400)

    booking = guide_service.book_guide(user_id, guide_id, date, hours)
    if not booking:
        return error("GUIDE_NOT_FOUND", "No guide found for the given id", 404)
    return success({"booking": booking}, "Booking pending", 201)


@guides_bp.route('/review', methods=['POST'])
def review_guide():
    """
    Endpoint to submit a review for a guide (requires login).
    Expects JSON: {'guide_id': '...', 'rating': 1-5, 'comment': '...'}
    """
    user_id = session.get('user_id')
    if not user_id:
        return error("UNAUTHORIZED", "Please log in to leave a review", 401)

    payload = request.get_json(silent=True) or {}
    guide_id = payload.get('guide_id')
    comment = (payload.get('comment') or '').strip()
    try:
        rating = float(payload.get('rating'))
    except (TypeError, ValueError):
        return error("INVALID_RATING", "rating must be a number between 1 and 5", 400)

    if not guide_id:
        return error("MISSING_GUIDE_ID", "guide_id is required", 400)
    if not (1 <= rating <= 5):
        return error("INVALID_RATING", "rating must be between 1 and 5", 400)

    user_name = session.get('user_name', 'Traveller')
    if not guide_service.add_review(guide_id, user_name, rating, comment):
        return error("GUIDE_NOT_FOUND", "No guide found for the given id", 404)
    return success(message="Review submitted", status_code=201)
