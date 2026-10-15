import { useMemo, useRef } from "react";
import { createRecoveryTransport } from "../lib/recoveryTransport";
import { useRecoveryControllerLifecycle } from "./useRecoveryControllerLifecycle";
import { createOrderEditingRecovery } from "../lib/orderEditingRecovery";

export const useOrderEditingRecovery = (actorId, apiUrl, isOnline, token = null) => {
  const online = useRef(isOnline);
  online.current = isOnline;
  const current = useRef(null), alive = useRef(false);
  const controller = useMemo(() => {
    if (typeof actorId !== "string" || !actorId.trim() || actorId.length > 120 || actorId !== actorId.trim() ||
      Array.from(actorId).some((c) => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127)) return null;
    const api = createRecoveryTransport({ apiUrl, actorId, getToken: () => token });
    const storage = (name) => ({ getItem: (key) => window[name].getItem(key),
      setItem: (key, value) => window[name].setItem(key, value), removeItem: (key) => window[name].removeItem(key) });
    const instance = createOrderEditingRecovery({ actorId, api, durableStorage: storage("localStorage"),
      draftStorage: storage("sessionStorage"), crypto: window.crypto, locks: navigator.locks,
      isOnline: () => online.current, isOwnerActive: () => alive.current && current.current === instance });
    return instance;
  }, [actorId, apiUrl, token]);
  const lifecycle = useRecoveryControllerLifecycle({ controller, actorId, apiUrl, isOnline, current: current, alive, kind: "edit" });
  return { ...lifecycle, available: Boolean(controller) && typeof navigator.locks?.request === "function" };
};
