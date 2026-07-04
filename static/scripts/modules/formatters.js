import { t } from "./i18n.js";

export function formatPrice(price, currency = "") {
    if (price === null || price === undefined || price === "") {
        return t("common.na");
    }
    return currency ? `${price} ${currency}` : String(price);
}

export function compactLocation(location) {
    if (!location) {
        return t("common.na");
    }
    return location.formatted || location.city || location.address_line1 || t("common.na");
}

export function createFlightSummary(flight) {
    if (!flight) {
        return t("card.flight");
    }
    const lastSegment = (flight.segments || [])[flight.segments.length - 1] || {};
    return `${flight.airline || t("card.flight")} → ${lastSegment.destinationCity || t("card.destination")}`;
}
