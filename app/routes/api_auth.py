from flask import Blueprint, request, session
from ..services.auth_service import AuthService
from ..utils.api_response import success, error
from ..utils.validation import is_valid_email

MIN_PASSWORD_LENGTH = 8

auth_bp = Blueprint('auth_api', __name__)
auth_service = AuthService()

@auth_bp.route('/register', methods=['POST'])
def register():
    """
    Endpoint for user registration.
    Expects JSON: {'email': '...', 'password': '...', 'name': '...'}
    """
    data = request.get_json(silent=True) or {}
    email = data.get('email')
    password = data.get('password')
    name = data.get('name')

    if not all(isinstance(v, str) and v for v in (email, password, name)):
        return error("MISSING_REQUIRED_FIELDS", "Missing required fields", 400)

    if not is_valid_email(email):
        return error("INVALID_EMAIL", "A valid email address is required", 400)

    if not isinstance(password, str) or len(password) < MIN_PASSWORD_LENGTH:
        return error("WEAK_PASSWORD", f"Password must be at least {MIN_PASSWORD_LENGTH} characters", 400)

    result, status_code = auth_service.register_user(email, password, name)
    if status_code >= 400:
        return error("REGISTER_FAILED", result.get("error") or result.get("message") or "Registration failed", status_code)
    return success(result, status_code=status_code)

@auth_bp.route('/login', methods=['POST'])
def login():
    """
    Endpoint for secure user authentication and session management.
    Expects JSON: {'email': '...', 'password': '...'}
    """
    data = request.get_json(silent=True) or {}
    email = data.get('email')
    password = data.get('password')

    if not (isinstance(email, str) and email) or not (isinstance(password, str) and password):
        return error("MISSING_CREDENTIALS", "Missing email or password", 400)

    result, status_code = auth_service.login_user(email, password)
    
    if status_code == 200:
        session['user_id'] = result.get('user_id')
        session['user_name'] = result['user']['name']
        session['is_logged_in'] = True

    if status_code >= 400:
        return error("LOGIN_FAILED", result.get("error") or result.get("message") or "Login failed", status_code)
    return success(result, status_code=status_code)

@auth_bp.route('/logout', methods=['POST'])
def logout():
    """
    Endpoint to terminate the current user session.
    Clears all session data.
    """
    session.clear()
    return success(message="Logged out successfully", status_code=200)


@auth_bp.route('/me', methods=['GET'])
def me():
    """
    Returns the current session user, letting the frontend render auth-aware UI.
    """
    if not session.get('is_logged_in'):
        return error("UNAUTHENTICATED", "Not logged in", 401)
    return success({
        "user_id": session.get('user_id'),
        "name": session.get('user_name'),
    }, status_code=200)
