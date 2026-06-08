import { createContext, useContext, useState, useEffect, useMemo, useCallback } from "react";
import axios from "axios";

const AuthContext = createContext(null);

const API_URL = process.env.REACT_APP_BACKEND_URL;
axios.defaults.withCredentials = true;


const formatApiErrorDetail = (detail) => {
  if (detail == null) return "Something went wrong. Please try again.";
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) {
    return detail
      .map((entry) => (entry && typeof entry.msg === "string" ? entry.msg : JSON.stringify(entry)))
      .filter(Boolean)
      .join(" ");
  }
  if (detail && typeof detail.msg === "string") return detail.msg;
  return String(detail);
};

export const AuthProvider = ({ children }) => {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [isLoading, setIsLoading] = useState(true);

  const clearAuthState = useCallback(() => {
    setToken(null);
    setUser(null);
    delete axios.defaults.headers.common.Authorization;
  }, []);

  const applyAuthState = useCallback((userData, accessToken = null) => {
    setUser(userData);
    setToken(accessToken);
    if (accessToken) {
      axios.defaults.headers.common.Authorization = `Bearer ${accessToken}`;
    } else {
      delete axios.defaults.headers.common.Authorization;
    }
  }, []);

  useEffect(() => {
    const initAuth = async () => {
      try {
        const meResponse = await axios.get(`${API_URL}/api/auth/me`);
        applyAuthState(meResponse.data);
      } catch (error) {
        if (error.response?.status === 401) {
          try {
            const refreshResponse = await axios.post(`${API_URL}/api/auth/refresh`, {});
            const refreshedToken = refreshResponse.data?.token ?? null;
            const meResponse = await axios.get(`${API_URL}/api/auth/me`);
            applyAuthState(meResponse.data, refreshedToken);
          } catch {
            clearAuthState();
          }
        } else {
          clearAuthState();
        }
      } finally {
        setIsLoading(false);
      }
    };

    initAuth();
  }, [applyAuthState, clearAuthState]);

  useEffect(() => {
    const interceptorId = axios.interceptors.response.use(
      (response) => response,
      async (error) => {
        const originalRequest = error.config;

        if (
          error.response?.status === 401 &&
          originalRequest &&
          !originalRequest._retry &&
          !originalRequest.url?.includes("/api/auth/")
        ) {
          originalRequest._retry = true;
          try {
            const refreshResponse = await axios.post(`${API_URL}/api/auth/refresh`, {});
            const refreshedToken = refreshResponse.data?.token ?? null;
            if (refreshedToken) {
              axios.defaults.headers.common.Authorization = `Bearer ${refreshedToken}`;
            }
            return axios(originalRequest);
          } catch (refreshError) {
            clearAuthState();
            return Promise.reject(refreshError);
          }
        }

        return Promise.reject(error);
      },
    );

    return () => {
      axios.interceptors.response.eject(interceptorId);
    };
  }, [clearAuthState]);

  const login = useCallback(async (email, password) => {
    try {
      const response = await axios.post(`${API_URL}/api/auth/login`, {
        email,
        password,
      });

      const { token: newToken, user: userData } = response.data;

      applyAuthState(userData, newToken ?? null);

      return { success: true, user: userData };
    } catch (error) {
      return {
        success: false,
        error: formatApiErrorDetail(error.response?.data?.detail) || error.message,
      };
    }
  }, [applyAuthState]);

  const logout = useCallback(async () => {
    try {
      await axios.post(`${API_URL}/api/auth/logout`, {});
    } finally {
      clearAuthState();
    }
  }, [clearAuthState]);

  const value = useMemo(
    () => ({ user, token, login, logout, isLoading }),
    [user, token, login, logout, isLoading],
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
};

export const useAuth = () => {
  const context = useContext(AuthContext);
  if (!context) {
    throw new Error("useAuth must be used within AuthProvider");
  }
  return context;
};
