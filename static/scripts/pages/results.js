import { getSearchRequest, getSearchResults, getStoredJson, getStoredValue, setStoredJson, setStoredValue, removeStoredValue } from "../modules/storage.js";
import { STORAGE_KEYS } from "../modules/config.js";
import { travelApi, userApi } from "../modules/api.js";
import { t, getCurrentLanguage } from "../modules/i18n.js";
import { formatPrice } from "../modules/formatters.js";
import { refreshReveal } from "../modules/motion.js";
import {
    flightLayovers,
    formatTripDate,
    renderItineraryCards,
    renderJourneyTimeline,
    renderNoOptions,
    renderResultsHeader,
    segLabel,
} from "../modules/renderers.js";

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function parseNumeric(value) {
    const normalized = String(value ?? "").replaceAll(",", "");
    const parsed = Number.parseFloat(normalized);
    return Number.isFinite(parsed) ? parsed : Number.MAX_SAFE_INTEGER;
}

const PLACEHOLDER_IMG = "/static/img-placeholder.svg";

function getFlights(results) {
    return results.flights || results.hub_flight_fallback || [];
}

// Quick Pick: the single best combination for the chosen preference. Budget
// favours the train and the cheapest stay; Comfort favours the flight and the
// best-rated stay. A hub flight + onward train is kept together (multimodal).
function chooseQuickPick(results, preference) {
    const flights = results.flights || [];
    const fallbackFlights = results.hub_flight_fallback || [];
    const trains = results.trains || [];
    const hotels = results.hotels || [];

    let chosenFlight = null;
    let chosenTrain = null;

    if (results.multimodal && fallbackFlights.length && trains.length) {
        // Genuine multimodal: fly to the gateway, then the onward train.
        chosenFlight = fallbackFlights[0] || null;
        chosenTrain = trains[0] || null;
    } else {
        // Single-mode: flight and train are alternatives, pick exactly one.
        const availFlights = flights.length ? flights : fallbackFlights;
        if (preference === "Budget") {
            chosenTrain = trains[0] || null;
            chosenFlight = chosenTrain ? null : (availFlights[0] || null);
        } else {
            chosenFlight = availFlights[0] || null;
            chosenTrain = chosenFlight ? null : (trains[0] || null);
        }
    }

    const chosenHotel = preference === "Budget"
        ? hotels.slice().sort((a, b) => parseNumeric(a.price) - parseNumeric(b.price))[0] || null
        : hotels.slice().sort((a, b) => parseNumeric(b.rating || 0) - parseNumeric(a.rating || 0))[0] || null;

    return { flight: chosenFlight, train: chosenTrain, hotel: chosenHotel };
}

function buildSelectionPayload(mode, jobId, preference, manualSelection) {
    if (mode === "quickpick") {
        return { job_id: jobId, selection_type: "quickpick", preferences: preference };
    }
    return {
        job_id: jobId,
        selection_type: "manual",
        selection_data: {
            flight: manualSelection.flight || null,
            train: manualSelection.train || null,
            hotel: manualSelection.hotel || null,
        },
    };
}

function summarizeBundle(bundle) {
    const parts = [];
    if (bundle.flight) {
        parts.push(`${t("summarize.flight")}: ${bundle.flight.airline || ""}`.trim());
    }
    if (bundle.train) {
        parts.push(`${t("summarize.train")}: ${bundle.train.name || ""}`.trim());
    }
    if (bundle.hotel) {
        parts.push(`${t("summarize.stay")}: ${bundle.hotel.name || ""}`.trim());
    }
    return parts.join(" | ") || t("chat.summaryDefault");
}

// Manual wizard: one step per part of the journey (flight -> train -> stay ->
// review). Steps adapt to what's available; multimodal trips keep both transport
// steps. Confirm commits the manual selection.

function flightOption(flight, currency, selected, tripDate) {
    const segs = flight.segments || [];
    const last = segs[segs.length - 1] || {};
    const layovers = flightLayovers(flight);
    const stops = Number(flight.stops ?? (segs.length > 1 ? segs.length - 1 : 0));
    const stopsChip = stops > 0 ? t("flight.stopsCount").replace("{n}", String(stops)) : t("flight.nonstop");
    const layoverChips = layovers.length
        ? `<span class="wizard-option__via"><i class="ri-flight-land-line"></i> ${escapeHtml(t("flight.layover"))}: ${escapeHtml(layovers.map((l) => `${l.where}${l.wait ? ` (${l.wait})` : ""}`).join(", "))}</span>`
        : "";
    return optionShell(selected, `
        <div class="wizard-option__head">
            <strong>${escapeHtml(flight.airline || t("card.flight"))}</strong>
            <span class="wizard-option__tag">${escapeHtml(flight.flight_no || t("common.na"))}</span>
        </div>
        <div class="wizard-option__route">
            <span><b>${escapeHtml(flight.departure || "--:--")}</b><small>${escapeHtml(segLabel(segs[0], "origin") || t("card.origin"))}</small></span>
            <span class="wizard-option__dur"><i class="ri-arrow-right-line"></i>${escapeHtml(flight.duration || "")}</span>
            <span><b>${escapeHtml(flight.arrival || "--:--")}</b><small>${escapeHtml(segLabel(last, "destination") || t("card.destination"))}</small></span>
        </div>
        <div class="wizard-option__chips">
            ${tripDate ? `<span>${escapeHtml(tripDate)}</span>` : ""}
            <span>${escapeHtml(stopsChip)}</span>
        </div>
        ${layoverChips}
    `, formatPrice(flight.price, currency));
}

function trainOption(train, currency, selected) {
    return optionShell(selected, `
        <div class="wizard-option__head">
            <strong>${escapeHtml(train.name || t("card.train"))}</strong>
            <span class="wizard-option__tag">${escapeHtml(train.train_no || t("common.na"))}</span>
        </div>
        <div class="wizard-option__route">
            <span><b>${escapeHtml(train.departure || "--:--")}</b><small>${escapeHtml(train.source || t("card.origin"))}</small></span>
            <span class="wizard-option__dur"><i class="ri-arrow-right-line"></i>${escapeHtml(train.duration || "")}</span>
            <span><b>${escapeHtml(train.arrival || "--:--")}</b><small>${escapeHtml(train.destination || t("card.destination"))}</small></span>
        </div>
        <div class="wizard-option__chips"><span>${escapeHtml(train.class || t("common.na"))}</span><span>${escapeHtml(train.status || t("card.availabilityUnknown"))}</span></div>
    `, formatPrice(train.fare, currency));
}

function stayOption(hotel, currency, selected) {
    const img = escapeHtml(hotel.image || PLACEHOLDER_IMG);
    return optionShell(selected, `
        <div class="wizard-option__stay">
            <img src="${img}" alt="${escapeHtml(hotel.name || t("card.hotelImageAlt"))}" loading="lazy" onerror="this.onerror=null;this.src='${PLACEHOLDER_IMG}'">
            <div>
                <strong>${escapeHtml(hotel.name || t("common.na"))}</strong>
                <p class="results-subtle">${escapeHtml(hotel.location || t("common.na"))}</p>
                <div class="wizard-option__chips">
                    <span>${escapeHtml(`${t("card.rating")}: ${hotel.rating ?? t("common.na")}`)}</span>
                    <span>${escapeHtml(`${t("card.stars")}: ${hotel.stars ?? t("common.na")}`)}</span>
                </div>
            </div>
        </div>
    `, formatPrice(hotel.price, currency));
}

function optionShell(selected, main, price) {
    return `
        <div class="wizard-option__main">${main}</div>
        <div class="wizard-option__side">
            <span class="wizard-option__price">${escapeHtml(price)}</span>
            <span class="wizard-option__check"><i class="ri-checkbox-circle-fill"></i> ${escapeHtml(selected ? t("wizard.selected") : t("wizard.select"))}</span>
        </div>`;
}

// Parses a "YYYY-MM-DD"/"DD-MM-YYYY" date with an "HH:MM" time into a Date.
function parseDateTime(dateStr, timeStr) {
    if (!dateStr) {
        return null;
    }
    let y;
    let m;
    let d;
    let match = String(dateStr).match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
    if (match) {
        y = Number(match[1]); m = Number(match[2]); d = Number(match[3]);
    } else {
        match = String(dateStr).match(/^(\d{1,2})-(\d{1,2})-(\d{4})/);
        if (match) {
            d = Number(match[1]); m = Number(match[2]); y = Number(match[3]);
        }
    }
    if (!y) {
        return null;
    }
    const tm = String(timeStr || "").match(/(\d{1,2}):(\d{2})/);
    return new Date(y, m - 1, d, tm ? Number(tm[1]) : 0, tm ? Number(tm[2]) : 0);
}

// When a flight feeds a train (multimodal), the onward train must depart after
// the flight lands. abs_arrival is the flight's absolute arrival timestamp.
function flightArrival(flight) {
    const raw = flight?.abs_arrival;
    if (!raw) {
        return null;
    }
    const dt = new Date(raw);
    if (!Number.isNaN(dt.getTime())) {
        return dt;
    }
    const m = String(raw).match(/(\d{4})-(\d{1,2})-(\d{1,2})[T ](\d{1,2}):(\d{2})/);
    return m ? new Date(+m[1], +m[2] - 1, +m[3], +m[4], +m[5]) : null;
}

function trainDepartsBefore(train, arrival) {
    if (!arrival) {
        return false;
    }
    const dep = parseDateTime(train.departure_date, train.departure);
    return dep ? dep.getTime() < arrival.getTime() : false;
}

function skeletonCards(n = 3) {
    return Array.from({ length: n }, () => `<div class="wizard-option wizard-option--skeleton" aria-hidden="true"><span></span><span></span></div>`).join("");
}

function initWizard(container, results, currency, selection, tripDate, handlers, opts = {}) {
    const progressive = opts.progressive === true;
    const jobId = opts.jobId;

    // Live readers: in progressive mode trains arrive after a flight is chosen and
    // hotels stream in via polling, so never capture these once.
    const liveFlights = () => getFlights(results);
    const liveTrains = () => results.trains || [];
    const liveHotels = () => results.hotels || [];
    const hotelsLoading = () => progressive && !liveHotels().length && results._hotelsLoading;
    const trainsLoading = () => progressive && results._trainsLoading;

    // Genuinely multimodal = fly to a gateway THEN take an onward train.
    // Domestically flight & train are alternatives, shown as one "transport"
    // choice, never paired as legs.
    const isMultimodal = () => results.multimodal === true;
    let directTrainsFetched = false;

    const computeSteps = () => {
        const s = [];
        if (isMultimodal()) {
            if (liveFlights().length) s.push("flight");
            if (liveTrains().length || trainsLoading()) s.push("train");
        } else if (liveFlights().length || liveTrains().length || trainsLoading()) {
            s.push("transport");
        }
        s.push("stay");
        s.push("review");
        return s;
    };
    let steps = computeSteps();
    let step = 0;
    let trainsFetchedFor = null;
    // Step key -> the selection field it writes ("stay" step picks "hotel").
    const FIELD = { flight: "flight", train: "train", stay: "hotel", transport: "flight" };

    const recomputeSteps = () => {
        const current = steps[step];
        steps = computeSteps();
        const idx = steps.indexOf(current);
        step = idx >= 0 ? idx : Math.min(step, steps.length - 1);
    };

    const stepLabel = (key) => ({
        flight: t("wizard.stepFlight"),
        train: t("wizard.stepTrain"),
        transport: t("wizard.stepTransport"),
        stay: t("wizard.stepStay"),
        review: t("wizard.stepReview"),
    }[key]);

    const stepperHtml = () => `
        <ol class="wizard__steps">
            ${steps.map((key, i) => `
                <li class="wizard__step ${i === step ? "is-active" : ""} ${i < step ? "is-done" : ""}">
                    <span class="wizard__step-dot">${i < step ? '<i class="ri-check-line"></i>' : i + 1}</span>
                    <span class="wizard__step-label">${escapeHtml(stepLabel(key))}</span>
                </li>
            `).join("")}
        </ol>`;

    const innerFor = (key, item, isSel) => {
        if (key === "flight") return flightOption(item, currency, isSel, formatTripDate(tripDate));
        if (key === "train") return trainOption(item, currency, isSel);
        return stayOption(item, currency, isSel);
    };
    const optionButton = (key, idx, isSel, item, blocked) => {
        const note = blocked
            ? `<p class="wizard-option__warn"><i class="ri-time-line"></i> ${escapeHtml(t("wizard.beforeFlight"))}</p>`
            : "";
        return `<button type="button" class="wizard-option wizard-option--${key} ${isSel ? "is-selected" : ""} ${blocked ? "is-disabled" : ""}" data-step="${key}" data-idx="${idx}" aria-pressed="${isSel}" ${blocked ? 'disabled aria-disabled="true"' : ""}>${innerFor(key, item, isSel)}${note}</button>`;
    };
    const stepHeading = (title) => `
        <div class="section-heading section-heading--compact">
            <p class="eyebrow">${escapeHtml(t("wizard.eyebrow"))}</p>
            <h2>${escapeHtml(title)}</h2>
        </div>`;

    const renderStepBody = () => {
        const key = steps[step];
        if (key === "review") {
            const reviewBox = document.createElement("div");
            renderJourneyTimeline(reviewBox, selection, currency, results, { compact: true, date: tripDate });
            return `${stepHeading(t("wizard.reviewTitle"))}
                <p class="journey__intro">${escapeHtml(t("wizard.reviewIntro"))}</p>
                ${reviewBox.innerHTML}`;
        }

        // Single-mode: flight and train are alternatives, one combined step,
        // pick exactly one.
        if (key === "transport") {
            if (selection.flight && selection.train) {
                selection.train = null;
            }
            const fl = liveFlights();
            const tr = liveTrains();
            const flCards = fl.slice(0, 8).map((it, i) => optionButton("flight", i, selection.flight === it, it)).join("");
            const trCards = (trainsLoading() && !tr.length)
                ? skeletonCards(2)
                : tr.slice(0, 8).map((it, i) => optionButton("train", i, selection.train === it, it)).join("");
            return `${stepHeading(t("wizard.pickTransport"))}
                <p class="journey__intro">${escapeHtml(t("wizard.transportIntro"))}</p>
                ${fl.length ? `<p class="wizard__sub"><i class="ri-flight-takeoff-line"></i> ${escapeHtml(t("section.flights"))}</p><div class="wizard__options">${flCards}</div>` : ""}
                ${(tr.length || trainsLoading()) ? `<p class="wizard__sub"><i class="ri-train-line"></i> ${escapeHtml(t("section.trains"))}</p><div class="wizard__options">${trCards}</div>` : ""}`;
        }

        if (key === "train" && trainsLoading() && !liveTrains().length) {
            return `${stepHeading(t("wizard.pickTrain"))}
                <p class="wizard__note"><i class="ri-loader-4-line ri-spin"></i> ${escapeHtml(t("wizard.findingTrains"))}</p>
                <div class="wizard__options">${skeletonCards(3)}</div>`;
        }
        if (key === "stay" && hotelsLoading()) {
            return `${stepHeading(t("wizard.pickStay"))}
                <p class="wizard__note"><i class="ri-loader-4-line ri-spin"></i> ${escapeHtml(t("wizard.loadingStays"))}</p>
                <div class="wizard__options">${skeletonCards(3)}</div>`;
        }

        const config = {
            flight: { items: liveFlights(), title: t("wizard.pickFlight"), empty: t("wizard.noFlights") },
            train: { items: liveTrains(), title: t("wizard.pickTrain"), empty: t("wizard.noTrains") },
            stay: { items: liveHotels(), title: t("wizard.pickStay"), empty: t("empty.noHotels") },
        }[key];

        // Multimodal gating: trains that depart before the chosen flight lands are
        // shown but greyed out and can't be selected.
        const arrival = key === "train" ? flightArrival(selection.flight) : null;
        if (key === "train" && arrival) {
            const stillValid = selection.train && !trainDepartsBefore(selection.train, arrival);
            if (!stillValid) {
                selection.train = config.items.find((tr) => !trainDepartsBefore(tr, arrival)) || null;
            }
        }

        const selectedItem = selection[FIELD[key]];
        const cards = config.items.slice(0, 12).map((item, i) =>
            optionButton(key, i, item === selectedItem, item, key === "train" && trainDepartsBefore(item, arrival))).join("");

        const hint = key === "train" && arrival
            ? `<p class="wizard__note"><i class="ri-information-line"></i> ${escapeHtml(t("wizard.trainGateHint"))}</p>`
            : "";

        return `${stepHeading(config.title)}
            ${hint}
            <div class="wizard__options">${cards || `<article class="trip-card"><p>${escapeHtml(config.empty)}</p></article>`}</div>`;
    };

    const doFetchTrains = async (flight) => {
        try {
            const r = await travelApi.trainsForFlight({ job_id: jobId, flight: flight || null });
            results.trains = r.data?.trains || [];
            if (r.data?.transfer) {
                results.transfer = r.data.transfer;
            } else {
                delete results.transfer;
            }
            results.rail_hub = r.data?.rail_hub || null;
            results.flight_arrival_iso = r.data?.flight_arrival_iso || results.flight_arrival_iso;
        } catch (error) {
            results.trains = [];
        } finally {
            results._trainsLoading = false;
        }
    };

    // Single-mode manual: trains are deferred by the worker but they're an
    // ALTERNATIVE to the flight (not flight-dependent), so fetch them once for
    // the combined transport step.
    const fetchDirectTrains = async () => {
        if (directTrainsFetched || !jobId) {
            return;
        }
        directTrainsFetched = true;
        results._trainsLoading = true;
        recomputeSteps();
        if (steps[step] === "transport") {
            render();
        }
        await doFetchTrains(null);
        recomputeSteps();
        render();
    };

    const render = () => {
        const isReview = steps[step] === "review";
        container.innerHTML = `
            ${stepperHtml()}
            <div class="wizard__body">${renderStepBody()}</div>
            <div class="wizard__nav">
                <button type="button" class="ghost-button" data-wizard="back" ${step === 0 ? "disabled" : ""}>
                    <i class="ri-arrow-left-line"></i> ${escapeHtml(t("wizard.back"))}
                </button>
                ${isReview
                    ? `<button type="button" class="primary-button" data-wizard="confirm"><i class="ri-save-3-line"></i> ${escapeHtml(t("wizard.confirm"))}</button>`
                    : `<button type="button" class="primary-button" data-wizard="next">${escapeHtml(t("wizard.next"))} <i class="ri-arrow-right-line"></i></button>`}
            </div>`;

        container.querySelectorAll(".wizard-option").forEach((btn) => {
            if (btn.classList.contains("wizard-option--skeleton")) {
                return;
            }
            btn.addEventListener("click", () => {
                const key = btn.dataset.step;
                const idx = Number(btn.dataset.idx);
                const map = { flight: liveFlights(), train: liveTrains(), stay: liveHotels() }[key];
                selection[FIELD[key]] = map[idx];
                // Single-mode: picking one transport clears the other.
                if (!isMultimodal()) {
                    if (key === "flight") selection.train = null;
                    if (key === "train") selection.flight = null;
                }
                render();
            });
        });

        const back = container.querySelector('[data-wizard="back"]');
        const next = container.querySelector('[data-wizard="next"]');
        const confirm = container.querySelector('[data-wizard="confirm"]');
        if (back) back.addEventListener("click", () => { if (step > 0) { step -= 1; render(); } });
        if (next) {
            next.addEventListener("click", async () => {
                // Multimodal: leaving the Flight step triggers the onward-train
                // fetch, showing the Train step's skeleton until it resolves.
                if (progressive && isMultimodal() && steps[step] === "flight"
                        && selection.flight && trainsFetchedFor !== selection.flight) {
                    trainsFetchedFor = selection.flight;
                    selection.train = null;
                    results._trainsLoading = true;
                    recomputeSteps();
                    const ti = steps.indexOf("train");
                    if (ti >= 0) { step = ti; render(); }
                    await doFetchTrains(selection.flight);
                    recomputeSteps();
                    render();
                    return;
                }
                if (step < steps.length - 1) { step += 1; render(); }
            });
        }
        if (confirm) {
            confirm.addEventListener("click", async () => {
                confirm.disabled = true;
                const original = confirm.innerHTML;
                confirm.innerHTML = `<i class="ri-loader-4-line ri-spin"></i> ${t("results.saving")}`;
                try {
                    await handlers.onConfirm(selection);
                    renderFinal();
                } catch (error) {
                    const msg = (error.message || "").toLowerCase();
                    if (msg.includes("log in") || msg.includes("unauthorized") || msg.includes("unauthenticated")) {
                        window.location.href = "/auth";
                        return;
                    }
                    confirm.innerHTML = original;
                    confirm.disabled = false;
                }
            });
        }
    };

    // Final confirmed page: chosen legs + destination as a full journey timeline
    // (the Quick Pick look), with Edit + Save.
    const renderFinal = () => {
        const box = document.createElement("div");
        renderJourneyTimeline(box, selection, currency, results, { date: tripDate, footer: false });
        const placesBox = document.createElement("div");
        renderItineraryCards(placesBox, results.itinerary || []);
        container.innerHTML = `
            <div class="section-heading section-heading--compact">
                <p class="eyebrow">${escapeHtml(t("wizard.finalEyebrow"))}</p>
                <h2>${escapeHtml(t("wizard.finalTitle"))}</h2>
            </div>
            <p class="wizard__hint"><i class="ri-checkbox-circle-fill"></i> ${escapeHtml(t("wizard.confirmedHint"))}</p>
            ${box.innerHTML}
            <div class="wizard__nav">
                <button type="button" class="ghost-button" data-wizard="edit"><i class="ri-arrow-left-line"></i> ${escapeHtml(t("wizard.edit"))}</button>
                <button type="button" class="primary-button" data-wizard="save"><i class="ri-save-3-line"></i> ${escapeHtml(t("results.saveTrip"))}</button>
            </div>
            <section class="itinerary-section">
                <div class="section-heading section-heading--compact">
                    <p class="eyebrow">${escapeHtml(t("results.itineraryEyebrow"))}</p>
                    <h2>${escapeHtml(t("results.itineraryTitle"))}</h2>
                </div>
                <div class="itinerary-grid">${placesBox.innerHTML}</div>
            </section>`;
        container.querySelector('[data-wizard="edit"]').addEventListener("click", () => render());
        const save = container.querySelector('[data-wizard="save"]');
        save.addEventListener("click", async () => {
            save.disabled = true;
            const orig = save.innerHTML;
            save.innerHTML = `<i class="ri-loader-4-line ri-spin"></i> ${t("results.saving")}`;
            try {
                await handlers.onSave(selection);
                save.innerHTML = `<i class="ri-check-line"></i> ${t("results.saved")}`;
                save.classList.add("is-saved");
            } catch (error) {
                const msg = (error.message || "").toLowerCase();
                if (msg.includes("log in") || msg.includes("unauthorized") || msg.includes("unauthenticated")) {
                    window.location.href = "/auth";
                    return;
                }
                save.innerHTML = orig;
                save.disabled = false;
            }
        });
    };

    // Reopening a confirmed trip jumps straight to the final page.
    if (opts.startFinal) {
        renderFinal();
    } else {
        render();
        // Single-mode manual defers trains; fetch them once for the transport step.
        if (progressive && !isMultimodal() && !liveTrains().length) {
            fetchDirectTrains();
        }
    }
    // Refresh so external streaming updates (hotels arriving) re-render in place.
    return { refresh: () => { recomputeSteps(); render(); } };
}

// Trip assistant chat: only the selected trip is used as context.

function renderMarkdown(text) {
    if (window.marked && window.DOMPurify) {
        return window.DOMPurify.sanitize(window.marked.parse(text || ""));
    }
    return `<p>${escapeHtml(text)}</p>`;
}

function appendChatMessage(container, role, text) {
    const isAssistant = role === "assistant";
    const author = isAssistant ? t("chat.title") : t("chat.you");
    const icon = isAssistant ? "ri-sparkling-2-line" : "ri-user-3-line";
    const content = isAssistant ? renderMarkdown(text) : `<p>${escapeHtml(text)}</p>`;
    container.insertAdjacentHTML("beforeend", `
        <article class="trip-chat-message ${isAssistant ? "trip-chat-message--assistant" : "trip-chat-message--user"}">
            <div class="trip-chat-message__avatar"><i class="${icon}"></i></div>
            <div class="trip-chat-message__bubble">
                <p class="trip-chat-message__author">${author}</p>
                <div class="trip-chat-message__markdown">${content}</div>
            </div>
        </article>
    `);
    container.scrollTop = container.scrollHeight;
}

// Chat history is namespaced by the trip it belongs to (job id for a live
// search, saved-trip id for a reopened trip). Loading with a different key
// returns nothing — so a NEW itinerary never shows the previous trip's chat.
function chatKeyFor(ctx) {
    if (ctx.savedTripId) return `saved:${ctx.savedTripId}`;
    if (ctx.jobId) return `job:${ctx.jobId}`;
    return "adhoc";
}

function loadTripChatHistory(key) {
    const stored = getStoredJson(STORAGE_KEYS.tripChatHistory);
    if (stored && stored.key === key && Array.isArray(stored.messages)) {
        return stored.messages.filter((m) => m?.content);
    }
    return [];
}

function saveTripChatHistory(key, messages) {
    setStoredJson(STORAGE_KEYS.tripChatHistory, { key, messages });
}

// Assistant "typing…" bubble shown while the reply is in flight.
function appendTypingIndicator(container) {
    container.insertAdjacentHTML("beforeend", `
        <article class="trip-chat-message trip-chat-message--assistant" data-typing>
            <div class="trip-chat-message__avatar"><i class="ri-sparkling-2-line"></i></div>
            <div class="trip-chat-message__bubble">
                <div class="trip-chat-typing" aria-label="${escapeHtml(t("chat.typing"))}">
                    <span></span><span></span><span></span>
                </div>
            </div>
        </article>
    `);
    container.scrollTop = container.scrollHeight;
    return container.querySelector("[data-typing]");
}

// Wires the trip-assistant chat widget. Shared by the search-results flow and
// the read-only saved-trip view. Chat context lives server-side in the session.
// ctx: { summaryText, jobId, savedTripId, initialHistory }.
function setupTripChat(ctx = {}) {
    const toggle = document.getElementById("trip-chat-toggle");
    const widget = document.getElementById("trip-chat-widget");
    const closeBtn = document.getElementById("trip-chat-close");
    const clearBtn = document.getElementById("trip-chat-clear");
    const summary = document.getElementById("trip-chat-summary");
    const thread = document.getElementById("trip-chat-thread");
    const form = document.getElementById("trip-chat-form");
    const input = document.getElementById("trip-chat-input");
    const submit = document.getElementById("trip-chat-submit");
    if (!toggle || !widget || !form) {
        return;
    }
    if (ctx.summaryText) {
        summary.textContent = ctx.summaryText;
    }
    const key = chatKeyFor(ctx);
    const savedTripId = ctx.savedTripId || null;
    const intro = thread.innerHTML;

    // Server-provided history (saved trip) wins; otherwise use the namespaced
    // local cache. A mismatched key yields [], clearing any stale conversation.
    let chatHistory = Array.isArray(ctx.initialHistory) && ctx.initialHistory.length
        ? ctx.initialHistory.filter((m) => m?.content)
        : loadTripChatHistory(key);
    if (chatHistory.length) {
        thread.innerHTML = "";
        chatHistory.forEach((m) => appendChatMessage(thread, m.role, m.content));
    }
    saveTripChatHistory(key, chatHistory);

    const persist = () => {
        saveTripChatHistory(key, chatHistory);
        // A reopened saved trip also persists ongoing chat to the account.
        if (savedTripId) {
            userApi.updateTripChat({ trip_id: savedTripId, chat_history: chatHistory }).catch(() => {});
        }
    };

    const setOpen = (open) => {
        widget.hidden = !open;
        toggle.setAttribute("aria-expanded", open ? "true" : "false");
    };
    toggle.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); setOpen(widget.hidden); });
    closeBtn.addEventListener("click", (e) => { e.preventDefault(); e.stopPropagation(); setOpen(false); });
    document.addEventListener("keydown", (e) => { if (e.key === "Escape" && !widget.hidden) setOpen(false); });
    document.addEventListener("click", (e) => {
        if (!widget.hidden && !widget.contains(e.target) && !toggle.contains(e.target)) setOpen(false);
    });

    if (clearBtn) {
        clearBtn.addEventListener("click", async (e) => {
            e.preventDefault();
            e.stopPropagation();
            chatHistory = [];
            thread.innerHTML = intro;
            persist();
            travelApi.resetChat().catch(() => {});
        });
    }

    // Enter sends; Shift+Enter inserts a newline. Ignore while an IME is
    // composing (e.g. typing in an Indic/CJK language) so it doesn't send early.
    input.addEventListener("keydown", (e) => {
        if (e.key === "Enter" && !e.shiftKey && !e.isComposing) {
            e.preventDefault();
            form.requestSubmit();
        }
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const message = input.value.trim();
        if (!message) {
            return;
        }
        appendChatMessage(thread, "user", message);
        chatHistory = [...chatHistory, { role: "user", content: message }];
        persist();
        input.value = "";
        submit.disabled = true;
        const typing = appendTypingIndicator(thread);
        try {
            const response = await travelApi.chat({ message, language: getCurrentLanguage() });
            const rp = response.data?.response;
            const reply = Array.isArray(rp)
                ? rp.map((i) => i?.text || "").join("\n\n")
                : (rp?.text || rp || t("chat.unavailable"));
            typing.remove();
            appendChatMessage(thread, "assistant", reply);
            chatHistory = [...chatHistory, { role: "assistant", content: reply }];
            persist();
        } catch (error) {
            typing.remove();
            const fb = error.message || t("chat.unavailable");
            appendChatMessage(thread, "assistant", fb);
            chatHistory = [...chatHistory, { role: "assistant", content: fb }];
            persist();
        } finally {
            submit.disabled = false;
        }
    });
}

// Read-only view of a trip opened from the dashboard: the journey timeline +
// places, plus the assistant (session already scoped to this trip server-side).
function initSavedTripView(trip, meta = {}) {
    const segments = trip.segments || {};
    const bundle = { flight: segments.flight, train: segments.train, hotel: segments.hotel };
    const view = {
        destination: trip.destination,
        currency: trip.currency || "",
        transfer: trip.transfer,
        rail_hub: trip.rail_hub,
        itinerary: Array.isArray(trip.itinerary) ? trip.itinerary : [],
        multimodal: trip.multimodal,
    };
    const titleEl = document.getElementById("results-title");
    const subtitleEl = document.getElementById("results-subtitle");
    if (titleEl) {
        titleEl.textContent = `${placeName(trip.source)} → ${placeName(trip.destination)}`;
    }
    if (subtitleEl) {
        subtitleEl.textContent = t("results.savedTrip");
    }
    // Saved trips are read-only, so hide the search-only controls entirely.
    document.querySelector(".results-actions")?.setAttribute("hidden", "");
    const customizeView = document.getElementById("customize-view");
    if (customizeView) customizeView.hidden = true;
    const quickpickView = document.getElementById("quickpick-view");
    if (quickpickView) quickpickView.hidden = false;

    renderJourneyTimeline(document.getElementById("journey-timeline"), bundle, view.currency, view, { footer: false });
    renderItineraryCards(document.getElementById("itinerary-grid"), view.itinerary);
    setupTripChat({
        summaryText: summarizeBundle(bundle),
        savedTripId: meta.tripId || null,
        initialHistory: meta.chatHistory || [],
    });
    refreshReveal();
}

function placeName(loc) {
    if (loc && typeof loc === "object") {
        return loc.city || loc.formatted || loc.name || "";
    }
    return loc || "";
}

function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

// Manual/progressive: poll the job until completed, streaming hotels (and, for
// the no-flight case, server-resolved trains) into the live results + wizard.
async function pollManualUpdates(jobId, results, wizard) {
    for (let i = 0; i < 45; i += 1) {
        await sleep(2000);
        let resp;
        try {
            resp = await travelApi.getSearchStatus(jobId);
        } catch (error) {
            continue;
        }
        const job = resp.data || {};
        const r = job.results || {};
        let changed = false;
        if ((r.hotels || []).length && !(results.hotels || []).length) {
            results.hotels = r.hotels;
            results._hotelsLoading = false;
            changed = true;
        }
        // No-flight destinations: trains/transfer are resolved server-side.
        if ((r.trains || []).length && !(results.trains || []).length && !getFlights(results).length) {
            results.trains = r.trains;
            if (r.transfer) results.transfer = r.transfer;
            results.rail_hub = r.rail_hub || results.rail_hub;
            changed = true;
        }
        const done = (job.status || resp.job_status) === "completed";
        if (done && (r.hotels || []).length && !(results.hotels || []).length) {
            results.hotels = r.hotels;
            changed = true;
        }
        if (done) {
            results._hotelsLoading = false;
            changed = true;
        }
        if (changed) {
            wizard.refresh();
        }
        if (done) {
            break;
        }
    }
    results._hotelsLoading = false;
    wizard.refresh();
}

export function initResultsPage() {
    // A trip opened from the dashboard renders read-only (no search job).
    const savedView = getStoredJson(STORAGE_KEYS.savedTripView);
    if (savedView) {
        removeStoredValue(STORAGE_KEYS.savedTripView);
        // Shape: { trip, trip_id, chat_history }; tolerate a bare itinerary.
        const trip = savedView.trip || savedView;
        initSavedTripView(trip, {
            tripId: savedView.trip_id || null,
            chatHistory: savedView.chat_history || [],
        });
        return;
    }

    const searchPayload = getSearchRequest();
    const storedResults = getSearchResults();
    const selectionMode = getStoredValue(STORAGE_KEYS.lastSelectionMode) || "quickpick";

    if (!searchPayload || !storedResults?.data?.results) {
        window.location.href = "/";
        return;
    }

    const results = storedResults.data.results;
    const jobId = storedResults.data.job_id;
    const preference = searchPayload.preferences || "Comfort";
    const currency = results.currency || "";
    // Manual jobs may still be streaming hotels when the page loads; quick-pick
    // jobs always arrive complete.
    const isManual = storedResults.data.mode === "manual";
    const jobCompleted = (storedResults.data.status || storedResults.job_status) === "completed";

    const titleEl = document.getElementById("results-title");
    const subtitleEl = document.getElementById("results-subtitle");
    const quickpickView = document.getElementById("quickpick-view");
    const customizeView = document.getElementById("customize-view");
    const journeyTimeline = document.getElementById("journey-timeline");
    const wizardEl = document.getElementById("wizard");
    const itineraryGrid = document.getElementById("itinerary-grid");
    const tripChatToggle = document.getElementById("trip-chat-toggle");
    const tripChatWidget = document.getElementById("trip-chat-widget");
    const tripChatClose = document.getElementById("trip-chat-close");
    const tripChatSummary = document.getElementById("trip-chat-summary");
    const tripChatThread = document.getElementById("trip-chat-thread");
    const tripChatForm = document.getElementById("trip-chat-form");
    const tripChatInput = document.getElementById("trip-chat-input");
    const tripChatSubmit = document.getElementById("trip-chat-submit");
    const saveTripBtn = document.getElementById("save-trip-btn");

    const hasTransport = getFlights(results).length > 0 || (results.trains || []).length > 0;
    const quickBundle = chooseQuickPick(results, preference);

    renderResultsHeader(titleEl, subtitleEl, searchPayload, results);
    renderItineraryCards(itineraryGrid, results.itinerary || []);

    // Quick Pick shows the auto-bundle timeline; manual is the wizard only.
    if (!isManual) {
        if (hasTransport) {
            renderJourneyTimeline(journeyTimeline, quickBundle, currency, results, { date: searchPayload.date });
        } else {
            renderNoOptions(journeyTimeline, results);
        }
    } else {
        results._hotelsLoading = !((results.hotels || []).length) && !jobCompleted;
    }

    const manualSelection = {
        flight: getFlights(results)[0] || null,
        train: (results.trains || [])[0] || null,
        hotel: (results.hotels || [])[0] || null,
    };

    let activeMode = "quickpick";

    // Commit a selection to the backend (sets the session trip used as chat
    // context). Not the same as saving to the account.
    const syncSelection = async (mode) => {
        try {
            const response = await travelApi.selectTrip(buildSelectionPayload(mode, jobId, preference, manualSelection));
            const trip = response.data?.trip;
            if (trip) {
                setStoredJson(STORAGE_KEYS.selectedTrip, trip);
            }
            tripChatSummary.textContent = summarizeBundle(
                mode === "quickpick" ? quickBundle : manualSelection
            );
            return trip;
        } catch (error) {
            tripChatSummary.textContent = error.message || t("chat.contextUnavailable");
            throw error;
        }
    };

    const buttons = Array.from(document.querySelectorAll("[data-results-mode]"));
    const animateView = (el) => {
        el.classList.remove("view-anim");
        void el.offsetWidth;
        el.classList.add("view-anim");
    };
    const setMode = (mode) => {
        activeMode = mode;
        setStoredValue(STORAGE_KEYS.lastSelectionMode, mode);
        quickpickView.hidden = mode !== "quickpick";
        customizeView.hidden = mode !== "manual";
        animateView(mode === "quickpick" ? quickpickView : customizeView);
        buttons.forEach((item) => {
            const on = item.dataset.resultsMode === mode;
            item.classList.toggle("is-active", on);
            item.setAttribute("aria-pressed", on ? "true" : "false");
        });
        if (mode === "quickpick") {
            syncSelection("quickpick").catch(() => {});
        }
    };

    buttons.forEach((button) => {
        button.addEventListener("click", () => setMode(button.dataset.resultsMode));
    });
    // A manual search has no auto Quick Pick bundle, so hide the toggle.
    if (isManual) {
        document.querySelector(".mode-switch")?.setAttribute("hidden", "");
    }
    // The timeline footer's "Customize this trip" button also carries
    // data-results-mode="manual"; bind such buttons rendered after init.
    document.addEventListener("click", (event) => {
        const trigger = event.target.closest('[data-results-mode="manual"]');
        if (trigger && activeMode !== "manual") {
            setMode("manual");
        }
    });

    // Remember a confirmed manual trip (tagged with this job) so reopening
    // results shows the built trip instead of restarting the wizard.
    const rememberConfirmed = (selection) => {
        setStoredJson(STORAGE_KEYS.confirmedTrip, {
            jobId, flight: selection.flight, train: selection.train, hotel: selection.hotel,
        });
        // Persist the enriched results (on-demand trains + cab) so a reload
        // restores the SAME trip, cab included.
        try {
            setStoredJson(STORAGE_KEYS.lastSearchResults, storedResults);
        } catch (error) {
            /* storage quota */
        }
    };
    const wizardHandlers = {
        // Confirm only commits the selection (sets chat context); it does NOT save.
        onConfirm: async (selection) => {
            await travelApi.selectTrip(buildSelectionPayload("manual", jobId, preference, selection));
            rememberConfirmed(selection);
            tripChatSummary.textContent = summarizeBundle(selection);
        },
        // Save persists to the account (explicit action on the final page).
        onSave: async (selection) => {
            await travelApi.selectTrip(buildSelectionPayload("manual", jobId, preference, selection));
            await userApi.saveTrip();
            rememberConfirmed(selection);
            tripChatSummary.textContent = summarizeBundle(selection);
        },
    };

    // Restore a previously confirmed trip for this job so reopening shows the
    // built trip, not the wizard again.
    const confirmed = getStoredJson(STORAGE_KEYS.confirmedTrip);
    const restoreConfirmed = isManual && confirmed && confirmed.jobId === jobId
        ? { flight: confirmed.flight, train: confirmed.train, hotel: confirmed.hotel }
        : null;
    if (restoreConfirmed) {
        manualSelection.flight = restoreConfirmed.flight;
        manualSelection.train = restoreConfirmed.train;
        manualSelection.hotel = restoreConfirmed.hotel;
    }

    // Manual mode with nothing to travel on: show the no-options notice + places
    // inside the wizard area.
    const manualNoOptions = isManual && jobCompleted
        && !getFlights(results).length && !(results.trains || []).length;

    if (manualNoOptions) {
        renderNoOptions(wizardEl, results);
        const placesBox = document.createElement("div");
        renderItineraryCards(placesBox, results.itinerary || []);
        wizardEl.insertAdjacentHTML("beforeend", `
            <section class="itinerary-section">
                <div class="section-heading section-heading--compact">
                    <p class="eyebrow">${t("results.itineraryEyebrow")}</p>
                    <h2>${t("results.itineraryTitle")}</h2>
                </div>
                <div class="itinerary-grid">${placesBox.innerHTML}</div>
            </section>`);
    } else if (hasTransport || (results.hotels || []).length || isManual) {
        // The wizard mutates manualSelection in place; in manual mode it's
        // progressive (trains per chosen flight, hotels stream in).
        const wizard = initWizard(wizardEl, results, currency, manualSelection, searchPayload.date,
            wizardHandlers, { progressive: isManual, jobId, startFinal: Boolean(restoreConfirmed) });
        if (isManual && !jobCompleted) {
            pollManualUpdates(jobId, results, wizard);
        }
    }

    if (saveTripBtn) {
        saveTripBtn.addEventListener("click", async () => {
            const original = saveTripBtn.innerHTML;
            saveTripBtn.disabled = true;
            saveTripBtn.innerHTML = `<i class="ri-loader-4-line ri-spin"></i> ${t("results.saving")}`;
            try {
                await travelApi.selectTrip(buildSelectionPayload(activeMode, jobId, preference, manualSelection));
                await userApi.saveTrip();
                saveTripBtn.innerHTML = `<i class="ri-check-line"></i> ${t("results.saved")}`;
                saveTripBtn.classList.add("is-saved");
            } catch (error) {
                const msg = (error.message || "").toLowerCase();
                if (msg.includes("log in") || msg.includes("unauthorized") || msg.includes("unauthenticated")) {
                    window.location.href = "/auth";
                    return;
                }
                saveTripBtn.innerHTML = original;
                saveTripBtn.disabled = false;
                tripChatSummary.textContent = error.message || t("results.couldNotSave");
            }
        });
    }

    // Chat is namespaced to this job so a new search never shows stale messages.
    setupTripChat({ jobId });

    // Quick-pick mode syncs its selection so the assistant has trip context
    // immediately (setMode handles the sync).
    setMode(selectionMode === "manual" ? "manual" : "quickpick");

    refreshReveal();
}
