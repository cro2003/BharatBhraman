import { travelApi } from "../modules/api.js";
import { STORAGE_KEYS } from "../modules/config.js";
import { renderSuggestions } from "../modules/renderers.js";
import { storeSearchRequest, storeSearchResults, setStoredValue, getStoredValue } from "../modules/storage.js";
import { changeLanguage, t } from "../modules/i18n.js";

function debounce(callback, wait = 300) {
    let timeoutId = null;
    return (...args) => {
        clearTimeout(timeoutId);
        timeoutId = window.setTimeout(() => callback(...args), wait);
    };
}

function setStatusElements(visible, state = {}) {
    const panel = document.getElementById("search-status");
    const title = document.getElementById("status-title");
    const chip = document.getElementById("status-chip");
    const message = document.getElementById("status-message");
    const bar = document.getElementById("status-progress-bar");

    panel.hidden = !visible;
    if (!visible) {
        return;
    }

    title.textContent = state.title || t("status.preparing");
    chip.textContent = state.chip || t("status.working");
    // message === null means "leave it alone" (the fact rotator owns it).
    if (state.message !== null) {
        message.textContent = state.message || t("status.fetching");
    }
    bar.style.width = `${state.progress || 20}%`;
}

// Cycles entertaining-but-true status lines while the trip is generated, so the
// wait feels alive instead of frozen. Returns a stop() to call when done.
function startFactRotation() {
    const keys = [
        "status.fact1", "status.fact2", "status.fact3", "status.fact4",
        "status.fact5", "status.fact6", "status.fact7",
    ];
    const message = document.getElementById("status-message");
    let i = 0;
    const tick = () => {
        if (message) {
            message.textContent = t(keys[i % keys.length]);
            message.classList.remove("status-fact-in");
            void message.offsetWidth;
            message.classList.add("status-fact-in");
        }
        i += 1;
    };
    tick();
    const id = window.setInterval(tick, 2800);
    return () => window.clearInterval(id);
}

// The search-panel chip becomes a travel "reel" while a search runs: it plays a
// travel-icon wave (CSS) and cycles through phase label SETS. Returns stop().
function startTravelReel() {
    const chip = document.getElementById("travel-reel");
    if (!chip) {
        return () => {};
    }
    const label = chip.querySelector(".travel-reel__label");
    const sets = ["reel.route", "reel.flights", "reel.trains", "reel.stays", "reel.itinerary"];
    chip.classList.add("is-searching");
    let i = 0;
    const swap = () => {
        if (!label) {
            return;
        }
        label.classList.add("is-swapping");
        window.setTimeout(() => {
            label.textContent = t(sets[i % sets.length]);
            label.classList.remove("is-swapping");
            i += 1;
        }, 200);
    };
    swap();
    const id = window.setInterval(swap, 1900);
    return () => {
        window.clearInterval(id);
        chip.classList.remove("is-searching");
        if (label) {
            label.classList.remove("is-swapping");
            label.textContent = t("panel.chip");
        }
    };
}

function setupModeSwitch(form) {
    const buttons = Array.from(document.querySelectorAll("[data-mode]"));
    const hiddenInput = form.querySelector('input[name="selectionMode"]');
    const hint = document.getElementById("search-hint");

    buttons.forEach((button) => {
        button.addEventListener("click", () => {
            buttons.forEach((item) => {
                item.classList.remove("is-active");
                item.setAttribute("aria-pressed", "false");
            });
            button.classList.add("is-active");
            button.setAttribute("aria-pressed", "true");
            hiddenInput.value = button.dataset.mode;

            hint.textContent = button.dataset.mode === "quickpick"
                ? t("form.hint")
                : t("form.hintManual");
        });
    });
}

function setupDestinationButtons(destinationInput) {
    document.querySelectorAll("[data-fill-destination]").forEach((button) => {
        button.addEventListener("click", () => {
            destinationInput.value = button.dataset.fillDestination;
            destinationInput.focus();
        });
    });
}

function setupLanguageSelect() {
    const select = document.getElementById("language-select");
    if (!select) {
        return;
    }
    const saved = getStoredValue(STORAGE_KEYS.selectedLanguage);
    if (saved) {
        select.value = saved;
    }

    select.addEventListener("change", async () => {
        select.disabled = true;
        try {
            await changeLanguage(select.value);
        } finally {
            select.disabled = false;
        }
    });
}

function setupAutocomplete(inputId, suggestionsId) {
    const input = document.getElementById(inputId);
    const suggestions = document.getElementById(suggestionsId);

    const lookup = debounce(async () => {
        const value = input.value.trim();
        if (value.length < 2) {
            renderSuggestions(suggestions, [], () => {});
            return;
        }

        try {
            const response = await travelApi.lookupLocations(value);
            const items = response.data || [];
            renderSuggestions(suggestions, items, (item) => {
                input.value = item.city || item.formatted || value;
                suggestions.classList.remove("is-visible");
            });
        } catch (error) {
            renderSuggestions(suggestions, [], () => {});
        }
    }, 280);

    input.addEventListener("input", lookup);
    input.addEventListener("blur", () => {
        window.setTimeout(() => suggestions.classList.remove("is-visible"), 120);
    });
    // Close the dropdown on any click outside the field (blur alone is flaky —
    // clicking a non-focusable area sometimes leaves the list open).
    document.addEventListener("click", (event) => {
        if (!input.contains(event.target) && !suggestions.contains(event.target)) {
            suggestions.classList.remove("is-visible");
        }
    });
    input.addEventListener("keydown", (event) => {
        if (event.key === "Escape") {
            suggestions.classList.remove("is-visible");
        }
    });
}

async function pollForResults(jobId, mode = "quickpick") {
    const POLL_INTERVAL_MS = 1800;
    const MAX_WAIT_MS = 90000;
    const start = Date.now();
    let progress = 35;

    while (true) {
        const response = await travelApi.getSearchStatus(jobId);
        const job = response.data;
        const status = response.job_status || job.status;

        if (status === "completed") {
            return response;
        }

        // Manual/progressive: hand off to the results page as soon as flights are
        // published (it keeps polling for hotels and fetches trains per flight).
        if (mode === "manual" && (job.stage === "flights" || job.stage === "hotels")) {
            return response;
        }

        if (status === "failed") {
            throw new Error(job.error || t("status.failed"));
        }

        if (Date.now() - start > MAX_WAIT_MS) {
            throw new Error(t("status.timeout"));
        }

        // Advance gradually toward 90% so the bar reflects ongoing work.
        progress = Math.min(90, progress + 6);
        setStatusElements(true, {
            title: t("status.searching"),
            chip: t("status.processing"),
            message: null,
            progress,
        });
        await new Promise((resolve) => window.setTimeout(resolve, POLL_INTERVAL_MS));
    }
}

export function initHomePage() {
    const form = document.getElementById("trip-search-form");
    const originInput = document.getElementById("origin-input");
    const destinationInput = document.getElementById("destination-input");
    const dateInput = document.getElementById("date-input");
    const submitButton = document.getElementById("search-submit");
    const languageSelect = document.getElementById("language-select");

    dateInput.min = new Date().toISOString().split("T")[0];

    setupModeSwitch(form);
    setupDestinationButtons(destinationInput);
    setupLanguageSelect();
    setupAutocomplete("origin-input", "origin-suggestions");
    setupAutocomplete("destination-input", "destination-suggestions");

    form.addEventListener("submit", async (event) => {
        event.preventDefault();

        const formData = new FormData(form);
        const selectionMode = formData.get("selectionMode");
        const payload = {
            origin: formData.get("origin").trim(),
            destination: formData.get("destination").trim(),
            date: formData.get("date"),
            preferences: formData.get("preferences"),
            language: languageSelect.value || "English",
            mode: selectionMode === "manual" ? "manual" : "quickpick",
        };

        storeSearchRequest({ ...payload, selectionMode });
        setStoredValue(STORAGE_KEYS.lastSelectionMode, selectionMode);

        submitButton.disabled = true;
        setStatusElements(true, {
            title: t("status.submitting"),
            chip: t("status.queued"),
            message: t("status.starting"),
            progress: 28,
        });

        const panel = document.getElementById("search-status");
        panel.classList.remove("is-error");
        panel.classList.add("is-loading");
        const stopFacts = startFactRotation();
        const stopReel = startTravelReel();
        try {
            const searchResponse = await travelApi.startSearch(payload);
            const jobId = searchResponse.data?.job_id || searchResponse.job_id;

            setStatusElements(true, {
                title: t("status.building"),
                chip: t("status.searchingChip"),
                message: null,
                progress: 50,
            });

            const resultResponse = await pollForResults(jobId, payload.mode);
            stopFacts();
            stopReel();
            storeSearchResults(resultResponse);
            window.location.href = "/results";
        } catch (error) {
            stopFacts();
            stopReel();
            panel.classList.remove("is-loading");
            panel.classList.add("is-error");
            setStatusElements(true, {
                title: t("status.failed"),
                chip: t("status.error"),
                message: error.message || t("status.somethingWrong"),
                progress: 100,
            });
            submitButton.disabled = false;
        }
    });

    [originInput, destinationInput].forEach((input) => {
        input.addEventListener("focus", () => {
            if (!submitButton.disabled) {
                setStatusElements(false);
            }
        });
    });
}
