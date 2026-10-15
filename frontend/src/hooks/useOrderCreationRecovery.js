import { useMemo, useRef } from "react";
import { createRecoveryTransport } from "../lib/recoveryTransport";
import { useRecoveryControllerLifecycle } from "./useRecoveryControllerLifecycle";
import { createOrderRecovery } from "../lib/orderCreationRecovery";
import { canonicalApiBase } from "../lib/orderFinancePreview";

export const useOrderCreationRecovery = (actorId, apiUrl, isOnline, token = null, context = null) => {
  const alive = useRef(false), currentController = useRef(null);
  const onlineRef = useRef(isOnline);
  const tokenRef = useRef(token);
  onlineRef.current = isOnline;
  tokenRef.current = token;
  const controller = useMemo(() => {
    if (typeof actorId !== "string" || !actorId.trim() || actorId.length > 120 || actorId !== actorId.trim()) return null;
    const api = createRecoveryTransport({ apiUrl, actorId, getToken: () => tokenRef.current });
    let financialOptions = {};
    if (context) {
      try {
        const apiBase = canonicalApiBase(apiUrl);
        financialOptions = { apiBase, actorRole: context.role, actorRestaurantId: context.restaurant_id ?? null,
          financialApi: createRecoveryTransport({ apiUrl: apiBase, actorId, getToken: () => tokenRef.current }) };
      } catch { financialOptions = { actorRole: context.role }; }
    }
    // Storage getters themselves can throw in restricted browser modes.
    const storage = (name) => ({
      getItem: (key) => window[name].getItem(key),
      setItem: (key, value) => window[name].setItem(key, value),
      removeItem: (key) => window[name].removeItem(key),
    });
    const instance = createOrderRecovery({ actorId, api, ...financialOptions, durableStorage: storage("localStorage"),
      draftStorage: storage("sessionStorage"), locks: navigator.locks, crypto: window.crypto,
      isOnline: () => onlineRef.current,
      isOwnerActive: () => alive.current && currentController.current === instance });
    return instance;
  }, [actorId, apiUrl, context?.role, context?.restaurant_id, context ? token : null]);
  const lifecycle = useRecoveryControllerLifecycle({ controller, actorId, apiUrl, isOnline, current: currentController, alive, kind: "create" });
  return { ...lifecycle, available: Boolean(controller) && typeof navigator.locks?.request === "function",
    captureIntent: () => controller?.captureIntent(), isCurrentIntent: (proof, acknowledged = false) => controller?.isCurrentIntent(proof, acknowledged) === true };
};
