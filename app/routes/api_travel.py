from flask import Blueprint, request, session
from ..services.travel_orchestrator import TravelOrchestrator
from ..services.ai_service import AIService
from ..services.location_service import LocationService
from ..services.flight_service import FlightService
from ..services.train_service import TrainService
from ..services.quick_pick_service import QuickPickService
from ..utils.api_response import success, error
from ..utils.validation import is_iso_date, normalize_preference, same_place

MAX_CHAT_MESSAGE_CHARS = 2000
MAX_CHAT_TURNS = 8
SUPPORTED_CHAT_LANGUAGES = {"English", "Hindi", "Marathi", "Gujarati", "Tamil", "Kannada"}

travel_bp = Blueprint('travel_api', __name__)
orchestrator = TravelOrchestrator()
ai_service = AIService()
loc_service = LocationService()
flight_service = FlightService()
train_service = TrainService()
qp_service = QuickPickService()

@travel_bp.route('/lookup/location', methods=['GET'])
def lookup_location():
    """
    Endpoint for city and place name autocompletion using Geoapify.
    Query Params: ?q=Mumb
    :return: List of top 5 location matches.
    """
    query = request.args.get('q')
    if not query:
        return success([], status_code=200)
    results = loc_service.search_locations(query)
    return success(results, status_code=200)

@travel_bp.route('/lookup/airport', methods=['GET'])
def lookup_airport():
    """
    Endpoint for airport code and name autocompletion via IRCTC Air.
    Query Params: ?q=BOM
    :return: List of matching airport objects.
    """
    query = request.args.get('q')
    if not query:
        return success([], status_code=200)
    results = flight_service.get_airport_data(query)
    return success([results] if results else [], status_code=200)

@travel_bp.route('/lookup/train-station', methods=['GET'])
def lookup_train_station():
    """
    Endpoint for Indian Railways station resolution via RailYatri.
    Query Params: ?q=Bhopal
    :return: Station name and code dictionary.
    """
    query = request.args.get('q')
    if not query:
        return success([], status_code=200)
    result = train_service.get_station_data(query)
    return success([result] if result else [], status_code=200)

@travel_bp.route('/search', methods=['POST'])
def start_trip_search():
    """
    Initiates an asynchronous multi-modal travel search job.
    Expects JSON: {'origin': '...', 'destination': '...', 'date': 'YYYY-MM-DD', 'preferences': 'Comfort'|'Budget', 'language': '...', 'mode': 'manual'|...}
    A 'manual' mode runs the progressive worker (flights first, trains on-demand);
    anything else is the one-shot quick-pick bundle.
    :return: Job ID and initial processing status.
    """
    data = request.get_json(silent=True) or {}
    origin = data.get('origin')
    destination = data.get('destination')
    date = data.get('date')
    pref = normalize_preference(data.get('preferences', 'Comfort'))
    lang = data.get('language', 'English')
    mode = 'manual' if data.get('mode') == 'manual' else 'quickpick'

    if not origin or not destination or not date:
        return error("MISSING_SEARCH_PARAMETERS", "Missing required search parameters", 400)

    if not is_iso_date(date):
        return error("INVALID_DATE", "date must be in YYYY-MM-DD format", 400)

    if same_place(origin, destination):
        return error("SAME_ORIGIN_DESTINATION", "Origin and destination must be different", 400)

    job_id = orchestrator.create_search_job(origin, destination, date, pref, language=lang, mode=mode)
    return success({"job_id": job_id}, status_code=202, job_id=job_id, job_status="processing")


@travel_bp.route('/trains-for-flight', methods=['POST'])
def trains_for_flight():
    """
    Manual mode: resolve the onward train(s) + cab transfer for the flight the
    user just chose, so trains always connect to that specific flight.
    Expects JSON: {'job_id': '...', 'flight': {...}}  (flight may be null for the
    no-flight / train-only case).
    """
    data = request.get_json(silent=True) or {}
    job_id = data.get('job_id')
    flight = data.get('flight')
    if not job_id:
        return error("MISSING_JOB_ID", "job_id is required", 400)

    job = orchestrator.get_job_status(job_id)
    if not job:
        return error("JOB_NOT_FOUND", "Job not found", 404)
    if not job.get('ctx'):
        return error("JOB_NOT_MANUAL", "This job has no manual context to resolve trains from", 400)

    result = orchestrator.resolve_trains_for_flight(job_id, flight)
    if result is None:
        return error("TRAINS_UNAVAILABLE", "Could not resolve onward trains", 500)
    return success(result)

@travel_bp.route('/status/<job_id>', methods=['GET'])
def get_trip_status(job_id):
    """
    Retrieves the current status and results of a travel search job.
    :param job_id: Unique identifier returned by the /search endpoint.
    :return: Job results if completed, else status ('processing'|'failed').
    """
    job = orchestrator.get_job_status(job_id)
    if not job:
        return error("JOB_NOT_FOUND", "Job not found", 404)
    return success(job, status_code=200, job_status=job.get("status"))

@travel_bp.route('/select', methods=['POST'])
def select_trip_results():
    """
    Commits specific travel segments from a search job to the user's active session.
    Expects JSON: {'job_id': '...', 'selection_type': 'quickpick'|'manual', 'selection_data': {...}}
    Selecting a new trip drops any prior assistant conversation so the chat stays
    scoped to this trip. Transfer/hub fields are carried into the session trip so a
    saved/opened trip can re-render its journey (cab leg, etc.) without the job.
    :return: Confirmation of session commit.
    """
    data = request.get_json(silent=True) or {}
    job_id = data.get('job_id')
    sel_type = data.get('selection_type', 'manual')

    job = orchestrator.get_job_status(job_id)
    if not job or job.get('status') != 'completed':
        return error("JOB_NOT_COMPLETED", "Job not completed or not found", 400)

    results = job.get('results')
    if not isinstance(results, dict) or not results.get('source') or not results.get('destination'):
        return error("JOB_RESULTS_MISSING", "Job completed but results are unavailable", 500)

    session.pop('chat_history', None)

    base_trip = {
        "source": results['source'],
        "destination": results['destination'],
        "currency": results.get('currency', 'INR'),
        "transfer": results.get('transfer'),
        "rail_hub": results.get('rail_hub'),
        "hub_city": results.get('hub_city'),
        "multimodal": results.get('multimodal', False),
    }

    if sel_type == 'quickpick':
        pref = normalize_preference(data.get('preferences', 'Comfort'))
        bundle = qp_service.select_best_bundle(results, preference=pref)
        session['trip'] = {
            **base_trip,
            "segments": {
                "flight": bundle['flight'],
                "train": bundle['train'],
                "hotel": bundle['hotel'],
            },
            "transfer_status": bundle.get('transfer_status'),
            "itinerary": bundle['itinerary'],
        }
    else:
        sel_data = data.get('selection_data') or {}
        session['trip'] = {
            **base_trip,
            "segments": {
                "flight": sel_data.get('flight'),
                "train": sel_data.get('train'),
                "hotel": sel_data.get('hotel'),
            },
            "itinerary": results.get('itinerary', []),
        }

    return success({"trip": session['trip']}, "Trip selections committed to session", 200)

@travel_bp.route('/chat', methods=['POST'])
def travel_chatbot():
    """
    Provides an interactive, context-aware AI travel consultant.
    Expects JSON: {'message': '...', 'language': 'Hindi'}
    The reply language is whitelisted and both the trip context and history are
    derived from the server-side session only (never the client), so neither can
    be spoofed or used for prompt injection.
    :return: AI response text (in the requested language).
    """
    data = request.get_json(silent=True) or {}
    user_msg = data.get('message')

    if not isinstance(user_msg, str) or not user_msg.strip():
        return error("MISSING_MESSAGE", "A non-empty message is required", 400)
    if len(user_msg) > MAX_CHAT_MESSAGE_CHARS:
        return error("MESSAGE_TOO_LONG", f"Message exceeds {MAX_CHAT_MESSAGE_CHARS} characters", 400)

    language = data.get('language') if data.get('language') in SUPPORTED_CHAT_LANGUAGES else "English"

    context = AIService.build_trip_context(session.get('trip'))
    history = session.get('chat_history', [])

    response = ai_service.get_chatbot_response(user_msg, trip_context=context, history=history, language=language)

    history = history + [
        {"role": "user", "content": user_msg},
        {"role": "assistant", "content": response},
    ]
    session['chat_history'] = history[-(MAX_CHAT_TURNS * 2):]

    return success({"response": response}, status_code=200)


@travel_bp.route('/chat/reset', methods=['POST'])
def travel_chat_reset():
    """Clears the server-side conversation for the current trip (Clear chat)."""
    session.pop('chat_history', None)
    return success({}, "Chat history cleared", 200)
