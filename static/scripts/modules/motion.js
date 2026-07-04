// Global motion: page-load entrance, reveal-on-scroll, and a sticky-header
// lift. One IntersectionObserver drives every reveal so scrolling stays cheap.
// Everything degrades gracefully: with JS off or reduced-motion on, content is
// fully visible and static.

const REDUCED_MOTION = window.matchMedia("(prefers-reduced-motion: reduce)").matches;

// Selectors auto-tagged for reveal-on-scroll when a page doesn't tag its own.
// Heroes / first sections are intentionally excluded — they animate via the
// page-load entrance instead of waiting for a scroll.
const AUTO_REVEAL = [
    ".section-heading",
    ".insight-card",
    ".destination-card",
    ".guide-card",
    ".itinerary-card",
    ".feature-card",
    ".step-card",
    ".trip-card",
    ".booking-card",
    ".empty-state",
];

// Body carries the entrance so header + main orchestrate together.
function setupPageEntrance() {
    document.body.classList.add("page-enter");
}

function setupHeaderScroll() {
    const header = document.querySelector(".site-header");
    if (!header) {
        return;
    }
    let ticking = false;
    const update = () => {
        header.classList.toggle("is-scrolled", window.scrollY > 8);
        ticking = false;
    };
    window.addEventListener("scroll", () => {
        if (!ticking) {
            window.requestAnimationFrame(update);
            ticking = true;
        }
    }, { passive: true });
    update();
}

function setupReveal() {
    if (REDUCED_MOTION || !("IntersectionObserver" in window)) {
        // CSS keeps [data-reveal] visible when we don't observe it.
        return;
    }

    // Auto-tag content not explicitly marked, skipping page-level reveal groups
    // (children stagger via CSS) or hand-tagged elements.
    AUTO_REVEAL.forEach((sel) => {
        document.querySelectorAll(sel).forEach((el) => {
            if (el.hasAttribute("data-reveal") || el.closest("[data-reveal-group]")) {
                return;
            }
            el.setAttribute("data-reveal", "");
        });
    });

    const targets = document.querySelectorAll("[data-reveal]");
    if (!targets.length) {
        return;
    }

    const observer = new IntersectionObserver((entries, obs) => {
        entries.forEach((entry) => {
            if (entry.isIntersecting) {
                entry.target.classList.add("is-revealed");
                obs.unobserve(entry.target);
            }
        });
    }, { rootMargin: "0px 0px -8% 0px", threshold: 0.08 });

    targets.forEach((el) => {
        const rect = el.getBoundingClientRect();
        // Already in view on load: reveal immediately, no scroll needed.
        if (rect.top < window.innerHeight * 0.92) {
            el.classList.add("is-revealed");
        } else {
            observer.observe(el);
        }
    });
}

export function initMotion() {
    setupPageEntrance();
    setupHeaderScroll();
    // Defer one frame so page modules have rendered dynamic content first.
    window.requestAnimationFrame(setupReveal);
}

// Re-scan for reveal targets after a page injects content asynchronously.
// Safe to call multiple times.
export function refreshReveal() {
    window.requestAnimationFrame(setupReveal);
}
