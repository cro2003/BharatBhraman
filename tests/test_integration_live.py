"""
Live end-to-end integration tests.

These hit the REAL external APIs (Geoapify, IRCTC Air, RailYatri/ConfirmTkt,
Gemini, exchange-rate) and the REAL MongoDB, creating actual search jobs, users,
trips, guides, bookings and reviews — then cleaning them up. They are slow and
network-dependent, so they are opt-in:

    RUN_INTEGRATION=1 python -m pytest tests/test_integration_live.py -v

Run a single route/flow with -k, e.g.  RUN_INTEGRATION=1 pytest -k goa
"""
import datetime
import os
import time
import uuid

import pytest

RUN = os.environ.get("RUN_INTEGRATION") == "1"
pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(not RUN, reason="set RUN_INTEGRATION=1 to run live integration tests"),
]

_DEFAULT_SEARCH_DATE = (datetime.date.today() + datetime.timedelta(days=21)).isoformat()
SEARCH_DATE = os.environ.get("INTEGRATION_DATE", _DEFAULT_SEARCH_DATE)
RAILYATRI_DATE = "-".join(reversed(SEARCH_DATE.split("-")))  # YYYY-MM-DD -> DD-MM-YYYY


# --------------------------------------------------------------------------- fixtures

@pytest.fixture(scope="module")
def app_client():
    from app import create_app
    app = create_app()
    app.testing = True
    return app.test_client()


@pytest.fixture
def tracker():
    """Tracks created DB docs and removes them after the test."""
    from app.database.connection import users, guides, trips, db

    created = {"user_emails": [], "guide_ids": [], "job_ids": [], "user_ids": []}
    yield created

    from bson.objectid import ObjectId
    bookings = db["guide_bookings"]
    jobs = db["trip_jobs"]
    for email in created["user_emails"]:
        users.delete_many({"email": email})
    for uid in created["user_ids"]:
        trips.delete_many({"user_id": uid})
        bookings.delete_many({"user_id": uid})
    for gid in created["guide_ids"]:
        try:
            guides.delete_one({"_id": ObjectId(gid)})
        except Exception:
            pass
        bookings.delete_many({"guide_id": gid})
    for jid in created["job_ids"]:
        jobs.delete_many({"job_id": jid})


# --------------------------------------------------------------------------- helpers

def run_search(client, payload, tracker=None, timeout=150):
    resp = client.post("/api/travel/search", json=payload)
    assert resp.status_code == 202, resp.get_json()
    job_id = resp.get_json()["data"]["job_id"]
    if tracker is not None:
        tracker["job_ids"].append(job_id)

    start = time.time()
    while time.time() - start < timeout:
        body = client.get(f"/api/travel/status/{job_id}").get_json()
        status = body.get("job_status") or (body.get("data") or {}).get("status")
        if status == "completed":
            return job_id, body["data"]["results"]
        if status == "failed":
            pytest.fail(f"search job failed: {(body.get('data') or {}).get('error')}")
        time.sleep(2)
    pytest.fail("search timed out")


def register_and_login(client, tracker):
    email = f"itest_{uuid.uuid4().hex[:10]}@bharatbhraman.test"
    password = "TestPass123!"
    name = "Integration Tester"
    tracker["user_emails"].append(email)

    r = client.post("/api/auth/register", json={"email": email, "password": password, "name": name})
    assert r.status_code in (200, 201), r.get_json()

    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.get_json()
    uid = r.get_json()["data"]["user_id"]
    tracker["user_ids"].append(uid)
    return email, password, uid


# --------------------------------------------------------------------------- trip search

@pytest.mark.parametrize("origin,destination,expect", [
    ("Mumbai", "Goa", "domestic"),       # domestic, multi-station city (Madgaon)
    ("Delhi", "Vidisha", "hub"),         # hub fallback (Bhopal) + onward train
    ("Delhi", "Jaipur", "domestic"),     # straightforward domestic
])
def test_trip_search_combinations(app_client, tracker, origin, destination, expect):
    _, results = run_search(
        app_client,
        {"origin": origin, "destination": destination, "date": SEARCH_DATE,
         "preferences": "Comfort", "language": "English"},
        tracker,
    )

    # Locations resolved
    assert results["source"].get("city")
    assert results["destination"].get("city")

    # Currency code/rate consistency: domestic Indian trips must be INR
    assert results.get("currency") == "INR"

    flights = results.get("flights") or []
    hub = results.get("hub_flight_fallback") or []
    trains = results.get("trains") or []

    if expect == "hub":
        # Hub destinations should fly to a nearby hub and offer onward trains.
        assert hub, "expected hub_flight_fallback for a destination without its own airport"
        assert results.get("hub_city")
        assert trains, "hub route should provide onward trains"
    else:
        # Domestic destination with its own airport: direct flights and/or trains.
        assert flights or trains, "expected at least flights or trains"
        assert trains, "domestic Indian route should return trains"

    # AI itinerary present with validated images
    itinerary = results.get("itinerary") or []
    assert itinerary, "expected AI itinerary content"
    assert all(p.get("placeName") for p in itinerary)


def test_quickpick_bundles_for_both_preferences(app_client, tracker):
    from app.services.quick_pick_service import QuickPickService
    qp = QuickPickService()
    _, results = run_search(
        app_client,
        {"origin": "Mumbai", "destination": "Jaipur", "date": SEARCH_DATE, "preferences": "Comfort"},
        tracker,
    )
    for pref in ("Comfort", "Budget"):
        bundle = qp.select_best_bundle(results, preference=pref)
        assert set(["flight", "train", "hotel", "itinerary"]).issubset(bundle.keys())
        # A domestic route should yield at least one transport segment.
        assert bundle["flight"] or bundle["train"]


def test_international_destination_is_rejected(app_client, tracker):
    # BharatBhraman plans trips within India only. A foreign destination must
    # fail the job gracefully with a clear machine code, not return a partial trip.
    resp = app_client.post("/api/travel/search", json={
        "origin": "Mumbai", "destination": "Dubai", "date": SEARCH_DATE, "preferences": "Comfort"})
    assert resp.status_code == 202, resp.get_json()
    job_id = resp.get_json()["data"]["job_id"]
    tracker["job_ids"].append(job_id)

    start = time.time()
    while time.time() - start < 60:
        body = app_client.get(f"/api/travel/status/{job_id}").get_json()
        data = body.get("data") or {}
        status = body.get("job_status") or data.get("status")
        if status == "failed":
            assert data.get("error_code") == "DESTINATION_OUTSIDE_INDIA"
            assert "India" in (data.get("error") or "")
            return
        if status == "completed":
            pytest.fail("foreign destination should have been rejected, not completed")
        time.sleep(2)
    pytest.fail("rejection did not resolve in time")


def test_international_to_remote_india_routes_via_gateway(app_client, tracker):
    # London -> Maihar: should fly to a major Indian gateway (e.g. Delhi) and
    # continue by train, rather than returning no options at all.
    _, results = run_search(
        app_client,
        {"origin": "London", "destination": "Maihar", "date": SEARCH_DATE, "preferences": "Comfort"},
        tracker,
    )
    hub = results.get("hub_flight_fallback") or []
    trains = results.get("trains") or []
    assert results.get("currency") == "GBP"
    # A usable journey exists: inbound flights to the gateway and/or onward trains.
    assert hub or trains, "international -> remote India should yield gateway flights or onward trains"
    if hub:
        assert results.get("hub_city")


# --------------------------------------------------------------------------- lookups

def test_location_lookup(app_client):
    r = app_client.get("/api/travel/lookup/location?q=Mumb")
    assert r.status_code == 200
    assert isinstance(r.get_json()["data"], list)
    assert len(r.get_json()["data"]) > 0


def test_train_station_lookup_resolves_city(app_client):
    r = app_client.get("/api/travel/lookup/train-station?q=Delhi")
    assert r.status_code == 200
    data = r.get_json()["data"]
    assert data and data[0]["station_code"] == "NDLS"


# --------------------------------------------------------------------------- station resolution (the bug we fixed)

@pytest.mark.parametrize("city,code", [
    ("Mumbai", "MMCT"),
    ("Delhi", "NDLS"),
    ("Jaipur", "JP"),
    ("Goa", "MAO"),            # data-quirk override -> Madgaon
    ("Vidisha", "BHS"),
    ("Chitrakoot", "CKTD"),    # prefix-fallback handles the Chitrakut spelling
    ("Tirupati", "TPTY"),
    ("Pondicherry", "PDY"),    # RailYatri maps to Puducherry
    ("Mysuru", "MYS"),         # renamed city -> 3-char prefix finds Mysore
    ("Dehradun", "DDN"),
    ("Dehra Dun", "DDN"),      # IRCTC airport cityName (spaced) -> space-collapse
    ("Pathankot", "PTKC"),     # Kangra railhead
])
def test_station_resolution(city, code):
    from app.services.train_service import TrainService
    station = TrainService().get_station_data(city)
    assert station and station["station_code"] == code


def test_code_less_station_node_is_skipped():
    # RailYatri returned a junk code-less is_city node for the spaced "Dehra Dun";
    # it must resolve to the real DDN, never to None or a code-less node.
    from app.services.train_service import TrainService
    station = TrainService().get_station_data("Dehra Dun")
    assert station and station["station_code"] and station["station_name"]


# ----------------------------------------------- railhead / hub routing regressions

def _orchestrate(origin, destination, preference="Budget"):
    """Runs one search synchronously (no background thread) and returns results."""
    from app.services.travel_orchestrator import TravelOrchestrator
    from app.database.connection import db
    orch = TravelOrchestrator()
    jid = f"regr-{uuid.uuid4().hex[:10]}"
    db["trip_jobs"].insert_one({"job_id": jid, "status": "processing"})
    try:
        orch._run_synchronized_search(jid, origin, destination, SEARCH_DATE, preference, "English")
        doc = db["trip_jobs"].find_one({"job_id": jid})
        return doc.get("results") or {}, doc.get("status")
    finally:
        db["trip_jobs"].delete_one({"job_id": jid})


# Each row is one fixed routing bug. Expectations are declared as data so a
# single test interprets them — add a regression by appending a row, not a
# function. Keys (all optional except origin/destination/preference):
#   rail_hub_contains   substring the rail_hub must contain (and rail_hub set)
#   no_rail_hub         rail_hub must be falsy (destination has its own station)
#   no_hub_city         hub_city must be falsy (destination has its own airport)
#   has_hub_flight      hub_flight_fallback must be non-empty
#   no_trains           trains must be empty
#   trains_dest         a train's destination must contain this substring
#   bundle_flight       budget bundle's flight present (True) / absent (False)
#   bundle_train        budget bundle's train present (True) / absent (False)
ROUTING_REGRESSIONS = [
    {
        "id": "gangotri-budget-railheads-dehradun",
        "origin": "Delhi", "destination": "Gangotri", "preference": "Budget",
        "rail_hub_contains": "dehra", "trains_dest": "dehra",
    },
    {
        "id": "kangra-budget-railheads-pathankot",
        "origin": "Bhopal", "destination": "Kangra HP", "preference": "Budget",
        "rail_hub_contains": "pathankot", "trains_dest": "pathankot",
    },
    {
        "id": "badrinath-budget-flight-not-wrong-railhead",
        "origin": "Bhopal", "destination": "Badrinath", "preference": "Budget",
        "no_trains": True, "has_hub_flight": True,
        "bundle_flight": True, "bundle_train": False,
    },
    {
        "id": "jammu-not-promoted-to-amritsar-hub",
        "origin": "Bhopal", "destination": "Jammu", "preference": "Budget",
        "no_hub_city": True, "trains_dest": "jammu",
    },
    {
        "id": "mysuru-direct-train-not-coimbatore",
        "origin": "Bengaluru", "destination": "Mysuru", "preference": "Budget",
        "no_rail_hub": True, "trains_dest": "mysore",
    },
    {
        # Pakyong (39km, no flights) must not shadow Bagdogra (40km, has flights).
        "id": "darjeeling-flies-via-bagdogra",
        "origin": "Kolkata", "destination": "Darjeeling", "preference": "Comfort",
        "bundle_flight": True,
    },
    {
        # Remote own-airport place, no flights-from-source, no train -> salvage
        # to nearest gateway so the bundle is never empty.
        "id": "leh-salvage-hub-flight",
        "origin": "Pune", "destination": "Leh", "preference": "Comfort",
        "has_hub_flight": True, "bundle_flight": True,
    },
    {
        # Bundi's railhead is Kota (38km airport-town) — included despite being
        # within the hub radius.
        "id": "bundi-railheads-at-kota",
        "origin": "Jaipur", "destination": "Bundi", "preference": "Budget",
        "rail_hub_contains": "kota", "trains_dest": "kota",
    },
    {
        # Island UT: no railway -> must be flight-only, never a name-collision
        # train (Havelock -> "Vijay Nagar" -> a Ghaziabad station).
        "id": "havelock-island-is-flight-only",
        "origin": "Delhi", "destination": "Havelock Island", "preference": "Budget",
        "no_trains": True, "bundle_flight": True, "bundle_train": False,
    },
]


@pytest.mark.parametrize("case", ROUTING_REGRESSIONS, ids=[c["id"] for c in ROUTING_REGRESSIONS])
def test_routing_regressions(case):
    from app.services.quick_pick_service import QuickPickService
    res, status = _orchestrate(case["origin"], case["destination"], case["preference"])
    where = f'{case["origin"]}->{case["destination"]} [{case["preference"]}]'
    assert status == "completed", f"{where}: status={status}"

    rail_hub = (res.get("rail_hub") or "")
    trains = res.get("trains") or []

    if "rail_hub_contains" in case:
        # Space-insensitive: "Dehra Dun" (IRCTC cityName) == "Dehradun".
        hub_norm = rail_hub.lower().replace(" ", "")
        want = case["rail_hub_contains"].replace(" ", "")
        assert rail_hub and want in hub_norm, f"{where}: rail_hub={rail_hub!r}"
    if case.get("no_rail_hub"):
        assert not rail_hub, f"{where}: unexpected rail_hub={rail_hub!r}"
    if case.get("no_hub_city"):
        assert not res.get("hub_city"), f"{where}: unexpected hub_city={res.get('hub_city')!r}"
    if case.get("has_hub_flight"):
        assert res.get("hub_flight_fallback"), f"{where}: expected hub flights"
    if case.get("no_trains"):
        assert not trains, f"{where}: expected no trains, got {len(trains)}"
    if "trains_dest" in case:
        assert trains and any(case["trains_dest"] in (t.get("destination") or "").lower() for t in trains), \
            f"{where}: no train to {case['trains_dest']!r}; dests={[t.get('destination') for t in trains[:3]]}"

    if "bundle_flight" in case or "bundle_train" in case:
        bundle = QuickPickService().select_best_bundle(res, case["preference"])
        if "bundle_flight" in case:
            assert bool(bundle["flight"]) == case["bundle_flight"], f"{where}: flight={bundle['flight']}"
        if "bundle_train" in case:
            assert bool(bundle["train"]) == case["bundle_train"], f"{where}: train={bundle['train']}"


def _run_manual(origin, destination, preference="Comfort"):
    """
    Runs the progressive manual worker, then resolves onward trains for the best
    flight (mirrors what the frontend does on flight-select). For the no-flight
    case the worker already resolved trains, so return those.
    Returns (results, status, trains_and_transfer).
    """
    from app.services.travel_orchestrator import TravelOrchestrator
    from app.database.connection import db
    orch = TravelOrchestrator()
    jid = f"manual-{uuid.uuid4().hex[:10]}"
    db["trip_jobs"].insert_one({"job_id": jid, "status": "processing", "mode": "manual"})
    try:
        orch._run_manual_search(jid, origin, destination, SEARCH_DATE, preference, "English")
        doc = db["trip_jobs"].find_one({"job_id": jid})
        res = doc.get("results") or {}
        flights = res.get("flights") or res.get("hub_flight_fallback") or []
        if flights:
            tnt = orch.resolve_trains_for_flight(jid, flights[0]) or {}
        else:
            tnt = {"trains": res.get("trains") or [], "transfer": res.get("transfer"),
                   "rail_hub": res.get("rail_hub")}
        return res, doc.get("status"), tnt
    finally:
        db["trip_jobs"].delete_one({"job_id": jid})


# Progressive manual mode must produce the SAME onward trains + cab transfer as
# the synchronized quick-pick path, for every route archetype.
MANUAL_PARITY = [
    ("Mumbai", "Vidisha", "hub-onward"),
    ("London", "Vidisha", "intl-hub-onward"),
    ("Bhopal", "Kangra HP", "railhead-cab"),
    ("Bengaluru", "Mysuru", "direct-train"),
]


@pytest.mark.network
@pytest.mark.parametrize("origin,destination,kind", MANUAL_PARITY, ids=[k for *_, k in MANUAL_PARITY])
def test_manual_matches_synchronized(origin, destination, kind):
    sync_res, sync_status = _orchestrate(origin, destination, "Comfort")
    man_res, man_status, tnt = _run_manual(origin, destination, "Comfort")
    where = f"{origin}->{destination} [{kind}]"
    assert sync_status == "completed" and man_status == "completed", \
        f"{where}: sync={sync_status} manual={man_status}"
    sync_trains = sync_res.get("trains") or []
    man_trains = tnt.get("trains") or []
    assert len(sync_trains) == len(man_trains), \
        f"{where}: sync {len(sync_trains)} vs manual {len(man_trains)} trains"
    sync_xfer = (sync_res.get("transfer") or {}).get("distance_km")
    man_xfer = (tnt.get("transfer") or {}).get("distance_km")
    assert sync_xfer == man_xfer, f"{where}: transfer {sync_xfer} vs {man_xfer}"


@pytest.mark.network
def test_manual_onward_trains_connect_after_flight():
    """Regression for the 'all trains greyed' bug (e.g. London->Vidisha): the
    on-demand onward train must be catchable after the chosen flight lands."""
    import datetime
    import re
    res, status, tnt = _run_manual("London", "Vidisha", "Comfort")
    assert status == "completed"
    assert res.get("flights") or res.get("hub_flight_fallback"), "expected a hub flight"
    trains = tnt.get("trains") or []
    assert trains, "expected onward trains for the chosen flight"
    arr_iso = tnt.get("flight_arrival_iso")
    if arr_iso:
        arr = datetime.datetime.fromisoformat(arr_iso).replace(tzinfo=None)
        first = trains[0]
        md = re.match(r"(\d{2})-(\d{2})-(\d{4})", first.get("departure_date") or "")
        mt = re.match(r"(\d{1,2}):(\d{2})", first.get("departure") or "")
        if md and mt:
            dep = datetime.datetime(int(md.group(3)), int(md.group(2)), int(md.group(1)),
                                    int(mt.group(1)), int(mt.group(2)))
            assert dep >= arr, f"first onward train departs {dep} before flight lands {arr}"


@pytest.mark.network
def test_same_origin_destination_rejected():
    """Delhi and New Delhi resolve to the same city -> the job must fail."""
    _res, status = _orchestrate("Delhi", "New Delhi", "Comfort")
    assert status == "failed", f"expected failed for same place, got {status}"


@pytest.mark.network
def test_international_hill_reaches_railhead_with_cab():
    """London->Darjeeling: fly to a gateway, onward train to the railhead, then a
    cab. Must be multimodal with a train + a cab transfer (not empty)."""
    res, status = _orchestrate("London", "Darjeeling", "Comfort")
    assert status == "completed"
    assert res.get("hub_flight_fallback"), "expected an international hub flight"
    assert res.get("trains"), "expected an onward train to the railhead"
    assert res.get("multimodal") is True, "international fly-then-train is multimodal"
    transfer = res.get("transfer") or {}
    assert transfer.get("distance_km"), "expected a cab transfer to Darjeeling"


@pytest.mark.network
def test_open_saved_trip_restores_session(app_client, tracker):
    """Save a trip, then open it: the endpoint returns it and scopes chat to it."""
    email, _, uid = register_and_login(app_client, tracker)
    # Run a quick domestic search and save it.
    job_id, _results = run_search(app_client, {
        "origin": "Delhi", "destination": "Jaipur", "date": SEARCH_DATE, "preferences": "Comfort",
    }, tracker)
    app_client.post("/api/travel/select", json={
        "job_id": job_id, "selection_type": "quickpick", "preferences": "Comfort",
    })
    save = app_client.post("/api/user/save-trip")
    trip_id = save.get_json()["data"]["trip_id"]
    tracker["user_ids"].append(uid)

    opened = app_client.post("/api/user/open-trip", json={"trip_id": trip_id})
    assert opened.status_code == 200
    trip = opened.get_json()["data"]["trip"]
    assert trip.get("source") and trip.get("destination")
    # Chat now works against the opened trip (session scoped server-side).
    chat = app_client.post("/api/travel/chat", json={"message": "Is this a good plan?"})
    assert chat.status_code == 200


@pytest.mark.network
def test_saved_trip_persists_and_restores_chat(app_client, tracker):
    """Chat about a trip, save it, reopen it: the conversation comes back."""
    email, _, uid = register_and_login(app_client, tracker)
    job_id, _ = run_search(app_client, {
        "origin": "Delhi", "destination": "Jaipur", "date": SEARCH_DATE, "preferences": "Comfort",
    }, tracker)
    app_client.post("/api/travel/select", json={
        "job_id": job_id, "selection_type": "quickpick", "preferences": "Comfort",
    })
    tracker["user_ids"].append(uid)

    # Have a conversation, then save — the chat should be stored with the trip.
    app_client.post("/api/travel/chat", json={"message": "What is the weather like?"})
    trip_id = app_client.post("/api/user/save-trip").get_json()["data"]["trip_id"]

    opened = app_client.post("/api/user/open-trip", json={"trip_id": trip_id})
    history = opened.get_json()["data"]["chat_history"]
    assert any(m.get("role") == "user" for m in history), "saved chat should restore on open"

    # Update the saved chat and confirm it persists across a re-open.
    new_hist = history + [{"role": "user", "content": "One more question"}]
    upd = app_client.post("/api/user/update-trip-chat",
                          json={"trip_id": trip_id, "chat_history": new_hist})
    assert upd.status_code == 200
    reopened = app_client.post("/api/user/open-trip", json={"trip_id": trip_id})
    assert len(reopened.get_json()["data"]["chat_history"]) == len(new_hist)


@pytest.mark.network
def test_delete_saved_trip(app_client, tracker):
    """A saved trip can be deleted and then no longer opens."""
    email, _, uid = register_and_login(app_client, tracker)
    job_id, _ = run_search(app_client, {
        "origin": "Delhi", "destination": "Jaipur", "date": SEARCH_DATE, "preferences": "Comfort",
    }, tracker)
    app_client.post("/api/travel/select", json={
        "job_id": job_id, "selection_type": "quickpick", "preferences": "Comfort",
    })
    tracker["user_ids"].append(uid)
    trip_id = app_client.post("/api/user/save-trip").get_json()["data"]["trip_id"]

    deleted = app_client.post("/api/user/delete-trip", json={"trip_id": trip_id})
    assert deleted.status_code == 200
    # Reopening a deleted trip 404s, and it's gone from the dashboard.
    assert app_client.post("/api/user/open-trip", json={"trip_id": trip_id}).status_code == 404
    dash = app_client.get("/api/user/dashboard").get_json()["data"]
    assert all(tp["_id"] != trip_id for tp in dash["trips"])


@pytest.mark.parametrize("country,currency", [
    ("US", "USD"), ("GB", "GBP"), ("AE", "AED"), ("IT", "EUR"), ("JP", "JPY"),
])
def test_currency_resolution_live(country, currency):
    from app.services.currency_service import CurrencyService
    info = CurrencyService().get_rate_info(country)
    assert info["code"] == currency
    assert info["rate"] > 0


# --------------------------------------------------------------------------- auth + save trip

def test_full_auth_and_save_trip_flow(app_client, tracker):
    email, _, uid = register_and_login(app_client, tracker)

    me = app_client.get("/api/auth/me")
    assert me.status_code == 200
    assert me.get_json()["data"]["user_id"] == uid

    job_id, _ = run_search(
        app_client,
        {"origin": "Mumbai", "destination": "Jaipur", "date": SEARCH_DATE, "preferences": "Comfort"},
        tracker,
    )
    sel = app_client.post("/api/travel/select", json={
        "job_id": job_id, "selection_type": "quickpick", "preferences": "Comfort",
    })
    assert sel.status_code == 200, sel.get_json()

    saved = app_client.post("/api/user/save-trip")
    assert saved.status_code == 201, saved.get_json()

    dash = app_client.get("/api/user/dashboard")
    assert dash.status_code == 200
    assert len(dash.get_json()["data"]["trips"]) >= 1

    app_client.post("/api/auth/logout")
    assert app_client.get("/api/auth/me").status_code == 401


# --------------------------------------------------------------------------- guide booking + reviews

def test_full_guide_flow_with_pricing_and_reviews(app_client, tracker):
    register_and_login(app_client, tracker)

    city = f"Testville{uuid.uuid4().hex[:6]}"
    reg = app_client.post("/api/guides/register", json={
        "name": "Test Guide", "email": f"guide_{uuid.uuid4().hex[:8]}@bharatbhraman.test",
        "phone": "9999999999", "city": city, "languages": "English, Hindi",
        "hourly_rate": 500, "age": 30, "gender": "other",
    })
    assert reg.status_code == 201, reg.get_json()
    guide_id = reg.get_json()["data"]["guide_id"]
    tracker["guide_ids"].append(guide_id)

    # Search finds the new guide
    found = app_client.get(f"/api/guides/search?city={city}")
    assert found.status_code == 200
    guides_list = found.get_json()["data"]
    assert any(g["_id"] == guide_id for g in guides_list)
    new_guide = next(g for g in guides_list if g["_id"] == guide_id)
    assert new_guide["rating"] is None  # no fake default
    assert "is_verified" not in new_guide  # badge dropped

    # Booking with pricing breakdown (500/hr x 3h + 25% fee)
    booking = app_client.post("/api/guides/book", json={"guide_id": guide_id, "date": SEARCH_DATE, "hours": 3})
    assert booking.status_code == 201, booking.get_json()
    b = booking.get_json()["data"]["booking"]
    assert b["base_price"] == 1500.0
    assert b["platform_fee"] == 375.0
    assert b["total_price"] == 1875.0

    # Review updates the aggregate rating
    review = app_client.post("/api/guides/review", json={"guide_id": guide_id, "rating": 4, "comment": "Great"})
    assert review.status_code == 201, review.get_json()

    found2 = app_client.get(f"/api/guides/search?city={city}")
    g2 = next(g for g in found2.get_json()["data"] if g["_id"] == guide_id)
    assert g2["rating"] == 4.0
    assert g2["review_count"] == 1


def test_guide_booking_requires_login(app_client):
    # Fresh client with no session
    from app import create_app
    anon = create_app().test_client()
    r = anon.post("/api/guides/book", json={"guide_id": "x", "date": SEARCH_DATE, "hours": 2})
    assert r.status_code == 401


# --------------------------------------------------------------------------- AI chat

def test_trip_aware_chat(app_client, tracker):
    register_and_login(app_client, tracker)
    job_id, _ = run_search(
        app_client,
        {"origin": "Delhi", "destination": "Jaipur", "date": SEARCH_DATE, "preferences": "Comfort"},
        tracker,
    )
    app_client.post("/api/travel/select", json={
        "job_id": job_id, "selection_type": "quickpick", "preferences": "Comfort",
    })
    chat = app_client.post("/api/travel/chat", json={"message": "What should I pack for this trip?"})
    assert chat.status_code == 200
    assert isinstance(chat.get_json()["data"]["response"], str)
    assert len(chat.get_json()["data"]["response"]) > 0


# ===================================================================== regression

ARCHETYPES = [
    ("Mumbai", "Delhi", "metro"),          # both have airports + trains
    ("Chennai", "Port Blair", "island"),   # flight-only, no trains
    ("Bangalore", "Ooty", "hub_no_train"), # hub flight, no onward train
    ("Mumbai", "Kerala", "state_input"),   # state -> capital city
]


@pytest.mark.parametrize("origin,dest,kind", ARCHETYPES)
def test_archetype_trip_data(app_client, tracker, origin, dest, kind):
    from app.services.quick_pick_service import QuickPickService
    _, res = run_search(app_client, {"origin": origin, "destination": dest,
                                     "date": SEARCH_DATE, "preferences": "Comfort"}, tracker)

    # Locations resolved to real cities (state inputs must NOT stay as the state).
    assert res["source"].get("city")
    dst_city = res["destination"].get("city")
    assert dst_city
    if kind == "state_input":
        assert dst_city.lower() != "kerala"  # resolved to a city (Thiruvananthapuram)

    assert res.get("currency") == "INR"

    flights = res.get("flights") or []
    hub = res.get("hub_flight_fallback") or []
    trains = res.get("trains") or []
    assert res.get("hotels"), "expected hotels"
    assert len(res.get("itinerary") or []) >= 4

    # Every archetype must yield at least one usable transport option and a
    # non-empty quick-pick bundle (Comfort + Budget).
    assert flights or hub or trains, "no transport found"
    qp = QuickPickService()
    for pref in ("Comfort", "Budget"):
        bundle = qp.select_best_bundle(res, pref)
        assert bundle["flight"] or bundle["train"], f"{kind} {pref}: empty bundle"
        assert bundle["hotel"] is not None

    if kind == "island":
        assert flights and not trains
    if kind == "hub_no_train":
        assert hub, "expected hub_flight_fallback for hill station"


def test_itinerary_has_images_for_known_city(app_client, tracker):
    # A famous destination must come back with real images (retry/self-heal).
    _, res = run_search(app_client, {"origin": "Delhi", "destination": "Jaipur",
                                     "date": SEARCH_DATE, "preferences": "Comfort"}, tracker)
    itin = res.get("itinerary") or []
    assert len(itin) >= 5
    assert sum(1 for p in itin if p.get("image_url")) >= 3


@pytest.mark.parametrize("query,expect_cc,expect_city", [
    ("Kochi", "in", None),                 # not Japan
    ("Kerala", "in", "thiruvananthapuram"),  # state -> capital
    ("India", "in", "new delhi"),          # country -> capital
    ("Nainital", "in", "nainital"),        # district keeps its name
    ("London", "gb", None),                # foreign still resolves
])
def test_location_resolution_to_city(query, expect_cc, expect_city):
    from app.services.travel_orchestrator import TravelOrchestrator
    loc = TravelOrchestrator()._resolve_location(query)
    assert loc and loc.get("country_code", "").lower() == expect_cc
    assert loc.get("result_type") not in {"state", "country"}  # never a bare area
    if expect_city:
        assert expect_city in (loc.get("city") or "").lower()


# ----------------------------------------------------------- post-creation data

def test_persisted_job_and_itinerary_cache(app_client, tracker):
    from app.database.connection import db, content
    job_id, res = run_search(app_client, {"origin": "Mumbai", "destination": "Jaipur",
                                          "date": SEARCH_DATE, "preferences": "Comfort"}, tracker)
    # The job document persisted with completed status + a well-formed results blob.
    job = db["trip_jobs"].find_one({"job_id": job_id})
    assert job and job["status"] == "completed"
    assert isinstance(job["results"], dict)
    assert job["results"]["source"].get("city") and job["results"]["destination"].get("city")
    # The itinerary was cached for the destination city.
    cached = content.find_one({"city": (res["destination"]["city"]).lower(), "language": "english"})
    assert cached and len(cached.get("places", [])) >= 4


def test_saved_trip_persisted_with_segments(app_client, tracker):
    from app.database.connection import trips
    _, _, uid = register_and_login(app_client, tracker)

    job_id, _ = run_search(app_client, {"origin": "Mumbai", "destination": "Jaipur",
                                        "date": SEARCH_DATE, "preferences": "Comfort"}, tracker)
    sel = app_client.post("/api/travel/select", json={
        "job_id": job_id, "selection_type": "quickpick", "preferences": "Comfort"})
    assert sel.status_code == 200
    saved = app_client.post("/api/user/save-trip")
    assert saved.status_code == 201

    # The persisted trip doc carries the committed trip with its segments.
    doc = trips.find_one({"user_id": uid})
    assert doc is not None
    trip = doc.get("itinerary") or {}
    assert trip.get("source") and trip.get("destination")
    assert "segments" in trip


def test_guide_booking_doc_persisted_with_pricing(app_client, tracker):
    from app.database.connection import db
    _, _, uid = register_and_login(app_client, tracker)
    city = f"Bookville{uuid.uuid4().hex[:6]}"
    reg = app_client.post("/api/guides/register", json={
        "name": "Doc Guide", "email": f"g_{uuid.uuid4().hex[:8]}@bharatbhraman.test",
        "phone": "9999999999", "city": city, "languages": "English", "hourly_rate": 400,
    })
    gid = reg.get_json()["data"]["guide_id"]
    tracker["guide_ids"].append(gid)
    app_client.post("/api/guides/book", json={"guide_id": gid, "date": SEARCH_DATE, "hours": 2})

    booking = db["guide_bookings"].find_one({"guide_id": gid})
    assert booking is not None
    assert booking["user_id"] == uid
    assert booking["base_price"] == 800.0
    assert booking["platform_fee"] == 200.0
    assert booking["total_price"] == 1000.0
    assert booking["status"] == "pending"


# ----------------------------------------------------------- route validation (edge)

@pytest.mark.parametrize("payload,code", [
    ({}, 400),                                                              # missing fields
    ({"origin": "Pune", "destination": "pune", "date": SEARCH_DATE}, 400),  # same place
    ({"origin": "Pune", "destination": "Goa", "date": "01-07-2026"}, 400),  # bad date format
])
def test_search_validation(app_client, payload, code):
    assert app_client.post("/api/travel/search", json=payload).status_code == code


def test_chat_requires_message(app_client):
    assert app_client.post("/api/travel/chat", json={"message": "  "}).status_code == 400


def test_select_unknown_job(app_client):
    r = app_client.post("/api/travel/select", json={"job_id": "does-not-exist", "selection_type": "quickpick"})
    assert r.status_code == 400
