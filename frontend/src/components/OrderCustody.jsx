import { useEffect, useRef, useState } from "react";
import { Button } from "./ui/button";
import { custodyId, custodyLabels, custodyEventLabels, custodyCommandEligible, readCustodyActivity } from "../lib/orderCustody";
import { custodyApplied, custodyTerminal, custodyFailureMessage } from "../lib/orderCustodyRecovery";

export const OrderCustodySummary = ({ order }) => {
  const activity = readCustodyActivity(order);
  if (activity.state === "none") return null;
  if (activity.state === "invalid") return <p role="alert" className="my-3 rounded-lg border border-amber-500/40 p-3 text-sm" data-testid="custody-invalid">Evidența produselor necesită verificare. Acțiunile sunt blocate până la reîncărcare.</p>;
  const v = activity.value, delivered = order.status === "DELIVERED";
  return <section className="my-3 min-w-0 space-y-2 break-words rounded-lg border border-sky-500/40 p-3 text-sm" aria-label="Custodia produselor" data-testid="custody-summary">
    <h3 className="font-bold">{delivered ? "Incident închis prin livrare" : custodyLabels[v.status]}</h3>
    <p>Motiv consemnat: {v.reason === "absent" ? "client absent" : "clientul refuză"}. Incident: {v.incident_id}</p>
    <p>Sosire și așteptare declarate la {new Date(v.wait_started_at).toLocaleString("ro-RO")}. Declarația nu constituie dovadă GPS.</p>
    {v.review_id && <p>Administratorul a consemnat încercarea contactării clientului, contactarea restaurantului și coordonarea cu acesta.</p>}
    {!delivered && v.status === "return_requested" && <p>Decizia solicită returul integral. Restaurantul va confirma separat primirea efectivă.</p>}
    {!delivered && v.status === "keep_authorized" && <p>Restaurantul permite păstrarea tuturor produselor. Livratorul confirmă separat primirea instrucțiunii.</p>}
    {v.resolved_at && <p>Custodie închisă la {new Date(v.resolved_at).toLocaleString("ro-RO")}. Această comandă nu este o livrare finalizată către client.</p>}
    {!delivered && <p>Calculul cursei nereușite este în așteptarea grilei. {v.status === "returned" ? "Remunerația returului pentru zona 1 și transportul restaurantului necesită tarifele confirmate." : v.status === "kept" ? "Păstrarea produselor nu creează un retur sau remunerație de retur." : "Sumele returului nu sunt confirmate."}</p>}
    {!delivered && <p className="text-xs opacity-80">Custodia nu confirmă o plată sau rambursare. Restanța pentru ridicarea fără plată se păstrează; nu se compensează automat.</p>}
  </section>;
};

export const CustodyControls = ({ order, actor, recovery, isOnline, disabled = false, incidentId = null }) => {
  const [reason, setReason] = useState("absent"), [facts, setFacts] = useState({}), [confirmed, setConfirmed] = useState(false), [now, setNow] = useState(Date.now());
  const activity = readCustodyActivity(order), v = activity.value;
  useEffect(() => { setReason("absent"); setFacts({}); setConfirmed(false); }, [order?.id, order?.order_version, actor?.id, actor?.role, actor?.restaurant_id, actor?.driver_id]);
  useEffect(() => {
    if (order?.status !== "PICKED_UP" || v?.status !== "waiting") return;
    setNow(Date.now()); const timer = setInterval(() => setNow(Date.now()), 1000); return () => clearInterval(timer);
  }, [order?.status, v?.status, v?.wait_started_at]);
  if (!order || order.status !== "PICKED_UP" || !recovery?.available || activity.state === "invalid") return null;
  const owns = actor?.role === "admin" || actor?.[`${actor?.role}_id`] === order[`${actor?.role}_id`];
  if (!owns) return null;
  const blocked = disabled || !isOnline || recovery.blocked || !recovery.durableAvailable;
  const submit = (command) => { if (!blocked && custodyCommandEligible(order, actor, command)) void recovery.submit({ order, command }); };
  const common = v ? { incident_id: v.incident_id } : { incident_id: incidentId };
  const checkbox = (name, label) => <label className="flex min-h-11 items-start gap-3 py-2"><input type="checkbox" className="mt-1 h-5 w-5 shrink-0" checked={facts[name] === true} disabled={blocked} onChange={(e) => setFacts((old) => ({ ...old, [name]: e.target.checked }))} data-testid={`custody-${name}`} /><span>{label}</span></label>;
  return <section className="my-3 min-w-0 space-y-3 rounded-lg border border-sky-500/30 p-3 text-sm" aria-label="Rezolvarea livrării blocate" data-testid="custody-controls">
    {v?.status === "waiting" && <div role="status"><p>Așteptarea minimă se încheie la {new Date(v.wait_eligible_at).toLocaleString("ro-RO")} (minimum 10 minute).</p><p>{now < Date.parse(v.wait_eligible_at) ? `Estimare locală: mai sunt ${Math.ceil((Date.parse(v.wait_eligible_at) - now) / 1000)} secunde.` : "Estimarea arată că așteptarea s-a încheiat. Durata se verifică la confirmare."}</p><p className="text-xs opacity-80">Timerul este orientativ. Nu anulează comanda și nu autorizează automat returul.</p></div>}
    {!recovery.capability?.enabled ? <>
      <p>Rezolvarea returului/păstrării nu este disponibilă momentan. Încercarea salvată poate fi verificată mai jos.</p>
      <Button variant="outline" className="h-auto min-h-11 w-full whitespace-normal" onClick={recovery.chooseProtocol} disabled={blocked} data-testid="custody-check-capability">Verifică disponibilitatea returului/păstrării</Button>
    </> : <>
      {actor.role === "driver" && activity.state === "none" && <>
        <p>Raportează „Livrare blocată”, apoi selectează raportul propriu din lista incidentelor. Declară sosirea numai când ești la adresa clientului.</p>
        {incidentId && <p className="break-all">Incident selectat: {incidentId}</p>}
        <label className="block">Motivul așteptării<select className="mt-1 min-h-11 w-full rounded border bg-background p-2 text-foreground" value={reason} disabled={blocked} onChange={(e) => setReason(e.target.value)} data-testid="custody-reason"><option value="absent">Client absent</option><option value="refused">Clientul refuză</option></select></label>
        <p className="text-xs">Pentru ambele motive se verifică minimum zece minute. Ora este consemnată de server la primirea declarației.</p>
        <Button className="h-auto min-h-11 w-full whitespace-normal" disabled={blocked || !custodyId.safeParse(incidentId).success} onClick={() => submit({ ...common, event_type: "delivery_wait_started", reason })} data-testid="custody-start-wait">Sunt la adresă — încep așteptarea</Button>
      </>}
      {actor.role === "admin" && v?.status === "waiting" && <>
        {checkbox("customer_contact_attempted", "Confirm că a fost încercată contactarea clientului.")}
        {checkbox("restaurant_contacted", "Confirm că restaurantul a fost contactat.")}
        {checkbox("coordination_confirmed", "Confirm coordonarea situației cu restaurantul; decizia produselor îi aparține.")}
        <Button className="h-auto min-h-11 w-full whitespace-normal" disabled={blocked || !facts.customer_contact_attempted || !facts.restaurant_contacted || !facts.coordination_confirmed} onClick={() => submit({ ...common, event_type: "delivery_failure_reviewed", predecessor_id: v.wait_event_id, customer_contact_attempted: true, restaurant_contacted: true, coordination_confirmed: true })} data-testid="custody-review">Consemnez verificarea și coordonarea</Button>
      </>}
      {actor.role === "restaurant" && v?.status === "reviewed" && <>
        <p>Decizia privește toate produsele comenzii, aflate la livrator. Returul solicitat va necesita confirmarea separată a primirii.</p>
        <div className="flex flex-wrap gap-2">{[["return", "Solicit returul integral"], ["keep", "Permit păstrarea de către livrator"]].map(([decision, label]) => <Button key={decision} variant="outline" className="h-auto min-h-11 flex-1 whitespace-normal" disabled={blocked} onClick={() => submit({ ...common, event_type: "products_disposition_decided", predecessor_id: v.review_id, decision })} data-testid={`custody-decide-${decision}`}>{label}</Button>)}</div>
      </>}
      {((actor.role === "restaurant" && v?.status === "return_requested") || (actor.role === "driver" && v?.status === "keep_authorized")) && <>
        <label className="flex min-h-11 items-start gap-3"><input className="mt-1 h-5 w-5 shrink-0" type="checkbox" checked={confirmed} disabled={blocked} onChange={(e) => setConfirmed(e.target.checked)} data-testid="custody-resolution-confirm" /><span>{actor.role === "restaurant" ? "Confirm că am primit efectiv toate produsele de la livrator." : "Confirm că am primit instrucțiunea restaurantului de a păstra toate produsele."}</span></label>
        <Button className="h-auto min-h-11 w-full whitespace-normal" disabled={blocked || !confirmed} onClick={() => submit({ ...common, event_type: actor.role === "restaurant" ? "products_return_received" : "products_keep_acknowledged", predecessor_id: v.decision_id })} data-testid={actor.role === "restaurant" ? "custody-receive-return" : "custody-ack-keep"}>{actor.role === "restaurant" ? "Confirm primirea efectivă a produselor" : "Confirm instrucțiunea de păstrare"}</Button>
      </>}
      {actor.role === "restaurant" && v?.status === "waiting" && <p>Decizia este disponibilă după verificarea administratorului și coordonarea cu restaurantul.</p>}
      {actor.role === "driver" && ["waiting", "reviewed"].includes(v?.status) && <p>Așteaptă coordonarea administratorului și decizia restaurantului. Nu porni automat returul.</p>}
    </>}
  </section>;
};

export const CustodyRecoveryPanel = ({ recovery, isOnline, onAcknowledged, scopeKey = "global" }) => {
  const mounted = useRef(false), currentScope = useRef(scopeKey); currentScope.current = scopeKey;
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  const { record, busy, error, storageInvalid, sessionSuspended, checkingSession } = recovery;
  if (!record && !error && !sessionSuspended) return null;
  const receipt = record?.receipt, blocked = busy || sessionSuspended || storageInvalid || !recovery.durableAvailable || !isOnline;
  return <section className="my-3 min-w-0 space-y-2 break-words rounded-xl border border-amber-500/40 p-3 text-sm" data-testid="custody-recovery-panel">
    <h2 className="font-bold">Confirmarea custodiei produselor</h2>
    {!isOnline && <p role="status">Fără internet. Încercarea inițială rămâne păstrată.</p>}{error && <p role="alert">{error}</p>}
    {busy && <p role="status">Se verifică aceeași încercare…</p>}
    {sessionSuspended && <p role="status">{checkingSession ? "Se verifică sesiunea…" : "Reverifică sesiunea pentru aceeași încercare."}</p>}
    {record && <div role="status"><p>Comanda {record.order_id} · {custodyEventLabels[record.command.event_type]}</p><p>{custodyApplied(receipt) ? "Operația este confirmată de server. Reîncarcă starea comenzii." : receipt?.state === "rejected" ? custodyFailureMessage(receipt.error_code) : recovery.notAdmitted ? "Încercarea nu este încă găsită pe server. Retrimiterea păstrează aceeași identitate." : "Rezultat neconfirmat. Încercarea inițială rămâne păstrată."}</p></div>}
    {record && !recovery.durableAvailable && <p role="alert">Browserul nu poate proteja această operație între taburi. Încercarea este păstrată.</p>}
    <div className="flex flex-wrap gap-2">
      {sessionSuspended && <Button variant="outline" onClick={recovery.revalidateSession} disabled={!isOnline || checkingSession || !recovery.available}>Reverifică sesiunea</Button>}
      {record && !custodyTerminal(receipt) && <Button variant="outline" className="h-auto min-h-11 whitespace-normal" onClick={recovery.recover} disabled={blocked}>Verifică aceeași încercare</Button>}
      {record && recovery.notAdmitted && !receipt && <Button variant="outline" className="h-auto min-h-11 whitespace-normal" onClick={recovery.resend} disabled={blocked}>Retrimite aceeași încercare</Button>}
      {receipt?.state === "pending" && <Button variant="outline" onClick={recovery.resume} disabled={blocked}>Continuă încercarea</Button>}
      {custodyTerminal(receipt) && <Button className="h-auto min-h-11 whitespace-normal" disabled={blocked} onClick={async () => { const scope = currentScope.current, lease = recovery.captureLease(), fresh = await recovery.acknowledge(); if (fresh && mounted.current && currentScope.current === scope && recovery.isCurrentLease(lease)) onAcknowledged?.(fresh); }}>Am văzut rezultatul și reîncarc comanda</Button>}
      {!record && error && !sessionSuspended && <Button variant="outline" onClick={recovery.chooseProtocol} disabled={busy || storageInvalid || !isOnline || !recovery.available}>Verifică disponibilitatea custodiei</Button>}
    </div>
  </section>;
};
