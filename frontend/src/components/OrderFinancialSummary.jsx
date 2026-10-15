import { readCustodyActivity } from "../lib/orderCustody";
import { OrderCustodySummary } from "./OrderCustody";
import { formatBani, readOrderFinance } from "../lib/orderFinance";
import { OrderFinancialActivitySummary } from "./OrderFinancialActivity";

const FinancialValues = ({ order, role = "restaurant" }) => {
  const finance = readOrderFinance(order);
  if (finance.state === "legacy") return null;
  if (finance.state === "invalid") return <p role="alert" className="break-words rounded-lg border border-amber-500/40 p-3 text-sm" data-testid="order-finance-unavailable">Sumele comenzii necesită verificare. Reîncarcă datele înainte de încasare.</p>;
  const value = finance.value;
  const rows = [
    ["Produse", "products_bani"],
    ["De încasat de la client", "client_collection_bani"],
    ["Transport datorat de restaurant", "restaurant_transport_bani"],
    ...((role === "driver" || role === "admin") && Object.hasOwn(value, "courier_remuneration_bani")
      ? [["Remunerație livrator", "courier_remuneration_bani"]] : []),
    ["Avans necesar la restaurant", "advance_required_bani"],
    ["Avans achitat", "advance_paid_bani"],
    ["Rambursare datorată", "refund_due_bani"],
    ["Rambursare achitată", "refund_paid_bani"],
  ];
  return <section className="mt-3 min-w-0 space-y-2 border-t border-current/20 pt-3 text-sm" aria-label="Sumele comenzii" data-testid="order-finance-summary">
    {readCustodyActivity(order).state === "ready" && order.status !== "DELIVERED" && <p className="font-semibold">Calcul inițial al comenzii — decontarea cursei nereușite rămâne în așteptare. Remunerația afișată nu este acumulată prin rezolvarea custodiei.</p>}
    <dl className="grid grid-cols-[minmax(0,1fr)_auto] gap-x-3 gap-y-2">
      {rows.map(([label, key]) => <div key={key} className="contents"><dt className="min-w-0 break-words">{label}</dt><dd className="text-right font-semibold tabular-nums" data-testid={`order-finance-${key}`}>{formatBani(value[key])}</dd></div>)}
    </dl>
    {order.payment_type === "CARD" && <p className="text-xs">Produse preplătite: nu se încasează din nou de la client.</p>}
    <p className="break-words text-xs opacity-75">Grila aplicată: {value.tariff_version}. „Neconsemnat” nu confirmă o plată.</p>
    <OrderFinancialActivitySummary order={order} />
  </section>;
};

export const OrderFinancialSummary = (props) => <><OrderCustodySummary order={props.order} /><FinancialValues {...props} /></>;
