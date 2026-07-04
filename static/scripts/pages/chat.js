import { travelApi } from "../modules/api.js";
import { getSearchRequest, getSearchResults, setStoredValue, getStoredValue } from "../modules/storage.js";
import { t, getCurrentLanguage } from "../modules/i18n.js";

const CHAT_HISTORY_KEY = "bb:chat-history";

function escapeHtml(value) {
    return String(value ?? "")
        .replaceAll("&", "&amp;")
        .replaceAll("<", "&lt;")
        .replaceAll(">", "&gt;")
        .replaceAll('"', "&quot;")
        .replaceAll("'", "&#39;");
}

function renderMarkdown(text) {
    if (window.marked && window.DOMPurify) {
        const rawHtml = window.marked.parse(text || "");
        return window.DOMPurify.sanitize(rawHtml);
    }
    return `<p>${escapeHtml(text)}</p>`;
}

function loadHistory() {
    try {
        return JSON.parse(getStoredValue(CHAT_HISTORY_KEY) || "[]")
            .filter((message) => message?.content && message.content !== "[object Object]");
    } catch {
        return [];
    }
}

function saveHistory(history) {
    setStoredValue(CHAT_HISTORY_KEY, JSON.stringify(history));
}

function appendMessage(container, role, text) {
    const isBot = role === "assistant";
    const icon = isBot ? "ri-sparkling-2-line" : "ri-user-3-line";
    const label = isBot ? "BharatBhraman Guru" : t("chat.you");
    const content = isBot
        ? renderMarkdown(text)
        : `<p>${escapeHtml(text)}</p>`;

    container.insertAdjacentHTML("beforeend", `
        <article class="chat-message ${isBot ? "chat-message--bot" : "chat-message--user"}">
            <div class="chat-avatar"><i class="${icon}"></i></div>
            <div class="chat-bubble">
                <p class="chat-author">${escapeHtml(label)}</p>
                <div class="chat-markdown">${content}</div>
            </div>
        </article>
    `);
    container.scrollTop = container.scrollHeight;
}

function normalizeChatResponse(payload) {
    if (typeof payload === "string") {
        return payload;
    }
    if (Array.isArray(payload)) {
        return payload
            .map((item) => {
                if (typeof item === "string") {
                    return item;
                }
                if (item && typeof item.text === "string") {
                    return item.text;
                }
                return "";
            })
            .filter(Boolean)
            .join("\n\n");
    }
    if (payload && typeof payload.text === "string") {
        return payload.text;
    }
    return t("chat.unavailable");
}

function buildTripContext() {
    const search = getSearchRequest();
    const results = getSearchResults()?.data?.results;
    if (!search && !results) {
        return "";
    }

    const lines = [];
    if (search) {
        lines.push(`Route: ${search.origin} to ${search.destination}`);
        lines.push(`Date: ${search.date}`);
        lines.push(`Preference: ${search.preferences}`);
    }
    if (results?.currency) {
        lines.push(`Currency: ${results.currency}`);
    }
    if (results?.itinerary?.length) {
        lines.push(`Itinerary places: ${results.itinerary.map((item) => item.placeName).join(", ")}`);
    }
    return lines.join("\n");
}

export function initChatPage() {
    const form = document.getElementById("chat-form");
    const input = document.getElementById("chat-input");
    const thread = document.getElementById("chat-thread");
    const submit = document.getElementById("chat-submit");
    const contextField = document.getElementById("chat-context");
    const useContextButton = document.getElementById("chat-use-trip-context");
    let history = loadHistory();

    if (history.length) {
        thread.innerHTML = "";
        history.forEach((message) => appendMessage(thread, message.role, message.content));
    }

    useContextButton.addEventListener("click", () => {
        contextField.value = buildTripContext();
    });

    document.querySelectorAll("[data-chat-prompt]").forEach((button) => {
        button.addEventListener("click", () => {
            input.value = button.dataset.chatPrompt;
            input.focus();
        });
    });

    // Enter sends; Shift+Enter inserts a newline. Ignore mid-IME composition so
    // typing in an Indic/CJK language doesn't send before the word is committed.
    input.addEventListener("keydown", (event) => {
        if (event.key === "Enter" && !event.shiftKey && !event.isComposing) {
            event.preventDefault();
            form.requestSubmit();
        }
    });

    form.addEventListener("submit", async (event) => {
        event.preventDefault();
        const message = input.value.trim();
        if (!message) {
            return;
        }

        appendMessage(thread, "user", message);
        const nextHistory = [...history, { role: "user", content: message }];
        saveHistory(nextHistory);
        input.value = "";
        submit.disabled = true;

        try {
            const response = await travelApi.chat({
                message,
                history: nextHistory,
                trip_context: contextField.value.trim() || buildTripContext(),
                language: getCurrentLanguage(),
            });
            const reply = normalizeChatResponse(response.data?.response);
            appendMessage(thread, "assistant", reply);
            nextHistory.push({ role: "assistant", content: reply });
            saveHistory(nextHistory);
            history = nextHistory;
        } catch (error) {
            const fallback = error.message || t("chat.unavailable");
            appendMessage(thread, "assistant", fallback);
            nextHistory.push({ role: "assistant", content: fallback });
            saveHistory(nextHistory);
            history = nextHistory;
        } finally {
            submit.disabled = false;
        }
    });
}
