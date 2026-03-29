// frontend/src/lib/api.js
// Define la URL base del backend con prefijo /api obligatorio.
// REACT_APP_BACKEND_URL tiene prioridad; REACT_APP_API_URL es retrocompatible.
// Si ninguna se define, usamos http://localhost:8001 como fallback.
const trimTrailingSlash = (url = "") => url.replace(/\/+$/, "");

const rawRoot =
  process.env.REACT_APP_BACKEND_URL || process.env.REACT_APP_API_URL;

const backendRoot = rawRoot ? trimTrailingSlash(rawRoot) : "http://localhost:8001";

const ensureApiSuffix = (url) =>
  url.toLowerCase().endsWith("/api") ? url : `${trimTrailingSlash(url)}/api`;

export const API = ensureApiSuffix(backendRoot);
