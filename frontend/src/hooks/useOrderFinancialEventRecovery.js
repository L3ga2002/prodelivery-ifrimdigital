import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRecoveryTransport } from "../lib/recoveryTransport";
import { createOrderFinancialEventRecovery, financialEventTerminal, validFinancialEventActor, validFinancialEventToken } from "../lib/orderFinancialEventRecovery";
import { useRecoveryAction } from "./useRecoveryAction";

export const useOrderFinancialEventRecovery = (actor, apiUrl, isOnline, token = null) => {
  const current = useRef(null), alive = useRef(false), online = useRef(isOnline);
  const flight = useRef(null), epoch = useRef(0), suspended = useRef(null);
  const [view, setView] = useState({});
  online.current = isOnline;
  const actorId = actor?.id, role = actor?.role, restaurantId = actor?.restaurant_id, driverId = actor?.driver_id;
  const disabled = actor?.is_disabled, accountDisabled = actor?.account_disabled;
  const controller = useMemo(() => {
    const ownerActor = { id: actorId, role, restaurant_id: restaurantId, driver_id: driverId,
      ...(disabled === undefined ? {} : { is_disabled: disabled }),
      ...(accountDisabled === undefined ? {} : { account_disabled: accountDisabled }) };
    if (!validFinancialEventActor(ownerActor) || !validFinancialEventToken(token) || typeof apiUrl !== "string") return null;
    const api = createRecoveryTransport({ apiUrl, actorId, getToken: () => token });
    const storage = { getItem: (key) => window.localStorage.getItem(key),
      setItem: (key, value) => window.localStorage.setItem(key, value), removeItem: (key) => window.localStorage.removeItem(key) };
    const instance = createOrderFinancialEventRecovery({ actor: ownerActor, api, durableStorage: storage,
      locks: navigator.locks, crypto: window.crypto, isOnline: () => online.current,
      isOwnerActive: () => alive.current && current.current === instance });
    return instance;
  }, [actorId, role, restaurantId, driverId, disabled, accountDisabled, apiUrl, token]);
  current.current = controller;
  const valid = useCallback(() => alive.current && current.current === controller, [controller]);
  const bumpEpoch = useCallback(() => { epoch.current++; }, []);
  const update = useCallback((patch) => {
    if (valid()) setView((v) => ({ ...(v.owner === controller ? v : {}), ...patch, owner: controller }));
  }, [controller, valid]);
  const read = useCallback(() => {
    if (!controller || !valid() || suspended.current?.owner === controller) return;
    try { update({ record: controller.snapshot(), storageInvalid: controller.storageBlocked() }); }
    catch (error) { update({ storageInvalid: controller.storageBlocked(), error: error.message, errorCode: error.code }); }
  }, [controller, valid, update]);
  const perform = useRecoveryAction({ controller, valid, suspended, flight, epoch, update, read });
  const run = useCallback(async (action, value) => {
    if (!valid() || !controller || suspended.current?.owner === controller || flight.current?.owner === controller) return null;
    const generation = epoch.current;
    update({ notAdmitted: false });
    const result = await perform(action, value);
    if (!valid() || generation !== epoch.current || result === null) return null;
    if (action === "capability") update({ capability: { ready: true, enabled: result } });
    else update({ notAdmitted: result?.not_admitted === true });
    return result;
  }, [controller, valid, update, perform]);
  const revalidateSession = useCallback(async () => {
    const suspension = suspended.current;
    if (!controller || !valid() || suspension?.owner !== controller || !suspension.persisted || suspension.restoring) return null;
    suspension.restoring = true; update({ checkingSession: true, error: "", errorCode: "" });
    try {
      await controller.restoreSession();
      if (!valid() || suspended.current !== suspension) return null;
      suspended.current = null; update({ sessionSuspended: false, error: "", errorCode: "" }); read();
      // Session reactivation can only look up the existing intention.
      if (online.current) await run(controller.snapshot() ? "recover" : "capability");
      return valid() && !suspended.current ? true : null;
    } catch (error) {
      if (valid() && suspended.current === suspension) update({ error: error.message, errorCode: error.code });
      return null;
    } finally {
      suspension.restoring = false;
      if (valid() && (!suspended.current || suspended.current === suspension)) update({ checkingSession: false });
    }
  }, [controller, valid, update, read, run]);
  useEffect(() => {
    alive.current = true; suspended.current = null; controller?.activate();
    const generation = ++epoch.current;
    let disposed = false;
    update({ busy: flight.current?.owner === controller, sessionSuspended: false, checkingSession: false }); read();
    const restore = () => {
      if (disposed || !valid() || epoch.current !== generation || suspended.current || !online.current) return;
      try { const r = controller?.snapshot(); if (r && !financialEventTerminal(r.receipt)) void run("recover"); else if (!r) void run("capability"); } catch { read(); }
    };
    const prior = flight.current;
    if (prior?.owner === controller) prior.settled.then(restore); else restore();
    const storageChanged = () => { if (!suspended.current) read(); };
    const pageHide = (event) => {
      bumpEpoch();
      suspended.current = { owner: controller, persisted: event.persisted === true, restoring: false };
      update({ sessionSuspended: true, checkingSession: false, notAdmitted: false, capability: { ready: false, enabled: false } });
      controller?.deactivate();
    };
    const pageShow = (event) => { if (event.persisted === true) void revalidateSession(); };
    window.addEventListener("storage", storageChanged); window.addEventListener("pagehide", pageHide); window.addEventListener("pageshow", pageShow);
    return () => {
      disposed = true; alive.current = false; bumpEpoch(); controller?.deactivate();
      window.removeEventListener("storage", storageChanged); window.removeEventListener("pagehide", pageHide); window.removeEventListener("pageshow", pageShow);
    };
  }, [controller, valid, update, read, run, revalidateSession, bumpEpoch]);
  useEffect(() => {
    if (!isOnline || !controller || !valid() || suspended.current) return;
    try { const r = controller.snapshot(); if (r && !financialEventTerminal(r.receipt)) void run("recover"); else if (!r) void run("capability"); } catch { read(); }
  }, [controller, isOnline, valid, run, read]);
  const state = view.owner === controller ? view : {};
  const available = Boolean(controller);
  const durableAvailable = available && typeof navigator.locks?.request === "function";
  return { ...state, available, durableAvailable,
    captureLease: useCallback(() => ({ owner: controller, generation: epoch.current }), [controller]),
    isCurrentLease: useCallback((lease) => Boolean(controller) && valid() && !suspended.current &&
      lease?.owner === controller && lease.generation === epoch.current, [controller, valid]),
    error: !available ? "Sesiunea nu permite operațiile de numerar." : state.error || "",
    blocked: !available || state.sessionSuspended || state.storageInvalid || state.busy || Boolean(state.record),
    chooseProtocol: useCallback(() => run("capability"), [run]),
    submit: useCallback((command) => run("submit", command), [run]),
    recover: useCallback(() => run("recover"), [run]),
    resend: useCallback(() => run("resend"), [run]),
    resume: useCallback(() => run("resume"), [run]),
    acknowledge: useCallback(() => run("acknowledge"), [run]), revalidateSession };
};
