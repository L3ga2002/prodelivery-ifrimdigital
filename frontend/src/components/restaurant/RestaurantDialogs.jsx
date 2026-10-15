import { CustodyControls, CustodyRecoveryPanel } from "../OrderCustody";
import { OrderFinancialSummary } from "../OrderFinancialSummary";
import { clientCollectionText, orderAmountLabel } from "../../lib/orderFinance";
import { Button } from "../ui/button";
import { Textarea } from "../ui/textarea";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle, DialogFooter } from "../ui/dialog";
import { IncidentSummary } from "../OperationalIncidentReporter";
import { AlertTriangle, CheckCircle2, XCircle, SlidersHorizontal, History, BarChart3, CalendarDays, TimerReset, BookOpen, Truck, PlusCircle } from "lucide-react";
import { canChangeOrderStatus } from "../../lib/orderStatusRecovery";
import { RESTAURANT_DAYS, getStatusConfig } from "../../lib/restaurantPresentation";
import { OrderRemakeDialog } from "../OrderRemakeDialog";
import { pureLegacyRemake } from "../../lib/orderRemakeFinance";

export const RestaurantReadyDialog = ({ open, confirmReadyOrder, setConfirmReadyOrder, markAsReady, isOnline, pendingOrderAction, isCancellingOrder, statusRecovery, canConfirmReady, preparationBlocked = false }) => (
  <Dialog open={open} onOpenChange={(open) => !open && setConfirmReadyOrder(null)}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2">
          <AlertTriangle className="w-5 h-5 text-orange-500" />
          Confirmare - Comanda Gata
        </DialogTitle>
        <DialogDescription>Confirmă trecerea comenzii în status gata pentru ridicare.</DialogDescription>
      </DialogHeader>
      <div className="py-4">
        <p className="text-base">
          Confirmați că comanda <strong>{confirmReadyOrder?.order_number}</strong> este gata pentru ridicare?
        </p>
        <p className="text-sm text-muted-foreground mt-2">
          După confirmare, livratorul va fi notificat să ridice comanda.
        </p>
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={() => setConfirmReadyOrder(null)} data-testid="cancel-ready-confirm">
          Înapoi
        </Button>
        <Button
          className="bg-green-600 hover:bg-green-700"
          onClick={() => markAsReady(confirmReadyOrder?.id)}
          disabled={preparationBlocked || !isOnline || pendingOrderAction !== null || isCancellingOrder || statusRecovery.record || statusRecovery.busy || !canConfirmReady}
          data-testid="confirm-ready-btn"
        >
          <CheckCircle2 className="w-4 h-4 mr-2" />
          {pendingOrderAction !== null ? "Se procesează..." : "Da, Comanda e Gata"}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
);

export const RestaurantScheduleDialog = ({ open, setScheduleDialogOpen, scheduleForm, setScheduleForm, isSavingSchedule, saveScheduleSettings, isOnline }) => (
  <Dialog open={open} onOpenChange={setScheduleDialogOpen}>
    <DialogContent className="max-w-2xl" data-testid="restaurant-schedule-dialog">
      <DialogHeader><DialogTitle>Program de lucru restaurant</DialogTitle><DialogDescription>Setează zilele active și intervalele orare ale restaurantului.</DialogDescription></DialogHeader>
      <div className="max-h-[65vh] space-y-3 overflow-y-auto">
        {RESTAURANT_DAYS.map((day) => {
          const value = scheduleForm[day.key] || { enabled: true, open_time: "10:00", close_time: "22:00" };
          return <div key={day.key} className="grid items-center gap-2 rounded-lg border p-3 sm:grid-cols-[110px_1fr_1fr_1fr]" data-testid={`restaurant-schedule-day-${day.key}`}><Label className="font-black">{day.label}</Label><Button type="button" variant={value.enabled ? "default" : "outline"} onClick={() => setScheduleForm((prev) => ({ ...prev, [day.key]: { ...value, enabled: !value.enabled } }))} data-testid={`restaurant-schedule-enabled-${day.key}`}>{value.enabled ? "Deschis" : "Închis"}</Button><Input type="time" value={value.open_time} onChange={(event) => setScheduleForm((prev) => ({ ...prev, [day.key]: { ...value, open_time: event.target.value } }))} data-testid={`restaurant-schedule-open-${day.key}`} /><Input type="time" value={value.close_time} onChange={(event) => setScheduleForm((prev) => ({ ...prev, [day.key]: { ...value, close_time: event.target.value } }))} data-testid={`restaurant-schedule-close-${day.key}`} /></div>;
        })}
      </div>
      <DialogFooter><Button variant="outline" onClick={() => setScheduleDialogOpen(false)} disabled={isSavingSchedule} data-testid="restaurant-schedule-cancel-button">Anulează</Button><Button onClick={saveScheduleSettings} disabled={isSavingSchedule || !isOnline} data-testid="restaurant-schedule-save-button">{isSavingSchedule ? "Se salvează..." : "Salvează program"}</Button></DialogFooter>
    </DialogContent>
  </Dialog>
);

export const RestaurantMoreDialog = ({ open, setMoreDialogOpen, openMoreView, setScheduleDialogOpen, closeRestaurantDay, isOnline, closeDayReporting, isUpdatingRestaurantStatus }) => (
  <Dialog open={open} onOpenChange={setMoreDialogOpen}>
    <DialogContent className="max-w-xl border-zinc-800 bg-zinc-950 text-zinc-50" data-testid="restaurant-more-dialog">
      <DialogHeader><DialogTitle className="flex items-center gap-2"><SlidersHorizontal className="h-5 w-5 text-orange-400" /> Mai mult</DialogTitle><DialogDescription className="text-zinc-400">Setări operaționale și zone secundare, fără să aglomerăm dashboardul principal.</DialogDescription></DialogHeader>
      <div className="grid gap-3 sm:grid-cols-2">
        <button type="button" onClick={() => openMoreView("history")} className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 text-left hover:border-orange-500/40" data-testid="restaurant-more-history-button"><History className="mb-3 h-5 w-5 text-orange-400" /><p className="font-black">Istoric comenzi</p><p className="mt-1 text-sm text-zinc-400">Caută și deschide detalii complete.</p></button>
        <button type="button" onClick={() => openMoreView("analytics")} className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 text-left hover:border-orange-500/40" data-testid="restaurant-more-analytics-button"><BarChart3 className="mb-3 h-5 w-5 text-orange-400" /><p className="font-black">Analytics</p><p className="mt-1 text-sm text-zinc-400">Grafice și timpi operaționali.</p></button>
        <button type="button" onClick={() => { setScheduleDialogOpen(true); setMoreDialogOpen(false); }} className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 text-left hover:border-orange-500/40" data-testid="restaurant-more-schedule-button"><CalendarDays className="mb-3 h-5 w-5 text-orange-400" /><p className="font-black">Program lucru</p><p className="mt-1 text-sm text-zinc-400">Zile și ore de funcționare.</p></button>
        <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4" data-testid="restaurant-more-pause-panel"><TimerReset className="mb-3 h-5 w-5 text-orange-400" /><p className="font-black">Închiderea zilei</p><p className="mt-2 text-sm text-zinc-400">Dispeceratul controlează pauza. Închiderea zilei păstrează statusul administrativ și comenzile.</p><Button size="sm" variant="outline" className="mt-3" onClick={() => closeRestaurantDay()} disabled={!isOnline || closeDayReporting.blocked || !closeDayReporting.available || isUpdatingRestaurantStatus || closeDayReporting.pending} data-testid="restaurant-close-today-button">Închide azi</Button></div>
        <div className="rounded-xl border border-dashed border-zinc-700 bg-zinc-900/60 p-4 sm:col-span-2" data-testid="restaurant-more-future-catalog"><BookOpen className="mb-3 h-5 w-5 text-zinc-500" /><p className="font-black text-zinc-300">Catalog produse / meniu</p><p className="mt-1 text-sm text-zinc-500">Pregătit pentru viitoarea aplicație de client: produse, categorii, meniu și disponibilitate.</p></div>
      </div>
    </DialogContent>
  </Dialog>
);

export const RestaurantHistoryDetailDialog = ({ open, historyDetailOrder, user, custodyRecovery, isOnline, custodyDisabled, onCustodyAcknowledged, setHistoryDetailOrder, setIncidentOrder, setProblemOrder }) => (
  <Dialog open={open} onOpenChange={(open) => !open && setHistoryDetailOrder(null)}>
    <DialogContent className="max-h-[calc(100dvh-2rem)] w-[calc(100%-2rem)] max-w-2xl overflow-y-auto overscroll-contain border-zinc-800 bg-zinc-950 text-zinc-50" data-testid="restaurant-history-detail-dialog">
      <DialogHeader><DialogTitle>Detalii comandă · {historyDetailOrder?.order_number}</DialogTitle><DialogDescription className="text-zinc-400">Toate informațiile salvate pentru comanda selectată.</DialogDescription></DialogHeader>
      {historyDetailOrder && <><IncidentSummary order={historyDetailOrder} />{historyDetailOrder.status !== "CANCELLED" && <Button variant="outline" data-testid="history-detail-incident-button" onClick={() => { setIncidentOrder(historyDetailOrder); setHistoryDetailOrder(null); }}>Raportează incident</Button>}</>}
      {custodyRecovery && <CustodyRecoveryPanel recovery={custodyRecovery} isOnline={isOnline} scopeKey={historyDetailOrder?.id} onAcknowledged={onCustodyAcknowledged} />}
      {historyDetailOrder && <div className="space-y-4"><div className="grid gap-3 sm:grid-cols-2"><div className="rounded-xl border border-zinc-800 bg-zinc-900 p-3"><p className="text-xs text-zinc-500">Client</p><p className="font-black">{historyDetailOrder.customer_name}</p><p className="font-mono text-sm text-zinc-300">{historyDetailOrder.customer_phone}</p></div><div className="rounded-xl border border-zinc-800 bg-zinc-900 p-3"><p className="text-xs text-zinc-500">Adresă</p><p className="text-sm text-zinc-300">{historyDetailOrder.customer_address}</p></div><div className="rounded-xl border border-zinc-800 bg-zinc-900 p-3"><p className="text-xs text-zinc-500">Status</p><p className="font-black">{getStatusConfig(historyDetailOrder.status).label}</p></div><div className="rounded-xl border border-zinc-800 bg-zinc-900 p-3"><p className="text-xs text-zinc-500">{orderAmountLabel(historyDetailOrder)}</p><p className="text-2xl font-black text-orange-300">{clientCollectionText(historyDetailOrder)}</p></div></div><div className="rounded-xl border border-zinc-800 bg-black/30 p-3"><p className="mb-2 font-black">Produse</p>{historyDetailOrder.items?.map((item) => <div key={`${historyDetailOrder.id}-${item.name}`} className="flex justify-between border-b border-zinc-800 py-2 text-sm last:border-0"><span>{item.quantity}× {item.name}</span><span className="font-mono text-zinc-400">{item.price * item.quantity} RON</span></div>)}</div><OrderFinancialSummary order={historyDetailOrder} role="restaurant" /><CustodyControls order={historyDetailOrder} actor={user} recovery={custodyRecovery} isOnline={isOnline} disabled={custodyDisabled} />{historyDetailOrder.driver_name && <div className="rounded-xl border border-blue-500/30 bg-blue-500/10 p-3 text-blue-100"><Truck className="mr-2 inline h-4 w-4" /> Livrator: {historyDetailOrder.driver_name}</div>}{historyDetailOrder.notes && <div className="rounded-xl border border-orange-500/30 bg-orange-500/10 p-3 text-orange-100">Notă: {historyDetailOrder.notes}</div>}{historyDetailOrder.status === "DELIVERED" && <Button className="w-full bg-orange-500 font-black text-zinc-950 hover:bg-orange-400" onClick={() => { setProblemOrder(historyDetailOrder); setHistoryDetailOrder(null); }} data-testid="history-detail-problem-button"><PlusCircle className="mr-2 h-4 w-4" /> Produs lipsă / adaugă produs</Button>}</div>}
    </DialogContent>
  </Dialog>
);

const LegacyRestaurantProblemDialog = ({ open, problemOrder, setProblemOrder, problemForm, setProblemForm, isCreatingProblem, createProblemOrder, isOnline }) => (
  <Dialog open={open} onOpenChange={(open) => !open && setProblemOrder(null)}>
    <DialogContent data-testid="restaurant-problem-order-dialog">
      <DialogHeader><DialogTitle>Comandă cu problemă · {problemOrder?.order_number}</DialogTitle><DialogDescription>Creează o comandă nouă legată de comanda originală.</DialogDescription></DialogHeader>
      <div className="space-y-3">
        <div className="grid grid-cols-2 gap-2"><Button type="button" variant={problemForm.problem_type === "missing_product" ? "default" : "outline"} onClick={() => setProblemForm((prev) => ({ ...prev, problem_type: "missing_product" }))} data-testid="problem-type-missing-button">Produs lipsă</Button><Button type="button" variant={problemForm.problem_type === "new_product" ? "default" : "outline"} onClick={() => setProblemForm((prev) => ({ ...prev, problem_type: "new_product" }))} data-testid="problem-type-new-button">Produs nou</Button></div>
        <div><Label>Produs</Label><Input value={problemForm.item_name} onChange={(event) => setProblemForm((prev) => ({ ...prev, item_name: event.target.value }))} placeholder="Ex: Sos usturoi / Pizza extra" data-testid="problem-item-name-input" /></div>
        <div className="grid grid-cols-2 gap-3"><div><Label>Cantitate</Label><Input type="number" min="1" value={problemForm.quantity} onChange={(event) => setProblemForm((prev) => ({ ...prev, quantity: event.target.value }))} data-testid="problem-quantity-input" /></div><div><Label>Preț</Label><Input type="number" min="0" value={problemForm.price} onChange={(event) => setProblemForm((prev) => ({ ...prev, price: event.target.value }))} data-testid="problem-price-input" /></div></div>
        <div><Label>Descriere problemă</Label><Textarea value={problemForm.problem_description} onChange={(event) => setProblemForm((prev) => ({ ...prev, problem_description: event.target.value }))} placeholder="Ce trebuie să știe dispeceratul/livratorul?" data-testid="problem-description-input" /></div>
      </div>
      <DialogFooter><Button variant="outline" onClick={() => setProblemOrder(null)} disabled={isCreatingProblem} data-testid="problem-cancel-button">Anulează</Button><Button onClick={createProblemOrder} disabled={isCreatingProblem || !isOnline} data-testid="problem-submit-button">{isCreatingProblem ? "Se creează..." : "Creează comandă legată"}</Button></DialogFooter>
    </DialogContent>
  </Dialog>
);

export const RestaurantProblemDialog = (props) => {
  if (props.problemOrder && !pureLegacyRemake(props.problemOrder)) return <OrderRemakeDialog
    key={`${props.actor?.id}:${props.actor?.role}:${props.actor?.restaurant_id}:${props.problemOrder.id}`}
    open={props.open} order={props.problemOrder} actor={props.actor} apiUrl={props.apiUrl} token={props.token}
    isOnline={props.isOnline} recovery={props.remakeRecovery} originalFinancialRecovery={props.financialRecovery}
    blocked={props.remakeBlocked} onClose={() => props.setProblemOrder(null)} />;
  return <LegacyRestaurantProblemDialog {...props} />;
};

export const RestaurantCancelDialog = ({ open, cancelOrder, setCancelOrder, cancelReason, setCancelReason, cancelStatusVersioned, statusRecovery, isCancellingOrder, handleCancelOrder, pendingOrderAction, isOnline, orders, user, preparationBlocked = false }) => (
  <Dialog open={open} onOpenChange={(open) => !open && setCancelOrder(null)}>
    <DialogContent>
      <DialogHeader>
        <DialogTitle className="flex items-center gap-2 text-red-600">
          <XCircle className="w-5 h-5" />
          Anulare Comandă {cancelOrder?.order_number}
        </DialogTitle>
        <DialogDescription>Completează motivul anulării pentru trasabilitate.</DialogDescription>
        {cancelStatusVersioned && !statusRecovery.capability.enabled && <p role="status">{statusRecovery.capability.ready ? "Statusul versionat este dezactivat. Fluxul legacy este blocat." : "Disponibilitatea statusului versionat nu este confirmata."}</p>}
      </DialogHeader>
      <div className="space-y-4 py-2">
        <p className="text-sm text-muted-foreground">
          Motivul anulării este obligatoriu. Vă rugăm să specificați de ce anulați această comandă.
        </p>
        <Textarea
          placeholder="Scrieți motivul anulării..."
          value={cancelReason}
          maxLength={500}
          disabled={isCancellingOrder || statusRecovery.blocked}
          onChange={(e) => setCancelReason(e.target.value)}
          className="min-h-[100px]"
          data-testid="cancel-reason-input"
        />
      </div>
      <DialogFooter>
        <Button variant="outline" onClick={() => setCancelOrder(null)}>
          Înapoi
        </Button>
        <Button
          variant="destructive"
          onClick={handleCancelOrder}
          disabled={preparationBlocked || isCancellingOrder || pendingOrderAction !== null || !cancelReason.trim() || !isOnline || !statusRecovery.canSubmit(orders.find((o) => o.id === cancelOrder?.id) || cancelOrder) || !canChangeOrderStatus(orders.find((o) => o.id === cancelOrder?.id) || cancelOrder, "CANCELLED", user)}
          data-testid="confirm-cancel-btn"
        >
          <XCircle className="w-4 h-4 mr-2" />
          {isCancellingOrder ? "Se anulează..." : "Confirmă Anularea"}
        </Button>
      </DialogFooter>
    </DialogContent>
  </Dialog>
);
