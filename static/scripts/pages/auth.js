import { authApi } from "../modules/api.js";
import { t } from "../modules/i18n.js";

export function initAuthPage() {
    const form = document.getElementById("auth-form");
    const nameField = document.getElementById("name-field");
    const nameInput = document.getElementById("auth-name");
    const emailInput = document.getElementById("auth-email");
    const passwordInput = document.getElementById("auth-password");
    
    const eyebrow = document.getElementById("auth-eyebrow");
    const title = document.getElementById("auth-title");
    const btnText = document.getElementById("auth-btn-text");
    const submitBtn = document.getElementById("auth-submit");
    const note = document.getElementById("auth-note");

    const showNote = (text) => {
        if (!note) {
            return;
        }
        note.textContent = text || "";
        note.hidden = !text;
    };

    let mode = "login";

    document.querySelectorAll("#auth-mode-switch .mode-switch__button").forEach((btn) => {
        btn.addEventListener("click", () => {
            document.querySelectorAll("#auth-mode-switch .mode-switch__button").forEach(b => {
                b.classList.remove("is-active");
                b.setAttribute("aria-pressed", "false");
            });
            btn.classList.add("is-active");
            btn.setAttribute("aria-pressed", "true");
            mode = btn.dataset.mode;
            
            if (mode === "register") {
                nameField.style.display = "flex";
                nameInput.required = true;
                eyebrow.textContent = t("auth.newAccount");
                title.textContent = t("auth.registerTitle");
                btnText.textContent = t("auth.register");
            } else {
                nameField.style.display = "none";
                nameInput.required = false;
                eyebrow.textContent = t("auth.welcomeBack");
                title.textContent = t("auth.loginTitle");
                btnText.textContent = t("auth.login");
            }
        });
    });

    form.addEventListener("submit", async (e) => {
        e.preventDefault();
        
        const payload = {
            email: emailInput.value.trim(),
            password: passwordInput.value,
        };
        
        if (mode === "register") {
            payload.name = nameInput.value.trim();
        }
        
        const originalBtnHtml = submitBtn.innerHTML;
        submitBtn.disabled = true;
        showNote("");
        submitBtn.innerHTML = `<span>${t("auth.processing")}</span><i class="ri-loader-4-line ri-spin"></i>`;

        try {
            if (mode === "register") {
                await authApi.register(payload);
                await authApi.login({ email: payload.email, password: payload.password });
            } else {
                await authApi.login(payload);
            }

            window.location.href = "/dashboard";
        } catch (error) {
            showNote(error.message || t("auth.authFailed"));
            submitBtn.disabled = false;
            submitBtn.innerHTML = originalBtnHtml;
        }
    });
}
