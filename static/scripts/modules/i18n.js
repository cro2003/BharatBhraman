import { STORAGE_KEYS } from "./config.js";
import { getStoredValue, setStoredValue } from "./storage.js";

// Human-readable language names mapped to BCP-47 codes.
export const LANG_CODES = {
    English: "en", Hindi: "hi", Marathi: "mr",
    Gujarati: "gu", Tamil: "ta", Kannada: "kn",
};
export const SUPPORTED_LANGUAGES = Object.keys(LANG_CODES);

// Single English source of truth for every UI string. Non-English languages are
// produced on demand by the backend translator (LLM + cache), so we never hand-
// maintain per-language dictionaries. Numbers/placeholders ({n}) are preserved.
const EN = {
    "nav.planner": "Planner", "nav.quickpicks": "Quick Picks", "nav.howItWorks": "How It Works",
    "nav.results": "Results", "nav.guides": "Local Guides", "nav.assistant": "Trip Assistant",
    "nav.dashboard": "Dashboard", "nav.logout": "Logout", "nav.login": "Login / Register",
    "nav.planTrip": "Plan Trip",
    "hero.eyebrow": "Multilingual trip planning for India",
    "hero.title": "Plan your perfect Indian journey with AI-powered live search.",
    "hero.text": "Search flights, trains, stays, and destination ideas in one place. Use quick picks for instant bundles or manual mode when you want to choose each segment yourself.",
    "pill.flights": "Flights", "pill.trains": "Trains", "pill.hotels": "Hotels", "pill.itinerary": "AI Itinerary",
    "panel.kicker": "Trip Modes", "panel.title": "Search Your Journey",
    "mode.quickpicks": "Quick Picks", "mode.manual": "Manual Mode",
    "form.from": "From", "form.to": "To", "form.date": "Departure Date", "form.preference": "Preference",
    "form.fromPlaceholder": "Delhi, Mumbai, Dubai", "form.toPlaceholder": "Jaipur, Udaipur, Varanasi",
    "pref.comfort": "Comfort", "pref.budget": "Budget",
    "form.hint": "Quick picks automatically bundle the best travel combination for the chosen preference.",
    "form.hintManual": "Manual mode still runs a full search, then lets you compare flights, trains, and stays in detail.",
    "form.search": "Search Trip",
    "destinations.eyebrow": "Popular quick picks",
    "destinations.title": "Travel ideas people can start from immediately",
    "card.useDestination": "Use as destination",
    "how.eyebrow": "How this planner works",
    "how.title": "Built for both fast decisions and detailed control",
    "status.submitting": "Submitting search", "status.queued": "Queued",
    "status.starting": "Starting your live trip search.",
    "status.searching": "Searching live routes", "status.processing": "Processing",
    "status.checking": "Checking flights, trains, hotels, and itinerary content.",
    "status.timeout": "This search is taking longer than usual. Please try again in a moment.",
    "status.failed": "Search failed", "status.preparing": "Preparing your trip", "status.connecting": "Connecting",
    "status.resolving": "Resolving cities, airports, and live travel options.",
    "status.working": "Working", "status.fetching": "Fetching travel options.",
    "status.building": "Building your trip", "status.searchingChip": "Searching",
    "status.resolvingHubs": "Resolving hubs, routes, hotels, and itinerary suggestions.",
    "status.error": "Error", "status.somethingWrong": "Something went wrong while searching.",
    "status.fact1": "Comparing flights, trains, and stays across providers…",
    "status.fact2": "India runs one of the world's largest rail networks — finding your train…",
    "status.fact3": "Scouting the nearest railhead for hard-to-reach hill stations…",
    "status.fact4": "Lining up onward trains with your flight's arrival time…",
    "status.fact5": "Picking comfortable stays close to where you land…",
    "status.fact6": "Asking our AI for places worth your time at the destination…",
    "status.fact7": "Measuring the last-mile cab hop when there's no station nearby…",
    "results.recommendedTrip": "Recommended trip", "results.manualPreview": "Manual preview",
    "results.bundleTitle": "Your selected journey bundle", "results.snapshotTitle": "Chosen trip snapshot",
    "results.bundleIntro": "Only the recommended segments are shown here. Full comparison stays inside Manual Mode.",
    "results.manualIntro": "Compare all options below, while keeping your current picked segments visible here.",
    "results.saveTrip": "Save Trip", "results.saved": "Saved", "results.saving": "Saving...",
    "results.couldNotSave": "Could not save trip.",
    "results.modeQuick": "Quick Pick Preview", "results.modeManual": "Manual Compare",
    "results.subtitleCompare": "Comparing flights, trains, hotels, and itinerary suggestions.",
    "results.heroEyebrow": "Your trip, planned", "results.heroTitle": "Trip options ready",
    "results.transportEyebrow": "Transport", "results.transportTitle": "Flight and train options",
    "results.stayEyebrow": "Stay", "results.stayTitle": "Hotel options",
    "results.itineraryEyebrow": "AI itinerary", "results.itineraryTitle": "Places to visit at your destination",
    "results.pricesIn": "Prices in {currency}",
    "card.flight": "Flight", "card.train": "Train", "card.stay": "Stay",
    "card.suggestedStay": "Suggested stay", "card.staySnapshot": "Stay snapshot",
    "card.departure": "Departure", "card.arrival": "Arrival", "card.stops": "Stops",
    "card.duration": "Duration", "card.rating": "Rating", "card.stars": "Stars",
    "card.origin": "Origin", "card.destination": "Destination", "card.viewStay": "View stay details",
    "card.direct": "Direct", "card.directRoute": "Direct route",
    "flight.layover": "Layover", "flight.via": "Via", "flight.nonstop": "Non-stop", "flight.stopsCount": "{n} stop(s)",
    "card.durationUnavailable": "Duration unavailable", "card.availabilityUnknown": "Availability unknown",
    "section.flights": "Flights", "section.trains": "Trains", "section.hotels": "Hotels",
    "common.options": "options", "common.na": "N/A",
    "empty.noHotels": "No hotels found for this route yet.",
    "empty.itineraryLoading": "Itinerary details are still loading.",
    "transfer.no_connection": "Heads up: we couldn't find a train that reliably connects after your flight lands. Check the onward timing before you book.",
    "transfer.unverified": "We couldn't verify the flight-to-train connection time. Confirm the onward train departs after you land.",
    "journey.eyebrow": "Your trip, start to finish",
    "journey.title": "How you'll get there",
    "journey.intro": "We've picked the best combination for your preference. Each stop links to its location on the map.",
    "journey.legFlight": "Fly", "journey.legTrain": "Take the train", "journey.legCab": "Road transfer", "journey.legStay": "Check in",
    "journey.cabNote": "{km} km by cab from {from} to {to}",
    "journey.startAt": "Depart", "journey.arriveAt": "Arrive",
    "journey.customize": "Customize this trip",
    "map.badge": "Map", "map.open": "Open in Google Maps",
    "noopts.eyebrow": "No travel for this date",
    "noopts.title": "We couldn't find a way to travel on this day",
    "noopts.body": "Flights and trains weren't available for this route on your chosen date. Try another date — meanwhile, here's what's worth seeing once you arrive.",
    "wizard.eyebrow": "Build your own trip",
    "wizard.title": "Choose each part of your journey",
    "wizard.stepFlight": "Flight", "wizard.stepTrain": "Train", "wizard.stepStay": "Stay", "wizard.stepReview": "Review",
    "wizard.stepTransport": "Travel", "wizard.pickTransport": "Choose how you'll travel",
    "wizard.transportIntro": "Pick a flight or a train — whichever suits you. You only need one.",
    "wizard.back": "Back", "wizard.next": "Next", "wizard.confirm": "Confirm trip",
    "wizard.pickFlight": "Pick your flight", "wizard.pickTrain": "Pick your train", "wizard.pickStay": "Pick your stay",
    "wizard.reviewTitle": "Review your journey", "wizard.reviewIntro": "Here's the trip you've built. Confirm it to use with the assistant, then Save Trip to keep it.",
    "wizard.selected": "Selected", "wizard.select": "Select", "wizard.confirmed": "Trip confirmed",
    "wizard.confirmedHint": "Trip confirmed. Save it to keep it in your account.",
    "wizard.edit": "Edit trip", "wizard.finalEyebrow": "Trip confirmed",
    "wizard.finalTitle": "Your journey is ready",
    "wizard.noFlights": "No flights available for this route.", "wizard.noTrains": "No trains available for this route.",
    "wizard.beforeFlight": "Departs before your flight lands", "wizard.trainGateHint": "Only trains that depart after your flight lands can be selected.",
    "wizard.findingTrains": "Finding trains for your flight…", "wizard.loadingStays": "Finding stays…",
    "summary.route": "Route", "summary.flightOptions": "Flight options",
    "summary.trainOptions": "Train options", "summary.hotelOptions": "Hotel options",
    "chat.title": "Trip Assistant",
    "chat.headerEyebrow": "Planned trip assistant", "chat.headerTitle": "Ask about this trip",
    "chat.summaryIntro": "The assistant will answer from your selected route, stay, and itinerary.",
    "chat.contextNote": "Only the chosen trip bundle and itinerary are sent as context.",
    "chat.openAria": "Open trip assistant", "chat.closeAria": "Close trip assistant",
    "chat.clear": "Clear", "chat.clearAria": "Clear chat history", "chat.typing": "Assistant is typing",
    "chat.summaryDefault": "Trip context will update once a bundle is selected.",
    "chat.contextUnavailable": "Trip assistant context is not available yet.",
    "chat.placeholder": "Example: Is this plan better for a relaxed family trip or a fast sightseeing trip?",
    "chat.send": "Send", "chat.you": "You",
    "chat.intro": "Ask about your selected route, stay, local logistics, or itinerary tradeoffs.",
    "chat.unavailable": "The assistant is unavailable right now.",
    "summarize.flight": "Flight", "summarize.train": "Train", "summarize.stay": "Stay",
    "guides.heroEyebrow": "Ground support",
    "guides.heroTitle": "Find local guides for the destination you already planned.",
    "guides.heroText": "Search verified local guides by city and language, see their rates and reviews, and book directly.",
    "guides.searchKicker": "Guide search", "guides.searchHeading": "Discover local experts",
    "guides.city": "City", "guides.language": "Language",
    "guides.cityPlaceholder": "Vidisha, Jaipur, Mumbai", "guides.langPlaceholder": "Optional: English, Hindi",
    "guides.searchHint": "Guide search matches the exact city name.",
    "guides.searchBtn": "Search Guides",
    "guides.availableEyebrow": "Available guides", "guides.searchToLoad": "Search to load guide cards",
    "guides.cardsAppear": "Guide cards will appear here",
    "guides.becomeEyebrow": "Become a guide", "guides.registerHeading": "Register as a local guide",
    "guides.registerSubtitle": "Share your city knowledge and earn by guiding travelers.",
    "guides.regKicker": "Guide registration", "guides.regHeading": "Your profile details",
    "guides.fullName": "Full name", "guides.email": "Email", "guides.phone": "Phone",
    "guides.cityCovered": "City you cover", "guides.languagesCsv": "Languages (comma separated)",
    "guides.hourlyRate": "Hourly rate (₹)", "guides.age": "Age", "guides.gender": "Gender",
    "guides.genderSelect": "Select", "guides.male": "Male", "guides.female": "Female", "guides.other": "Other",
    "guides.regHint": "Your profile will be visible to travelers searching this city.",
    "guides.register": "Register",
    "guides.pillDestination": "Destination matching", "guides.pillLanguage": "Language filtering",
    "guides.pillRatings": "Ratings & pricing", "guides.chipApi": "Live listings", "guides.chipNew": "New guide",
    "guides.noSearchYet": "No guide search has been run yet.",
    "guides.emptyCardHint": "Search by destination city and optional language to load available guides.",
    "guides.findTitle": "Find a local guide", "guides.noGuides": "No guides found",
    "guides.noGuidesHint": "Try a different destination spelling or remove the language filter.",
    "guides.loading": "Loading guides...", "guides.loadingHint": "Fetching guide profiles.",
    "guides.noReviews": "No reviews yet", "guides.review": "Review", "guides.book": "Book",
    "guides.submitReview": "Submit review", "guides.reviewThanks": "Thanks for your review!",
    "guides.cityUnavailable": "City unavailable", "guides.unnamed": "Unnamed guide",
    "guides.ratingLabel": "Rating", "guides.commentLabel": "Comment",
    "guides.commentPlaceholder": "How was your experience?",
    "guides.reviewOne": "review", "guides.reviewMany": "reviews", "guides.traveller": "Traveller",
    "guides.rate5": "5 — Excellent", "guides.rate4": "4 — Good", "guides.rate3": "3 — Okay",
    "guides.rate2": "2 — Poor", "guides.rate1": "1 — Bad",
    "guides.searchingFor": "Searching guides for", "guides.filteringBy": "Filtering by language:",
    "guides.checkingAll": "Checking all guide profiles for this city.",
    "guides.guidesFound": "guides found for", "guides.guideFound": "guide found for",
    "guides.loadedNote": "Guide cards below are the current guide listings.",
    "guides.noneMatched": "No guide profiles matched this city and language combination.",
    "guides.searchFailed": "Guide search failed", "guides.unableLoad": "Unable to load guide profiles right now.",
    "guides.reviewSubmitted": "Thanks for your review!", "guides.couldNotReview": "Could not submit review.",
    "booking.retry": "Retry", "booking.failed": "Booking failed.",
    "reg.requiredFields": "Name, email, and city are required.",
    "reg.registering": "Registering...", "reg.registered": "Registered successfully!",
    "reg.failed": "Registration failed.", "reg.idLabel": "Guide ID:",
    "guides.latestDest": "Latest trip destination detected:",
    "booking.bookedToast": "Booked! Total {total} (incl. fee). See it in your Dashboard.",
    "booking.kicker": "Book guide",
    "booking.title": "Confirm booking", "booking.date": "Select date", "booking.hours": "Hours",
    "booking.confirm": "Confirm Booking", "booking.booking": "Booking...", "booking.booked": "Booked!",
    "booking.guideCost": "Guide", "booking.platformFee": "Platform fee", "booking.total": "Total",
    "booking.hint": "Choose a date and number of hours for your guided tour.",
    "dashboard.savedTrips": "Saved Trips", "dashboard.bookings": "Guide Bookings",
    "dashboard.noTrips": "You haven't saved any trips yet.", "dashboard.planTrip": "Plan a Trip",
    "dashboard.planTripSub": "Start a fresh search",
    "dashboard.noBookings": "No local guides booked yet.", "dashboard.findGuide": "Find a Guide",
    "dashboard.loadingTrips": "Loading your trips...", "dashboard.loadingBookings": "Loading your bookings...",
    "dashboard.guide": "Guide", "dashboard.account": "Your Account",
    "dashboard.welcome": "Welcome", "dashboard.failedLoad": "Failed to load dashboard data.",
    "dashboard.openTrip": "Open trip", "dashboard.opening": "Opening…",
    "dashboard.deleteTrip": "Delete", "dashboard.confirmDelete": "Tap again to delete",
    "dashboard.deleting": "Deleting…",
    "results.savedTrip": "Your saved trip",
    "auth.login": "Login", "auth.register": "Register", "auth.email": "Email Address",
    "auth.password": "Password", "auth.fullName": "Full Name",
    "auth.welcomeBack": "Welcome Back", "auth.loginTitle": "Login to your account",
    "auth.newAccount": "New Account", "auth.registerTitle": "Create your account",
    "auth.authFailed": "Authentication failed. Please try again.", "auth.processing": "Processing...",
    "auth.asideLead": "Plan smarter journeys across India — save trips, book local guides, and pick up right where you left off.",
    "auth.asidePoint1": "Save and reopen your trips",
    "auth.asidePoint2": "Book verified local guides",
    "auth.asidePoint3": "Chat with your AI trip assistant",
    "chatpage.eyebrow": "Trip assistance",
    "chatpage.title": "Ask BharatBhraman anything about your route, destination, or itinerary.",
    "chatpage.contextKicker": "Trip context",
    "chatpage.contextPlaceholder": "Optional context about your trip, destination, budget, or selected travel plan.",
    "chatpage.yourQuestion": "Your question",
    "chatpage.questionPlaceholder": "Example: Is train better than flight for this route if I want to save money?",
    "insight.quickTitle": "Quick Picks",
    "insight.quickText": "Best for instant bundling. We compare flights, trains, hotels, and onward routes for you.",
    "insight.manualTitle": "Manual Mode",
    "insight.manualText": "Best for travelers who want to compare segments individually before committing the trip.",
    "insight.fallbackTitle": "Smart fallback routing",
    "insight.fallbackText": "When a destination is not a direct air hub, the planner can combine airport hub arrivals with train connections.",
    "brand.tagHome": "AI Trip Planner", "brand.tagResults": "Trip Results",
    "brand.tagChat": "AI Travel Guide", "brand.tagGuides": "Local Guide Discovery",
    "brand.tagDashboard": "Dashboard", "brand.tagAuth": "Authentication",
    "panel.chip": "Live travel search", "status.kicker": "Search Status",
    "reel.route": "Charting the route", "reel.flights": "Finding flights",
    "reel.trains": "Checking trains", "reel.stays": "Finding stays",
    "reel.itinerary": "Building itinerary",
    "dest.mumbai": "Mumbai", "dest.kerala": "Kerala", "dest.jaipur": "Jaipur", "dest.agra": "Agra",
    "dest.mumbaiDesc": "Food, coastlines, and late-night city energy",
    "dest.keralaDesc": "Backwaters, slow routes, and comfort-first escapes",
    "dest.jaipurDesc": "Historic forts, city bazaars, and weekend planning",
    "dest.agraDesc": "Classic itinerary building with rail-friendly travel",
    "guides.navRegister": "Register as guide", "guides.navFind": "Find a guide",
    "auth.namePlaceholder": "E.g., Priya Patel", "auth.emailPlaceholder": "E.g., traveler@example.com",
    "auth.passwordPlaceholder": "Enter your password",
    "chatpage.useContext": "Use latest trip context",
    "chatpage.heroText": "The assistant uses your latest search context, itinerary hints, and destination details to answer with specifics — not generic advice.",
    "chatpage.greeting": "Hello. Ask about routes, stay decisions, attraction planning, food, timing, or trip tradeoffs.",
    "chatpage.hint": "Answers are tailored to your trip context when provided.",
    "chatpage.chip2day": "2-day plan", "chatpage.chipPacking": "Packing help", "chatpage.chipFood": "Local food",
    "common.logoutFailed": "Failed to logout. Please try again.",
    "common.requestFailed": "Request failed", "common.invalidResponse": "Invalid JSON response",
    "common.unknownDate": "Unknown Date", "common.unknownPlace": "Unknown place",
    "card.untitledPlace": "Untitled place", "card.descUnavailable": "Description unavailable",
    "card.addrUnavailable": "Address unavailable", "card.hotelImageAlt": "Hotel image", "card.placeImageAlt": "Place image",
    "title.home": "BharatBhraman", "title.results": "BharatBhraman Results",
    "title.guides": "BharatBhraman Guides", "title.chat": "BharatBhraman AI Guide",
    "title.dashboard": "BharatBhraman - Dashboard", "title.auth": "BharatBhraman - Authentication",
};

// Currently active dictionary (English by default; replaced after async load).
let activeDict = EN;

export function getCurrentLanguage() {
    const stored = getStoredValue(STORAGE_KEYS.selectedLanguage);
    return SUPPORTED_LANGUAGES.includes(stored) ? stored : "English";
}

export function setCurrentLanguage(language) {
    if (SUPPORTED_LANGUAGES.includes(language)) {
        setStoredValue(STORAGE_KEYS.selectedLanguage, language);
    }
}

// `language` is accepted for compatibility; the active dictionary already
// reflects the selected language after loadTranslations().
export function t(key, language) {
    return activeDict[key] || EN[key] || key;
}

// Cheap stable hash of the key set so cached translations invalidate when
// strings are added/removed.
function keysetHash() {
    const s = Object.keys(EN).sort().join("|");
    let h = 0;
    for (let i = 0; i < s.length; i++) {
        h = (h * 31 + s.charCodeAt(i)) | 0;
    }
    return String(h);
}

async function loadTranslations(language) {
    if (!language || language === "English") {
        activeDict = EN;
        return;
    }
    const cacheKey = `bb:i18n:${language}:${keysetHash()}`;
    const cached = sessionStorage.getItem(cacheKey);
    if (cached) {
        try {
            activeDict = { ...EN, ...JSON.parse(cached) };
            return;
        } catch (e) { /* refetch */ }
    }
    try {
        const resp = await fetch("/api/i18n/translate", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            credentials: "same-origin",
            body: JSON.stringify({ language, strings: EN }),
        });
        const body = await resp.json();
        if (resp.ok && body.data) {
            activeDict = { ...EN, ...body.data };
            try { sessionStorage.setItem(cacheKey, JSON.stringify(body.data)); } catch (e) { /* quota */ }
        } else {
            activeDict = EN;
        }
    } catch (e) {
        activeDict = EN;
    }
}

export function applyTranslations() {
    document.documentElement.lang = LANG_CODES[getCurrentLanguage()] || "en";
    document.querySelectorAll("[data-i18n]").forEach((el) => {
        el.textContent = t(el.dataset.i18n);
    });
    document.querySelectorAll("[data-i18n-placeholder]").forEach((el) => {
        el.setAttribute("placeholder", t(el.dataset.i18nPlaceholder));
    });
    document.querySelectorAll("[data-i18n-aria-label]").forEach((el) => {
        el.setAttribute("aria-label", t(el.dataset.i18nAriaLabel));
    });
}

// Loads the active language's dictionary (await before page render) and applies
// it to static markup. JS-rendered content should call t() at render time.
export async function initI18n() {
    await loadTranslations(getCurrentLanguage());
    applyTranslations();
}

// Switches language live: persist, load, re-apply. Returns once applied.
export async function changeLanguage(language) {
    setCurrentLanguage(language);
    await loadTranslations(language);
    applyTranslations();
}
