import { useEffect, useRef, useState } from "react";
import { Loader2, Pencil, RefreshCw, Save } from "lucide-react";
import { RecoverySessionNotice } from "../RecoverySessionNotice";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Textarea } from "../ui/textarea";
import { Checkbox } from "../ui/checkbox";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from "../ui/dialog";
import { isOrderEditable, normalizeOrderCorrections } from "../../lib/orderEditingRecovery";

const fields = ["customer_name", "customer_phone", "customer_address", "notes"];
export const correctionForm = (value) => {
  const order = value || {};
  return {
    customer_name: order.customer_name ?? "", customer_phone: order.customer_phone ?? "",
    customer_address: order.customer_address ?? "", notes: order.notes ?? "",
    latitude: order.customer_latitude == null ? "" : String(order.customer_latitude),
    longitude: order.customer_longitude == null ? "" : String(order.customer_longitude), clearCoordinates: false,
  };
};
export const correctionChanges = (order, form) => {
  const changes = {};
  fields.forEach((key) => { if (form[key].trim() !== (order[key] ?? "")) changes[key] = form[key]; });
  if (form.clearCoordinates) {
    changes.customer_latitude = null; changes.customer_longitude = null;
  } else {
    const number = (v) => v.trim() === "" ? null : Number(v);
    const lat = number(form.latitude), lng = number(form.longitude);
    if (lat !== (order.customer_latitude ?? null) || lng !== (order.customer_longitude ?? null)) {
      changes.customer_latitude = lat; changes.customer_longitude = lng;
    }
  }
  return normalizeOrderCorrections(order, changes);
};

export const OrderCorrectionDialog = ({ order, open, onClose, recovery, isOnline, onApplied }) => {
  const [baseline, setBaseline] = useState(order);
  const [form, setForm] = useState(() => correctionForm(order));
  const [editing, setEditing] = useState(false), [refreshed, setRefreshed] = useState(false);
  const [localError, setLocalError] = useState("");
  const initialized = useRef(null), applied = useRef(null), mounted = useRef(true), currentTarget = useRef(null);
  const record = recovery.record;
  const receipt = record?.receipt;
  const target = record?.order_id || order?.id || baseline?.id || initialized.current;
  currentTarget.current = target;
  const eligible = isOrderEditable(order || baseline);
  useEffect(() => {
    mounted.current = true;
    return () => { mounted.current = false; };
  }, []);
  useEffect(() => {
    if (!open) { initialized.current = null; return; }
    if (!target || initialized.current === target) return;
    initialized.current = target;
    const base = order?.id === target ? order : null;
    setBaseline(base); setForm(correctionForm(base)); setEditing(Boolean(record)); setRefreshed(false); setLocalError("");
    if (recovery.draft?.order_id === target) {
      const c = recovery.draft.changes;
      setForm((f) => ({ ...f, ...Object.fromEntries(fields.filter((k) => Object.hasOwn(c, k)).map((k) => [k, c[k] ?? ""])),
        ...(Object.hasOwn(c, "customer_latitude") ? { latitude: c.customer_latitude == null ? "" : String(c.customer_latitude),
          longitude: c.customer_longitude == null ? "" : String(c.customer_longitude), clearCoordinates: c.customer_latitude == null } : {}) }));
    }
  }, [open, target, order, record, recovery.draft]);
  useEffect(() => {
    if (["applied", "replayed"].includes(receipt?.state) && applied.current !== record.client_operation_id) {
      applied.current = record.client_operation_id; onApplied?.();
    }
  }, [receipt, record, onApplied]);
  let changes, validation = "";
  try { if (baseline && editing && !record) changes = correctionChanges(baseline, form); }
  catch (e) { validation = e.message; }
  const disabled = recovery.sessionSuspended || recovery.busy || Boolean(record) || recovery.storageInvalid || !eligible;
  const submit = async () => {
    setLocalError("");
    try { await recovery.submit({ order: baseline, changes: correctionChanges(baseline, form) }); }
    catch (e) { if (mounted.current) setLocalError(e.message); }
  };
  const newAttempt = async () => {
    let corrections = recovery.draft?.changes || {};
    if (!recovery.draft && baseline) {
      try { corrections = correctionChanges(baseline, form); } catch { /* Invalid unsent form is not an admitted draft. */ }
    }
    const originalTarget = target;
    const fresh = await recovery.refreshForNewAttempt();
    if (!fresh || !mounted.current || currentTarget.current !== originalTarget) return;
    // Preserve edited fields, not stale untouched values from before the conflict.
    const restored = correctionForm(fresh), c = corrections;
    fields.forEach((k) => { if (Object.hasOwn(c, k)) restored[k] = c[k] ?? ""; });
    if (Object.hasOwn(c, "customer_latitude")) {
      restored.latitude = c.customer_latitude == null ? "" : String(c.customer_latitude);
      restored.longitude = c.customer_longitude == null ? "" : String(c.customer_longitude);
      restored.clearCoordinates = c.customer_latitude == null;
    }
    setForm(restored);
    setBaseline(fresh); setRefreshed(true); setLocalError("");
  };
  return <Dialog open={open} onOpenChange={(value) => { if (!value && !recovery.busy) onClose(); }}>
    <DialogContent className="z-[1300] flex max-h-[calc(100dvh-2rem)] max-w-lg flex-col overflow-hidden" data-testid="order-correction-dialog">
      <DialogHeader>
        <DialogTitle className="break-words text-base">Detalii comanda {order?.order_number || target}</DialogTitle>
        <DialogDescription>Corectii operationale</DialogDescription>
      </DialogHeader>
      <div className="min-h-0 space-y-3 overflow-y-auto text-sm">
        {baseline && <dl className="grid grid-cols-[auto_minmax(0,1fr)] gap-x-3 gap-y-1 break-words" data-testid="correction-current-order">
          <dt>Client</dt><dd>{baseline.customer_name}</dd><dt>Telefon</dt><dd>{baseline.customer_phone}</dd>
          <dt>Adresa</dt><dd>{baseline.customer_address}</dd><dt>Status</dt><dd>{baseline.status}</dd>
          <dt>Versiune</dt><dd>{String(baseline.order_version ?? "Legacy")}</dd>
        </dl>}
        {!baseline && <p>Comanda {target}: verificarea operatiei salvate nu necesita reincarcarea datelor clientului.</p>}
        {!record && !recovery.capability.ready && <p role="status">{recovery.checkingCapability ? "Se verifica disponibilitatea..." : "Disponibilitatea nu este confirmata."}</p>}
        {recovery.capability.ready && !recovery.capability.enabled && <p role="status">Corectiile operationale sunt indisponibile. Comanda nu a fost modificata.</p>}
        <RecoverySessionNotice recovery={recovery} isOnline={isOnline} />
        {!isOnline && <p role="status">Fara internet. Trimiterea si verificarea sunt suspendate.</p>}
        {!editing && eligible && <Button variant="outline" className="h-auto min-h-9 max-w-full whitespace-normal" onClick={() => setEditing(true)} data-testid="order-correct-button">
          <Pencil className="mr-2 h-4 w-4" />Corecteaza datele clientului
        </Button>}
        {!record && !eligible && <p>Comanda nu este eligibila pentru corectii versionate.</p>}
        {editing && <div className="space-y-3">
          <fieldset disabled={disabled} className="space-y-3">
            {[["customer_name", "Nume", 140], ["customer_phone", "Telefon", 24], ["customer_address", "Adresa", 300]].map(([key, label, max]) => <div key={key}>
              <Label htmlFor={`edit-${key}`}>{label}</Label>
              <Input id={`edit-${key}`} maxLength={max} value={form[key]} onChange={(e) => setForm({ ...form, [key]: e.target.value })} />
            </div>)}
            <div><Label htmlFor="edit-notes">Note</Label><Textarea id="edit-notes" maxLength={1000} value={form.notes} onChange={(e) => setForm({ ...form, notes: e.target.value })} /></div>
            <div className="flex items-center gap-2"><Checkbox id="edit-clear-coordinates" checked={form.clearCoordinates} onCheckedChange={(checked) => setForm({ ...form, clearCoordinates: checked === true })} />
              <Label htmlFor="edit-clear-coordinates">Sterge explicit coordonatele</Label></div>
            <div className="grid grid-cols-2 gap-3">
              <div><Label htmlFor="edit-latitude">Latitudine</Label><Input id="edit-latitude" inputMode="decimal" disabled={form.clearCoordinates} value={form.latitude} onChange={(e) => setForm({ ...form, latitude: e.target.value })} /></div>
              <div><Label htmlFor="edit-longitude">Longitudine</Label><Input id="edit-longitude" inputMode="decimal" disabled={form.clearCoordinates} value={form.longitude} onChange={(e) => setForm({ ...form, longitude: e.target.value })} /></div>
            </div>
          </fieldset>
          {refreshed && <p role="status">Comanda a fost reincarcata. Formularul tau este pastrat; confirma corectiile fata de versiunea {baseline.order_version}.</p>}
          {validation && <p role="status">{validation}</p>}
        </div>}
        {record && <div role="status" data-testid="correction-recovery-state">
          {receipt?.state === "rejected" ? `Corectia a fost respinsa: ${receipt.error_code}. Formularul este pastrat.` :
            ["applied", "replayed"].includes(receipt?.state) ? `Corectia este confirmata, versiunea ${receipt.order_version}.` : "Corectie neconfirmata. Verifica aceeasi operatie."}
        </div>}
        {(localError || recovery.error) && <p role="alert">{localError || recovery.error}</p>}
      </div>
      <DialogFooter className="shrink-0 flex-wrap gap-2">
        <Button variant="outline" disabled={recovery.busy} onClick={onClose}>Inchide</Button>
        {!record && <Button variant="outline" disabled={recovery.sessionSuspended || !isOnline || recovery.checkingCapability} onClick={recovery.verifyCapability} title="Verifica disponibilitatea"><RefreshCw className="h-4 w-4" /></Button>}
        {record && (!receipt || receipt.state === "pending") && <Button className="h-auto min-h-9 whitespace-normal" disabled={recovery.sessionSuspended || recovery.busy || !isOnline || recovery.storageInvalid} onClick={recovery.recover}><RefreshCw className="mr-2 h-4 w-4" />Verifica aceeasi corectie</Button>}
        {receipt?.state === "rejected" && <Button className="h-auto min-h-9 whitespace-normal" disabled={recovery.sessionSuspended || recovery.busy || !isOnline || recovery.storageInvalid} onClick={newAttempt}><RefreshCw className="mr-2 h-4 w-4" />Reincarca pentru o noua incercare</Button>}
        {["applied", "replayed"].includes(receipt?.state) && <Button disabled={recovery.sessionSuspended || recovery.busy || recovery.storageInvalid} onClick={async () => { if (await recovery.acknowledge() && mounted.current) onClose(); }}>Confirma si inchide</Button>}
        {editing && !record && <Button data-testid="correction-submit" disabled={disabled || !changes || !isOnline || !recovery.capability.enabled || !recovery.capability.ready} onClick={submit}>
          {recovery.busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}Salveaza corectiile
        </Button>}
      </DialogFooter>
    </DialogContent>
  </Dialog>;
};
