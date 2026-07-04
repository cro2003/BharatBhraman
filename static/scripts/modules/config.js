export const API_BASE_URL = "";
export const STORAGE_KEYS = {
    lastSearchResults: "bb:last-search-results",
    lastSearchRequest: "bb:last-search-request",
    lastSelectionMode: "bb:last-selection-mode",
    selectedLanguage: "bb:selected-language",
    selectedTrip: "bb:selected-trip",
    tripChatHistory: "bb:trip-chat-history",
    // Confirmed manual selection, tagged with its job_id, so reopening results
    // restores the built trip instead of restarting the wizard.
    confirmedTrip: "bb:confirmed-trip",
    // Saved trip opened from the dashboard (rendered read-only + chat).
    savedTripView: "bb:saved-trip-view",
};
