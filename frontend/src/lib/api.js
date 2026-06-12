import axios from "axios";

export const DEFAULT_API_TIMEOUT_MS = 15000;
export const LONG_API_TIMEOUT_MS = 30000;
export const API_CONNECTION_EVENT = "prodelivery-api-connection";

const configuredTimeout = Number.parseInt(process.env.REACT_APP_API_TIMEOUT_MS || "", 10);
export const API_TIMEOUT_MS = Number.isFinite(configuredTimeout) && configuredTimeout > 0
  ? configuredTimeout
  : DEFAULT_API_TIMEOUT_MS;

const sleep = (delayMs) => new Promise((resolve) => setTimeout(resolve, delayMs));

const emitConnectionStatus = (detail) => {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new CustomEvent(API_CONNECTION_EVENT, { detail }));
};

const formatApiErrorDetail = (detail) => {
  if (detail == null) return "";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => {
        if (typeof entry === "string") return entry;
        if (entry && typeof entry.msg === "string") return entry.msg;
        return "";
      })
      .filter(Boolean)
      .join(" ");
  }
  if (detail && typeof detail.msg === "string") return detail.msg;
  if (detail && typeof detail.message === "string") return detail.message;
  return "";
};

export const isBrowserOffline = () => (
  typeof navigator !== "undefined" && navigator.onLine === false
);

export const isTimeoutError = (error) => (
  error?.code === "ECONNABORTED" ||
  error?.code === "ETIMEDOUT" ||
  /timeout|exceeded/i.test(error?.message || "")
);

export const isConnectionError = (error) => (
  isBrowserOffline() ||
  isTimeoutError(error) ||
  (!error?.response && Boolean(error?.request || error?.message))
);

export const isRetryableReadError = (error) => {
  if (isBrowserOffline()) return false;
  if (isTimeoutError(error) || (!error?.response && error?.request)) return true;
  const status = error?.response?.status;
  return status === 408 || status === 429 || (status >= 500 && status < 600);
};

export const getApiErrorMessage = (error, fallback = "A apărut o eroare. Încearcă din nou.") => {
  const detail = formatApiErrorDetail(error?.response?.data?.detail);
  if (detail) return detail;

  if (isBrowserOffline()) {
    return "Nu ai conexiune la internet. Verifică rețeaua și încearcă din nou.";
  }

  if (isTimeoutError(error)) {
    return "Request-ul a durat prea mult. Încearcă din nou.";
  }

  if (!error?.response && (error?.request || error?.message)) {
    return "Serverul nu răspunde. Verifică conexiunea sau încearcă mai târziu.";
  }

  const status = error?.response?.status;
  if (status === 401) return "Sesiunea a expirat. Conectează-te din nou.";
  if (status === 403) return "Nu ai permisiune pentru această acțiune.";
  if (status === 404) return "Resursa cerută nu a fost găsită.";
  if (status === 409) return "Datele au fost modificate între timp. Reîncarcă și încearcă din nou.";
  if (status >= 500) return "Serverul a returnat o eroare. Încearcă din nou în câteva momente.";

  return fallback;
};

export const normalizeArray = (value, fallback = []) => (
  Array.isArray(value) ? value : fallback
);

export const normalizeObject = (value, fallback = {}) => (
  value && typeof value === "object" && !Array.isArray(value) ? value : fallback
);

export const retryApiCall = async (apiCall, { retries = 1, delayMs = 500 } = {}) => {
  let lastError;
  for (let attempt = 0; attempt <= retries; attempt += 1) {
    try {
      return await apiCall();
    } catch (error) {
      lastError = error;
      if (attempt >= retries || !isRetryableReadError(error)) break;
      await sleep(delayMs * (attempt + 1));
    }
  }
  throw lastError;
};

axios.defaults.withCredentials = true;
axios.defaults.timeout = API_TIMEOUT_MS;

if (typeof window !== "undefined" && !window.__PRODELIVERY_API_HARDENING__) {
  window.__PRODELIVERY_API_HARDENING__ = true;
  axios.interceptors.response.use(
    (response) => {
      emitConnectionStatus({ status: "ok" });
      return response;
    },
    (error) => {
      if (isConnectionError(error)) {
        emitConnectionStatus({
          status: "error",
          message: getApiErrorMessage(error, "Serverul nu răspunde."),
        });
      }
      return Promise.reject(error);
    },
  );
}
