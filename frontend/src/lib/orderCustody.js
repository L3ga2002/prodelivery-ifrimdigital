import { z } from "zod";

export const custodyIdentifier = z.string().min(1).max(240).refine((v) => Array.from(v).length <= 120 && v === v.trim() && !/[\u0000-\u001f\u007f]/.test(v))
  .refine((v) => { try { encodeURIComponent(v); return true; } catch { return false; } });
export const custodyId = z.string().regex(/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/);
export const custodyOperationId = custodyId.refine((v) => v[14] === "4" && /[89ab]/.test(v[19]));
export const custodyVersion = z.number().refine((v) => Number.isSafeInteger(v) && v >= 0 && v < Number.MAX_SAFE_INTEGER);
export const custodyInstant = z.string().max(40).refine((v) => /^(?!0000)\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(v) &&
  Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 19) === v.slice(0, 19));
const activitySchema = z.object({
  contract_version: z.literal(1), status: z.enum(["waiting", "reviewed", "return_requested", "keep_authorized", "returned", "kept"]),
  driver_id: custodyIdentifier, incident_id: custodyId, reason: z.enum(["absent", "refused"]), arrival_evidence: z.literal("declared"),
  wait_event_id: custodyId, wait_started_at: custodyInstant, wait_eligible_at: custodyInstant,
  review_id: custodyId.nullable(), reviewed_at: custodyInstant.nullable(), customer_contact_attempted: z.literal(true).nullable(),
  restaurant_contacted: z.literal(true).nullable(), coordination_confirmed: z.literal(true).nullable(),
  decision_id: custodyId.nullable(), decision: z.enum(["return", "keep"]).nullable(), decided_at: custodyInstant.nullable(),
  resolution_id: custodyId.nullable(), resolved_at: custodyInstant.nullable(), pricing_status: z.literal("pending"),
}).strict();
export const custodyLabels = { waiting: "Așteptare declarată la client", reviewed: "Administratorul a consemnat coordonarea", return_requested: "Retur solicitat — produsele sunt la livrator", keep_authorized: "Păstrare autorizată — se așteaptă confirmarea livratorului", returned: "Produse primite de restaurant", kept: "Instrucțiune de păstrare confirmată de livrator" };
export const custodyEventLabels = { delivery_wait_started: "Declararea sosirii și așteptării", delivery_failure_reviewed: "Verificarea livrării blocate", products_disposition_decided: "Decizia restaurantului", products_return_received: "Confirmarea primirii produselor", products_keep_acknowledged: "Confirmarea instrucțiunii de păstrare" };
const invalid = () => ({ state: "invalid", value: null });
export const readCustodyActivity = (order) => {
  if (!order) return { state: "none", value: null };
  if (Object.hasOwn(order, "read_custody_invalid") && order.read_custody_invalid !== false) return invalid();
  const marker = Object.hasOwn(order, "custody_contract_version"), data = Object.hasOwn(order, "custody_activity");
  if (!marker && !data) return { state: "none", value: null };
  if (!marker || !data || order.custody_contract_version !== 1) return invalid();
  const parsed = activitySchema.safeParse(order.custody_activity);
  if (!parsed.success || !custodyIdentifier.safeParse(order.id).success || !custodyIdentifier.safeParse(order.restaurant_id).success || !custodyInstant.safeParse(order.picked_up_at).success) return invalid();
  const v = parsed.data, reviewed = v.status !== "waiting", decided = ["return_requested", "keep_authorized", "returned", "kept"].includes(v.status), resolved = ["returned", "kept"].includes(v.status);
  if (v.driver_id !== order.driver_id || Date.parse(v.wait_started_at) < Date.parse(order.picked_up_at) || Date.parse(v.wait_eligible_at) - Date.parse(v.wait_started_at) !== 600000 ||
    ["review_id", "reviewed_at", "customer_contact_attempted", "restaurant_contacted", "coordination_confirmed"].some((k) => (v[k] !== null) !== reviewed) ||
    ["decision_id", "decision", "decided_at"].some((k) => (v[k] !== null) !== decided) || ["resolution_id", "resolved_at"].some((k) => (v[k] !== null) !== resolved) ||
    (reviewed && Date.parse(v.reviewed_at) < Date.parse(v.wait_eligible_at)) || (decided && Date.parse(v.decided_at) < Date.parse(v.reviewed_at)) ||
    (resolved && Date.parse(v.resolved_at) < Date.parse(v.decided_at)) || (decided && v.decision !== (["return_requested", "returned"].includes(v.status) ? "return" : "keep"))) return invalid();
  if (!resolved && (order.cancelled_by != null || order.cancellation_reason != null)) return invalid();
  const ids = [v.wait_event_id, v.review_id, v.decision_id, v.resolution_id].filter(Boolean);
  if (new Set(ids).size !== ids.length) return invalid();
  if (resolved ? order.status !== "CANCELLED" || order.cancellation_reason !== `custody_${v.status}` || !custodyIdentifier.safeParse(order.cancelled_by).success || order.delivered_at != null || !custodyInstant.safeParse(order.cancelled_at).success || Date.parse(order.cancelled_at) !== Date.parse(v.resolved_at) :
    decided ? order.status !== "PICKED_UP" || order.delivered_at != null || order.cancelled_at != null : !["PICKED_UP", "DELIVERED"].includes(order.status) || order.cancelled_at != null) return invalid();
  if (!resolved && !decided && (order.status === "DELIVERED" ? !custodyInstant.safeParse(order.delivered_at).success || Date.parse(order.delivered_at) < Date.parse(v.reviewed_at || v.wait_started_at) : order.delivered_at != null)) return invalid();
  return { state: "ready", value: v };
};
export const custodyResolved = (order) => ["returned", "kept"].includes(readCustodyActivity(order).value?.status);
export const custodyBlocksNormalMutation = (order) => {
  const result = readCustodyActivity(order);
  return result.state === "invalid" || ["return_requested", "keep_authorized", "returned", "kept"].includes(result.value?.status);
};
const common = { event_type: z.string(), incident_id: custodyId };
export const custodyCommandSchema = z.discriminatedUnion("event_type", [
  z.object({ ...common, event_type: z.literal("delivery_wait_started"), reason: z.enum(["absent", "refused"]) }).strict(),
  z.object({ ...common, event_type: z.literal("delivery_failure_reviewed"), predecessor_id: custodyId, customer_contact_attempted: z.literal(true), restaurant_contacted: z.literal(true), coordination_confirmed: z.literal(true) }).strict(),
  z.object({ ...common, event_type: z.literal("products_disposition_decided"), predecessor_id: custodyId, decision: z.enum(["return", "keep"]) }).strict(),
  z.object({ ...common, event_type: z.literal("products_return_received"), predecessor_id: custodyId }).strict(),
  z.object({ ...common, event_type: z.literal("products_keep_acknowledged"), predecessor_id: custodyId }).strict(),
]);
export const custodyCommandRole = (type) => type === "delivery_failure_reviewed" ? "admin" : ["products_disposition_decided", "products_return_received"].includes(type) ? "restaurant" : "driver";
export const custodyCommandEligible = (order, actor, input) => {
  const command = custodyCommandSchema.safeParse(input), activity = readCustodyActivity(order);
  if (!command.success || !order || order.status !== "PICKED_UP" || order.read_data_invalid || order.read_actions_unavailable || activity.state === "invalid" || !custodyVersion.safeParse(order.order_version).success ||
    !custodyIdentifier.safeParse(order.id).success || !custodyIdentifier.safeParse(order.restaurant_id).success || !custodyIdentifier.safeParse(order.driver_id).success || !custodyInstant.safeParse(order.picked_up_at).success ||
    actor?.role !== custodyCommandRole(command.data.event_type) || (actor.role !== "admin" && actor[`${actor.role}_id`] !== order[`${actor.role}_id`])) return false;
  const c = command.data, v = activity.value;
  if (c.event_type === "delivery_wait_started") return activity.state === "none";
  if (!v || c.incident_id !== v.incident_id) return false;
  return c.event_type === "delivery_failure_reviewed" ? v.status === "waiting" && c.predecessor_id === v.wait_event_id :
    c.event_type === "products_disposition_decided" ? v.status === "reviewed" && c.predecessor_id === v.review_id :
      c.event_type === "products_return_received" ? v.status === "return_requested" && c.predecessor_id === v.decision_id : v.status === "keep_authorized" && c.predecessor_id === v.decision_id;
};
