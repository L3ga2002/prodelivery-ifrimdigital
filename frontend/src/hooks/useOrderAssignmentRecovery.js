import { useMemo, useRef } from "react";
import { createRecoveryTransport } from "../lib/recoveryTransport";
import { useRecoveryControllerLifecycle } from "./useRecoveryControllerLifecycle";
import { createOrderAssignmentRecovery, validAssignmentActor, validAssignmentToken } from "../lib/orderAssignmentRecovery";

export const useOrderAssignmentRecovery = (actorId, apiUrl, isOnline, token = null) => {
  const online = useRef(isOnline); online.current = isOnline;
  const current = useRef(null), alive = useRef(false);
  const controller = useMemo(() => {
    if (!validAssignmentActor(actorId) || !validAssignmentToken(token) || typeof apiUrl !== "string") return null;
    const api = createRecoveryTransport({ apiUrl, actorId, getToken: () => token });
    const storage = { getItem: (key) => window.localStorage.getItem(key),
      setItem: (key, value) => window.localStorage.setItem(key, value), removeItem: (key) => window.localStorage.removeItem(key) };
    const instance = createOrderAssignmentRecovery({ actorId, api, durableStorage: storage,
      crypto: window.crypto, locks: navigator.locks, isOnline: () => online.current,
      isOwnerActive: () => alive.current && current.current === instance });
    return instance;
  }, [actorId, apiUrl, token]);
  const lifecycle = useRecoveryControllerLifecycle({ controller, actorId, apiUrl, isOnline, current: current, alive, kind: "assign" });
  return { ...lifecycle, available: Boolean(controller) && typeof navigator.locks?.request === "function" };
};
