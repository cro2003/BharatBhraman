from flask import Blueprint, request
from ..services.ai_service import AIService
from ..services.i18n_service import I18nService
from ..utils.api_response import success, error

i18n_bp = Blueprint('i18n_api', __name__)
_i18n_service = I18nService(AIService())

MAX_STRINGS = 400


@i18n_bp.route('/translate', methods=['POST'])
def translate():
    """
    Translates a UI string set into a language (cached server-side).
    Expects JSON: {'language': 'Hindi', 'strings': {'key': 'English text', ...}}
    Returns: {'data': {'key': 'translated text', ...}}
    """
    data = request.get_json(silent=True) or {}
    language = data.get('language')
    strings = data.get('strings')

    if not language or not isinstance(strings, dict):
        return error("INVALID_I18N_REQUEST", "language and strings are required", 400)
    if len(strings) > MAX_STRINGS:
        return error("TOO_MANY_STRINGS", f"At most {MAX_STRINGS} strings per request", 400)

    translations = _i18n_service.get_translations(language, strings)
    return success(translations, status_code=200)
