import datetime
import logging
import os
from typing import List, Dict, Optional
from bson.objectid import ObjectId
from bson.errors import InvalidId
from ..database.connection import guides, db

logger = logging.getLogger(__name__)


class GuideService:
    """
    Manages the travel guide marketplace logic.
    Handles guide registration, discovery, booking, and reviews within a specialized ecosystem.
    """
    def __init__(self):
        """Initializes the guide service with database collections."""
        self.guides = guides
        self.bookings = db['guide_bookings']
        try:
            self.platform_fee = float(os.environ.get('PLATFORM_FEE', 0.25))
        except (TypeError, ValueError):
            self.platform_fee = 0.25

    @staticmethod
    def _to_object_id(guide_id: str) -> Optional[ObjectId]:
        """Safely converts a string id to an ObjectId, or None if malformed."""
        try:
            return ObjectId(guide_id)
        except (InvalidId, TypeError):
            return None

    def register_guide(self, guide_data: Dict) -> str:
        """
        Registers a new travel guide. Rating starts empty (no fake default) and
        accrues only from real reviews; guides are not auto-verified.

        :param guide_data: Dictionary with guide info (name, age, cities, etc.)
        :return: The generated string ID of the new guide.
        """
        guide_data.update({
            "rating": None,
            "review_count": 0,
            "reviews": [],
            "created_at": datetime.datetime.now(datetime.timezone.utc)
        })
        result = self.guides.insert_one(guide_data)
        return str(result.inserted_id)

    def search_guides(self, city: str, language: str = None) -> List[Dict]:
        """
        Finds guides available in a specific city, optionally filtered by language.

        Contact PII (email, phone) is projected out — the public search must not
        expose it; it is only revealed to the traveller after a confirmed booking.

        :param city: The target city. Ex: 'Bhopal'
        :param language: Optional preferred language. Ex: 'Hindi'
        :return: A list of guide dictionaries without contact PII.
        """
        query = {"cities_covered": city}
        if language:
            query["languages"] = language

        cursor = self.guides.find(query, {"email": 0, "phone": 0})
        results = []
        for g in cursor:
            g['_id'] = str(g['_id'])
            results.append(g)
        return results

    def get_guide(self, guide_id: str) -> Optional[Dict]:
        """Fetches a single guide by id (with _id stringified), or None if not found."""
        oid = self._to_object_id(guide_id)
        if not oid:
            return None
        guide = self.guides.find_one({"_id": oid})
        if guide:
            guide['_id'] = str(guide['_id'])
        return guide

    def quote_booking(self, hourly_rate: float, hours: float) -> Dict:
        """Computes the price breakdown for a booking (base + platform fee)."""
        base_price = round(float(hourly_rate) * float(hours), 2)
        platform_fee = round(base_price * self.platform_fee, 2)
        total_price = round(base_price + platform_fee, 2)
        return {
            "base_price": base_price,
            "platform_fee": platform_fee,
            "platform_fee_rate": self.platform_fee,
            "total_price": total_price,
        }

    def book_guide(self, user_id: str, guide_id: str, date: str, hours: float = 1) -> Optional[Dict]:
        """
        Creates a guide booking with a full price breakdown, after validating the
        guide exists.

        :param user_id: Authenticated user ID.
        :param guide_id: Target guide ID.
        :param date: Booking date. Format: 'YYYY-MM-DD'
        :param hours: Number of hours booked. Default: 1
        :return: The created booking document (with id), or None if the guide is unknown.
        """
        oid = self._to_object_id(guide_id)
        if not oid:
            return None
        guide = self.guides.find_one({"_id": oid})
        if not guide:
            return None

        quote = self.quote_booking(guide.get('hourly_rate', 0) or 0, hours)
        booking = {
            "user_id": user_id,
            "guide_id": guide_id,
            "guide_name": guide.get('name'),
            "date": date,
            "hours": float(hours),
            **quote,
            "currency": "INR",
            "status": "pending",
            "timestamp": datetime.datetime.now(datetime.timezone.utc)
        }
        result = self.bookings.insert_one(booking)
        booking["_id"] = str(result.inserted_id)
        return booking

    def add_review(self, guide_id: str, user_name: str, rating: float, comment: str) -> bool:
        """
        Adds a user review and recomputes the guide's aggregate rating and count.

        :param guide_id: ID of the guide being reviewed.
        :param user_name: Name of the reviewer.
        :param rating: Numeric rating (1.0 to 5.0).
        :param comment: Textual review content.
        :return: True if the review was recorded, False if the guide is unknown.
        """
        oid = self._to_object_id(guide_id)
        if not oid:
            return False
        guide = self.guides.find_one({"_id": oid})
        if not guide:
            return False

        review = {
            "user": user_name,
            "rating": float(rating),
            "comment": comment,
            "date": datetime.datetime.now(datetime.timezone.utc)
        }
        self.guides.update_one({"_id": oid}, {"$push": {"reviews": review}})

        all_ratings = [r['rating'] for r in guide.get('reviews', [])] + [float(rating)]
        new_avg = round(sum(all_ratings) / len(all_ratings), 1)
        self.guides.update_one(
            {"_id": oid},
            {"$set": {"rating": new_avg, "review_count": len(all_ratings)}}
        )
        return True
