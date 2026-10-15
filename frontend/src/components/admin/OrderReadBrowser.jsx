import { CustodyControls, CustodyRecoveryPanel } from "../OrderCustody";
import { custodyEventLabels } from "../../lib/orderCustody";
import { useEffect, useState } from "react";
import { ChevronLeft, ChevronRight, Eye, Loader2, Package, Pencil, RefreshCw } from "lucide-react";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from "../ui/dialog";
import { useOrderReadDetail, useOrderReads } from "../../hooks/useOrderReads";
import { OperationalIncidentReporter, IncidentSummary } from "../OperationalIncidentReporter";
import { OrderFinancialSummary } from "../OrderFinancialSummary";
import { clientCollectionText, formatBani, readOrderFinance } from "../../lib/orderFinance";
import { emptyReadFilters, formatReadTime, ORDER_READ_STATUSES, ORDER_SOURCE_LABELS, ORDER_STATUS_LABELS, readOwnLabel, readText, validReadActor } from "../../lib/orderReads";
import { isOrderEditable } from "../../lib/orderEditingRecovery";
import { isOrderAssignable } from "../../lib/orderAssignmentRecovery";

const statusLabel = (value) => readOwnLabel(ORDER_STATUS_LABELS, value);
const changeLabels = { from_status: "Status anterior", to_status: "Status nou", from_preparation_status: "Pregatire anterioara", to_preparation_status: "Pregatire noua", old_driver_id: "Livrator anterior", new_driver_id: "Livrator nou", driver_id: "Livrator", driver_name: "Nume livrator", fields: "Campuri corectate", preparation_status: "Pregatire", preparation_time: "Minute de pregatire", preparation_due_at: "Termen de pregatire", preparation_estimated_seconds: "Pregatire estimata (secunde)", preparation_actual_seconds: "Pregatire efectiva (secunde)", preparation_delay_seconds: "Intarziere (secunde)", cancellation_reason: "Motiv anulare", customer_name: "Nume client", customer_phone: "Telefon client", customer_address: "Adresa client", customer_latitude: "Latitudine client", customer_longitude: "Longitudine client", notes: "Note" };
const actionLabels = { "order.created": "Comanda creata", "order.assigned": "Livrator alocat", "order.reassigned": "Livrator realocat", "order.corrected": "Date corectate", "order.edited": "Date corectate", "order.status_changed": "Status schimbat", "order.preparing_started": "Pregatire inceputa", "order.ready": "Comanda gata", "order.accepted": "Comanda acceptata", "order.picked_up": "Comanda ridicata", "order.delivered": "Comanda livrata", "order.cancelled": "Comanda anulata" };
Object.entries(custodyEventLabels).forEach(([key, label]) => { actionLabels[`order.${key}`] = label; });
const roleLabels = { admin: "Administrator", restaurant: "Restaurant", driver: "Livrator", system: "Sistem" };
changeLabels.financial_snapshot_digest = "Referință calcul financiar";
changeLabels.courier_remuneration_bani = "Remunerație livrator";
changeLabels.linked_problem_order_id = "Comandă inițială";
changeLabels.problem_followup_order_id = "Comandă suplimentară";
actionLabels["order.remake_linked"] = "Comandă suplimentară legată de original";
actionLabels["order.remake_created"] = "Comandă suplimentară creată";
actionLabels["order.advance_not_paid_declared"] = "Lipsă numerar declarată";
actionLabels["order.advance_shortfall_acknowledged"] = "Ridicare fără plată aprobată de restaurant";
changeLabels.declaration_id = "Referință declarație numerar";
changeLabels.approval_id = "Referință aprobare restaurant";
changeLabels.declared_unpaid_bani = "Avans neachitat declarat (bani)";
changeLabels.outstanding_bani = "Restanță (bani)";
changeLabels.amount_bani = "Sumă consemnată (bani)";
const changeText = (key, value) => value === null ? "Eliminat" : ["from_status", "to_status", "from_preparation_status", "to_preparation_status", "preparation_status"].includes(key) ? statusLabel(value) : key === "fields" && typeof value === "string" ? value.split(", ").map((field) => readOwnLabel(changeLabels, field, field)).join(", ") : String(value);
const Status = ({ value }) => <Badge variant="outline" className="whitespace-normal">{statusLabel(value)}</Badge>;
const OverviewAmount = ({ order }) => <><span className="block text-xs text-muted-foreground">{readOrderFinance(order).state === "legacy" ? "Total" : "De încasat"}</span>{clientCollectionText(order)}</>;
const ReadState = ({ read }) => <>
  {read.phase === "loading" && <p role="status" className="flex items-center gap-2 p-4 text-sm"><Loader2 className="h-4 w-4 animate-spin" />Se incarca...</p>}
  {read.phase === "offline" && <p role="status" className="p-4 text-sm">Fara internet. Citirea se reia dupa reconectare.</p>}
  {(read.error || read.cursorError) && <p role="alert" className="break-words p-4 text-sm text-destructive">{read.error || read.cursorError}</p>}
  {read.warnings.length > 0 && <p role="status" className="break-words border-b px-4 py-2 text-sm text-amber-800 dark:text-amber-200" data-testid="order-read-warnings">Date partial indisponibile: {read.warnings.join(", ")}</p>}
</>;
const PageButtons = ({ read, prefix = "order-read", history = false }) => <div className="flex flex-wrap items-center justify-between gap-2 border-t p-3 text-sm">
  <span data-testid={`${prefix}-page`}>Pagina {read.page}{!history && read.phase === "ready" ? ` | ${read.items.length} pe pagina` : ""}</span>
  <div className="flex shrink-0 items-center gap-1">
    <Button variant="outline" size="icon" title={history ? "Istoric mai nou" : "Pagina precedenta"} aria-label={history ? "Istoric mai nou" : "Pagina precedenta"} disabled={read.phase !== "ready" || !read.canPrevious} onClick={read.previous} data-testid={`${prefix}-prev`}><ChevronLeft className="h-4 w-4" /></Button>
    <Button variant="outline" size="icon" title={history ? "Istoric mai vechi" : "Pagina urmatoare"} aria-label={history ? "Istoric mai vechi" : "Pagina urmatoare"} disabled={!read.canNext} onClick={read.next} data-testid={`${prefix}-next`}><ChevronRight className="h-4 w-4" /></Button>
  </div>
</div>;
const SelectFilter = ({ id, label, value, onChange, children }) => <div className="min-w-0 space-y-1">
  <Label htmlFor={id}>{label}</Label>
  <select id={id} data-testid={id} className="h-10 w-full min-w-0 rounded-md border border-input bg-background px-2 text-sm" value={value} onChange={(event) => onChange(event.target.value)}>{children}</select>
</div>;
const options = (values) => Array.isArray(values) ? values.filter((item) => item && validReadActor(item.id) && typeof item.name === "string").filter((item, index, all) => all.findIndex((other) => other.id === item.id) === index) : [];
const adminEligible = (context) => context.role === "admin" && context.actorId && context.isOnline !== false && context.canCorrect !== false;

const OrderReadDetail = ({ context, orderId, onClose, onInspectOrder, onOpenRelated }) => {
  const read = useOrderReadDetail(context, orderId, context.reloadKey);
  const order = read.data?.order;
  const eligible = read.phase === "ready" && adminEligible(context) && !order.read_data_invalid && !order.read_actions_unavailable && isOrderEditable(order);
  return <Dialog open onOpenChange={(open) => { if (!open) onClose(); }}>
    <DialogContent className="flex max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-2xl flex-col overflow-hidden" data-testid="order-read-detail">
      <DialogHeader className="shrink-0 pr-6">
        <DialogTitle className="break-words text-base">Comanda {readText(order?.order_number || orderId)}</DialogTitle>
        <DialogDescription>Detaliu si istoric</DialogDescription>
      </DialogHeader>
      <div className="min-h-0 overflow-y-auto">
        <ReadState read={read} />
        {context.custodyRecovery && <CustodyRecoveryPanel recovery={context.custodyRecovery} isOnline={context.isOnline !== false} scopeKey={orderId} onAcknowledged={(fresh) => { context.onCustodyAcknowledged?.(fresh); onClose(); }} />}
        {order && <>
          <dl className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-x-3 gap-y-2 break-words text-sm" data-testid="order-read-detail-order">
            <dt>Restaurant</dt><dd>{readText(order.restaurant_name || order.restaurant_id)}</dd>
            <dt>Client</dt><dd>{readText(order.customer_name)}</dd>
            <dt>Telefon</dt><dd>{readText(order.customer_phone)}</dd>
            <dt>Adresa</dt><dd>{readText(order.customer_address)}</dd>
            <dt>Note</dt><dd className="whitespace-pre-wrap">{readText(order.notes)}</dd>
            <dt>Sursa</dt><dd>{readOwnLabel(ORDER_SOURCE_LABELS, order.source)}</dd>
            <dt>Pregatire</dt><dd>{statusLabel(order.preparation_status)}</dd>
            <dt>Livrare / status</dt><dd>{statusLabel(order.status)}</dd>
            <dt>Livrator</dt><dd>{readText(order.driver_name || order.driver_id)}</dd>
            {readOrderFinance(order).state === "legacy" && <><dt>Total RON</dt><dd>{readText(order.total_amount)}</dd></>}
            <dt>Plata</dt><dd>{readText(order.payment_type)}</dd>
            <dt>Creat</dt><dd>{formatReadTime(order.created_at)}</dd>
            <dt>Versiune</dt><dd>{readText(order.order_version)}</dd>
          </dl>
          {order.items && <ul className="mt-4 divide-y border-y text-sm">{order.items.map((item, index) => <li key={index} className="flex flex-wrap justify-between gap-2 py-2"><span className="min-w-0 break-words">{item.quantity} x {item.name}</span><span>{item.price} RON</span></li>)}</ul>}
          <OrderFinancialSummary order={order} role="admin" />
          <CustodyControls order={order} actor={{ id: context.actorId, role: context.role }} recovery={context.custodyRecovery} isOnline={context.isOnline !== false} disabled={context.custodyDisabled || read.phase !== "ready"} />
          {order.read_remake_invalid && <p role="alert" className="mt-3 text-sm">Legătura dintre comenzi necesită verificare. Reîncarcă datele.</p>}
          {(order.linked_problem_order_id || order.problem_followup_order_id) && <section className="mt-4 min-w-0 space-y-2 rounded-lg border p-3" aria-label="Comenzi legate">
            <h3 className="text-sm font-semibold">Comenzi legate</h3>
            {order.problem_description && <p className="break-words text-sm">{order.problem_description}</p>}
            <div className="flex flex-wrap gap-2">
              {order.linked_problem_order_id && <Button variant="outline" className="h-auto whitespace-normal" onClick={() => onOpenRelated(order.linked_problem_order_id)}>Vezi comanda inițială</Button>}
              {order.problem_followup_order_id && <Button variant="outline" className="h-auto whitespace-normal" onClick={() => onOpenRelated(order.problem_followup_order_id)}>Vezi comanda suplimentară</Button>}
            </div>
          </section>}
          <IncidentSummary order={order} />
          <OperationalIncidentReporter actor={{ id: context.actorId, role: context.role }} token={context.token} scope="admin-incidents" disabled={Boolean(context.custodyRecovery?.record || context.custodyRecovery?.busy || context.custodyRecovery?.storageInvalid)} apiUrl={context.apiUrl} isOnline={context.isOnline !== false} order={order} onReported={read.refresh} />
          <h3 className="mt-4 text-sm font-semibold">Istoric</h3>
          {read.data.history.length === 0 ? <p className="py-3 text-sm text-muted-foreground">Nu exista evenimente disponibile pe aceasta pagina.</p> :
            <ol className="mt-2 divide-y" data-testid="order-read-history">{read.data.history.map((entry, index) => <li key={`${entry.id || "entry"}:${index}`} className="space-y-1 py-3 text-sm">
              <p className="break-words font-medium">{readOwnLabel(actionLabels, entry.action, entry.action)}</p>
              <p className="break-words text-muted-foreground">{readOwnLabel(roleLabels, entry.performed_by_role)} | {readText(entry.performed_by)} | {formatReadTime(entry.created_at)}</p>
              {(entry.from_order_version !== undefined || entry.to_order_version !== undefined) && <p>Versiune {readText(entry.from_order_version)} - {readText(entry.to_order_version)}</p>}
              {Object.entries(entry.changes).map(([key, value]) => <p key={key} className="break-words"><span className="font-medium">{readOwnLabel(changeLabels, key, key)}: </span>{key === "courier_remuneration_bani" ? formatBani(value) : changeText(key, value)}</p>)}
            </li>)}</ol>}
          <PageButtons read={read} prefix="order-read-history" history />
        </>}
      </div>
      <DialogFooter className="shrink-0 gap-2">
        <Button variant="outline" onClick={onClose}>Inchide</Button>
        <Button variant="outline" size="icon" aria-label="Reincarca detaliul" title="Reincarca detaliul" disabled={context.isOnline === false || read.phase === "loading"} onClick={read.refresh} data-testid="order-read-detail-refresh"><RefreshCw className="h-4 w-4" /></Button>
        {eligible && onInspectOrder && <Button variant="outline" className="h-auto min-h-10 whitespace-normal" onClick={() => { if (eligible) { onClose(); onInspectOrder(order); } }} data-testid="order-read-correct"><Pencil className="mr-2 h-4 w-4 shrink-0" />Corecteaza datele clientului</Button>}
      </DialogFooter>
    </DialogContent>
  </Dialog>;
};

export const OrderReadBrowser = ({ context, onAssignOrder, onInspectOrder }) => {
  const [filters, setFilters] = useState(emptyReadFilters);
  const [selection, setSelection] = useState(null);
  const read = useOrderReads(context, filters, context.reloadKey);
  useEffect(() => { setSelection(null); }, [context.actorId, context.token]);
  const selectedId = selection?.actorId === context.actorId && selection?.token === context.token ? selection.id : null;
  const update = (key, value) => { setSelection(null); setFilters((old) => ({ ...old, [key]: value })); };
  const inspect = (order) => setSelection({ id: order.id, actorId: context.actorId, token: context.token });
  const assignable = (order) => adminEligible(context) && !order.read_data_invalid && !order.read_actions_unavailable && isOrderAssignable(order);
  const restaurants = options(context.restaurants), drivers = options(context.drivers);
  const actions = (order, mobile) => <div className="flex flex-wrap justify-end gap-1">
    <Button variant="ghost" size="icon" title="Detalii comanda" aria-label={`Detalii comanda ${order.order_number || order.id}`} onClick={() => inspect(order)} data-testid={`order-read-eye${mobile ? "-mobile" : ""}-${order.id}`}><Eye className="h-4 w-4" /></Button>
    {onAssignOrder && assignable(order) && <Button variant="outline" size="sm" onClick={() => onAssignOrder(order)} data-testid={`order-read-assign${mobile ? "-mobile" : ""}-${order.id}`}>Aloca</Button>}
  </div>;
  return <section className="control-surface min-w-0 overflow-hidden rounded-lg border bg-card" aria-label="Comenzi" data-testid="order-read-browser">
    <div className="flex flex-wrap items-center justify-between gap-3 border-b bg-slate-50/70 p-4 dark:bg-slate-900/50">
      <h2 className="flex items-center gap-2 text-lg font-semibold"><Package className="h-5 w-5" />Comenzi</h2>
      <Button variant="outline" size="icon" title="Reincarca prima pagina" aria-label="Reincarca prima pagina" disabled={context.isOnline === false || read.phase === "loading"} onClick={read.refresh} data-testid="order-read-refresh"><RefreshCw className="h-4 w-4" /></Button>
    </div>
    <div className="grid min-w-0 grid-cols-1 gap-3 border-b p-4 sm:grid-cols-2 xl:grid-cols-3">
      <SelectFilter id="order-read-view" label="Vizualizare" value={filters.view} onChange={(value) => update("view", value)}>
        <option value="active">Active</option><option value="history">Istoric</option><option value="all">Toate</option>
      </SelectFilter>
      <SelectFilter id="order-read-status" label="Status" value={filters.status} onChange={(value) => update("status", value)}>
        <option value="">Orice status</option>{ORDER_READ_STATUSES.map((status) => <option key={status} value={status}>{statusLabel(status)}</option>)}
      </SelectFilter>
      <SelectFilter id="order-read-restaurant" label="Restaurant" value={filters.restaurant_id} onChange={(value) => update("restaurant_id", value)}>
        <option value="">Orice restaurant</option>{restaurants.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        {filters.restaurant_id && !restaurants.some((item) => item.id === filters.restaurant_id) && <option value={filters.restaurant_id}>{filters.restaurant_id}</option>}
      </SelectFilter>
      <SelectFilter id="order-read-driver" label="Livrator" value={filters.driver_id} onChange={(value) => update("driver_id", value)}>
        <option value="">Orice livrator</option>{drivers.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
        {filters.driver_id && !drivers.some((item) => item.id === filters.driver_id) && <option value={filters.driver_id}>{filters.driver_id}</option>}
      </SelectFilter>
      <div className="min-w-0 space-y-1"><Label htmlFor="order-read-from">De la (UTC)</Label><Input className="min-w-0 max-w-full" id="order-read-from" data-testid="order-read-from" type="date" value={filters.from_date} onChange={(event) => update("from_date", event.target.value)} /></div>
      <div className="min-w-0 space-y-1"><Label htmlFor="order-read-to">Pana la (exclusiv UTC)</Label><Input className="min-w-0 max-w-full" id="order-read-to" data-testid="order-read-to" type="date" value={filters.to_date} onChange={(event) => update("to_date", event.target.value)} /></div>
    </div>
    <ReadState read={read} />
    {read.phase === "ready" && (read.items.length === 0 ? <p role="status" className="p-6 text-center text-sm text-muted-foreground" data-testid="order-read-empty">Nu exista comenzi pe aceasta pagina pentru filtrele selectate.</p> : <>
      <div className="grid gap-3 p-3 md:hidden">{read.items.map((order) => <article key={order.id} className="min-w-0 rounded-lg border p-3" data-testid={`order-read-mobile-${order.id}`}>
        <div className="flex items-start justify-between gap-2"><div className="min-w-0"><p className="break-words font-mono text-xs">{readText(order.order_number || order.id)}</p><h3 className="break-words font-semibold">{readText(order.restaurant_name || order.restaurant_id)}</h3></div><Status value={order.status} /></div>
        <dl className="mt-3 grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-x-2 gap-y-1 break-words text-sm"><dt>Client</dt><dd>{readText(order.customer_name)}</dd><dt>Telefon</dt><dd>{readText(order.customer_phone)}</dd><dt>Sumă</dt><dd><OverviewAmount order={order} /></dd><dt>Sursa</dt><dd>{readOwnLabel(ORDER_SOURCE_LABELS, order.source)}</dd><dt>Livrator</dt><dd>{readText(order.driver_name || order.driver_id)}</dd><dt>Creat</dt><dd>{formatReadTime(order.created_at)}</dd></dl>
        {actions(order, true)}
      </article>)}</div>
      <div className="hidden overflow-x-auto md:block"><Table className="min-w-[920px]"><TableHeader><TableRow><TableHead>Nr.</TableHead><TableHead>Sursa</TableHead><TableHead>Restaurant</TableHead><TableHead>Client</TableHead><TableHead>Sumă</TableHead><TableHead>Status</TableHead><TableHead>Creat</TableHead><TableHead>Livrator</TableHead><TableHead className="text-right">Actiuni</TableHead></TableRow></TableHeader><TableBody>
        {read.items.map((order) => <TableRow key={order.id} data-testid={`order-read-row-${order.id}`}><TableCell className="font-mono text-xs">{readText(order.order_number || order.id)}</TableCell><TableCell>{readOwnLabel(ORDER_SOURCE_LABELS, order.source)}</TableCell><TableCell>{readText(order.restaurant_name || order.restaurant_id)}</TableCell><TableCell><p>{readText(order.customer_name)}</p><p className="text-xs text-muted-foreground">{readText(order.customer_phone)}</p></TableCell><TableCell><OverviewAmount order={order} /></TableCell><TableCell><Status value={order.status} /></TableCell><TableCell className="text-xs">{formatReadTime(order.created_at)}</TableCell><TableCell>{readText(order.driver_name || order.driver_id)}</TableCell><TableCell>{actions(order, false)}</TableCell></TableRow>)}
      </TableBody></Table></div>
    </>)}
    <PageButtons read={read} />
    {selectedId && <OrderReadDetail key={`${context.actorId}:${selectedId}`} context={context} orderId={selectedId} onClose={() => setSelection(null)} onInspectOrder={onInspectOrder} onOpenRelated={(id) => setSelection({id,actorId:context.actorId,token:context.token})} />}
  </section>;
};
