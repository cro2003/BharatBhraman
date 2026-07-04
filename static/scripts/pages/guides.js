import { guidesApi } from "../modules/api.js";
import { getSearchRequest } from "../modules/storage.js";
import { t } from "../modules/i18n.js";
import { refreshReveal } from "../modules/motion.js";

// Indicative only — the backend recomputes the authoritative breakdown on booking.
const PLATFORM_FEE_RATE = 0.25;

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function isAuthError(err) {
    const m = (err?.message || "").toLowerCase();
    return m.includes("log in") || m.includes("unauthorized") || m.includes("unauthenticated");
}

function redirectToLogin() {
    window.location.href = "/auth";
}

function ratingSummary(guide) {
    const count = guide.review_count || (guide.reviews || []).length || 0;
    if (!count || guide.rating == null) {
        return `<span class="guide-rating guide-rating--empty"><i class="ri-star-line"></i> ${escapeHtml(t("guides.noReviews"))}</span>`;
    }
    const word = count === 1 ? t("guides.reviewOne") : t("guides.reviewMany");
    return `<span class="guide-rating"><i class="ri-star-fill"></i> ${escapeHtml(guide.rating)} · ${count} ${escapeHtml(word)}</span>`;
}

function recentReviews(guide) {
    const reviews = (guide.reviews || []).slice(-2).reverse();
    if (!reviews.length) return "";
    return `
        <div class="guide-reviews">
            ${reviews.map(r => `
                <div class="guide-review">
                    <strong>${escapeHtml(r.user || t("guides.traveller"))}</strong>
                    <span><i class="ri-star-fill"></i> ${escapeHtml(r.rating)}</span>
                    <p>${escapeHtml(r.comment || "")}</p>
                </div>
            `).join("")}
        </div>
    `;
}

function renderGuideCards(container, guides) {
    if (!guides.length) {
        container.innerHTML = `
            <article class="trip-card guide-empty-card">
                <h3>${escapeHtml(t("guides.noGuides"))}</h3>
                <p>${escapeHtml(t("guides.noGuidesHint"))}</p>
            </article>
        `;
        return;
    }

    container.innerHTML = guides.map((guide) => `
        <article class="trip-card guide-card">
            <div class="guide-card__top">
                <div class="guide-avatar"><i class="ri-user-star-line"></i></div>
                <div>
                    <h3>${escapeHtml(guide.name || t("guides.unnamed"))}</h3>
                    <p>${escapeHtml((guide.cities_covered || []).join(", ") || t("guides.cityUnavailable"))}</p>
                </div>
            </div>
            <div class="guide-card__chips">
                ${ratingSummary(guide)}
                <span><i class="ri-translate-2"></i> ${escapeHtml((guide.languages || []).join(", ") || t("common.na"))}</span>
                <span><i class="ri-money-rupee-circle-line"></i> ₹${escapeHtml(guide.hourly_rate ?? t("common.na"))}/hr</span>
            </div>
            ${recentReviews(guide)}
            <div class="guide-card__actions">
                <button class="primary-button guide-book-btn"
                        data-guide-id="${escapeHtml(guide._id)}"
                        data-guide-name="${escapeHtml(guide.name)}"
                        data-rate="${escapeHtml(guide.hourly_rate ?? 0)}">
                    <span>${escapeHtml(t("guides.book"))}</span>
                    <i class="ri-calendar-check-line"></i>
                </button>
                <button class="ghost-button guide-review-toggle" type="button" data-guide-id="${escapeHtml(guide._id)}">
                    <i class="ri-chat-1-line"></i> ${escapeHtml(t("guides.review"))}
                </button>
            </div>
            <form class="guide-review-form" data-guide-id="${escapeHtml(guide._id)}" hidden>
                <label class="field">
                    <span>${escapeHtml(t("guides.ratingLabel"))}</span>
                    <select name="rating">
                        <option value="5">${escapeHtml(t("guides.rate5"))}</option>
                        <option value="4">${escapeHtml(t("guides.rate4"))}</option>
                        <option value="3">${escapeHtml(t("guides.rate3"))}</option>
                        <option value="2">${escapeHtml(t("guides.rate2"))}</option>
                        <option value="1">${escapeHtml(t("guides.rate1"))}</option>
                    </select>
                </label>
                <label class="field">
                    <span>${escapeHtml(t("guides.commentLabel"))}</span>
                    <input type="text" name="comment" maxlength="300" placeholder="${escapeHtml(t("guides.commentPlaceholder"))}">
                </label>
                <button class="primary-button" type="submit"><span>${escapeHtml(t("guides.submitReview"))}</span><i class="ri-send-plane-line"></i></button>
                <p class="guide-status-banner guide-review-status" hidden></p>
            </form>
        </article>
    `).join("");

    refreshReveal();
}

function computeQuote(rate, hours) {
    const base = (Number(rate) || 0) * (Number(hours) || 0);
    const fee = base * PLATFORM_FEE_RATE;
    return { base, fee, total: base + fee };
}

function initBookingDialog(grid, rerunSearch) {
    const dialog = document.getElementById("booking-dialog");
    if (!dialog) return;

    const closeBtn = document.getElementById("booking-dialog-close");
    const form = document.getElementById("booking-form");
    const guideIdInput = document.getElementById("booking-guide-id");
    const rateInput = document.getElementById("booking-rate");
    const dateInput = document.getElementById("booking-date");
    const hoursInput = document.getElementById("booking-hours");
    const quoteBox = document.getElementById("booking-quote");
    const dialogTitle = document.getElementById("booking-dialog-title");
    const hint = document.getElementById("booking-hint");
    const submitBtn = document.getElementById("booking-submit");

    const today = new Date().toISOString().split("T")[0];
    dateInput.min = today;

    function refreshQuote() {
        const { base, fee, total } = computeQuote(rateInput.value, hoursInput.value);
        if (!base) {
            quoteBox.textContent = "";
            return;
        }
        quoteBox.innerHTML = `
            <div class="booking-quote__row"><span>${escapeHtml(t("booking.guideCost"))} (${escapeHtml(hoursInput.value)}h)</span><span>₹${base.toFixed(2)}</span></div>
            <div class="booking-quote__row"><span>${escapeHtml(t("booking.platformFee"))} (${PLATFORM_FEE_RATE * 100}%)</span><span>₹${fee.toFixed(2)}</span></div>
            <div class="booking-quote__row booking-quote__total"><span>${escapeHtml(t("booking.total"))}</span><span>₹${total.toFixed(2)}</span></div>
        `;
    }

    hoursInput.addEventListener("input", refreshQuote);

    grid.addEventListener("click", (e) => {
        const btn = e.target.closest(".guide-book-btn");
        if (!btn) return;

        guideIdInput.value = btn.dataset.guideId;
        rateInput.value = btn.dataset.rate || "0";
        dialogTitle.textContent = `${t("guides.book")} ${btn.dataset.guideName}`;
        hint.textContent = t("booking.hint");
        hint.className = "search-hint";
        submitBtn.querySelector("span").textContent = t("booking.confirm");
        submitBtn.disabled = false;
        dateInput.value = "";
        hoursInput.value = "2";
        refreshQuote();
        dialog.showModal();
    });

    closeBtn.addEventListener("click", () => dialog.close());
    dialog.addEventListener("click", (e) => {
        if (e.target === dialog) dialog.close();
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        const guideId = guideIdInput.value;
        const date = dateInput.value;
        const hours = Number(hoursInput.value);
        if (!guideId || !date || !hours) return;

        submitBtn.disabled = true;
        submitBtn.querySelector("span").textContent = t("booking.booking");

        try {
            const res = await guidesApi.book({ guide_id: guideId, date, hours });
            const booking = res.data?.booking || {};
            const total = `₹${booking.total_price ?? t("common.na")}`;
            hint.textContent = `✓ ${t("booking.bookedToast").replace("{total}", total)}`;
            hint.className = "search-hint guide-status-banner--success";
            submitBtn.querySelector("span").textContent = t("booking.booked");
            setTimeout(() => dialog.close(), 2200);
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            hint.textContent = `✕ ${err.message || t("booking.failed")}`;
            hint.className = "search-hint guide-status-banner--error";
            submitBtn.disabled = false;
            submitBtn.querySelector("span").textContent = t("booking.retry");
        }
    });
}

function initReviews(grid, rerunSearch) {
    grid.addEventListener("click", (e) => {
        const toggle = e.target.closest(".guide-review-toggle");
        if (!toggle) return;
        const card = toggle.closest(".guide-card");
        const reviewForm = card?.querySelector(".guide-review-form");
        if (reviewForm) reviewForm.hidden = !reviewForm.hidden;
    });

    grid.addEventListener("submit", async (e) => {
        const reviewForm = e.target.closest(".guide-review-form");
        if (!reviewForm) return;
        e.preventDefault();

        const guideId = reviewForm.dataset.guideId;
        const rating = reviewForm.querySelector("[name='rating']").value;
        const comment = reviewForm.querySelector("[name='comment']").value.trim();
        const status = reviewForm.querySelector(".guide-review-status");
        const btn = reviewForm.querySelector("button[type='submit']");

        btn.disabled = true;
        try {
            await guidesApi.review({ guide_id: guideId, rating: Number(rating), comment });
            status.hidden = false;
            status.className = "guide-status-banner guide-status-banner--success guide-review-status";
            status.textContent = `✓ ${t("guides.reviewSubmitted")}`;
            setTimeout(() => rerunSearch && rerunSearch(), 1200);
        } catch (err) {
            if (isAuthError(err)) {
                redirectToLogin();
                return;
            }
            status.hidden = false;
            status.className = "guide-status-banner guide-status-banner--error guide-review-status";
            status.textContent = `✕ ${err.message || t("guides.couldNotReview")}`;
            btn.disabled = false;
        }
    });
}

function initRegistrationForm() {
    const form = document.getElementById("guide-register-form");
    const status = document.getElementById("register-status");
    if (!form || !status) return;

    form.addEventListener("submit", async (e) => {
        e.preventDefault();

        const payload = {
            name: document.getElementById("reg-name").value.trim(),
            email: document.getElementById("reg-email").value.trim(),
            phone: document.getElementById("reg-phone").value.trim(),
            city: document.getElementById("reg-city").value.trim(),
            languages: document.getElementById("reg-languages").value.trim(),
            hourly_rate: parseFloat(document.getElementById("reg-rate").value) || 0,
            age: parseInt(document.getElementById("reg-age").value) || null,
            gender: document.getElementById("reg-gender").value || null,
        };

        if (!payload.name || !payload.email || !payload.city) {
            showStatus(status, "error", t("reg.requiredFields"));
            return;
        }

        const btn = document.getElementById("guide-register-submit");
        btn.disabled = true;
        btn.querySelector("span").textContent = t("reg.registering");

        try {
            const res = await guidesApi.register(payload);
            showStatus(status, "success", `✓ ${t("reg.registered")} ${t("reg.idLabel")} ${res.data?.guide_id || t("common.na")}`);
            form.reset();
        } catch (err) {
            showStatus(status, "error", `✕ ${err.message || t("reg.failed")}`);
        } finally {
            btn.disabled = false;
            btn.querySelector("span").textContent = t("guides.register");
        }
    });
}

function showStatus(el, type, message) {
    el.hidden = false;
    el.textContent = message;
    el.className = `guide-status-banner guide-status-banner--${type}`;
    if (type === "success") {
        setTimeout(() => { el.hidden = true; }, 5000);
    }
}

export function initGuidesPage() {
    const form = document.getElementById("guide-search-form");
    const cityInput = document.getElementById("guide-city");
    const langInput = document.getElementById("guide-language");
    const title = document.getElementById("guides-results-title");
    const subtitle = document.getElementById("guides-results-subtitle");
    const grid = document.getElementById("guides-grid");
    const latestSearch = getSearchRequest();

    if (latestSearch?.destination) {
        cityInput.value = latestSearch.destination;
        subtitle.textContent = `${t("guides.latestDest")} ${latestSearch.destination}`;
    }

    async function runSearch() {
        const city = cityInput.value.trim();
        const language = langInput.value.trim();
        if (!city) return;

        title.textContent = `${t("guides.searchingFor")} ${city}`;
        subtitle.textContent = language
            ? `${t("guides.filteringBy")} ${language}`
            : t("guides.checkingAll");
        grid.innerHTML = `<article class="trip-card guide-empty-card"><h3>${escapeHtml(t("guides.loading"))}</h3><p>${escapeHtml(t("guides.loadingHint"))}</p></article>`;

        try {
            const response = await guidesApi.search(city, language);
            const guides = response.data || [];
            const word = guides.length === 1 ? t("guides.guideFound") : t("guides.guidesFound");
            title.textContent = `${guides.length} ${word} ${city}`;
            subtitle.textContent = guides.length ? t("guides.loadedNote") : t("guides.noneMatched");
            renderGuideCards(grid, guides);
        } catch (error) {
            title.textContent = t("guides.searchFailed");
            subtitle.textContent = error.message || t("guides.unableLoad");
            renderGuideCards(grid, []);
        }
    }

    form.addEventListener("submit", (event) => {
        event.preventDefault();
        runSearch();
    });

    initBookingDialog(grid, runSearch);
    initReviews(grid, runSearch);
    initRegistrationForm();
}
