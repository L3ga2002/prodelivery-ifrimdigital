import { custodyId } from "../lib/orderCustody";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { useOperationalReporting, OperationalReportingPanel } from "../hooks/useOperationalReporting";
import { reportApplied } from "../lib/operationalReporting";
import { Button } from "./ui/button";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "./ui/dialog";

const labels = { missing_product: "Produs lipsă", damaged_product: "Produs deteriorat", pickup_blocked: "Ridicare blocată", delivery_blocked: "Livrare blocată", other: "Alt incident" };
export const IncidentHistory = ({ actor, token, apiUrl, isOnline, order, reloadKey, onSelectBlockedIncident, selectionDisabled = false }) => {
  const session = useMemo(() => ({ actorId: actor?.id, role: actor?.role, restaurantId: actor?.restaurant_id, driverId: actor?.driver_id, token, apiUrl, orderId: order?.id, isOnline, reloadKey, version: order?.order_version }), [actor?.id, actor?.role, actor?.restaurant_id, actor?.driver_id, token, apiUrl, order?.id, order?.order_version, isOnline, reloadKey]);
  const current = useRef(session), mounted = useRef(false), flight = useRef(null), lifecycle = useRef(0); current.current = session;
  const [view, setView] = useState({});
  const load = useCallback(async (cursor = null) => {
    if (!mounted.current || current.current !== session || !session.actorId || !session.apiUrl || !session.orderId || !session.isOnline || flight.current?.session === session) return;
    const abort = new AbortController(), job = { session, abort, epoch: lifecycle.current }; flight.current = job;
    const owns = () => mounted.current && current.current === session && flight.current === job && lifecycle.current === job.epoch;
    setView((v) => ({ ...(v.session === session ? v : {}), session, busy: true, error: "" }));
    let timer;
    try {
      const response = await Promise.race([
        Promise.resolve().then(async () => {
          const connection = axios.create({ withCredentials: true });
          const config = { timeout: 15000, signal: abort.signal, headers: { Authorization: session.token ? `Bearer ${session.token}` : null, "X-Expected-Actor-ID": session.actorId } };
          const auth = await connection.get(`${session.apiUrl}/api/auth/me`, config);
          if (!owns()) throw Error("SESSION_CHANGED");
          if (auth?.status !== 200 || auth.data?.id !== session.actorId || auth.data?.role !== session.role ||
            (session.role === "restaurant" && auth.data.restaurant_id !== session.restaurantId) ||
            (session.role === "driver" && auth.data.driver_id !== session.driverId) ||
            auth.data.account_disabled === true || auth.data.is_disabled === true) throw Error("SESSION_CHANGED");
          return connection.get(`${session.apiUrl}/api/orders/${encodeURIComponent(session.orderId)}/incidents`, { ...config, params: { limit: 50, ...(cursor ? { cursor } : {}) } });
        }),
        new Promise((_, reject) => { timer = setTimeout(() => { abort.abort(); reject(Error("Citirea incidentelor a expirat. Reîncearcă manual.")); }, 15000); }),
      ]);
      if (!owns()) return;
      const data = response?.data;
      if (response.status !== 200 || !Array.isArray(data?.incidents) || data.incidents.length > 50 || !(data.next_cursor === null || (typeof data.next_cursor === "string" && data.next_cursor.length > 0 && data.next_cursor.length <= 4096)) || data.incidents.some((entry) => !entry || typeof entry.id !== "string" || !Object.hasOwn(labels, entry.incident_type) || typeof entry.description !== "string" || entry.description.length > 500 || entry.order_id !== session.orderId)) throw Error("Lista incidentelor nu poate fi verificată.");
      setView((v) => {
        const previous = cursor && v.session === session ? v.items || [] : [], items = [...previous, ...data.incidents], ids = new Set(items.map((entry) => entry.id));
        if (ids.size !== items.length || items.length > 1600 || (cursor && data.next_cursor === cursor)) return { ...v, session, busy: false, error: "Pagina incidentelor este inconsistentă. Reîncarcă lista." };
        return { session, items, cursor: data.next_cursor, busy: false, error: "" };
      });
    } catch (error) { if (owns()) setView({ session, items: [], cursor: null, busy: false, error: error.response?.status === 403 ? "Nu ai acces la incidentele acestei comenzi." : "Incidentele nu au putut fi încărcate. Reîncearcă manual." }); }
    finally { clearTimeout(timer); if (flight.current === job) flight.current = null; }
  }, [session]);
  const invalidate = useCallback(() => { lifecycle.current++; if (flight.current?.session === session) flight.current.abort.abort(); }, [session]);
  useEffect(() => {
    mounted.current = true; void load();
    const hide = () => { invalidate(); setView({ session, items: [], cursor: null, busy: false, suspended: true }); };
    window.addEventListener("pagehide", hide);
    return () => { window.removeEventListener("pagehide", hide); invalidate(); mounted.current = false; };
  }, [load, session, invalidate]);
  if (!order) return null;
  const state = view.session === session ? view : {};
  return <section className="my-3 space-y-2 text-sm" data-testid="operational-incident-history">
    <p className="font-semibold">Incidente raportate</p>
    {!isOnline && <p>Fără internet. Lista se actualizează după reconectare.</p>}
    {state.suspended && <p>Sesiunea trebuie reverificată înainte de afișarea incidentelor.</p>}
    {state.busy && <p role="status">Se încarcă...</p>}
    {state.error && <p role="alert">{state.error}</p>}
    {state.items?.length === 0 && !state.busy && <p>Niciun incident raportat.</p>}
    <ul className="space-y-2">{state.items?.map((entry) => <li key={entry.id} className="break-words rounded border p-2"><p>{labels[entry.incident_type]} · {entry.id}</p><p className="whitespace-pre-wrap">{entry.description}</p>{onSelectBlockedIncident && actor?.role === "driver" && order.status === "PICKED_UP" && entry.incident_type === "delivery_blocked" && entry.status_at_report === "PICKED_UP" && entry.driver_id_at_report === actor.driver_id && entry.performed_by === actor.id && entry.performed_by_role === "driver" && Date.parse(entry.reported_at) >= Date.parse(order.picked_up_at) && custodyId.safeParse(entry.id).success && <Button type="button" variant="outline" className="mt-2 h-auto min-h-11 whitespace-normal" disabled={!isOnline || selectionDisabled || state.suspended} onClick={() => onSelectBlockedIncident(entry.id)} data-testid={`custody-select-incident-${entry.id}`}>Folosește pentru așteptarea la client</Button>}</li>)}</ul>
    <div className="flex gap-2"><Button type="button" variant="outline" size="sm" disabled={!isOnline || state.busy} onClick={() => load()} data-testid="operational-incident-refresh">Actualizează incidentele</Button>{state.cursor && <Button type="button" variant="outline" size="sm" disabled={!isOnline || state.busy} onClick={() => load(state.cursor)} data-testid="operational-incident-next">Mai multe incidente</Button>}</div>
  </section>;
};
export const IncidentSummary = ({ order }) => {
  const values = Array.isArray(order?.incident_summary) ? order.incident_summary : order?.incident_summary ? [order.incident_summary] : [];
  return values.length ? <ul className="my-2 space-y-1 text-sm" data-testid="order-incident-summary">{values.map((entry) => <li key={entry.id}>Incident {entry.id}: {labels[entry.incident_type] || "Raportat"}</li>)}</ul> : null;
};
export const OperationalIncidentReporter = ({ actor, token, scope, apiUrl, isOnline, order, onClose, onReported, showTrigger = true, onSelectBlockedIncident, selectionDisabled = false, disabled = false }) => {
  const reporting = useOperationalReporting(actor, scope, apiUrl, token, isOnline);
  const [open, setOpen] = useState(false), [type, setType] = useState("other"), [description, setDescription] = useState("");
  const owner = useRef(null); owner.current = JSON.stringify([actor?.id, actor?.role, actor?.restaurant_id, actor?.driver_id, token, order?.id]);
  useEffect(() => { setOpen(false); setType("other"); setDescription(""); }, [actor?.id, actor?.role, actor?.restaurant_id, actor?.driver_id, token, order?.id]);
  const close = () => { setOpen(false); onClose?.(); };
  const submitted = async (action) => {
    const session = owner.current, lease = reporting.captureLease(), receipt = await action();
    if (session !== owner.current || !reporting.isCurrentLease(lease) || !reportApplied(receipt) || !reporting.isCurrentReceipt(receipt)) return;
    close(); setDescription(""); onReported?.(receipt, { isCurrent: () => reporting.isCurrentLease(lease) && reporting.isCurrentReceipt(receipt) });
  };
  const submit = () => !disabled && submitted(() => reporting.submit({ operation_type: "incident", resource_id: order.id,
    expected_order_version: Object.hasOwn(order, "order_version") ? order.order_version : null, incident_type: type, description: description.trim() }));
  const allowed = order && !["CANCELLED"].includes(order.status) && (actor?.role !== "driver" || ["ASSIGNED", "ACCEPTED", "PICKED_UP"].includes(order.status));
  return <>
    <IncidentHistory actor={actor} token={token} apiUrl={apiUrl} isOnline={isOnline} order={order} reloadKey={reporting.record?.receipt?.incident_id} onSelectBlockedIncident={onSelectBlockedIncident} selectionDisabled={selectionDisabled} />
    <OperationalReportingPanel reporting={reporting} onRecover={(retry) => submitted(() => reporting.recover(retry))} />
    {showTrigger && allowed && <Button type="button" variant="outline" disabled={disabled || !isOnline || reporting.busy || reporting.pending || reporting.blocked} onClick={() => setOpen(true)} data-testid="report-operational-incident">Raportează incident</Button>}
    <Dialog open={Boolean(!reporting.suspended && allowed && (showTrigger ? open : order))} onOpenChange={(value) => { if (!value) close(); }}>
      <DialogContent data-testid="operational-incident-dialog">
        <DialogHeader><DialogTitle>Incident · {order?.order_number}</DialogTitle><DialogDescription>Raportul păstrează comanda și livratorul alocat. Dispeceratul verifică rezolvarea; taxele și rambursările necesită o decizie separată.</DialogDescription></DialogHeader>
        <div className="space-y-3">
          <Label htmlFor="operational-incident-type">Tip incident</Label>
          <select id="operational-incident-type" className="w-full rounded-md border bg-background p-2" value={type} disabled={disabled || reporting.pending || reporting.busy} onChange={(event) => setType(event.target.value)} data-testid="operational-incident-type">{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select>
          <Label htmlFor="operational-incident-description">Ce s-a întâmplat?</Label>
          <Textarea id="operational-incident-description" maxLength={500} value={description} disabled={disabled || reporting.pending || reporting.busy} onChange={(event) => setDescription(event.target.value)} data-testid="operational-incident-description" />
          {reporting.error && <p role="alert">{reporting.error}</p>}
        </div>
        <DialogFooter><Button type="button" variant="outline" onClick={close}>Închide</Button><Button type="button" onClick={submit} disabled={disabled || !isOnline || !description.trim() || reporting.busy || reporting.pending || reporting.blocked || !reporting.available} data-testid="operational-incident-submit">{reporting.busy ? "Se verifică..." : "Salvează raportul"}</Button></DialogFooter>
      </DialogContent>
    </Dialog>
  </>;
};
