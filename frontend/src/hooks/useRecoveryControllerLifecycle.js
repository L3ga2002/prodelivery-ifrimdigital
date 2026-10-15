import { useRecoveryAction } from "./useRecoveryAction";
import { useCallback, useEffect, useRef, useState } from "react";

// Shared page lifecycle for isolated transports. Controllers also fence every durable effect by epoch.
export const useRecoveryControllerLifecycle = ({ controller, actorId, apiUrl, isOnline, current, alive, kind }) => {
  current.current = controller;
  const flight = useRef(null), epoch = useRef(0), capEpoch = useRef(0), suspended = useRef(null);
  const session = useRef(null), online = useRef(isOnline);
  const financialQueued = useRef(null);
  online.current = isOnline; session.current = { controller, actorId, apiUrl };
  const [view, setView] = useState({});
  const bumpLifecycle = useCallback(() => { epoch.current++; capEpoch.current++; }, []);
  const valid = useCallback(() => alive.current && current.current === controller, [alive, current, controller]);
  const update = useCallback((patch) => {
    if (valid()) setView((v) => ({ ...(v.owner === controller ? v : {}), ...patch, owner: controller }));
  }, [controller, valid]);
  const read = useCallback(() => {
    if (!controller || !valid() || suspended.current?.owner === controller) return;
    try { update({ record: controller.snapshot(), ...(kind === "edit" ? { draft: controller.savedDraft() } : {}), storageInvalid: controller.storageBlocked?.() || false }); }
    catch (e) { update({ storageInvalid: e.code === "STORAGE_UNAVAILABLE" || controller.storageBlocked?.() || false, error: e.message, errorCode: e.code }); }
  }, [controller, valid, update, kind]);
  const perform = useRecoveryAction({ controller, valid, suspended, flight, epoch: epoch, update, read });
  const requestFinancialRecovery = useCallback(() => {
    if (!controller || !valid() || suspended.current?.owner === controller || !online.current) return;
    try { if (controller.snapshot()?.version !== 2) return; } catch { read(); return; }
    const pending = flight.current;
    if (pending?.owner === controller) {
      if (financialQueued.current?.job === pending) return;
      const queued = { job: pending }; financialQueued.current = queued;
      pending.settled.then(() => {
        if (financialQueued.current !== queued) return;
        financialQueued.current = null;
        if (valid() && !suspended.current && online.current) {
          try { if (controller.snapshot()?.version === 2) void perform("recover"); } catch { read(); }
        }
      });
    } else void perform("recover");
  }, [controller, valid, perform, read]);
  const verifyCapability = useCallback(async () => {
    if (!controller || !valid() || suspended.current?.owner === controller || !online.current) return;
    const generation = ++capEpoch.current;
    update({ checkingCapability: true, capability: { ready: false, enabled: false }, capabilityError: "" });
    try {
      const response = await controller.capability();
      const enabled = kind === "create" ? response?.data?.create_recovery_enabled : response;
      if ((kind === "create" && response?.status !== 200) || typeof enabled !== "boolean") throw new Error("CAPABILITY_UNAVAILABLE");
      if (generation === capEpoch.current) update({ capability: { ready: true, enabled } });
    } catch { if (generation === capEpoch.current) update({ capabilityError: "Disponibilitatea operatiei nu poate fi verificata." }); }
    finally { if (generation === capEpoch.current) update({ checkingCapability: false }); }
  }, [controller, valid, update, kind]);
  const revalidateSession = useCallback(async () => {
    const suspension = suspended.current;
    if (!controller || !valid() || suspension?.owner !== controller || !suspension.persisted || suspension.restoring) return null;
    suspension.restoring = true; update({ checkingSession: true, error: "", errorCode: "" });
    try {
      await controller.restoreSession();
      if (!valid() || suspended.current !== suspension) return null;
      suspended.current = null; update({ sessionSuspended: false, error: "", errorCode: "" }); read();
      requestFinancialRecovery();
      await verifyCapability();
      return valid() && !suspended.current ? true : null;
    } catch (e) { if (valid() && suspended.current === suspension) update({ error: e.message, errorCode: e.code }); return null; }
    finally { suspension.restoring = false; if (valid() && (!suspended.current || suspended.current === suspension)) update({ checkingSession: false }); }
  }, [controller, valid, update, read, verifyCapability, requestFinancialRecovery]);
  useEffect(() => {
    alive.current = true; suspended.current = null; controller?.activate();
    update({ busy: flight.current?.owner === controller, sessionSuspended: false, checkingSession: false }); read();
    const generation = ++epoch.current;
    let disposed = false;
    const initialRecovery = () => {
      if (disposed || !valid() || generation !== epoch.current || suspended.current?.owner === controller || !online.current) return;
      try { const record = controller?.snapshot(); if (record && (record.version === 2 || !record.receipt || record.receipt.state === "pending")) void perform("recover"); }
      catch { read(); }
    };
    const previous = flight.current;
    if (previous?.owner === controller) previous.settled.then(initialRecovery); else initialRecovery();
    const storageChanged = (event) => {
      if (!valid()) return;
      try {
        if (suspended.current?.owner === controller) { controller?.rememberStorage?.(event); return; }
        const financialHint = controller?.observeStorage?.(event); read();
        if (financialHint === true) requestFinancialRecovery();
      }
      catch (e) { update({ storageInvalid: true, error: e.message, errorCode: e.code }); }
    };
    const pageHide = (event) => {
      bumpLifecycle();
      suspended.current = { owner: controller, persisted: event.persisted === true, restoring: false };
      update({ sessionSuspended: true, checkingSession: false, checkingCapability: false, capability: { ready: false, enabled: false } });
      try { controller?.deactivate({ preserveDraft: true }); } catch { /* Intent is retained. */ }
    };
    const pageShow = (event) => { if (event.persisted === true) void revalidateSession(); };
    window.addEventListener("storage", storageChanged); window.addEventListener("pagehide", pageHide); window.addEventListener("pageshow", pageShow);
    window.addEventListener("focus", requestFinancialRecovery);
    return () => {
      disposed = true; alive.current = false; bumpLifecycle();
      window.removeEventListener("storage", storageChanged); window.removeEventListener("pagehide", pageHide); window.removeEventListener("pageshow", pageShow);
      window.removeEventListener("focus", requestFinancialRecovery);
      const retire = (preserveDraft = false) => { try { controller?.deactivate({ preserveDraft }); } catch { /* Retired owner cannot publish. */ } };
      if (current.current !== controller) retire(Boolean(session.current?.controller && session.current.actorId === actorId && session.current.apiUrl === apiUrl));
      else queueMicrotask(() => { if (!alive.current || current.current !== controller) retire(); });
    };
  }, [controller, actorId, apiUrl, alive, current, valid, update, read, perform, revalidateSession, bumpLifecycle, requestFinancialRecovery]);
  useEffect(() => { if (isOnline) { void verifyCapability(); requestFinancialRecovery(); } }, [isOnline, verifyCapability, requestFinancialRecovery]);
  const state = view.owner === controller ? view : {};
  return { ...state, capability: state.capability || { ready: false, enabled: false }, error: state.error || state.capabilityError || "",
    submit: useCallback((command) => perform("submit", command), [perform]), submitLegacy: useCallback((command) => perform("submitLegacy", command), [perform]),
    recover: useCallback(() => perform("recover"), [perform]), acknowledge: useCallback(() => perform("acknowledge"), [perform]),
    retrySubmission: useCallback(() => perform("retrySubmission"), [perform]), resume: useCallback(() => perform("resume"), [perform]),
    closeIntent: useCallback(() => perform("closeIntent"), [perform]),
    refreshForNewAttempt: useCallback(() => perform("refreshForNewAttempt"), [perform]), verifyCapability, revalidateSession };
};
