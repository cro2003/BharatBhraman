import datetime
from typing import Dict, List, Optional
from ..database.connection import users, trips, db

class UserService:
    """
    Manages user-specific data and persistence.
    Handles saving travel itineraries and retrieving dashboard information.
    """
    def __init__(self):
        """Initializes the user service with database collections."""
        self.users = users
        self.trips = trips
        self.bookings = db['guide_bookings']

    def save_trip(self, user_id: str, trip_data: Dict, chat_history: List = None) -> str:
        """Persists a travel itinerary (and any chat about it) to the account."""
        trip_doc = {
            "user_id": user_id,
            "itinerary": trip_data,
            "chat_history": chat_history or [],
            "saved_at": datetime.datetime.now(datetime.timezone.utc)
        }
        result = self.trips.insert_one(trip_doc)
        return str(result.inserted_id)

    def get_trip(self, user_id: str, trip_id: str) -> Optional[Dict]:
        """Returns a saved trip's itinerary + chat history for the user, or None.

        Shape: {"itinerary": {...}, "chat_history": [...], "trip_id": "..."}.
        """
        from bson.objectid import ObjectId
        try:
            doc = self.trips.find_one({"_id": ObjectId(trip_id), "user_id": user_id})
        except Exception:
            return None
        if not doc:
            return None
        return {
            "itinerary": doc.get("itinerary"),
            "chat_history": doc.get("chat_history", []),
            "trip_id": str(doc["_id"]),
        }

    def delete_trip(self, user_id: str, trip_id: str) -> bool:
        """Removes a saved trip owned by the user. Returns True if one was deleted."""
        from bson.objectid import ObjectId
        try:
            result = self.trips.delete_one({"_id": ObjectId(trip_id), "user_id": user_id})
        except Exception:
            return False
        return result.deleted_count > 0

    def update_trip_chat(self, user_id: str, trip_id: str, chat_history: List) -> bool:
        """Persists ongoing chat for a saved trip. Returns True if it was updated."""
        from bson.objectid import ObjectId
        try:
            result = self.trips.update_one(
                {"_id": ObjectId(trip_id), "user_id": user_id},
                {"$set": {"chat_history": chat_history or []}},
            )
        except Exception:
            return False
        return result.matched_count > 0

    def get_dashboard_data(self, user_id: str) -> Dict:
        """Aggregates all user-specific data including saved trips and guide bookings."""
        saved_trips = list(self.trips.find({"user_id": user_id}).sort("saved_at", -1))
        guide_bookings = list(self.bookings.find({"user_id": user_id}).sort("timestamp", -1))
        
        for t in saved_trips: t['_id'] = str(t['_id'])
        for b in guide_bookings: b['_id'] = str(b['_id'])
        
        return {
            "trips": saved_trips,
            "bookings": guide_bookings
        }
