import { useEffect, useMemo, useState } from "react";
import { API_CONNECTION_EVENT } from "../lib/api";

const getOnlineState = () => (
  typeof navigator === "undefined" ? true : navigator.onLine !== false
);

export const useNetworkStatus = () => {
  const [isOnline, setIsOnline] = useState(getOnlineState);
  const [apiIssue, setApiIssue] = useState(null);

  useEffect(() => {
    const handleOnline = () => {
      setIsOnline(true);
      setApiIssue(null);
    };
    const handleOffline = () => {
      setIsOnline(false);
      setApiIssue("Nu ai conexiune la internet. Acțiunile se vor putea trimite după reconectare.");
    };
    const handleApiConnection = (event) => {
      if (event.detail?.status === "ok") {
        setApiIssue(null);
        return;
      }
      if (event.detail?.status === "error") {
        setApiIssue(event.detail.message || "Serverul nu răspunde momentan.");
      }
    };

    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    window.addEventListener(API_CONNECTION_EVENT, handleApiConnection);

    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
      window.removeEventListener(API_CONNECTION_EVENT, handleApiConnection);
    };
  }, []);

  return useMemo(() => ({
    isOnline,
    apiIssue,
    hasConnectionProblem: !isOnline || Boolean(apiIssue),
    message: !isOnline
      ? "Nu ai conexiune la internet. Acțiunile se vor putea trimite după reconectare."
      : apiIssue,
  }), [apiIssue, isOnline]);
};
