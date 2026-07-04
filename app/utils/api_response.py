from flask import jsonify


def success(data=None, message=None, status_code=200, **extra):
    payload = {"status": "success"}
    if message is not None:
        payload["message"] = message
    if data is not None:
        payload["data"] = data
    payload.update(extra)
    return jsonify(payload), status_code


def error(code, message, status_code=400, **extra):
    payload = {
        "status": "error",
        "code": code,
        "message": message,
    }
    payload.update(extra)
    return jsonify(payload), status_code
