from flask import Blueprint, render_template, request, session
from ..database.connection import languages

core_bp = Blueprint('core', __name__)

@core_bp.route('/', methods=['GET', 'POST'])
def index():
    """Serves the API-driven landing page shell."""
    selected_lang = request.form.get('selectedLang', session.get('lang', 'en'))
    session['lang'] = selected_lang
    return render_template('index.html')

@core_bp.route('/results', methods=['GET'])
def results():
    """Serves the API-driven trip results shell."""
    return render_template('results.html')

@core_bp.route('/flight-results', methods=['GET'])
def flight_results():
    """Redirects legacy flight-results URLs to the unified results page."""
    return render_template('results.html')

@core_bp.route('/train-results', methods=['GET'])
def train_results():
    """Redirects legacy train-results URLs to the unified results page."""
    return render_template('results.html')

@core_bp.route('/hotel-results', methods=['GET'])
def hotel_results():
    """Redirects legacy hotel-results URLs to the unified results page."""
    return render_template('results.html')

@core_bp.route('/itinerary-results', methods=['GET'])
def itinerary_results():
    """Redirects legacy itinerary URLs to the unified results page."""
    return render_template('results.html')

@core_bp.route('/chat', methods=['GET'])
def chat():
    """Serves the static AI travel consultant shell."""
    return render_template('chatBot.html')

@core_bp.route('/guides', methods=['GET'])
def guides():
    """Serves the static guide discovery shell."""
    return render_template('guideIndex.html')

@core_bp.route('/auth', methods=['GET'])
def auth():
    """Serves the authentication page shell."""
    return render_template('auth.html')

@core_bp.route('/dashboard', methods=['GET'])
def dashboard():
    """Serves the user dashboard shell."""
    return render_template('dashboard.html')
