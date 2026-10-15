import { CustodyControls } from "../OrderCustody";
import { Button } from "../ui/button";
import { Badge } from "../ui/badge";
import { IncidentSummary } from "../OperationalIncidentReporter";
import { OrderFinancialSummary } from "../OrderFinancialSummary";
import { FinancialEventControls } from "../OrderFinancialActivity";
import { readOrderFinance } from "../../lib/orderFinance";
import { Bell, ChefHat, CheckCircle2, Truck, User, Phone, MapPin, PlusCircle, XCircle } from "lucide-react";
import { getPreparationStatus, isShortPreparationBlocked } from "../../lib/orderWorkflow";
import { hasStatusRevision, canChangeOrderStatus } from "../../lib/orderStatusRecovery";
import { PREPARATION_OPTIONS_MINUTES, getPreparationTimer } from "../../lib/restaurantPresentation";

const orderLaneMeta = {
  NEW: { title: "Nouă", className: "border-orange-500/40 bg-orange-500/10 text-orange-200", icon: Bell },
  PREPARING: { title: "În lucru", className: "border-blue-500/40 bg-blue-500/10 text-blue-200", icon: ChefHat },
  READY: { title: "Gata", className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200", icon: CheckCircle2 },
  ASSIGNED: { title: "Ridicare", className: "border-sky-500/40 bg-sky-500/10 text-sky-200", icon: Truck },
  ACCEPTED: { title: "Ridicare", className: "border-sky-500/40 bg-sky-500/10 text-sky-200", icon: Truck },
  PICKED_UP: { title: "Ridicată", className: "border-sky-500/40 bg-sky-500/10 text-sky-200", icon: Truck },
  DELIVERED: { title: "Livrată", className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200", icon: CheckCircle2 },
  CANCELLED: { title: "Anulată", className: "border-red-500/40 bg-red-500/10 text-red-200", icon: XCircle },
};
const unavailableLane = { title: "Status indisponibil", className: "border-zinc-500/40 bg-zinc-500/10 text-zinc-200", icon: Bell };

export const RestaurantOrderCard = ({ order, now, isOnline, pendingOrderAction,
  isCancellingOrder, statusRecovery, prepAvailability, user, preparationBlocked = false, financialRecovery, custodyRecovery,
  onPrepare, onReady, onIncident, onProblem, onCancel }) => {
  const preparationStatus = getPreparationStatus(order);
  const timer = getPreparationTimer(order, now);
  const laneKey = ["PICKED_UP", "DELIVERED", "CANCELLED"].includes(order.status) ? order.status : preparationStatus;
  const lane = (typeof order.id === "string" && order.id.trim() && orderLaneMeta[laneKey]) || unavailableLane;
  const LaneIcon = lane.icon;
  return (
    <article key={order.id} className={`flex min-h-[420px] min-w-0 flex-col rounded-2xl border bg-zinc-900 p-4 shadow-xl transition-colors hover:border-zinc-700 ${preparationStatus === "NEW" ? "border-orange-500/50" : "border-zinc-800"}`} data-testid={`order-card-${order.id}`}>
      <div className="mb-3 flex items-start justify-between gap-3 border-b border-zinc-800 pb-3">
        <div className="min-w-0">
          <p className="font-mono text-sm font-black text-zinc-400">{order.order_number}</p>
          <h3 className="mt-1 truncate text-xl font-black text-white">{order.customer_name}</h3>
        </div>
        <Badge className={`${lane.className} border`}><LaneIcon className="mr-1 h-3.5 w-3.5" />{lane.title}</Badge>
      </div>

      <div className="space-y-3">
        <div className="rounded-xl border border-zinc-800 bg-black/30 p-3">
          <div className="mb-2 flex items-center justify-between text-xs text-zinc-500"><span>Produse</span><span>{order.items?.length || 0} poziții</span></div>
          <div className="space-y-2">
            {order.items?.map((item) => (
              <div key={`${order.id}-${item.name}-${item.price}-${item.quantity}`} className="flex items-start justify-between gap-3 border-b border-zinc-800/70 pb-2 last:border-0 last:pb-0">
                <span className="text-sm font-semibold text-zinc-100">{item.quantity}× {item.name}</span>
                <span className="font-mono text-sm text-zinc-400">{item.price * item.quantity}</span>
              </div>
            ))}
          </div>
          {readOrderFinance(order).state === "legacy" && <div className="mt-3 flex items-center justify-between border-t border-zinc-800 pt-3 text-lg font-black"><span>Total</span><span className="text-orange-300">{order.total_amount} RON</span></div>}
          <OrderFinancialSummary order={order} role="restaurant" />
          <FinancialEventControls order={order} actor={user} recovery={financialRecovery} isOnline={isOnline}
            disabled={preparationBlocked || pendingOrderAction !== null || isCancellingOrder || statusRecovery.record || statusRecovery.busy} />
        </div>

        <div className="space-y-2 text-sm text-zinc-400">
          <p className="flex gap-2"><User className="mt-0.5 h-4 w-4 text-zinc-500" /><span className="min-w-0 truncate">{order.customer_name}</span></p>
          <p className="flex gap-2"><Phone className="mt-0.5 h-4 w-4 text-zinc-500" /><span className="font-mono text-zinc-200" data-testid={`restaurant-order-phone-${order.id}`}>{order.customer_phone}</span></p>
          <p className="flex gap-2"><MapPin className="mt-0.5 h-4 w-4 shrink-0 text-zinc-500" /><span className="line-clamp-2">{order.customer_address}</span></p>
          {order.notes && <p className="rounded-lg border border-orange-500/20 bg-orange-500/10 p-2 text-orange-200">📝 {order.notes}</p>}
        </div>

        {order.driver_name && <div className="flex items-center gap-2 rounded-xl border border-blue-500/20 bg-blue-500/10 p-2 text-sm font-semibold text-blue-200"><Truck className="h-4 w-4" /> Livrator: {order.driver_name}</div>}
      </div>

      <div className="mt-auto space-y-3 pt-4">
        {preparationStatus === 'NEW' && (
          <div className="space-y-2" data-testid={`prep-options-${order.id}`}>
            <p className="text-xs font-black uppercase tracking-[0.15em] text-zinc-500">Setează timp</p>
            <div className="grid grid-cols-3 gap-2">
              {PREPARATION_OPTIONS_MINUTES.map((minutes) => (
                <Button key={minutes} variant="outline" disabled={preparationBlocked || !isOnline || pendingOrderAction !== null || isCancellingOrder || statusRecovery.record || statusRecovery.busy || isShortPreparationBlocked(order, minutes, prepAvailability)} onClick={() => onPrepare(order.id, minutes)} className="h-11 border-zinc-700 bg-zinc-800 text-zinc-100 hover:bg-orange-500 hover:text-zinc-950 disabled:opacity-40" data-testid={`prep-${minutes}-${order.id}`}>{minutes}m</Button>
              ))}
            </div>
          </div>
        )}

        {preparationStatus === 'PREPARING' && (
          <div className={`rounded-xl border p-4 ${timer?.isLate ? "border-red-500/50 bg-red-500/10" : "border-orange-500/40 bg-orange-500/10"}`} data-testid={`preparation-timer-${order.id}`}>
            <div className="flex items-center justify-between gap-3">
              <div><p className="text-xs font-black uppercase tracking-[0.15em] text-zinc-500">Timer</p><p className="text-sm text-zinc-400">Estimare {order.preparation_time || "-"} min</p></div>
              <p className={`font-mono text-4xl font-black ${timer?.isLate ? "animate-pulse text-red-300" : "text-orange-300"}`} data-testid={`restaurant-timer-display-${order.id}`}>{timer?.label || "--:--"}</p>
            </div>
            <Button className="mt-3 h-13 w-full bg-emerald-500 font-black text-emerald-950 hover:bg-emerald-400" onClick={() => onReady(order)} disabled={preparationBlocked || !isOnline || pendingOrderAction !== null || isCancellingOrder || statusRecovery.record || statusRecovery.busy} data-testid={`ready-${order.id}`}><CheckCircle2 className="mr-2 h-5 w-5" /> COMANDA GATA</Button>
          </div>
        )}

        {preparationStatus === 'READY' && <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-center text-emerald-200"><CheckCircle2 className="mx-auto mb-1 h-8 w-8" /><p className="font-black">GATA PENTRU RIDICARE</p><p className="text-sm opacity-80">Așteptăm livratorul</p></div>}

        {['ASSIGNED', 'ACCEPTED'].includes(order.status) && <div className="rounded-xl border border-sky-500/40 bg-sky-500/10 p-4 text-center text-sky-200"><Truck className="mx-auto mb-1 h-8 w-8" /><p className="font-black">LIVRATORUL VINE</p><p className="text-sm opacity-80">{order.driver_name} preia comanda</p></div>}

        <CustodyControls order={order} actor={user} recovery={custodyRecovery} isOnline={isOnline}
          disabled={preparationBlocked || pendingOrderAction !== null || isCancellingOrder || statusRecovery.blocked || financialRecovery?.blocked} />
        <IncidentSummary order={order} />
        {order.status !== "CANCELLED" && <Button variant="outline" onClick={() => onIncident(order)} disabled={!isOnline} data-testid={`incident-${order.id}`}>Raportează incident</Button>}
        {order.status === 'DELIVERED' && <Button variant="outline" className="h-11 w-full border-amber-500/30 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20" onClick={() => onProblem(order)} data-testid={`problem-${order.id}`}><PlusCircle className="mr-2 h-4 w-4" /> Problemă comandă</Button>}
        {(hasStatusRevision(order) ? canChangeOrderStatus(order, "CANCELLED", user) : ['NEW', 'PREPARING', 'READY'].includes(order.status)) && <Button variant="outline" className="h-11 w-full border-red-500/30 bg-red-500/10 text-red-300 hover:bg-red-500/20" onClick={() => onCancel(order)} disabled={preparationBlocked || !isOnline || pendingOrderAction !== null || isCancellingOrder || statusRecovery.blocked || !canChangeOrderStatus(order, "CANCELLED", user)} data-testid={`cancel-${order.id}`}><XCircle className="mr-2 h-4 w-4" /> Anulează</Button>}
      </div>
    </article>
  );
};
