import { STORAGE_KEYS } from "./config.js";

export function setStoredJson(key, value) {
    sessionStorage.setItem(key, JSON.stringify(value));
}

export function getStoredJson(key) {
    const raw = sessionStorage.getItem(key);
    if (!raw) {
        return null;
    }
    try {
        return JSON.parse(raw);
    } catch (error) {
        return null;
    }
}

export function storeSearchResults(payload) {
    setStoredJson(STORAGE_KEYS.lastSearchResults, payload);
}

export function getSearchResults() {
    return getStoredJson(STORAGE_KEYS.lastSearchResults);
}

export function storeSearchRequest(payload) {
    setStoredJson(STORAGE_KEYS.lastSearchRequest, payload);
}

export function getSearchRequest() {
    return getStoredJson(STORAGE_KEYS.lastSearchRequest);
}

export function setStoredValue(key, value) {
    sessionStorage.setItem(key, value);
}

export function getStoredValue(key) {
    return sessionStorage.getItem(key);
}

export function removeStoredValue(key) {
    sessionStorage.removeItem(key);
}
