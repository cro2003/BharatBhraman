from flask import Blueprint
from ..database.telemetry import get_aggregated_stats
from ..utils.api_response import success

telemetry_bp = Blueprint('telemetry', __name__)

@telemetry_bp.route('/stats', methods=['GET'])
def portfolio_stats():
    """
    Endpoint for retrieving aggregated system and business metrics for the portfolio dashboard.
    Returns: JSON containing 'technical' (performance) and 'business' (usage) stats.
    """
    stats = get_aggregated_stats(project_name="BharatBhraman")
    return success(stats, status_code=200)
