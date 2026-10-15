import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { createOperationalReporting, reportApplied, reportTerminal } from "../lib/operationalReporting";

export const useOperationalReporting = (actor, scope, apiUrl, token, isOnline) => {
  const alive = useRef(false), current = useRef(null), online = useRef(isOnline), flight = useRef(null);
  const lifecycle = useRef(0), suspended = useRef(false), receipts = useRef(new WeakMap());
  online.current = isOnline;
  const [view, setView] = useState({});
  const actorId = actor?.id, role = actor?.role, restaurantId = actor?.restaurant_id, driverId = actor?.driver_id;
  const controller = useMemo(() => {
    if (!actorId || !scope || !apiUrl || (token != null && (typeof token !== "string" || !token.trim()))) return null;
    let transport;
    const connection = () => { if (!transport) transport = axios.create({ withCredentials: true }); return transport; };
    const options = (config) => ({ ...config, headers: { Authorization: token ? `Bearer ${token}` : null, "X-Expected-Actor-ID": actorId } });
    const api = { get: (path, config) => connection().get(`${apiUrl}${path}`, options(config)),
      patch: (path, data, config) => connection().patch(`${apiUrl}${path}`, data, options(config)),
      post: (path, data, config) => connection().post(`${apiUrl}${path}`, data, options(config)) };
    const instance = createOperationalReporting({ actor: { id: actorId, role, restaurant_id: restaurantId, driver_id: driverId }, scope, api,
      storage: { getItem: (key) => window.sessionStorage.getItem(key), setItem: (key, value) => window.sessionStorage.setItem(key, value), removeItem: (key) => window.sessionStorage.removeItem(key) },
      crypto: window.crypto, isOnline: () => online.current, isOwnerActive: () => alive.current && current.current === instance,
      onChange: (record) => { if (alive.current && current.current === instance) setView((v) => ({ ...(v.owner === instance ? v : {}), owner: instance, record })); } });
    return instance;
  }, [actorId, role, restaurantId, driverId, scope, apiUrl, token]);
  current.current = controller;
  const update = useCallback((patch) => { if (alive.current && current.current === controller) setView((v) => ({ ...(v.owner === controller ? v : {}), owner: controller, ...patch })); }, [controller]);
  const perform = useCallback(async (action, value) => {
    if (!controller || !alive.current || current.current !== controller || flight.current?.owner === controller) return null;
    const job = { owner: controller, epoch: lifecycle.current }; flight.current = job;
    const owns = () => alive.current && current.current === controller && lifecycle.current === job.epoch;
    update({ busy: true, error: "", errorCode: "" });
    try {
      const result = await controller[action](value);
      if (!owns()) return null;
      if (result && typeof result === "object") receipts.current.set(result, { controller, epoch: job.epoch });
      return result;
    }
    catch (error) { if (owns()) update({ error: error.message || "Operația nu este confirmată. Verifică intenția existentă.", errorCode: error.code || "UNCERTAIN" }); return null; }
    finally { if (flight.current === job) flight.current = null; if (owns()) update({ busy: false, record: controller.snapshot() }); }
  }, [controller, update]);
  const invalidate = useCallback(() => { lifecycle.current++; suspended.current = true; controller?.suspend(); }, [controller]);
  useEffect(() => {
    alive.current = true; suspended.current = false;
    try { controller?.activate(); update({ record: controller?.snapshot(), busy: false, suspended: false }); }
    catch (error) { update({ error: error.message, errorCode: error.code }); }
    const hide = () => { invalidate(); update({ suspended: true, busy: false }); };
    window.addEventListener("pagehide", hide);
    return () => { window.removeEventListener("pagehide", hide); invalidate(); alive.current = false; };
  }, [controller, update, invalidate]);
  const state = view.owner === controller ? view : {};
  const captureLease = useCallback(() => ({ controller, epoch: lifecycle.current }), [controller]);
  const isCurrentLease = useCallback((lease) => Boolean(lease && alive.current && current.current === controller && lease.controller === controller && lease.epoch === lifecycle.current && !suspended.current), [controller]);
  const active = async (action, value) => {
    const epoch = lifecycle.current;
    if (suspended.current) {
      const result = await perform("revalidate");
      if (!result || lifecycle.current !== epoch || current.current !== controller || !alive.current) return null;
      suspended.current = false; update({ suspended: false });
    }
    if (lifecycle.current !== epoch || current.current !== controller || !alive.current) return null;
    return perform(action, value);
  };
  return { ...state, available: Boolean(controller), blocked: controller?.blocked(),
    captureLease, isCurrentLease,
    pending: Boolean(state.record && !reportTerminal(state.record.receipt)),
    submit: (command) => active("submit", command), recover: (retry = false) => active("recover", retry),
    acknowledge: () => active("acknowledge"), applied: reportApplied(state.record?.receipt),
    isCurrentReceipt: (receipt) => { const lease = receipt && receipts.current.get(receipt); return Boolean(lease && alive.current && current.current === controller && lease.controller === controller && lease.epoch === lifecycle.current && !suspended.current); } };
};

export const OperationalReportingPanel = ({ reporting, onRecover }) => {
  if (!reporting.record && !reporting.error) return null;
  const receipt = reporting.record?.receipt;
  return <div role="status" className="my-3 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm" data-testid="operational-report-recovery">
    <p>{reporting.record?.command.operation_type === "close_day" ? "Închiderea zilei" : "Raportarea incidentului"}: {reporting.suspended ? "sesiune de reverificat" : reportApplied(receipt) ? "confirmată" : receipt?.state === "rejected" ? "refuzată" : "neconfirmată"}.</p>
    {reporting.error && <p>{reporting.error}</p>}
    {receipt?.state === "rejected" && <p>Cod: {receipt.error_code}</p>}
    <div className="mt-2 flex flex-wrap gap-2">
      {(reporting.pending || (reporting.suspended && reporting.record)) && <button type="button" disabled={reporting.busy} onClick={() => onRecover(false)} data-testid="operational-report-lookup">Verifică intenția</button>}
      {reporting.errorCode === "NOT_ADMITTED" && <button type="button" disabled={reporting.busy} onClick={() => onRecover(true)} data-testid="operational-report-retry">Retrimite aceeași intenție</button>}
      {reportTerminal(receipt) && !reporting.suspended && <button type="button" disabled={reporting.busy} onClick={reporting.acknowledge} data-testid="operational-report-ack">Am văzut rezultatul</button>}
    </div>
  </div>;
};
