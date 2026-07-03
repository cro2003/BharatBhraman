"""Itinerary JSON parsing must survive common LLM formatting defects."""
from app.services.ai_service import AIService


def test_clean_json():
    raw = '{"places": [{"placeName": "A"}, {"placeName": "B"}]}'
    assert len(AIService._parse_places(raw)) == 2


def test_markdown_fenced_json():
    raw = '```json\n{"places": [{"placeName": "A"}]}\n```'
    assert AIService._parse_places(raw) == [{"placeName": "A"}]


def test_trailing_comma_is_repaired():
    raw = '{"places": [{"placeName": "A"},]}'
    assert AIService._parse_places(raw) == [{"placeName": "A"}]


def test_bare_list_is_accepted():
    raw = '[{"placeName": "A"}]'
    assert AIService._parse_places(raw) == [{"placeName": "A"}]


def test_garbage_returns_empty_not_crash():
    assert AIService._parse_places("not json at all") == []
    assert AIService._parse_places("") == []


def test_non_dict_entries_are_filtered():
    raw = '{"places": [{"placeName": "A"}, "junk", 5]}'
    assert AIService._parse_places(raw) == [{"placeName": "A"}]


# --- chat content normalization (Gemini may return a list of parts, not a string) ---

def test_content_plain_string():
    assert AIService._content_to_text("hello") == "hello"


def test_content_list_of_parts():
    content = [{"type": "text", "text": "Hello "}, {"type": "text", "text": "world", "extras": {"x": 1}}]
    assert AIService._content_to_text(content) == "Hello world"


def test_content_mixed_list():
    assert AIService._content_to_text(["a", {"text": "b"}, {"no_text": 1}]) == "ab"


def test_content_empty():
    assert AIService._content_to_text(None) == ""
    assert AIService._content_to_text([]) == ""


def test_itinerary_from_gemini_list_content():
    # Regression: gemini-flash-lite returns content as a list of parts wrapping
    # the JSON. Flatten -> parse must recover the full itinerary (was yielding 0).
    gemini_content = [{
        "type": "text",
        "text": '{"places": [{"placeName": "Ramghat"}, {"placeName": "Kamadgiri"}]}',
        "extras": {"signature": "abc"},
    }]
    text = AIService._content_to_text(gemini_content)
    places = AIService._parse_places(text)
    assert [p["placeName"] for p in places] == ["Ramghat", "Kamadgiri"]
