import { API_BASE_URL } from "./config.js";
import { t } from "./i18n.js";

async function request(path, options = {}) {
    const response = await fetch(`${API_BASE_URL}${path}`, {
        headers: {
            "Content-Type": "application/json",
            ...(options.headers || {}),
        },
        credentials: "same-origin",
        ...options,
    });

    let body = null;
    try {
        body = await response.json();
    } catch (error) {
        body = { status: "error", message: t("common.invalidResponse") };
    }

    if (!response.ok) {
        const message = body?.message || t("common.requestFailed");
        throw new Error(message);
    }

    return body;
}

export const travelApi = {
    lookupLocations(query) {
        return request(`/api/travel/lookup/location?q=${encodeURIComponent(query)}`);
    },
    startSearch(payload) {
        return request("/api/travel/search", {
            method: "POST",
            body: JSON.stringify(payload),
        });
    },
    getSearchStatus(jobId) {
        return request(`/api/travel/status/${jobId}`);
    },
    trainsForFlight(payload) {
        return request("/api/travel/trains-for-flight", {
            method: "POST",
            body: JSON.stringify(payload),
        });
    },
    selectTrip(payload) {
        return request("/api/travel/select", {
            method: "POST",
            body: JSON.stringify(payload),
        });
    },
    chat(payload) {
        return request("/api/travel/chat", {
            method: "POST",
            body: JSON.stringify(payload),
        });
    },
    resetChat() {
        return request("/api/travel/chat/reset", { method: "POST" });
    },
};

export const guidesApi = {
    search(city, lang = "") {
        const params = new URLSearchParams({ city });
        if (lang) {
            params.set("lang", lang);
        }
        return request(`/api/guides/search?${params.toString()}`);
    },
    register(payload) {
        return request("/api/guides/register", {
            method: "POST",
            body: JSON.stringify(payload),
        });
    },
    book(payload) {
        return request("/api/guides/book", {
            method: "POST",
            body: JSON.stringify(payload),
        });
    },
    review(payload) {
        return request("/api/guides/review", {
            method: "POST",
            body: JSON.stringify(payload),
        });
    },
};

export const authApi = {
    register(payload) {
        return request("/api/auth/register", {
            method: "POST",
            body: JSON.stringify(payload),
        });
    },
    login(payload) {
        return request("/api/auth/login", {
            method: "POST",
            body: JSON.stringify(payload),
        });
    },
    logout() {
        return request("/api/auth/logout", {
            method: "POST",
        });
    },
    me() {
        return request("/api/auth/me");
    },
};

export const userApi = {
    getDashboard() {
        return request("/api/user/dashboard");
    },
    saveTrip() {
        return request("/api/user/save-trip", {
            method: "POST",
        });
    },
    openTrip(payload) {
        return request("/api/user/open-trip", {
            method: "POST",
            body: JSON.stringify(payload),
        });
    },
    deleteTrip(payload) {
        return request("/api/user/delete-trip", {
            method: "POST",
            body: JSON.stringify(payload),
        });
    },
    updateTripChat(payload) {
        return request("/api/user/update-trip-chat", {
            method: "POST",
            body: JSON.stringify(payload),
        });
    },
};
