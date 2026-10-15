import { custodyId, readCustodyActivity } from "./orderCustody";
import { z } from "zod";
import { readOrderFinance } from "./orderFinance";
import { readFinancialActivity } from "./orderFinancialActivity";

export const ORDER_READ_TIMEOUT_MS = 15000;
export const ORDER_READ_LIMIT = 25;
export const MAX_READ_CURSORS = 64;
export const ORDER_READ_STATUSES = ["NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"];
export const ORDER_STATUS_LABELS = { NEW: "Nou", PREPARING: "Preparare", READY: "Gata", ASSIGNED: "Alocat", ACCEPTED: "Acceptat", PICKED_UP: "Ridicat", DELIVERED: "Livrat", CANCELLED: "Anulat" };
export const ORDER_SOURCE_LABELS = { S: "Site", B: "Bolt", W: "Wolt", G: "Glovo" };
export const emptyReadFilters = () => ({ view: "active", status: "", restaurant_id: "", driver_id: "", from_date: "", to_date: "" });
// A valid 120-code-point identifier can occupy up to 240 UTF-16 units.
const identifier = z.string().min(1).max(240).refine((s) => Array.from(s).length <= 120)
  .refine((s) => s.trim() === s && !Array.from(s).some((c) => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127))
  .refine((s) => { try { encodeURIComponent(s); return true; } catch { return false; } });
const cursor = z.string().min(1).max(4096);
const integer = z.number().refine((n) => Number.isSafeInteger(n) && n >= 0);
const warning = z.string().regex(/^[A-Z][A-Z0-9_]{0,99}$/);
const warningsSchema = z.array(warning).max(200);
const record = (v) => v !== null && typeof v === "object" && !Array.isArray(v);
class OrderReadValidationError extends Error {}
const fail = (message = "Raspuns de citire invalid. Reincarca manual.") => { throw new OrderReadValidationError(message); };
export const validReadActor = (id) => identifier.safeParse(id).success;

const utcDay = (value) => {
  if (value === "" || value == null) return undefined;
  if (typeof value !== "string" || !/^\d{4}-\d{2}-\d{2}$/.test(value)) fail("Data filtrului este invalida.");
  const date = new Date(`${value}T00:00:00.000Z`);
  if (!Number.isFinite(date.getTime()) || date.toISOString().slice(0, 10) !== value || value.startsWith("0000")) fail("Data filtrului este invalida.");
  return date.toISOString();
};
export const normalizeReadFilters = (filters = {}) => {
  const parsed = z.object({ view: z.enum(["active", "history", "all"]), status: z.enum(ORDER_READ_STATUSES).optional(),
    restaurant_id: identifier.optional(), driver_id: identifier.optional(), limit: z.number().int().min(1).max(100) }).safeParse({
    view: filters.view ?? "active", status: filters.status === "" ? undefined : filters.status,
    restaurant_id: filters.restaurant_id === "" ? undefined : filters.restaurant_id,
    driver_id: filters.driver_id === "" ? undefined : filters.driver_id, limit: filters.limit ?? ORDER_READ_LIMIT,
  });
  if (!parsed.success) fail("Filtre invalide. Verifica selectiile.");
  const from_date = utcDay(filters.from_date), to_date = utcDay(filters.to_date);
  if (from_date && to_date && from_date >= to_date) fail("Data de inceput trebuie sa fie inainte de sfarsitul exclusiv.");
  return { ...parsed.data, ...(from_date ? { from_date } : {}), ...(to_date ? { to_date } : {}) };
};

export const readTimestamp = (value) => {
  if (typeof value !== "string") return null;
  const parts = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!parts) return null;
  const [year, month, day, hour, minute, second] = parts.slice(1, 7).map(Number);
  const calendar = new Date(Date.UTC(year, month - 1, day));
  if (year < 100 || calendar.getUTCFullYear() !== year || calendar.getUTCMonth() !== month - 1 || calendar.getUTCDate() !== day || hour > 23 || minute > 59 || second > 59) return null;
  const zone = parts[7];
  if (zone !== "Z" && (Number(zone.slice(1, 3)) > 23 || Number(zone.slice(4)) > 59)) return null;
  const time = Date.parse(value.replace(" ", "T"));
  return Number.isFinite(time) ? new Date(time).toISOString() : null;
};
export const formatReadTime = (value) => {
  const time = readTimestamp(value);
  return time ? `${time.slice(0, 10)} ${time.slice(11, 19)} UTC` : "Indisponibil";
};
export const readText = (value) => (typeof value === "string" && value.length) || (typeof value === "number" && Number.isFinite(value)) ? String(value) : "Indisponibil";
export const readOwnLabel = (labels, key, fallback = "Indisponibil") => typeof key === "string" &&
  Object.hasOwn(labels, key) && typeof labels[key] === "string" ? labels[key] : readText(fallback);

const textFields = ["order_number", "restaurant_name", "driver_name", "customer_name", "customer_phone", "customer_address", "notes", "payment_type", "delivery_zone_id", "delivery_zone_name", "delivery_sector", "cancelled_by", "cancellation_reason"];
const idFields = ["restaurant_id", "driver_id"];
const numberFields = ["subtotal_amount", "delivery_fee", "total_amount", "customer_latitude", "customer_longitude", "preparation_minutes", "preparation_time", "preparation_estimated_seconds", "preparation_actual_seconds", "preparation_delay_seconds", "delivery_zone_level"];
const dateFields = ["created_at", "updated_at", "assigned_at", "accepted_at", "picked_up_at", "delivered_at", "cancelled_at", "preparation_started_at", "preparation_due_at", "preparation_ready_at", "estimated_ready_at"];
const sanitizeOrder = (raw, warnings) => {
  if (!record(raw) || !identifier.safeParse(raw.id).success) { warnings.add("INVALID_ORDER_ITEM"); return null; }
  const order = { id: raw.id };
  let invalid = false;
  const bad = () => { invalid = true; warnings.add("INVALID_ORDER_FIELDS"); };
  if (Object.hasOwn(raw, "read_actions_unavailable")) {
    if (typeof raw.read_actions_unavailable === "boolean") order.read_actions_unavailable = raw.read_actions_unavailable;
    else { order.read_actions_unavailable = true; bad(); }
  }
  textFields.forEach((key) => {
    if (!Object.hasOwn(raw, key)) return;
    if (raw[key] === null || (typeof raw[key] === "string" && raw[key].length <= 4000)) order[key] = raw[key];
    else bad();
  });
  idFields.forEach((key) => {
    if (!Object.hasOwn(raw, key)) return;
    if (raw[key] === null || identifier.safeParse(raw[key]).success) order[key] = raw[key];
    else bad();
  });
  ["linked_problem_order_id", "problem_followup_order_id"].forEach((key) => {
    if (!Object.hasOwn(raw, key)) return;
    if (raw[key] === null || (identifier.safeParse(raw[key]).success && raw[key] !== raw.id)) order[key] = raw[key];
    else { order[key] = null; bad(); }
  });
  if (Object.hasOwn(raw, "read_remake_invalid")) {
    order.read_remake_invalid = raw.read_remake_invalid !== false;
    if (order.read_remake_invalid) {
      order.linked_problem_order_id = null;
      order.problem_followup_order_id = null;
      bad();
    }
  }
  if (Object.hasOwn(raw, "has_problem_followup")) {
    if (typeof raw.has_problem_followup === "boolean") order.has_problem_followup = raw.has_problem_followup;
    else { order.has_problem_followup = null; bad(); }
  }
  if (Object.hasOwn(raw, "problem_type")) {
    if (raw.problem_type === null || ["missing_product", "new_product"].includes(raw.problem_type)) order.problem_type = raw.problem_type;
    else bad();
  }
  if (Object.hasOwn(raw, "problem_description")) {
    if (raw.problem_description === null || (typeof raw.problem_description === "string" && raw.problem_description.length <= 1000)) order.problem_description = raw.problem_description;
    else bad();
  }
  numberFields.forEach((key) => {
    if (!Object.hasOwn(raw, key)) return;
    if (raw[key] === null || (typeof raw[key] === "number" && Number.isFinite(raw[key]))) order[key] = raw[key];
    else bad();
  });
  ["status", "preparation_status", "source"].forEach((key) => {
    const choices = key === "source" ? Object.keys(ORDER_SOURCE_LABELS) : key === "status" ? ORDER_READ_STATUSES : ["NEW", "PREPARING", "READY"];
    if (choices.includes(raw[key])) order[key] = raw[key];
    else if (key !== "status" && raw[key] == null) { if (Object.hasOwn(raw, key)) order[key] = null; }
    else if (key === "status" || Object.hasOwn(raw, key)) { if (key === "preparation_status") order[key] = null; bad(); }
  });
  dateFields.forEach((key) => {
    if (!Object.hasOwn(raw, key)) { if (key === "created_at") warnings.add("ORDER_DATE_UNAVAILABLE"); return; }
    const value = readTimestamp(raw[key]);
    order[key] = value;
    if (!value && raw[key] != null) bad();
    if (key === "created_at" && !value) warnings.add("ORDER_DATE_UNAVAILABLE");
  });
  if (Object.hasOwn(raw, "order_version")) {
    if (integer.safeParse(raw.order_version).success) order.order_version = raw.order_version;
    else { order.order_version = null; bad(); }
  }
  if (Object.hasOwn(raw, "items")) {
    if (!Array.isArray(raw.items) || raw.items.length > 500) bad();
    else order.items = raw.items.flatMap((item) => {
      const parsed = z.object({ name: z.string().max(400), quantity: z.number().finite().positive(), price: z.number().finite().nonnegative() }).safeParse(item);
      if (!parsed.success) { bad(); return []; }
      return [parsed.data];
    });
  }
  if (Object.hasOwn(raw, "financial_contract_version")) {
    order.financial_contract_version = raw.financial_contract_version === 1 ? 1 : null;
  }
  for (const key of ["financial_read_contract_version", "financial_read_visibility"]) {
    if (Object.hasOwn(raw, key)) {
      const valid = key === "financial_read_contract_version" ? raw[key] === 1 : ["restaurant", "assigned_driver"].includes(raw[key]);
      order[key] = valid ? raw[key] : null;
      if (!valid) bad();
    }
  }
  if (Object.hasOwn(raw, "incident_summary")) {
    const incidents = z.array(z.object({ id: identifier, incident_type: z.enum([
      "missing_product", "damaged_product", "pickup_blocked", "delivery_blocked", "other",
    ]) }).strict()).max(50).safeParse(raw.incident_summary);
    if (incidents.success) order.incident_summary = incidents.data;
    else { order.incident_summary = null; order.read_actions_unavailable = true; bad(); }
  }
  if (Object.hasOwn(raw, "read_financial_invalid")) {
    if (typeof raw.read_financial_invalid !== "boolean") { order.read_financial_invalid = true; bad(); }
    else order.read_financial_invalid = raw.read_financial_invalid;
  }
  const financial = readOrderFinance({ ...order, ...(Object.hasOwn(raw, "financial") ? { financial: raw.financial } : {}) });
  if (financial.state === "ready") order.financial = financial.value;
  if (financial.state === "invalid") {
    order.financial = {};
    order.read_actions_unavailable = true;
    warnings.add("INVALID_ORDER_FINANCE");
    bad();
  }
  const custody = readCustodyActivity({ ...order,
    ...(Object.hasOwn(raw, "custody_activity") ? { custody_activity: raw.custody_activity } : {}),
    ...(Object.hasOwn(raw, "custody_contract_version") ? { custody_contract_version: raw.custody_contract_version } : {}),
    ...(Object.hasOwn(raw, "read_custody_invalid") ? { read_custody_invalid: raw.read_custody_invalid } : {}) });
  if (custody.state === "ready") { order.custody_contract_version = 1; order.custody_activity = custody.value; }
  else if (custody.state === "invalid") { order.read_custody_invalid = true; order.read_actions_unavailable = true; warnings.add("INVALID_CUSTODY_ACTIVITY"); bad(); }
  if (Object.hasOwn(raw, "financial_activity_contract_version")) order.financial_activity_contract_version = raw.financial_activity_contract_version === 1 ? 1 : null;
  const activity = readFinancialActivity({ ...order, ...(Object.hasOwn(raw, "financial_activity") ? { financial_activity: raw.financial_activity } : {}),
    ...(Object.hasOwn(raw, "read_financial_activity_invalid") ? { read_financial_activity_invalid: raw.read_financial_activity_invalid } : {}) });
  if (activity.state === "ready") order.financial_activity = activity.value;
  else if (activity.state === "invalid") {
    order.read_financial_activity_invalid = true;
    order.read_actions_unavailable = true;
    warnings.add("INVALID_FINANCIAL_ACTIVITY");
    bad();
  }
  if (invalid) order.read_data_invalid = true;
  return order;
};

const pageSchema = z.object({ items: z.array(z.unknown()).max(100), next_cursor: cursor.nullable(), has_more: z.boolean(), limit: z.number().int().min(1).max(100), data_warnings: warningsSchema });
export const parseOrderPage = (raw, expectedLimit = ORDER_READ_LIMIT) => {
  const parsed = pageSchema.safeParse(raw);
  if (!parsed.success) fail();
  const page = parsed.data;
  if (page.limit !== expectedLimit || page.items.length > page.limit || page.has_more !== (page.next_cursor !== null)) fail();
  const warnings = new Set(page.data_warnings), ids = new Set();
  const items = page.items.flatMap((item) => {
    const order = sanitizeOrder(item, warnings);
    if (!order) return [];
    if (ids.has(order.id)) { warnings.add("DUPLICATE_ORDER_ITEM"); return []; }
    ids.add(order.id); return [order];
  });
  return { ...page, items, data_warnings: [...warnings] };
};

const approvedChanges = new Set(["from_status", "to_status", "from_preparation_status", "to_preparation_status", "old_driver_id", "new_driver_id", "driver_id", "driver_name", "fields", "preparation_time", "preparation_status", "preparation_due_at", "preparation_estimated_seconds", "preparation_actual_seconds", "preparation_delay_seconds", "cancellation_reason", "customer_name", "customer_phone", "customer_address", "customer_latitude", "customer_longitude", "notes"]);
const safeScalar = (v) => v === null || typeof v === "boolean" || (typeof v === "number" && Number.isFinite(v)) || (typeof v === "string" && v.length <= 4000);
const custodyHistoryDecisions = { waiting: null, reviewed: null, return_requested: "return", keep_authorized: "keep", returned: "return", kept: "keep" };
const financialHistoryStates = ["declared", "approved", "outstanding"];
const sanitizeHistory = (raw, warnings) => {
  if (!record(raw)) { warnings.add("INVALID_HISTORY_ITEM"); return null; }
  const entry = {};
  ["id", "action", "performed_by", "performed_by_role"].forEach((key) => {
    if (typeof raw[key] === "string" && raw[key].length <= 240) entry[key] = raw[key];
    else if (raw[key] != null) warnings.add("INVALID_HISTORY_FIELDS");
  });
  entry.created_at = readTimestamp(raw.created_at);
  if (!entry.created_at) warnings.add("HISTORY_DATE_UNAVAILABLE");
  ["from_order_version", "to_order_version"].forEach((key) => {
    if (integer.safeParse(raw[key]).success) entry[key] = raw[key];
    else if (raw[key] != null) warnings.add("INVALID_HISTORY_FIELDS");
  });
  entry.changes = {};
  if (record(raw.changes)) {
    Object.keys(raw.changes).forEach((key) => {
      if (["linked_problem_order_id", "problem_followup_order_id"].includes(key) && identifier.safeParse(raw.changes[key]).success) entry.changes[key] = raw.changes[key];
      else if (key === "financial_snapshot_digest" && typeof raw.changes[key] === "string" && /^[a-fA-F0-9]{64}$/.test(raw.changes[key])) entry.changes[key] = raw.changes[key];
      else if (key === "courier_remuneration_bani" && Number.isSafeInteger(raw.changes[key]) && raw.changes[key] >= 0 && raw.changes[key] <= 100000000) entry.changes[key] = raw.changes[key];
      else if (["declaration_id", "incident_id"].includes(key) && custodyId.safeParse(raw.changes[key]).success) entry.changes[key] = raw.changes[key];
      else if (key === "custody_event_id" && custodyId.safeParse(raw.changes[key]).success && raw.changes[key][14] === "5" && /[89ab]/.test(raw.changes[key][19])) entry.changes[key] = raw.changes[key];
      else if (key === "approval_id" && ((raw.changes[key] === null && raw.changes.financial_activity_status === "declared") ||
        (custodyId.safeParse(raw.changes[key]).success && ["approved", "outstanding"].includes(raw.changes.financial_activity_status)))) entry.changes[key] = raw.changes[key];
      else if (key === "declared_unpaid_bani" && Number.isSafeInteger(raw.changes[key]) && raw.changes[key] > 0 && raw.changes[key] <= 100000000) entry.changes[key] = raw.changes[key];
      else if (key === "financial_activity_status" && financialHistoryStates.includes(raw.changes[key])) entry.changes[key] = raw.changes[key];
      else if (key === "repayment_due_policy" && raw.changes[key] === "next_pickup_else_shift_end" && raw.changes.financial_activity_status === "outstanding") entry.changes[key] = raw.changes[key];
      else if (key === "custody_status" && typeof raw.changes[key] === "string" && Object.hasOwn(custodyHistoryDecisions, raw.changes[key])) entry.changes[key] = raw.changes[key];
      else if (key === "decision" && typeof raw.changes.custody_status === "string" && Object.hasOwn(custodyHistoryDecisions, raw.changes.custody_status) && raw.changes[key] === custodyHistoryDecisions[raw.changes.custody_status]) entry.changes[key] = raw.changes[key];
      else if (approvedChanges.has(key) && safeScalar(raw.changes[key])) entry.changes[key] = raw.changes[key];
      else warnings.add("HISTORY_CHANGE_UNAVAILABLE");
    });
  } else if (raw.changes != null) warnings.add("INVALID_HISTORY_FIELDS");
  return entry;
};
const detailSchema = z.object({ order: z.unknown(), history: z.array(z.unknown()).max(50), next_history_before: integer.nullable(), history_has_more: z.boolean(), data_warnings: warningsSchema });
export const parseOrderDetail = (raw, orderId, historyBefore = null) => {
  const parsed = detailSchema.safeParse(raw);
  if (!parsed.success) fail();
  const detail = parsed.data;
  const publicEnvelope = Object.hasOwn(raw, "read_contract_version") || Object.hasOwn(raw, "read_visibility");
  if (publicEnvelope) {
    if (raw.read_contract_version !== 1 || !["restaurant", "assigned_driver"].includes(raw.read_visibility)) fail();
    detail.read_contract_version = 1;
    detail.read_visibility = raw.read_visibility;
    if (record(raw.order) && ["financial", "financial_contract_version", "financial_read_contract_version", "financial_read_visibility"]
      .some((key) => Object.hasOwn(raw.order, key)) &&
      (raw.order.financial_read_contract_version !== 1 || raw.order.financial_read_visibility !== raw.read_visibility)) fail();
    const entryKeys = new Set(["index", "id", "action", "performed_by", "performed_by_role", "created_at", "from_order_version", "to_order_version", "changes"]);
    const publicChanges = new Set([...approvedChanges, "linked_problem_order_id", "problem_followup_order_id", "declared_unpaid_bani", "declaration_id", "approval_id", "financial_activity_status", "repayment_due_policy", "custody_status", "incident_id", "custody_event_id", "decision"]);
    for (const entry of detail.history) {
      if (!record(entry) || Object.keys(entry).some((key) => !entryKeys.has(key)) || !record(entry.changes) ||
        Object.keys(entry.changes).some((key) => !publicChanges.has(key)) || !integer.safeParse(entry.index).success) fail();
    }
  } else if (record(raw.order) && (Object.hasOwn(raw.order, "financial_read_contract_version") || Object.hasOwn(raw.order, "financial_read_visibility"))) fail();
  if (detail.history_has_more !== (detail.next_history_before !== null) ||
    (historyBefore !== null && detail.next_history_before !== null && detail.next_history_before >= historyBefore)) fail();
  const warnings = new Set(detail.data_warnings), order = sanitizeOrder(detail.order, warnings);
  if (!order || order.id !== orderId) fail("Detaliul primit nu corespunde comenzii selectate.");
  return { ...detail, order, history: detail.history.flatMap((entry) => {
    const safe = sanitizeHistory(entry, warnings); return safe ? [{ ...safe, ...(publicEnvelope ? { index: entry.index } : {}) }] : [];
  }), data_warnings: [...warnings] };
};

export const orderReadError = (error) => {
  const status = error?.response?.status;
  if (status === 401 || status === 403) return "Sesiunea sau accesul nu mai este valid. Reautentifica-te.";
  if (status === 409) return "Contul sau cursorul s-a schimbat. Reincarca prima pagina.";
  if (status === 400 || status === 422) return "Filtre sau cursor respinse. Verifica filtrele si reincarca.";
  if (status === 404) return "Comanda nu mai este disponibila.";
  if (status === 503) return "Citirea este temporar indisponibila. Reincarca manual.";
  if (error?.code === "ECONNABORTED" || error?.code === "ETIMEDOUT") return "Citirea a depasit 15 secunde. Reincarca manual.";
  return error instanceof OrderReadValidationError ? error.message : "Nu s-au putut citi datele. Reincarca manual.";
};
