import { createContext, useContext, useState, useEffect, useMemo, useCallback, useRef } from "react";
import axios from "axios";
import { getApiErrorMessage } from "../lib/api";

const AuthContext = createContext(null);
const API_URL = process.env.REACT_APP_BACKEND_URL;
const AUTH_TIMEOUT_MS = 15000;
const SUPERSEDED = "Sesiunea s-a schimbat. Conectează-te din nou.";

// Cookie exchanges must finish in order, including across provider remounts.
// A React lease cannot undo an already received HttpOnly Set-Cookie header.
let cookieExchange = Promise.resolve();
const sameActor = (left, right) => left && right &&
  ["id", "role", "restaurant_id", "driver_id"].every((key) => (left[key] ?? null) === (right[key] ?? null));
const actorKey = (actor) => actor ? JSON.stringify([actor.id, actor.role, actor.restaurant_id ?? null, actor.driver_id ?? null]) : null;

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const session = useRef({ alive: false, epoch: 0, user: null, refresh: null, initController: null });
  const owns = useCallback((epoch) => session.current.alive && session.current.epoch === epoch, []);
  const stale = useCallback(() => new axios.CanceledError(SUPERSEDED), []);

  const clearAuthState = useCallback(() => {
    session.current.user = null;
    setToken(null);
    setUser(null);
    delete axios.defaults.headers.common.Authorization;
  }, []);

  const applyAuthState = useCallback((userData, accessToken = null) => {
    session.current.user = userData;
    setUser(userData);
    setToken(accessToken);
    if (accessToken) axios.defaults.headers.common.Authorization = `Bearer ${accessToken}`;
    else delete axios.defaults.headers.common.Authorization;
  }, []);

  const authPost = useCallback((epoch, path, body) => {
    const exchange = cookieExchange.then(() => {
      if (path !== "logout" && !owns(epoch)) throw stale();
      return axios.post(`${API_URL}/api/auth/${path}`, body, { timeout: AUTH_TIMEOUT_MS });
    });
    cookieExchange = exchange.catch(() => {});
    return exchange;
  }, [owns, stale]);

  useEffect(() => {
    const ownedSession = session.current;
    ownedSession.alive = true;
    const epoch = ++ownedSession.epoch;
    const controller = new AbortController();
    ownedSession.initController = controller;
    const initAuth = async () => {
      try {
        await cookieExchange;
        if (!owns(epoch)) return;
        const meResponse = await axios.get(`${API_URL}/api/auth/me`, { timeout: AUTH_TIMEOUT_MS, signal: controller.signal });
        if (owns(epoch)) applyAuthState(meResponse.data);
      } catch (error) {
        if (!owns(epoch)) return;
        if (error.response?.status === 401) {
          try {
            const refreshResponse = await authPost(epoch, "refresh", {});
            if (!owns(epoch)) return;
            const refreshedToken = refreshResponse.data?.token ?? null;
            const meResponse = await axios.get(`${API_URL}/api/auth/me`, {
              timeout: AUTH_TIMEOUT_MS,
              signal: controller.signal,
              headers: { Authorization: refreshedToken ? `Bearer ${refreshedToken}` : null },
            });
            if (owns(epoch)) applyAuthState(meResponse.data, refreshedToken);
          } catch {
            if (owns(epoch)) clearAuthState();
          }
        } else clearAuthState();
      } finally {
        if (owns(epoch)) setIsLoading(false);
      }
    };
    initAuth();
    return () => { ownedSession.alive = false; ownedSession.epoch += 1; controller.abort(); };
  }, [applyAuthState, authPost, clearAuthState, owns]);

  useEffect(() => {
    const authRequest = (config) => config.url?.includes("/api/auth/");
    const ownsRequest = (config) => owns(config._authSessionEpoch) && config._authSessionActor !== null &&
      config._authSessionActor === actorKey(session.current.user);
    const requestId = axios.interceptors.request.use((config) => {
      if (!authRequest(config) && config._authSessionEpoch === undefined) {
        config._authSessionEpoch = session.current.epoch;
        config._authSessionActor = actorKey(session.current.user);
      }
      return config;
    }, undefined, { synchronous: true });
    const responseId = axios.interceptors.response.use(
      (response) => {
        if (!authRequest(response.config) && !ownsRequest(response.config)) throw stale();
        return response;
      },
      async (error) => {
        const originalRequest = error.config;
        if (!originalRequest || (!authRequest(originalRequest) && !ownsRequest(originalRequest))) return Promise.reject(stale());
        if (error.response?.status !== 401 || !originalRequest || originalRequest._retry || authRequest(originalRequest)) {
          return Promise.reject(error);
        }
        const epoch = originalRequest._authSessionEpoch;
        const actor = session.current.user;
        if (!ownsRequest(originalRequest) || !actor) return Promise.reject(stale());
        originalRequest._retry = true;
        try {
          let refresh = session.current.refresh;
          if (!refresh || refresh.epoch !== epoch) {
            const promise = authPost(epoch, "refresh", {}).then((response) => {
              if (!owns(epoch)) throw stale();
              if (response.data?.user && !sameActor(actor, response.data.user)) throw stale();
              const nextToken = response.data?.token ?? null;
              applyAuthState(response.data?.user ?? actor, nextToken);
              return nextToken;
            });
            refresh = { epoch, promise };
            session.current.refresh = refresh;
          }
          const nextToken = await refresh.promise;
          if (!ownsRequest(originalRequest)) throw stale();
          originalRequest.headers = {
            ...originalRequest.headers,
            Authorization: nextToken ? `Bearer ${nextToken}` : null,
          };
          return axios(originalRequest);
        } catch (refreshError) {
          if (owns(epoch)) { session.current.epoch += 1; clearAuthState(); setIsLoading(false); }
          return Promise.reject(refreshError);
        } finally {
          if (session.current.refresh?.epoch === epoch) session.current.refresh = null;
        }
      },
    );
    return () => {
      axios.interceptors.request.eject(requestId);
      axios.interceptors.response.eject(responseId);
    };
  }, [applyAuthState, authPost, clearAuthState, owns, stale]);

  const login = useCallback(async (email, password) => {
    if (!session.current.alive) return { success: false, error: SUPERSEDED };
    const epoch = ++session.current.epoch;
    session.current.initController?.abort();
    clearAuthState();
    setIsLoading(true);
    try {
      const response = await authPost(epoch, "login", { email, password });
      if (!owns(epoch)) return { success: false, error: SUPERSEDED };
      const { token: newToken, user: userData } = response.data;
      applyAuthState(userData, newToken ?? null);
      return { success: true, user: userData };
    } catch (error) {
      return { success: false, error: owns(epoch)
        ? getApiErrorMessage(error, "Nu te-am putut conecta. Verifică datele și încearcă din nou.")
        : SUPERSEDED };
    } finally {
      if (owns(epoch)) setIsLoading(false);
    }
  }, [applyAuthState, authPost, clearAuthState, owns]);

  const logout = useCallback(async () => {
    if (!session.current.alive) return;
    const epoch = ++session.current.epoch;
    session.current.initController?.abort();
    clearAuthState();
    setIsLoading(false);
    // Clear locally before waiting; a late logout never clears a subsequent login.
    await authPost(epoch, "logout", {});
  }, [authPost, clearAuthState]);

  const value = useMemo(() => ({ user, token, login, logout, isLoading }), [user, token, login, logout, isLoading]);
  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) throw new Error("useAuth must be used within AuthProvider");
  return context;
};
