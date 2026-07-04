import { initHomePage } from "./pages/home.js";
import { initResultsPage } from "./pages/results.js";
import { initChatPage } from "./pages/chat.js";
import { initGuidesPage } from "./pages/guides.js";
import { initAuthPage } from "./pages/auth.js";
import { initDashboardPage } from "./pages/dashboard.js";
import { authApi } from "./modules/api.js";
import { initI18n, t } from "./modules/i18n.js";
import { initMotion } from "./modules/motion.js";

function initNavigation() {
    const toggle = document.querySelector("[data-nav-toggle]");
    const panel = document.querySelector("[data-nav-panel]");

    if (!toggle || !panel) {
        return;
    }

    toggle.addEventListener("click", () => {
        panel.classList.toggle("is-open");
    });

    document.querySelectorAll("[data-action='logout']").forEach((btn) => {
        btn.addEventListener("click", async (e) => {
            e.preventDefault();
            const label = btn.querySelector("span") || btn;
            const original = label.textContent;
            try {
                await authApi.logout();
                window.location.href = "/";
            } catch (err) {
                // Inline, non-blocking feedback (no popups): briefly flag on the
                // link itself, then restore.
                label.textContent = t("common.logoutFailed");
                window.setTimeout(() => { label.textContent = original; }, 2600);
            }
        });
    });
}

document.addEventListener("DOMContentLoaded", async () => {
    // Load + apply the stored UI language BEFORE page init, so JS-rendered
    // content (cards, statuses) is produced in the selected language.
    await initI18n();
    initNavigation();

    const page = document.body.dataset.page;
    if (page === "home") {
        initHomePage();
    }
    if (page === "results") {
        initResultsPage();
    }
    if (page === "chat") {
        initChatPage();
    }
    if (page === "guides") {
        initGuidesPage();
    }
    if (page === "auth") {
        initAuthPage();
    }
    if (page === "dashboard") {
        initDashboardPage();
    }

    initMotion();
});
