import { useRef, useState } from "react";
import { useOrderRemakeFinancePreview } from "../hooks/useOrderRemakeFinancePreview";
import { assertNoOriginalFinancialIntent, remakeApplied, remakeTerminal } from "../lib/orderRemakeFinance";
import { formatBani } from "../lib/orderFinance";
import { Button } from "./ui/button";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Textarea } from "./ui/textarea";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from "./ui/dialog";

const empty = () => ({ problem_type: "missing_product", item_name: "", quantity: "1", unit_price: "", description: "", payment_type: "" });
export const OrderRemakeRecoveryPanel = ({ recovery, isOnline }) => {
  if (!recovery.record && !recovery.storageInvalid && !recovery.sessionSuspended) return null;
  const r = recovery.record, terminal = remakeTerminal(r?.receipt), applied = remakeApplied(r?.receipt);
  const disabled = !isOnline || recovery.busy || recovery.sessionSuspended || recovery.storageInvalid || !recovery.available;
  return <section role="region" aria-label="Recuperare refacere" className="mb-4 rounded-xl border border-orange-500/40 bg-orange-500/10 p-4 text-orange-100" data-testid="remake-recovery-panel">
    <h2 className="font-bold">Refacere păstrată pentru verificare</h2>
    {r && <p className="mt-1 break-all text-sm">Original: {r.parent_id} · Încercare: {r.client_operation_id}</p>}
    <p className="mt-2 text-sm">{applied ? "Comanda legată este confirmată de server. Confirmarea finală verifică legătura și reîncarcă lista."
      : terminal ? "Încercarea a fost refuzată. Confirmarea finală verifică rezultatul și reîncarcă lista înaintea unei încercări noi."
      : "Rezultatul este încă neconfirmat. Nu crea o altă refacere pentru aceeași intenție."}</p>
    {r?.receipt?.error_code && <p className="mt-1 break-words text-sm" data-testid="remake-rejection-code">{r.receipt.error_code}</p>}
    {recovery.storageInvalid && <p role="alert">Stocarea nu poate fi verificată. Datele păstrate nu vor fi șterse.</p>}
    {recovery.error && <p role="alert" className="mt-2 text-sm">{recovery.error}</p>}
    {!isOnline && <p role="status">Fără internet. Identitatea încercării este păstrată.</p>}
    <div className="mt-3 flex flex-wrap gap-2">
      {recovery.sessionSuspended && <Button variant="outline" onClick={recovery.revalidateSession} disabled={!isOnline || recovery.checkingSession} data-testid="remake-restore-session">Verifică sesiunea</Button>}
      <Button variant="outline" onClick={recovery.recover} disabled={disabled} data-testid="remake-recover">Verifică rezultatul</Button>
      {!terminal && <Button variant="outline" onClick={recovery.retrySubmission} disabled={disabled} data-testid="remake-retry">Retrimite aceeași încercare</Button>}
      {r?.receipt?.state === "pending" && <Button variant="outline" onClick={recovery.resume} disabled={disabled} data-testid="remake-resume">Reia operația admisă</Button>}
      {!terminal && <Button variant="outline" onClick={recovery.closeIntent} disabled={disabled} data-testid="remake-close">Închide dacă nu a fost admisă</Button>}
      {terminal && <Button onClick={recovery.acknowledge} disabled={disabled} data-testid="remake-acknowledge">Confirmă rezultatul și reîncarcă lista</Button>}
    </div>
    {!terminal && <p className="mt-2 text-xs">Retrimiterea necesită datele private din această filă. Închiderea funcționează și fără ele; o operație deja admisă rămâne păstrată.</p>}
  </section>;
};

export const OrderRemakeDialog = ({ open, order, actor, apiUrl, token, isOnline, recovery, originalFinancialRecovery, blocked = false, onClose }) => {
  const [form, setForm] = useState(empty), job = useRef(null);
  let originalBlock = "";
  try {
    if (originalFinancialRecovery?.storageInvalid) throw new Error("Evidența financiară salvată necesită verificare.");
    if (originalFinancialRecovery?.record?.order_id === order?.id) throw new Error("Confirmă mai întâi încercarea financiară păstrată pentru original.");
    if (order?.id) assertNoOriginalFinancialIntent(window.localStorage, actor, order.id);
  } catch (error) { originalBlock = error.message; }
  const enabled = Boolean(open && order && !recovery.blocked && !originalBlock && !blocked);
  const preview = useOrderRemakeFinancePreview({ actor, apiUrl, token, parentId: order?.id, parentVersion: order?.order_version,
    form, isOnline, enabled });
  const set = (name, value) => setForm((old) => ({ ...old, [name]: value }));
  const submit = async () => {
    if (!preview.readyToSubmit || !preview.submission || !recovery.available || recovery.blocked || originalBlock || blocked || job.current) return;
    const owned = {}; job.current = owned;
    try { await recovery.submit(preview.submission); }
    finally { if (job.current === owned) job.current = null; }
  };
  const disabled = !enabled || recovery.busy;
  return <Dialog open={open} onOpenChange={(value) => { if (!value) onClose(); }}>
    <DialogContent className="max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-xl overflow-y-auto overscroll-contain" data-testid="financial-remake-dialog">
      <DialogHeader><DialogTitle>Refacere · {order?.order_number || order?.id}</DialogTitle>
        <DialogDescription>Un bon nou, legat de original. Plata și rambursarea originalului se verifică separat.</DialogDescription></DialogHeader>
      {originalBlock && <p role="alert">{originalBlock}</p>}
      {blocked && <p role="status">Încheie verificarea operației curente înaintea unei refaceri noi.</p>}
      {!isOnline && <p role="status">Fără internet. Formularul nu poate fi trimis.</p>}
      {recovery.blocked && <p role="status">O încercare este păstrată. Folosește panoul de recuperare din pagina restaurantului.</p>}
      {!recovery.available && <p role="alert">Browserul sau sesiunea nu permite protejarea unei refaceri între file.</p>}
      {recovery.error && <p role="alert">{recovery.error}</p>}
      {preview.error && <p role="alert" data-testid="remake-preview-error">{preview.error}</p>}
      {preview.loading && <p role="status">Se verifică originalul și cotația…</p>}
      {preview.context && <div className="rounded-lg border p-3 text-sm" data-testid="remake-parent-context">
        <p>{preview.context.parent.customer_name} · {preview.context.parent.customer_phone}</p>
        <p>{preview.context.parent.customer_address}</p><p>Zona: {preview.context.parent.delivery_zone_name || "neconfirmată"}</p>
      </div>}
      <fieldset disabled={disabled} className="min-w-0 space-y-3">
        <legend className="sr-only">Datele noului bon</legend>
        <div className="grid grid-cols-2 gap-2">{[["missing_product", "Produs lipsă"], ["new_product", "Produs nou"]].map(([value, label]) =>
          <Button key={value} type="button" variant={form.problem_type === value ? "default" : "outline"} onClick={() => set("problem_type", value)}>{label}</Button>)}</div>
        <div><Label htmlFor="remake-item">Produs</Label><Input id="remake-item" value={form.item_name} maxLength={140} onChange={(e) => set("item_name", e.target.value)} data-testid="remake-item" /></div>
        <div className="grid grid-cols-2 gap-3"><div><Label htmlFor="remake-quantity">Cantitate</Label><Input id="remake-quantity" inputMode="numeric" value={form.quantity} maxLength={3} onChange={(e) => set("quantity", e.target.value)} data-testid="remake-quantity" /></div>
          <div><Label htmlFor="remake-price">Preț unitar (RON)</Label><Input id="remake-price" inputMode="decimal" value={form.unit_price} maxLength={32} placeholder="Introdu explicit suma" onChange={(e) => set("unit_price", e.target.value)} data-testid="remake-price" /></div></div>
        <div><Label htmlFor="remake-description">Descriere</Label><Textarea id="remake-description" value={form.description} maxLength={1000} onChange={(e) => set("description", e.target.value)} data-testid="remake-description" /></div>
        <div><Label htmlFor="remake-payment">Plata noului bon</Label><select id="remake-payment" className="w-full rounded-md border bg-background p-2" value={form.payment_type} onChange={(e) => set("payment_type", e.target.value)} data-testid="remake-payment">
          <option value="">Alege plata</option><option value="CASH">Numerar — bon nou de încasat</option><option value="CARD">Card — comandă nouă preplătită</option></select></div>
        <div><Label htmlFor="remake-tariff">Grila aprobată</Label><select id="remake-tariff" className="w-full rounded-md border bg-background p-2" value={preview.tariffVersion} onChange={(e) => preview.setTariffVersion(e.target.value)} data-testid="remake-tariff">
          <option value="">Alege explicit grila</option>{preview.tariffs.filter((v) => v.zone_ids.includes(preview.context?.parent.delivery_zone_id)).map((v) => <option key={v.version} value={v.version}>{v.version} · RON</option>)}</select></div>
      </fieldset>
      <div className="flex flex-wrap gap-2"><Button variant="outline" onClick={preview.refresh} disabled={!enabled || !isOnline || preview.loading} data-testid="remake-refresh-parent">Reîncarcă originalul</Button>
        <Button onClick={preview.requestQuote} disabled={!preview.readyToQuote || preview.loading} data-testid="remake-request-quote">Cere cotația</Button></div>
      {preview.quote && <section className="space-y-2 rounded-lg border p-3" aria-label="Cotația refacerii" data-testid="remake-quote">
        <p className="font-semibold">Cotație pentru noul bon</p>
        {[["Produse", "products_bani"], ["De încasat de la client", "client_collection_bani"], ["Transport datorat de restaurant", "restaurant_transport_bani"], ["Avans necesar", "advance_required_bani"]].map(([label, key]) =>
          <p key={key} className="flex flex-wrap justify-between gap-2 text-sm"><span>{label}</span><strong>{formatBani(preview.quote[key])}</strong></p>)}
        <p className="text-xs">Avansul achitat și rambursările nu sunt stabilite de această cotație.</p>
        <label className="flex items-start gap-2 text-sm"><input type="checkbox" checked={preview.confirmed} onChange={(e) => preview.confirm(e.target.checked)} disabled={disabled} data-testid="remake-confirm-quote" />Confirm cotația și plata noului bon.</label>
      </section>}
      <DialogFooter><Button variant="outline" onClick={onClose} data-testid="remake-hide">Înapoi</Button>
        <Button onClick={submit} disabled={!preview.readyToSubmit || !recovery.available || disabled} data-testid="remake-submit">{recovery.busy ? "Se verifică…" : "Creează refacerea confirmată"}</Button></DialogFooter>
    </DialogContent>
  </Dialog>;
};
