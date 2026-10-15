import { useRecoveryAction } from "./useRecoveryAction";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createRecoveryTransport } from "../lib/recoveryTransport";
import { CheckCircle2, RefreshCw } from "lucide-react";
import { Button } from "../components/ui/button";
import { createOrderStatusRecovery, statusTerminal, statusApplied, statusFailureMessage,
  validStatusActor, validStatusToken, hasStatusRevision } from "../lib/orderStatusRecovery";

export const useOrderStatusRecovery = (actor, apiUrl, isOnline, token = null, probeCapability = true) => {
  const online = useRef(isOnline); online.current = isOnline;
  const current = useRef(null), alive = useRef(false), flight = useRef(null), capEpoch = useRef(0);
  const session = useRef(null), suspended = useRef(null), lifecycleEpoch = useRef(0), capabilityOwner = useRef(null);
  const [view, setView] = useState({});
  const actorId = actor?.id, role = actor?.role, driverId = actor?.driver_id, restaurantId = actor?.restaurant_id;
  const disabled = actor?.is_disabled, accountDisabled = actor?.account_disabled;
  const controller = useMemo(() => {
    const ownerActor = { id: actorId, role, driver_id: driverId, restaurant_id: restaurantId,
      ...(disabled === undefined ? {} : { is_disabled: disabled }),
      ...(accountDisabled === undefined ? {} : { account_disabled: accountDisabled }) };
    if (!validStatusActor(ownerActor) || !validStatusToken(token) || typeof apiUrl !== "string") return null;
    const api = createRecoveryTransport({ apiUrl, actorId, getToken: () => token });
    const storage = (name) => ({ getItem: (key) => window[name].getItem(key),
      setItem: (key, value) => window[name].setItem(key, value), removeItem: (key) => window[name].removeItem(key) });
    const instance = createOrderStatusRecovery({ actor: ownerActor, api, durableStorage: storage("localStorage"),
      draftStorage: storage("sessionStorage"), crypto: window.crypto, locks: navigator.locks,
      isOnline: () => online.current, isOwnerActive: () => alive.current && current.current === instance,
      onRecordChange: (record) => {
        if (alive.current && current.current === instance) setView((v) => ({ ...(v.owner === instance ? v : {}), record, owner: instance }));
      } });
    return instance;
  }, [actorId, role, driverId, restaurantId, disabled, accountDisabled, apiUrl, token]);
  current.current = controller;
  session.current = { controller, actorId, role, driverId, restaurantId, apiUrl };
  const valid = useCallback(() => alive.current && current.current === controller, [controller]);
  const bumpLifecycle = useCallback(() => { lifecycleEpoch.current++; capEpoch.current++; }, []);
  const update = useCallback((patch) => {
    if (valid()) setView((v) => ({ ...(v.owner === controller ? v : {}), ...patch, owner: controller }));
  }, [controller, valid]);
  const read = useCallback(() => {
    if (!valid() || !controller || suspended.current?.owner === controller) return;
    try { update({ record: controller.snapshot(), storageInvalid: controller.storageBlocked() }); }
    catch (e) { update({ storageInvalid: e.code === "STORAGE_UNAVAILABLE" || controller.storageBlocked(), error: e.message, errorCode: e.code }); }
  }, [controller, valid, update]);
  const perform = useRecoveryAction({ controller, valid, suspended, flight, epoch: lifecycleEpoch, update, read });
  const verifyCapability = useCallback(async () => {
    if (!controller || !valid() || suspended.current?.owner === controller) return;
    capabilityOwner.current = controller;
    const epoch = ++capEpoch.current;
    update({ checkingCapability: true, capability: { ready: false, enabled: false }, capabilityError: "" });
    try { const enabled = await controller.capability(); if (epoch === capEpoch.current) { update({ capability: { ready: true, enabled } }); return valid() ? enabled : null; } return null; }
    catch { if (epoch === capEpoch.current) update({ capabilityError: "Disponibilitatea statusului nu poate fi verificata." }); return null; }
    finally { if (epoch === capEpoch.current) update({ checkingCapability: false }); }
  }, [controller, valid, update]);
  const revalidateSession = useCallback(async () => {
    const suspension = suspended.current;
    if (!controller || !valid() || suspension?.owner !== controller || !suspension.persisted || suspension.restoring) return null;
    suspension.restoring = true; update({ checkingSession: true, error: "", errorCode: "" });
    try {
      await controller.restoreSession();
      if (!valid() || suspended.current !== suspension) return null;
      suspended.current = null; update({ sessionSuspended: false, error: "", errorCode: "" }); read();
      if (capabilityOwner.current === controller) await verifyCapability();
      return valid() && !suspended.current ? true : null;
    } catch (e) {
      if (valid() && suspended.current === suspension) update({ error: e.message, errorCode: e.code });
      return null;
    } finally {
      suspension.restoring = false;
      if (valid() && (!suspended.current || suspended.current === suspension)) update({ checkingSession: false });
    }
  }, [controller, valid, update, read, verifyCapability]);
  useEffect(() => {
    alive.current = true; suspended.current = null; controller?.activate();
    update({ busy: flight.current?.owner === controller, sessionSuspended: false, checkingSession: false }); read();
    const epoch = lifecycleEpoch.current;
    let disposed = false;
    const recoverInitial = () => {
      if (disposed || !valid() || epoch !== lifecycleEpoch.current || suspended.current?.owner === controller || !online.current) return;
      try { const record = controller?.snapshot(); if (record && !statusTerminal(record.receipt)) void perform("recover"); }
      catch { read(); }
    };
    let initial; try { initial = controller?.snapshot(); } catch { /* Invalid storage remains retained and visible. */ }
    if (initial && !statusTerminal(initial.receipt) && online.current) {
      // StrictMode may retain an earlier lifecycle's flight; retry initialization once after it settles.
      const previous = flight.current;
      if (previous?.owner === controller) previous.settled.then(recoverInitial);
      else recoverInitial();
    }
    const pageHide = (event) => {
      bumpLifecycle();
      suspended.current = { owner: controller, persisted: event.persisted === true, restoring: false };
      update({ sessionSuspended: true, checkingSession: false, checkingCapability: false, capability: { ready: false, enabled: false } });
      try { controller?.deactivate({ preserveDraft: true }); } catch { /* Durable intent is retained. */ }
    };
    const pageShow = (event) => { if (event.persisted === true) revalidateSession(); };
    window.addEventListener("storage", read); window.addEventListener("pagehide", pageHide); window.addEventListener("pageshow", pageShow);
    return () => {
      disposed = true; alive.current = false; bumpLifecycle();
      window.removeEventListener("storage", read); window.removeEventListener("pagehide", pageHide); window.removeEventListener("pageshow", pageShow);
      const retire = (preserveDraft = false) => { try { controller?.deactivate({ preserveDraft }); } catch { /* A retired controller cannot send again. */ } };
      if (current.current !== controller) retire(Boolean(session.current?.controller && session.current.actorId === actorId &&
        session.current.role === role && session.current.driverId === driverId && session.current.restaurantId === restaurantId && session.current.apiUrl === apiUrl));
      else queueMicrotask(() => { if (!alive.current || current.current !== controller) retire(); });
    };
  }, [controller, update, read, perform, valid, revalidateSession, bumpLifecycle, actorId, role, driverId, restaurantId, apiUrl]);
  useEffect(() => { if (isOnline && probeCapability) verifyCapability(); }, [isOnline, probeCapability, verifyCapability]);
  const state = view.owner === controller ? view : {};
  const available = Boolean(controller) && typeof navigator.locks?.request === "function";
  const capability = state.capability || { ready: false, enabled: false };
  return { ...state, available, capability,
    error: !controller ? "Sesiunea nu permite modificarea statusului." : state.error || state.capabilityError || "",
    blocked: !available || state.sessionSuspended || state.storageInvalid || state.busy || Boolean(state.record),
    canSubmit: (order) => available && !state.sessionSuspended && !state.storageInvalid && !state.busy && !state.record && (!hasStatusRevision(order) || (capability.ready && capability.enabled)),
    submit: useCallback((command) => perform("submit", command), [perform]),
    submitLegacy: useCallback((command) => perform("submitLegacy", command), [perform]),
    recover: useCallback(() => perform("recover"), [perform]),
    refreshForNewAttempt: useCallback(() => perform("refreshForNewAttempt"), [perform]),
    acknowledge: useCallback(() => perform("acknowledge"), [perform]), verifyCapability, revalidateSession };
};

// Shared compact state stays outside the active-order list, including after delivery/reload.
export const OrderStatusRecoveryPanel = ({ recovery, isOnline, onAcknowledged, onRetry, order }) => {
  const { record, busy, error, storageInvalid, available, sessionSuspended, checkingSession } = recovery;
  const disabledVersioned = hasStatusRevision(order) && !recovery.capability.enabled;
  if (!record && !error && available && !disabledVersioned && !sessionSuspended) return null;
  const receipt = record?.receipt;
  return <section className="my-3 space-y-2 break-words border-y border-current/20 py-3 text-sm" data-testid="status-recovery-panel">
    {error && <p role="alert" data-testid="status-recovery-error">{error}</p>}
    {!available && <p role="alert">Sesiunea sau browserul nu permite protejarea statusului intre taburi.</p>}
    {sessionSuspended && <p role="status" data-testid="status-session-state">{checkingSession ? "Sesiunea se verifica. Intentia ramane pastrata." : "Sesiunea necesita reverificare inainte de reluare. Intentia ramane pastrata."}</p>}
    {!record && disabledVersioned && <p role="status" data-testid="status-capability-state">{recovery.capability.ready ? "Statusul versionat este dezactivat. Comanda nu a fost modificata; fluxul legacy este blocat." : "Disponibilitatea statusului versionat nu este confirmata."}</p>}
    {record && <div role="status" data-testid="status-recovery-state">
      <p>Comanda {record.order_id}: {record.status}</p>
      <p>{statusApplied(receipt) ? "Status confirmat." : receipt?.state === "rejected" ? statusFailureMessage(receipt.error_code) : "Status neconfirmat. Intentia ramane pastrata."}</p>
    </div>}
    <div className="flex flex-wrap gap-2">
      {sessionSuspended && <Button variant="outline" onClick={recovery.revalidateSession} disabled={!isOnline || checkingSession || !available} data-testid="status-session-button"><RefreshCw className="mr-2 h-4 w-4" />Reverifica sesiunea</Button>}
      {record && !statusTerminal(receipt) && <Button variant="outline" className="h-auto min-h-9 whitespace-normal" onClick={recovery.recover} disabled={sessionSuspended || busy || !isOnline || storageInvalid || !available} data-testid="status-recover-button"><RefreshCw className="mr-2 h-4 w-4" />Verifica aceeasi operatie</Button>}
      {receipt?.state === "rejected" && onRetry && <Button variant="outline" className="h-auto min-h-9 whitespace-normal" onClick={async () => { const fresh = await recovery.refreshForNewAttempt(); if (fresh) onRetry(fresh); }} disabled={sessionSuspended || busy || !isOnline || storageInvalid || !available} data-testid="status-retry-button"><RefreshCw className="mr-2 h-4 w-4" />Reincarca pentru o noua incercare</Button>}
      {record && statusTerminal(receipt) && <Button className="h-auto min-h-9 whitespace-normal" onClick={async () => { if (await recovery.acknowledge()) onAcknowledged?.(); }} disabled={sessionSuspended || busy || storageInvalid || !available} data-testid="status-acknowledge-button"><CheckCircle2 className="mr-2 h-4 w-4" />Confirma rezultatul</Button>}
      {!record && recovery.capability?.ready !== true && <Button variant="outline" onClick={recovery.verifyCapability} disabled={sessionSuspended || !isOnline || recovery.checkingCapability || !available} aria-label="Verifica disponibilitatea statusului" title="Verifica disponibilitatea statusului" data-testid="status-capability-button"><RefreshCw className="h-4 w-4" /></Button>}
    </div>
  </section>;
};
