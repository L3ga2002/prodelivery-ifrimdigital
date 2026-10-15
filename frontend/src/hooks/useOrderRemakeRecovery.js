import { useMemo, useRef } from "react";
import { createOrderRemakeRecovery } from "../lib/orderRemakeRecovery";
import { canonicalApiBase, validFinancialEventActor, validFinancialEventToken } from "../lib/orderRemakeFinance";
import { createRecoveryTransport } from "../lib/recoveryTransport";
import { useRecoveryControllerLifecycle } from "./useRecoveryControllerLifecycle";

export const useOrderRemakeRecovery = (actor, apiUrl, isOnline, token, refreshList) => {
  const alive = useRef(false), current = useRef(null), latest = useRef(null);
  latest.current = { isOnline, token, refreshList };
  const controller = useMemo(() => {
    if (actor?.role !== "restaurant" || !validFinancialEventActor(actor) || !validFinancialEventToken(token)) return null;
    let apiBase; try { apiBase = canonicalApiBase(apiUrl); } catch { return null; }
    const storage = (name) => ({ getItem: (key) => window[name].getItem(key), setItem: (key, value) => window[name].setItem(key, value), removeItem: (key) => window[name].removeItem(key) });
    const instance = createOrderRemakeRecovery({ actor, apiBase,
      api: createRecoveryTransport({ apiUrl: apiBase, actorId: actor.id, getToken: () => latest.current.token }),
      durableStorage: storage("localStorage"), draftStorage: storage("sessionStorage"), locks: navigator.locks, crypto: window.crypto,
      isOnline: () => latest.current.isOnline, isOwnerActive: () => alive.current && current.current === instance,
      refreshList: (guard) => latest.current.refreshList?.(guard) });
    return instance;
  }, [actor?.id, actor?.role, actor?.restaurant_id, actor?.account_disabled, actor?.is_disabled, apiUrl, token]);
  const lifecycle = useRecoveryControllerLifecycle({ controller, actorId: actor?.id, apiUrl, isOnline, current, alive, kind: "remake" });
  return { ...lifecycle, available: Boolean(controller) && typeof navigator.locks?.request === "function",
    blocked: Boolean(!controller || lifecycle.record || lifecycle.storageInvalid || lifecycle.busy || lifecycle.sessionSuspended),
    captureIntent: () => controller?.captureIntent(), isCurrentIntent: (proof, acknowledged = false) => controller?.isCurrentIntent(proof, acknowledged) === true,
    savedDraft: () => controller?.savedDraft() ?? null };
};
