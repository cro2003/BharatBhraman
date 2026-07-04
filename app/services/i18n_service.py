import hashlib
import logging
from typing import Dict

from ..database.connection import db

logger = logging.getLogger(__name__)


class I18nService:
    """
    Serves UI translations for a language, generated on demand by the LLM and
    cached in MongoDB. The cache key includes a hash of the English key-set, so
    adding/removing UI strings naturally produces a fresh cache entry rather than
    serving a stale, partial translation.
    """

    def __init__(self, ai_service):
        self.ai = ai_service
        self.cache = db["ui_translations"]

    @staticmethod
    def _cache_id(language: str, strings: Dict[str, str]) -> str:
        digest = hashlib.sha1("|".join(sorted(strings.keys())).encode("utf-8")).hexdigest()[:16]
        return f"{language.lower()}:{digest}"

    def get_translations(self, language: str, strings: Dict[str, str]) -> Dict[str, str]:
        """Returns {key: translated} for ``language`` (English passes through)."""
        if not strings:
            return {}
        if not language or language.strip().lower() == "english":
            return strings

        cache_id = self._cache_id(language, strings)
        cached = self.cache.find_one({"_id": cache_id})
        if cached and cached.get("translations"):
            return cached["translations"]

        translated = self.ai.translate_ui_strings(language, strings)
        if translated:
            try:
                self.cache.update_one(
                    {"_id": cache_id},
                    {"$set": {"language": language, "translations": translated}},
                    upsert=True,
                )
            except Exception as exc:
                logger.warning("Could not cache UI translations for %s: %s", language, exc)
            return translated
        return strings
