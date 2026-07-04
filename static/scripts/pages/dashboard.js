import { userApi } from "../modules/api.js";
import { t } from "../modules/i18n.js";
import { setStoredJson, removeStoredValue } from "../modules/storage.js";
import { STORAGE_KEYS } from "../modules/config.js";
import { refreshReveal } from "../modules/motion.js";

function setCount(elId, badgeId, value) {
    const el = document.getElementById(elId);
    if (el) {
        el.textContent = value;
    }
    const badge = document.getElementById(badgeId);
    if (badge) {
        badge.textContent = value;
        badge.hidden = value === 0;
    }
}

function formatDate(isoString) {
    if (!isoString) return t("common.unknownDate");
    return new Date(isoString).toLocaleDateString("en-US", {
        year: "numeric",
        month: "short",
        day: "numeric"
    });
}

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function placeLabel(loc) {
    if (loc && typeof loc === "object") {
        return loc.city || loc.formatted || loc.name || "Unknown";
    }
    return loc || "Unknown";
}

function renderTrips(trips, container) {
    if (!trips || trips.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="ri-route-line"></i>
                <p>${escapeHtml(t("dashboard.noTrips"))}</p>
                <a href="/" class="primary-button" style="margin-top: 16px; display: inline-flex;">${escapeHtml(t("dashboard.planTrip"))}</a>
            </div>
        `;
        return;
    }

    container.innerHTML = trips.map(trip => {
        // Saved trips store the committed session trip under `itinerary`:
        // { source, destination, currency, segments: { flight, train, hotel } }.
        const data = trip.itinerary || {};
        const segments = data.segments || {};
        const route = `${placeLabel(data.source)} → ${placeLabel(data.destination)}`;

        let detailsHtml = "";
        if (segments.flight) {
            detailsHtml += `<p><i class="ri-flight-takeoff-line"></i> Flight: ${escapeHtml(segments.flight.airline)} ${escapeHtml(segments.flight.flight_no || "")}</p>`;
        }
        if (segments.train) {
            detailsHtml += `<p><i class="ri-train-line"></i> Train: ${escapeHtml(segments.train.name)}</p>`;
        }
        if (segments.hotel) {
            detailsHtml += `<p><i class="ri-hotel-line"></i> Hotel: ${escapeHtml(segments.hotel.name)}</p>`;
        }
        if (!detailsHtml) {
            detailsHtml = "<p>No transport segments saved.</p>";
        }

        return `
            <article class="trip-card">
                <div class="trip-card-header">
                    <div class="trip-route"><span>${escapeHtml(route)}</span></div>
                    <span class="text-soft">${formatDate(trip.saved_at)}</span>
                </div>
                <div class="trip-card-body" style="color: var(--text-soft); line-height: 1.6;">
                    ${detailsHtml}
                </div>
                <div class="trip-card-footer">
                    <button class="trip-delete-btn" type="button" data-delete-trip="${escapeHtml(trip._id)}">
                        <i class="ri-delete-bin-line"></i> ${escapeHtml(t("dashboard.deleteTrip"))}
                    </button>
                    <button class="ghost-button" type="button" data-open-trip="${escapeHtml(trip._id)}">
                        <i class="ri-eye-line"></i> ${escapeHtml(t("dashboard.openTrip"))}
                    </button>
                </div>
            </article>
        `;
    }).join("");

    container.querySelectorAll("[data-open-trip]").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const original = btn.innerHTML;
            btn.disabled = true;
            btn.innerHTML = `<i class="ri-loader-4-line ri-spin"></i> ${t("dashboard.opening")}`;
            try {
                const response = await userApi.openTrip({ trip_id: btn.dataset.openTrip });
                // Hand the saved trip to the results page as a read-only view.
                setStoredJson(STORAGE_KEYS.savedTripView, response.data);
                removeStoredValue(STORAGE_KEYS.tripChatHistory);
                window.location.href = "/results";
            } catch (error) {
                btn.disabled = false;
                btn.innerHTML = original;
            }
        });
    });

    container.querySelectorAll("[data-delete-trip]").forEach((btn) => {
        btn.addEventListener("click", async () => {
            const card = btn.closest(".trip-card");
            const original = btn.innerHTML;
            // Inline two-step confirm (no popups): first click arms, second deletes.
            if (btn.dataset.armed !== "1") {
                btn.dataset.armed = "1";
                btn.innerHTML = `<i class="ri-error-warning-line"></i> ${t("dashboard.confirmDelete")}`;
                window.setTimeout(() => {
                    if (btn.dataset.armed === "1") {
                        btn.dataset.armed = "0";
                        btn.innerHTML = original;
                    }
                }, 3500);
                return;
            }
            btn.disabled = true;
            btn.innerHTML = `<i class="ri-loader-4-line ri-spin"></i> ${t("dashboard.deleting")}`;
            try {
                await userApi.deleteTrip({ trip_id: btn.dataset.deleteTrip });
                if (card) {
                    card.style.transition = "opacity 0.25s ease, transform 0.25s ease";
                    card.style.opacity = "0";
                    card.style.transform = "translateY(-8px)";
                    window.setTimeout(() => {
                        card.remove();
                        if (!container.querySelector(".trip-card")) {
                            renderTrips([], container);
                        }
                    }, 260);
                }
                const badge = document.getElementById("trips-count");
                const stat = document.getElementById("stat-trips");
                const next = Math.max(0, (parseInt(stat?.textContent, 10) || 1) - 1);
                if (stat) stat.textContent = next;
                if (badge) { badge.textContent = next; badge.hidden = next === 0; }
            } catch (error) {
                btn.disabled = false;
                btn.dataset.armed = "0";
                btn.innerHTML = original;
            }
        });
    });
}

function renderBookings(bookings, container) {
    if (!bookings || bookings.length === 0) {
        container.innerHTML = `
            <div class="empty-state">
                <i class="ri-map-pin-user-line"></i>
                <p>${escapeHtml(t("dashboard.noBookings"))}</p>
                <a href="/guides" class="primary-button" style="margin-top: 16px; display: inline-flex;">${escapeHtml(t("dashboard.findGuide"))}</a>
            </div>
        `;
        return;
    }

    container.innerHTML = bookings.map(booking => {
        const status = booking.status || "pending";
        const total = booking.total_price != null
            ? `₹${escapeHtml(booking.total_price)} (incl. fee)` : "";
        return `
            <article class="booking-card">
                <div>
                    <p style="font-weight: 700; margin-bottom: 4px;">${escapeHtml(t("dashboard.guide"))}: ${escapeHtml(booking.guide_name)}</p>
                    <p style="color: var(--text-soft); font-size: 0.9rem;">
                        <i class="ri-calendar-event-line"></i> ${escapeHtml(booking.date)}
                        ${booking.hours ? ` · ${escapeHtml(booking.hours)}h` : ""}
                        ${total ? ` · ${total}` : ""}
                    </p>
                </div>
                <div>
                    <span class="status-chip">${escapeHtml(status[0].toUpperCase() + status.slice(1))}</span>
                </div>
            </article>
        `;
    }).join("");
}

export async function initDashboardPage() {
    const tripsContainer = document.getElementById("saved-trips-list");
    const bookingsContainer = document.getElementById("guide-bookings-list");

    try {
        const response = await userApi.getDashboard();
        if (response.status === "success") {
            const trips = response.data.trips || [];
            const bookings = response.data.bookings || [];
            renderTrips(trips, tripsContainer);
            renderBookings(bookings, bookingsContainer);
            setCount("stat-trips", "trips-count", trips.length);
            setCount("stat-bookings", "bookings-count", bookings.length);
            refreshReveal();
        } else {
            throw new Error(response.message);
        }
    } catch (error) {
        tripsContainer.innerHTML = `<div class="empty-state"><p style="color: var(--danger);">${escapeHtml(t("dashboard.failedLoad"))} ${escapeHtml(error.message)}</p></div>`;
        bookingsContainer.innerHTML = "";

        if (error.message.toLowerCase().includes("unauthorized")) {
            window.location.href = "/auth";
        }
    }
}
