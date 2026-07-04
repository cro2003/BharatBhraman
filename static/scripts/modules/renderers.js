import { compactLocation, createFlightSummary, formatPrice } from "./formatters.js";
import { t } from "./i18n.js";

const PLACEHOLDER_IMG = "/static/img-placeholder.svg";

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

// Builds an <img> that always has alt text, lazy-loads, and falls back to a
// local placeholder when the source is empty or fails to load (no external
// placeholder dependency, no broken-image icons).
function imageTag(src, alt, className = "") {
    const safeSrc = escapeHtml(src || PLACEHOLDER_IMG);
    const safeAlt = escapeHtml(alt || "Image");
    const cls = className ? ` class="${className}"` : "";
    return `<img${cls} src="${safeSrc}" alt="${safeAlt}" loading="lazy" `
        + `onerror="this.onerror=null;this.src='${PLACEHOLDER_IMG}'">`;
}

function transferWarning(status) {
    if (status === "no_connection") return t("transfer.no_connection");
    if (status === "unverified") return t("transfer.unverified");
    return "";
}

// Pill linking to Google Maps. Prefers exact coordinates; else falls back to a
// text query — callers pass a SPECIFIC place query (e.g. "Bhopal Airport") so
// the pin lands on the right spot, not just the city centre.
export function mapBadge(label, coords) {
    let query;
    if (coords && coords.lat != null && coords.lon != null) {
        query = `${coords.lat},${coords.lon}`;
    } else {
        const text = String(label || "").trim();
        if (!text) {
            return "";
        }
        query = encodeURIComponent(text);
    }
    return `<a class="map-badge" href="https://www.google.com/maps/search/?api=1&query=${query}" `
        + `target="_blank" rel="noreferrer" title="${escapeHtml(t("map.open"))}">`
        + `<i class="ri-map-pin-line"></i>${escapeHtml(t("map.badge"))}</a>`;
}

// Formats a date string (YYYY-MM-DD or DD-MM-YYYY) as "DD Mon YYYY". Returns the
// input unchanged if it isn't a recognised date.
export function formatTripDate(value) {
    if (!value) {
        return "";
    }
    const s = String(value).trim();
    let y;
    let m;
    let d;
    let match = s.match(/^(\d{4})-(\d{1,2})-(\d{1,2})/);
    if (match) {
        [, y, m, d] = match.map(Number);
    } else {
        match = s.match(/^(\d{1,2})-(\d{1,2})-(\d{4})/);
        if (match) {
            d = Number(match[1]); m = Number(match[2]); y = Number(match[3]);
        }
    }
    if (!y || !m || !d) {
        return s;
    }
    const months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
    return `${String(d).padStart(2, "0")} ${months[m - 1]} ${y}`;
}

// Segment city label, falling back to the IATA code when the enriched city
// name isn't present in the provider payload.
export function segLabel(seg, end) {
    if (!seg) {
        return "";
    }
    return seg[`${end}City`] || seg[end] || "";
}

// Layovers/stops for a flight, parsed from each segment's `halt` text (covers
// both connections and en-route technical stops). The stop city lives inside the
// halt text; falls back to the segment's city. Returns [{where, wait}].
export function flightLayovers(flight) {
    const segs = flight?.segments || [];
    const out = [];
    segs.forEach((seg) => {
        const halt = String(seg.halt || "").trim();
        if (!halt) {
            return;
        }
        const whereMatch = halt.match(/\bat\s+([^|]+?)\s*(?:\||$)/i);
        const where = (whereMatch ? whereMatch[1].trim() : "") || segLabel(seg, "destination");
        let wait = (halt.match(/(\d+\s*h(?:\s*\d+\s*m)?|\d+\s*m)\b/i) || [])[1] || "";
        wait = wait.replace(/\s+/g, " ").replace(/^0h\s*/, "").trim();
        out.push({ where, wait });
    });
    return out;
}

function journeyPoint(label, time, place, mapLabel, date) {
    const dateLine = date ? `<span class="journey-point__date">${escapeHtml(date)}</span>` : "";
    return `
        <div class="journey-point">
            <p>${escapeHtml(label)}</p>
            <strong>${escapeHtml(time || "--:--")}</strong>
            ${dateLine}
            <span class="journey-point__place">${escapeHtml(place || "")}${mapBadge(mapLabel || place)}</span>
        </div>`;
}

// Vertical, step-by-step view of the chosen journey: each transport leg, the
// onward road transfer (for no-connectivity railheads), then the stay. This is
// the default Quick Pick view — the plan shown directly, not a comparison grid.
export function renderJourneyTimeline(container, bundle, currency, results, options = {}) {
    const compact = options.compact === true;
    const flight = bundle.flight;
    const train = bundle.train;
    const hotel = bundle.hotel;
    const transfer = results?.transfer;
    const warningText = transferWarning(results?.transfer_status || bundle.transfer_status);
    const legs = [];

    const dest = results?.destination || {};
    const destCity = dest.city || dest.formatted || dest.name || "";
    const destCoords = (dest.lat != null && dest.lon != null) ? { lat: dest.lat, lon: dest.lon } : null;
    const tripDate = formatTripDate(options.date);
    const airportQuery = (city) => (city ? `${city} Airport` : "");
    const stationQuery = (name) => (name ? `${name} Railway Station` : "");
    const hotelQuery = (h) => [h.name, h.location, destCity].filter(Boolean).join(", ");

    if (flight) {
        const segs = flight.segments || [];
        const last = segs[segs.length - 1] || {};
        const fromCity = segLabel(segs[0], "origin") || t("card.origin");
        const toCity = segLabel(last, "destination") || t("card.destination");
        const arrivalDate = formatTripDate(flight.abs_arrival) || tripDate;
        const layovers = flightLayovers(flight);
        const stops = Number(flight.stops ?? (segs.length > 1 ? segs.length - 1 : 0));
        const stopsChip = stops > 0
            ? t("flight.stopsCount").replace("{n}", String(stops))
            : t("flight.nonstop");
        const viaRow = layovers.length ? `
                    <div class="journey-leg__via">
                        <span class="journey-leg__via-label"><i class="ri-flight-land-line"></i> ${escapeHtml(t("flight.layover"))}</span>
                        ${layovers.map((l) => `<span class="journey-leg__layover">${escapeHtml(l.where || t("card.destination"))}${l.wait ? ` · ${escapeHtml(l.wait)}` : ""}</span>`).join("")}
                    </div>` : "";
        legs.push(`
            <li class="journey-leg journey-leg--flight">
                <span class="journey-leg__node"><i class="ri-flight-takeoff-line"></i></span>
                <article class="journey-leg__card">
                    <div class="journey-leg__top">
                        <div>
                            <p class="eyebrow">${escapeHtml(t("journey.legFlight"))}</p>
                            <h3>${escapeHtml(flight.airline || t("card.flight"))}</h3>
                        </div>
                        <span class="journey-leg__price">${escapeHtml(formatPrice(flight.price, currency))}</span>
                    </div>
                    <div class="journey-leg__points">
                        ${journeyPoint(t("journey.startAt"), flight.departure, fromCity, airportQuery(fromCity), tripDate)}
                        <span class="journey-leg__link"><i class="ri-flight-takeoff-line"></i>${escapeHtml(flight.duration || t("card.durationUnavailable"))}</span>
                        ${journeyPoint(t("journey.arriveAt"), flight.arrival, toCity, airportQuery(toCity), arrivalDate)}
                    </div>
                    ${viaRow}
                    <div class="journey-leg__chips">
                        <span>${escapeHtml(flight.flight_no || t("common.na"))}</span>
                        <span>${escapeHtml(stopsChip)}</span>
                    </div>
                </article>
            </li>`);
    }

    if (train) {
        const trainDate = formatTripDate(train.departure_date) || tripDate;
        const trainArrivalDate = formatTripDate(train.arrival_date) || trainDate;
        legs.push(`
            <li class="journey-leg journey-leg--train">
                <span class="journey-leg__node"><i class="ri-train-line"></i></span>
                <article class="journey-leg__card">
                    <div class="journey-leg__top">
                        <div>
                            <p class="eyebrow">${escapeHtml(t("journey.legTrain"))}</p>
                            <h3>${escapeHtml(train.name || t("card.train"))}</h3>
                        </div>
                        <span class="journey-leg__price">${escapeHtml(formatPrice(train.fare, currency))}</span>
                    </div>
                    <div class="journey-leg__points">
                        ${journeyPoint(t("journey.startAt"), train.departure, train.source || t("card.origin"), stationQuery(train.source), trainDate)}
                        <span class="journey-leg__link"><i class="ri-arrow-right-line"></i>${escapeHtml(train.duration || t("card.durationUnavailable"))}</span>
                        ${journeyPoint(t("journey.arriveAt"), train.arrival, train.destination || t("card.destination"), stationQuery(train.destination), trainArrivalDate)}
                    </div>
                    <div class="journey-leg__chips">
                        <span>${escapeHtml(train.train_no || t("common.na"))}</span>
                        <span>${escapeHtml(train.class || t("common.na"))}</span>
                        <span>${escapeHtml(train.status || t("card.availabilityUnknown"))}</span>
                    </div>
                </article>
            </li>`);
    }

    if (transfer && transfer.distance_km) {
        const note = t("journey.cabNote")
            .replace("{km}", String(transfer.distance_km))
            .replace("{from}", transfer.from || t("card.origin"))
            .replace("{to}", transfer.to || t("card.destination"));
        legs.push(`
            <li class="journey-leg journey-leg--cab">
                <span class="journey-leg__node"><i class="ri-taxi-line"></i></span>
                <article class="journey-leg__card journey-leg__card--cab">
                    <div class="journey-leg__top">
                        <div>
                            <p class="eyebrow">${escapeHtml(t("journey.legCab"))}</p>
                            <h3>${escapeHtml(note)}</h3>
                        </div>
                        <span class="journey-point__place">${escapeHtml(transfer.to || destCity || "")}${mapBadge(transfer.to || destCity, destCoords)}</span>
                    </div>
                </article>
            </li>`);
    }

    if (hotel) {
        legs.push(`
            <li class="journey-leg journey-leg--stay">
                <span class="journey-leg__node"><i class="ri-hotel-line"></i></span>
                <article class="journey-leg__card">
                    <div class="journey-leg__top">
                        <div>
                            <p class="eyebrow">${escapeHtml(t("journey.legStay"))}</p>
                            <h3>${escapeHtml(hotel.name || t("common.na"))}</h3>
                        </div>
                        <span class="journey-leg__price">${escapeHtml(formatPrice(hotel.price, currency))}</span>
                    </div>
                    <div class="journey-leg__stay">
                        ${imageTag(hotel.image, hotel.name || t("card.hotelImageAlt"))}
                        <div class="journey-leg__stay-copy">
                            <div class="journey-leg__chips">
                                <span>${escapeHtml(`${t("card.rating")}: ${hotel.rating ?? t("common.na")}`)}</span>
                                <span>${escapeHtml(`${t("card.stars")}: ${hotel.stars ?? t("common.na")}`)}</span>
                            </div>
                            <p class="results-subtle">${escapeHtml(hotel.location || t("common.na"))}${mapBadge(hotelQuery(hotel))}</p>
                            <a class="ghost-button journey-leg__cta" href="${escapeHtml(hotel.url || "#")}" ${hotel.url && hotel.url !== "#" ? 'target="_blank" rel="noreferrer"' : ""}>${escapeHtml(t("card.viewStay"))}</a>
                        </div>
                    </div>
                </article>
            </li>`);
    }

    if (!legs.length) {
        container.innerHTML = "";
        return;
    }

    const destLine = destCity
        ? `<p class="journey__dest"><i class="ri-map-pin-2-line"></i> ${escapeHtml(destCity)}${mapBadge(destCity, destCoords)}</p>`
        : "";
    const head = compact ? "" : `
            <div class="journey__head">
                <div>
                    <p class="eyebrow">${escapeHtml(t("journey.eyebrow"))}</p>
                    <h2>${escapeHtml(t("journey.title"))}</h2>
                    ${destLine}
                </div>
                <p class="journey__intro">${escapeHtml(t("journey.intro"))}</p>
            </div>`;
    const foot = (compact || options.footer === false) ? "" : `
            <div class="journey__foot">
                <button class="ghost-button" type="button" data-results-mode="manual">
                    <i class="ri-equalizer-3-line"></i> ${escapeHtml(t("journey.customize"))}
                </button>
            </div>`;

    container.innerHTML = `
        <section class="journey${compact ? " journey--compact" : ""}">
            ${head}
            ${warningText ? `<p class="travel-panel__warning" role="status"><i class="ri-error-warning-line"></i> ${escapeHtml(warningText)}</p>` : ""}
            <ol class="journey-timeline">${legs.join("")}</ol>
            ${foot}
        </section>`;
}

// Shown when neither flights nor trains exist for the date: a calm notice that
// invites trying another date, with the destination's places still below.
export function renderNoOptions(container, results) {
    const dest = results?.destination || {};
    const destCity = dest.city || dest.formatted || dest.name || "";
    const destCoords = (dest.lat != null && dest.lon != null) ? { lat: dest.lat, lon: dest.lon } : null;
    const destLine = destCity
        ? `<p class="journey__dest"><i class="ri-map-pin-2-line"></i> ${escapeHtml(destCity)}${mapBadge(destCity, destCoords)}</p>`
        : "";
    container.innerHTML = `
        <section class="journey journey--empty">
            <span class="journey__empty-icon"><i class="ri-calendar-close-line"></i></span>
            <div>
                <p class="eyebrow">${escapeHtml(t("noopts.eyebrow"))}</p>
                <h2>${escapeHtml(t("noopts.title"))}</h2>
                <p class="journey__intro">${escapeHtml(t("noopts.body"))}</p>
                ${destLine}
            </div>
        </section>`;
}

export function renderSuggestions(container, results, onSelect) {
    if (!container) {
        return;
    }

    if (!results.length) {
        container.classList.remove("is-visible");
        container.innerHTML = "";
        return;
    }

    container.innerHTML = results.map((item, index) => `
        <button type="button" data-index="${index}">
            ${escapeHtml(item.formatted || item.city || item.address_line1 || t("common.unknownPlace"))}
        </button>
    `).join("");
    container.classList.add("is-visible");

    container.querySelectorAll("button").forEach((button) => {
        button.addEventListener("click", () => {
            const picked = results[Number(button.dataset.index)];
            onSelect(picked);
        });
    });
}

export function renderResultsSummary(container, requestData, results) {
    const trains = results.trains || [];
    const flights = results.flights || results.hub_flight_fallback || [];
    const hotels = results.hotels || [];

    container.innerHTML = `
        <div class="summary-tile">
            <p>${escapeHtml(t("summary.route"))}</p>
            <h3>${escapeHtml(requestData.origin)} -> ${escapeHtml(requestData.destination)}</h3>
        </div>
        <div class="summary-tile">
            <p>${escapeHtml(t("summary.flightOptions"))}</p>
            <h3>${flights.length}</h3>
        </div>
        <div class="summary-tile">
            <p>${escapeHtml(t("summary.trainOptions"))}</p>
            <h3>${trains.length}</h3>
        </div>
        <div class="summary-tile">
            <p>${escapeHtml(t("summary.hotelOptions"))}</p>
            <h3>${hotels.length}</h3>
        </div>
    `;
}

export function renderBundlePreview(container, bundle, currency, mode, transferStatus) {
    const flight = bundle.flight;
    const train = bundle.train;
    const hotel = bundle.hotel;
    const flightSegments = flight?.segments || [];
    const finalFlightSegment = flightSegments[flightSegments.length - 1] || {};
    const segments = [];
    const warningText = transferWarning(transferStatus);

    if (flight) {
        segments.push(`
            <section class="travel-panel__card travel-panel__card--flight">
                <div class="travel-panel__header">
                    <div>
                        <p class="eyebrow">${escapeHtml(t("card.flight"))}</p>
                        <h3>${escapeHtml(createFlightSummary(flight))}</h3>
                    </div>
                    <span class="travel-panel__price">${escapeHtml(formatPrice(flight.price, currency))}</span>
                </div>
                <div class="travel-panel__route">
                    <div>
                        <p>${escapeHtml(t("card.departure"))}</p>
                        <strong>${escapeHtml(flight.departure || "--:--")}</strong>
                        <small>${escapeHtml(flightSegments[0]?.originCity || t("card.origin"))}</small>
                    </div>
                    <div class="travel-panel__route-mid">
                        <span>${escapeHtml(flight.duration || t("card.durationUnavailable"))}</span>
                        <small>${escapeHtml(t("card.stops"))}: ${escapeHtml(flight.stops ?? 0)}</small>
                    </div>
                    <div>
                        <p>${escapeHtml(t("card.arrival"))}</p>
                        <strong>${escapeHtml(flight.arrival || "--:--")}</strong>
                        <small>${escapeHtml(finalFlightSegment.destinationCity || t("card.destination"))}</small>
                    </div>
                </div>
                <div class="travel-panel__chips">
                    <span>${escapeHtml(flight.airline || t("common.na"))}</span>
                    <span>${escapeHtml(flight.flight_no || t("common.na"))}</span>
                </div>
                <p class="travel-panel__note">${escapeHtml(flightSegments.map((segment) => `${segment.originCity} -> ${segment.destinationCity}`).join(" | ") || t("card.directRoute"))}</p>
            </section>
        `);
    }

    if (train) {
        segments.push(`
            <section class="travel-panel__card travel-panel__card--train">
                <div class="travel-panel__header">
                    <div>
                        <p class="eyebrow">${escapeHtml(t("card.train"))}</p>
                        <h3>${escapeHtml(train.name || t("card.train"))}</h3>
                    </div>
                    <span class="travel-panel__price">${escapeHtml(formatPrice(train.fare, currency))}</span>
                </div>
                <div class="travel-panel__route">
                    <div>
                        <p>${escapeHtml(t("card.departure"))}</p>
                        <strong>${escapeHtml(train.departure || "--:--")}</strong>
                        <small>${escapeHtml(train.source || t("card.origin"))}</small>
                    </div>
                    <div class="travel-panel__route-mid">
                        <span>${escapeHtml(train.duration || t("card.durationUnavailable"))}</span>
                        <small>${escapeHtml(train.class || t("common.na"))}</small>
                    </div>
                    <div>
                        <p>${escapeHtml(t("card.arrival"))}</p>
                        <strong>${escapeHtml(train.arrival || "--:--")}</strong>
                        <small>${escapeHtml(train.destination || t("card.destination"))}</small>
                    </div>
                </div>
                <div class="travel-panel__chips">
                    <span>${escapeHtml(train.train_no || t("common.na"))}</span>
                    <span>${escapeHtml(train.departure_date || t("common.na"))}</span>
                    <span>${escapeHtml(train.status || t("card.availabilityUnknown"))}</span>
                </div>
            </section>
        `);
    }

    if (hotel) {
        segments.push(`
            <section class="travel-panel__card travel-panel__card--stay">
                <div class="travel-panel__header">
                    <div>
                        <p class="eyebrow">${escapeHtml(mode === "quickpick" ? t("card.suggestedStay") : t("card.staySnapshot"))}</p>
                        <h3>${escapeHtml(hotel?.name || t("common.na"))}</h3>
                    </div>
                    <span class="travel-panel__price">${escapeHtml(formatPrice(hotel.price, currency))}</span>
                </div>
                <div class="travel-panel__stay">
                    ${imageTag(hotel?.image, hotel?.name || t("card.hotelImageAlt"))}
                    <div class="travel-panel__stay-copy">
                        <div class="travel-panel__chips">
                            <span>${escapeHtml(`${t("card.rating")}: ${hotel.rating ?? t("common.na")}`)}</span>
                            <span>${escapeHtml(`${t("card.stars")}: ${hotel.stars ?? t("common.na")}`)}</span>
                        </div>
                        <p class="travel-panel__note">${escapeHtml(hotel.location || t("common.na"))}</p>
                        <a class="ghost-button travel-panel__cta" href="${escapeHtml(hotel.url || "#")}" ${hotel?.url && hotel.url !== "#" ? 'target="_blank" rel="noreferrer"' : ""}>${escapeHtml(t("card.viewStay"))}</a>
                    </div>
                </div>
            </section>
        `);
    }

    container.innerHTML = `
        <section class="travel-panel">
            <div class="travel-panel__top">
                <div>
                    <p class="eyebrow">${escapeHtml(mode === "quickpick" ? t("results.recommendedTrip") : t("results.manualPreview"))}</p>
                    <h2>${escapeHtml(mode === "quickpick" ? t("results.bundleTitle") : t("results.snapshotTitle"))}</h2>
                </div>
                <p class="travel-panel__intro">
                    ${escapeHtml(mode === "quickpick" ? t("results.bundleIntro") : t("results.manualIntro"))}
                </p>
            </div>
            ${warningText ? `<p class="travel-panel__warning" role="status"><i class="ri-error-warning-line"></i> ${escapeHtml(warningText)}</p>` : ""}
            <div class="travel-panel__rail ${segments.length === 1 ? "travel-panel__rail--single" : ""}">
                ${segments.join("")}
            </div>
        </section>
    `;
}

export function renderFlightCards(container, flights, currency) {
    if (!flights.length) {
        container.innerHTML = "";
        return;
    }

    container.innerHTML = `
        <div class="section-heading section-heading--compact">
            <p class="eyebrow">${escapeHtml(t("section.flights"))}</p>
            <h2>${flights.length} ${escapeHtml(t("common.options"))}</h2>
        </div>
        ${flights.slice(0, 8).map((flight) => `
            <article class="trip-card">
                <div class="trip-card__meta">
                    <span>${escapeHtml(flight.airline || t("card.flight"))}</span>
                    <span>${escapeHtml(flight.flight_no || t("common.na"))}</span>
                    <span>${escapeHtml(flight.duration || t("card.durationUnavailable"))}</span>
                </div>
                <div class="trip-card__route">
                    <div>
                        <p>${escapeHtml(t("card.departure"))}</p>
                        <strong>${escapeHtml(flight.departure || "--:--")}</strong>
                    </div>
                    <div class="trip-card__price">${escapeHtml(formatPrice(flight.price, currency))}</div>
                    <div>
                        <p>${escapeHtml(t("card.arrival"))}</p>
                        <strong>${escapeHtml(flight.arrival || "--:--")}</strong>
                    </div>
                </div>
                <div class="trip-card__footer">
                    <span>${escapeHtml(t("card.stops"))}: ${escapeHtml(flight.stops ?? 0)}</span>
                    <span>${escapeHtml((flight.segments || []).map((segment) => segment.destinationCity).filter(Boolean).join(" / ") || t("card.direct"))}</span>
                </div>
            </article>
        `).join("")}
    `;
}

export function renderTrainCards(container, trains, currency) {
    if (!trains.length) {
        container.innerHTML = "";
        return;
    }

    container.innerHTML = `
        <div class="section-heading section-heading--compact">
            <p class="eyebrow">${escapeHtml(t("section.trains"))}</p>
            <h2>${trains.length} ${escapeHtml(t("common.options"))}</h2>
        </div>
        ${trains.slice(0, 8).map((train) => `
            <article class="trip-card">
                <div class="trip-card__meta">
                    <span>${escapeHtml(train.name || t("card.train"))}</span>
                    <span>${escapeHtml(train.train_no || t("common.na"))}</span>
                    <span>${escapeHtml(train.class || t("common.na"))}</span>
                </div>
                <div class="trip-card__route">
                    <div>
                        <p>${escapeHtml(t("card.departure"))}</p>
                        <strong>${escapeHtml(train.departure || "--:--")}</strong>
                    </div>
                    <div class="trip-card__price">${escapeHtml(formatPrice(train.fare, currency))}</div>
                    <div>
                        <p>${escapeHtml(t("card.arrival"))}</p>
                        <strong>${escapeHtml(train.arrival || "--:--")}</strong>
                    </div>
                </div>
                <div class="trip-card__footer">
                    <span>${escapeHtml(train.source || t("card.origin"))}</span>
                    <span>${escapeHtml(train.destination || t("card.destination"))}</span>
                    <span>${escapeHtml(train.duration || t("card.durationUnavailable"))}</span>
                </div>
            </article>
        `).join("")}
    `;
}

export function renderHotelCards(container, hotels, currency) {
    if (!hotels.length) {
        container.innerHTML = `<article class="trip-card"><p>${escapeHtml(t("empty.noHotels"))}</p></article>`;
        return;
    }

    container.innerHTML = hotels.slice(0, 8).map((hotel) => `
        <article class="trip-card hotel-card">
            ${imageTag(hotel.image, hotel.name || "Hotel")}
            <div>
                <h3>${escapeHtml(hotel.name || t("common.na"))}</h3>
                <p>${escapeHtml(hotel.location || t("common.na"))}</p>
                <div class="hotel-card__meta">
                    <span>${escapeHtml(`${t("card.rating")}: ${hotel.rating ?? t("common.na")}`)}</span>
                    <span>${escapeHtml(`${t("card.stars")}: ${hotel.stars ?? t("common.na")}`)}</span>
                    <span>${escapeHtml(formatPrice(hotel.price, currency))}</span>
                </div>
            </div>
        </article>
    `).join("");
}

export function renderItineraryCards(container, places) {
    if (!places.length) {
        container.innerHTML = `<article class="trip-card"><p>${escapeHtml(t("empty.itineraryLoading"))}</p></article>`;
        return;
    }

    container.innerHTML = places.map((place) => `
        <article class="itinerary-card">
            ${imageTag(place.image_url, place.placeName || t("card.placeImageAlt"))}
            <div>
                <h3>${escapeHtml(place.placeName || t("card.untitledPlace"))}</h3>
                <p>${escapeHtml(place.description || t("card.descUnavailable"))}</p>
                <p class="results-subtle">${escapeHtml(place.address || t("card.addrUnavailable"))}</p>
            </div>
        </article>
    `).join("");
}

export function renderResultsHeader(titleEl, subtitleEl, requestData, results) {
    titleEl.textContent = `${requestData.origin} → ${requestData.destination}`;
    const route = `${compactLocation(results.source)} → ${compactLocation(results.destination)}`;
    const pricing = t("results.pricesIn").replace("{currency}", results.currency || t("common.na"));
    subtitleEl.textContent = `${route} · ${pricing}`;
}
