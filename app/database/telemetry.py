import time
from typing import Dict
from .connection import metrics

def log_api_request(project_name: str, endpoint: str, method: str, status_code: int, response_time_ms: int):
    """
    Records low-level technical performance metrics for an API request.
    Maintains a rolling buffer of the last 100 requests.

    :param project_name: Name of the application. Ex: 'BharatBhraman'
    :param endpoint: The API endpoint being called. Ex: 'travel.search'
    :param method: HTTP method (GET, POST, etc.).
    :param status_code: HTTP response status.
    :param response_time_ms: Time taken to process the request in milliseconds.
    """
    metrics.update_one(
        {"project_name": project_name, "type": "technical"},
        {
            "$inc": {
                "total_requests": 1,
                f"endpoints.{endpoint.replace('.', '_')}.count": 1
            },
            "$push": {
                "recent_requests": {
                    "$each": [{
                        "endpoint": endpoint,
                        "method": method,
                        "status_code": status_code,
                        "response_time_ms": response_time_ms,
                        "timestamp": time.time()
                    }],
                    "$slice": -100
                }
            }
        },
        upsert=True
    )

def log_business_metric(project_name: str, trip_data: Dict):
    """
    Records high-level business analytics such as total trips planned and transport preferences.

    :param project_name: Name of the application.
    :param trip_data: Dictionary containing 'transport_type' (Ex: 'flight'), 'duration_days', 'source', and 'destination'.
    """
    transport_type = trip_data.get('transport_type', 'unknown')
    duration = trip_data.get('duration_days', 0)
    
    metrics.update_one(
        {"project_name": project_name, "type": "business"},
        {
            "$inc": {
                "total_trips_planned": 1,
                f"transport_preference.{transport_type}": 1,
                "total_days_planned": duration
            },
            "$set": {
                "last_trip_at": time.time(),
                "last_trip_route": f"{trip_data.get('source')} -> {trip_data.get('destination')}"
            }
        },
        upsert=True
    )

def get_aggregated_stats(project_name: str) -> Dict:
    """
    Aggregates and returns all telemetry data for the portfolio dashboard.

    :param project_name: Name of the application.
    :return: A dictionary containing 'technical' and 'business' metric blocks.
    """
    tech = metrics.find_one({"project_name": project_name, "type": "technical"}) or {}
    biz = metrics.find_one({"project_name": project_name, "type": "business"}) or {}
    
    return {
        "technical": {
            "total_requests": tech.get("total_requests", 0),
            "recent_activity": tech.get("recent_requests", [])
        },
        "business": {
            "trips_planned": biz.get("total_trips_planned", 0),
            "days_planned": biz.get("total_days_planned", 0),
            "transport_split": biz.get("transport_preference", {}),
            "last_planned": biz.get("last_trip_route", "N/A")
        }
    }
