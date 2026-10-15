import { custodyResolved } from "./orderCustody";
import { z } from "zod";
import { readOrderFinance } from "./orderFinance";

export const financialIdentifier = z.string().min(1).max(240).refine((value) => Array.from(value).length <= 120 && value === value.trim() && !/[\u0000-\u001f\u007f]/.test(value))
  .refine((value) => { try { encodeURIComponent(value); return true; } catch { return false; } });
export const financialOperationId = z.string().uuid();
export const financialInteger = z.number().refine((value) => Number.isSafeInteger(value) && value >= 0 && value < Number.MAX_SAFE_INTEGER);
export const financialMoney = z.number().int().positive().max(100000000);
const instant = z.string().max(40).refine((value) => /^(?!0000)\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value) &&
  Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 19) === value.slice(0, 19));
const activitySchema = z.object({
  contract_version: z.literal(1), status: z.enum(["declared", "approved", "outstanding"]), driver_id: financialIdentifier,
  declared_unpaid_bani: financialMoney, declaration_id: financialOperationId, approval_id: financialOperationId.nullable(),
  declared_at: instant, approved_at: instant.nullable(), picked_up_at: instant.nullable(),
  outstanding_bani: financialMoney.nullable(), repayment_due_policy: z.literal("next_pickup_else_shift_end").nullable(),
}).strict();

// Payment is separate evidence. A declaration or restaurant approval can never
// make the immutable financial quote's unknown paid/refund fields become zero.
export const readFinancialActivity = (order) => {
  if (!order) return { state: "none", value: null };
  if (Object.hasOwn(order, "read_financial_activity_invalid") && order.read_financial_activity_invalid !== false) return { state: "invalid", value: null };
  const hasActivity = Object.hasOwn(order, "financial_activity"), hasMarker = Object.hasOwn(order, "financial_activity_contract_version");
  if (!hasActivity && !hasMarker) return { state: "none", value: null };
  if (!hasActivity || !hasMarker || order.financial_activity_contract_version !== 1) return { state: "invalid", value: null };
  const finance = readOrderFinance(order), parsed = activitySchema.safeParse(order.financial_activity);
  if (finance.state !== "ready" || order.payment_type !== "CASH" || !parsed.success) return { state: "invalid", value: null };
  const value = parsed.data;
  if (value.driver_id !== order.driver_id || value.declared_unpaid_bani !== finance.value.advance_required_bani ||
      (value.approval_id === null) !== (value.status === "declared") ||
      (value.approved_at === null) !== (value.status === "declared") ||
      (value.picked_up_at === null) !== (value.status !== "outstanding") ||
      (value.outstanding_bani === null) !== (value.status !== "outstanding") ||
      (value.repayment_due_policy === null) !== (value.status !== "outstanding") ||
      (value.outstanding_bani !== null && value.outstanding_bani !== value.declared_unpaid_bani) ||
      (value.approved_at && Date.parse(value.approved_at) < Date.parse(value.declared_at)) ||
      (value.picked_up_at && Date.parse(value.picked_up_at) < Date.parse(value.approved_at)) ||
      (value.status === "outstanding" ? (!["PICKED_UP", "DELIVERED"].includes(order.status) && !custodyResolved(order)) || !instant.safeParse(order.picked_up_at).success ||
        Date.parse(value.picked_up_at) !== Date.parse(order.picked_up_at) : !["ACCEPTED", "CANCELLED"].includes(order.status) || order.picked_up_at != null)) return { state: "invalid", value: null };
  return { state: "ready", value };
};

export const financialEventEligibility = (order, actor) => {
  const finance = readOrderFinance(order), activity = readFinancialActivity(order);
  if (!order || order.status !== "ACCEPTED" || order.read_actions_unavailable || order.read_data_invalid ||
      finance.state !== "ready" || order.payment_type !== "CASH" || finance.value.advance_required_bani <= 0 ||
      !financialInteger.safeParse(order.order_version).success || !financialIdentifier.safeParse(order.id).success ||
      activity.state === "invalid") return null;
  if (actor?.role === "driver" && financialIdentifier.safeParse(actor.driver_id).success && actor.driver_id === order.driver_id && activity.state === "none") {
    return { event_type: "advance_not_paid_declared", amount_bani: finance.value.advance_required_bani, declaration_id: null };
  }
  if (actor?.role === "restaurant" && actor.restaurant_id === order.restaurant_id && activity.value?.status === "declared") {
    return { event_type: "advance_shortfall_acknowledged", amount_bani: activity.value.declared_unpaid_bani, declaration_id: activity.value.declaration_id };
  }
  return null;
};

export const financialPickupBlocked = (order) => {
  const activity = readFinancialActivity(order);
  return activity.state === "invalid" || activity.value?.status === "declared" || readOrderFinance(order).state === "invalid" || Boolean(order?.read_actions_unavailable);
};
