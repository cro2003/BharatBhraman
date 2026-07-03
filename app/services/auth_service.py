import bcrypt
import datetime
from ..database.connection import users

class AuthService:
    """
    User authentication: bcrypt password hashing and credential verification.

    Authentication is session-based — on successful login the route stores the
    user id in the server-side (MongoDB-backed) Flask session. No token is issued
    to the client.
    """

    def register_user(self, email: str, password: str, name: str):
        """
        Creates a new user record with a per-user salted bcrypt hash.

        :param email: Unique user email address. Ex: 'guest@example.com'
        :param password: Raw password string to be hashed.
        :param name: Full name of the user. Ex: 'John Doe'
        :return: Success message and 201 status, or error message and 400 status.
        """
        if users.find_one({"email": email}):
            return {"error": "User already exists"}, 400

        hashed_pw = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt())

        user_doc = {
            "email": email,
            "password": hashed_pw,
            "name": name,
            "created_at": datetime.datetime.now(datetime.timezone.utc)
        }
        users.insert_one(user_doc)
        return {"message": "User registered successfully"}, 201

    def login_user(self, email: str, password: str):
        """
        Verifies credentials and returns the user identity for the caller to
        establish a session.

        :param email: Registered user email. Ex: 'guest@example.com'
        :param password: Raw password for verification.
        :return: User identity dict and 200 status, or error and 401 status.
        """
        user = users.find_one({"email": email})
        if not user:
            return {"error": "Invalid credentials"}, 401

        if bcrypt.checkpw(password.encode('utf-8'), user['password']):
            return {
                "message": "Login successful",
                "user_id": str(user['_id']),
                "user": {"name": user.get('name'), "email": user.get('email')}
            }, 200

        return {"error": "Invalid credentials"}, 401
