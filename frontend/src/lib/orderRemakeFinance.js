import { z } from "zod";
import { financialIdentifier, financialOperationId, financialMoney, financialInteger } from "./orderFinancialActivity";
import { canonical, canonicalApiBase, financeId, parseProductsRon, quoteConfirmationSchema,
  validateFinanceCapabilities, validateFinanceTariffs } from "./orderFinancePreview";
import { validateFinancialEventReceipt, financialEventRejectionStatus, validFinancialEventActor, validFinancialEventToken } from "./orderFinancialEventRecovery";

export { canonical, canonicalApiBase, financeId, quoteConfirmationSchema, validateFinanceCapabilities, validateFinanceTariffs };
export { validFinancialEventActor, validFinancialEventToken };
export const REMAKE_PROTOCOL = "financial_remake_v1";
export const REMAKE_TIMEOUT_MS = 15000;
export const operationIdSchema = z.string().min(16).max(128).regex(/^[A-Za-z0-9_-]+$/);
export const safeVersion = z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER);
const money = z.number().int().min(0).max(100000000);
const text = (min, max) => z.string().min(min).max(max).refine((v) => v === v.trim() && !/[\u0000-\u001f\u007f]/.test(v));
const status = z.enum(["NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"]);
const source = text(1, 12).refine((value) => /^[A-Za-z0-9_-]+$/.test(value));
export const remakeParentSchema = z.object({ order_id: financeId, order_version: safeVersion, status, source,
  customer_name: text(2, 140), customer_phone: text(7, 24), customer_address: text(5, 300),
  customer_latitude: z.number().finite().min(-90).max(90).nullable(), customer_longitude: z.number().finite().min(-180).max(180).nullable(),
  has_problem_followup: z.boolean(), problem_followup_order_id: financeId.nullable(), delivery_zone_id: financeId.nullable(),
  delivery_zone_name: text(1, 160).nullable(), delivery_sector: text(0, 80).nullable(), delivery_zone_level: z.number().int().min(0).max(50).nullable(),
}).strict().refine((v) => (v.customer_latitude === null) === (v.customer_longitude === null)
  && v.has_problem_followup === (v.problem_followup_order_id !== null));
export const parentContextSchema = z.object({ contract_version: z.literal(1), kind: z.literal("remake_parent"),
  actor_id: financeId, actor_role: z.literal("restaurant"), restaurant_id: financeId, parent: remakeParentSchema,
  eligibility: z.object({ can_preview: z.boolean(), blocking_code: z.enum(["REMAKE_REQUIRES_DELIVERED", "REMAKE_ALREADY_EXISTS",
    "ORDER_VERSION_EXHAUSTED", "RESTAURANT_PAUSED", "RESTAURANT_UNAVAILABLE", "FINANCIAL_REMAKE_NOT_ENABLED"]).nullable() }).strict()
    .refine((v) => v.can_preview === (v.blocking_code === null)),
}).strict();
export const remakeDraftSchema = z.object({ expected_order_version: safeVersion, problem_type: z.enum(["missing_product", "new_product"]),
  description: text(3, 1000), items: z.array(z.object({ name: text(1, 140), quantity: z.number().int().min(1).max(100),
    unit_price_bani: z.number().int().min(0).max(10000000) }).strict()).min(1).max(200), payment_type: z.enum(["CASH", "CARD"]),
  collection_basis: z.enum(["new_receipt", "prepaid_new_order"]), client_collection_bani: money, advance_required_bani: money,
  financial: z.object({ contract_version: z.literal(1), tariff_version: financeId, products_bani: money,
    basis: z.literal("zone"), zone_id: financeId }).strict(),
}).strict().refine((v) => v.expected_order_version < Number.MAX_SAFE_INTEGER
  && v.items.reduce((sum, item) => sum + item.quantity * item.unit_price_bani, 0) === v.financial.products_bani
  && v.collection_basis === (v.payment_type === "CASH" ? "new_receipt" : "prepaid_new_order")
  && v.client_collection_bani === (v.payment_type === "CASH" ? v.financial.products_bani : 0)
  && v.advance_required_bani === v.client_collection_bani);
export const publicRemakeFinancialSchema = z.object({ contract_version: z.literal(1), currency: z.literal("RON"), tariff_version: financeId,
  products_bani: money, collection_mode: z.enum(["cash", "prepaid"]), client_collection_bani: money,
  restaurant_transport_bani: money, advance_required_bani: money, advance_paid_bani: z.null(), refund_due_bani: z.null(), refund_paid_bani: z.null(),
  basis: z.literal("zone"), zone_id: financeId, zone_name: text(1, 160), zone_sector: text(0, 80).nullable(), zone_level: z.number().int().min(0).max(50).nullable(),
}).strict();
export const remakePreviewSchema = publicRemakeFinancialSchema.extend({ kind: z.literal("remake"), informational: z.literal(true),
  fingerprint_scope: z.literal("server_key_v1"), quote_fingerprint: quoteConfirmationSchema.shape.quote_fingerprint,
  actor_id: financeId, restaurant_id: financeId, parent_order_id: financeId, parent_order_version: safeVersion }).strict();
export const remakeReceiptSchema = z.object({ client_operation_id: operationIdSchema, state: z.enum(["applied", "replayed", "pending", "rejected"]),
  order_id: financeId.nullable(), order_version: safeVersion.nullable(), parent_order_id: financeId.nullable(), parent_order_version: safeVersion.nullable(),
  error_code: z.string().max(64).regex(/^[A-Z][A-Z0-9_]*$/).nullable(), retry_after_seconds: z.number().int().min(1).max(60).nullable() }).strict();
const readbackSchema = z.object({ contract_version: z.literal(1), kind: z.literal("remake_readback"), actor_id: financeId,
  actor_role: z.literal("restaurant"), restaurant_id: financeId, client_operation_id: operationIdSchema, quote_confirmation: quoteConfirmationSchema,
  receipt: remakeReceiptSchema, parent: z.object({ order_id: financeId, order_version: safeVersion, status,
    has_problem_followup: z.literal(true), problem_followup_order_id: financeId }).strict(),
  child: z.object({ order_id: financeId, order_version: safeVersion, status, linked_problem_order_id: financeId,
    creation_kind: z.literal("remake"), source, payment_type: z.enum(["CASH", "CARD"]) }).strict(), financial: publicRemakeFinancialSchema }).strict();

export class RemakeError extends Error { constructor(code, message) { super(message); this.name = "RemakeError"; this.code = code; } }
export const remakeFail = (code = "INVALID_RESPONSE", message = "Refacerea nu poate fi confirmată. Păstrează aceeași încercare și reia verificarea.") => { throw new RemakeError(code, message); };
export const remakeApplied = (r) => Boolean(r && ["applied", "replayed"].includes(r.state));
export const remakeTerminal = (r) => Boolean(r && ["applied", "replayed", "rejected"].includes(r.state));
export const semanticRemakeReceipt = (r) => canonical(r && { ...r, state: remakeApplied(r) ? "success" : r.state });
export const pureLegacyRemake = (order) => Boolean(order && typeof order === "object" && financeId.safeParse(order.id).success
  && !["order_version", "financial", "financial_contract_version", "financial_activity", "financial_activity_contract_version",
    "custody_activity", "custody_contract_version", "read_actions_unavailable", "read_error", "read_error_code", "read_financial_invalid", "read_remake_invalid", "read_custody_invalid", "read_financial_activity_invalid", "_read_invalid"].some((key) => Object.hasOwn(order, key)));
export const parseRemakeUnitPrice = (raw) => { const value = parseProductsRon(raw); if (value > 10000000) remakeFail("INVALID_PRICE", "Prețul unitar depășește limita permisă."); return value; };
export const buildRemakeDraft = (context, form, tariffVersion) => {
  const parsed = parentContextSchema.safeParse(context);
  if (!parsed.success || !parsed.data.eligibility.can_preview || !financeId.safeParse(context.parent.delivery_zone_id).success
    || context.parent.customer_latitude === null || !financeId.safeParse(tariffVersion).success) remakeFail("REMAKE_SELECTION_REQUIRED", "Verifică originalul și alege explicit grila pentru zona sa.");
  if (typeof form.quantity !== "string" || !/^\d{1,3}$/.test(form.quantity)) remakeFail("INVALID_QUANTITY", "Introdu o cantitate între 1 și 100.");
  const quantity = Number(form.quantity), price = parseRemakeUnitPrice(form.unit_price);
  const products = quantity * price, cash = form.payment_type === "CASH";
  const result = remakeDraftSchema.safeParse({ expected_order_version: context.parent.order_version, problem_type: form.problem_type,
    description: form.description.trim(), items: [{ name: form.item_name.trim(), quantity, unit_price_bani: price }], payment_type: form.payment_type,
    collection_basis: cash ? "new_receipt" : "prepaid_new_order", client_collection_bani: cash ? products : 0, advance_required_bani: cash ? products : 0,
    financial: { contract_version: 1, tariff_version: tariffVersion, products_bani: products, basis: "zone", zone_id: context.parent.delivery_zone_id } });
  if (!result.success) remakeFail("INVALID_REMAKE_DRAFT", "Completează produsul, cantitatea, prețul exact, descrierea și plata noului bon.");
  return result.data;
};
export const validateRemakeParent = (response, actor, parentId) => {
  const p = parentContextSchema.safeParse(response?.data);
  if (response?.status !== 200 || !p.success || p.data.actor_id !== actor.id || p.data.actor_role !== actor.role
    || p.data.restaurant_id !== actor.restaurant_id || p.data.parent.order_id !== parentId) remakeFail();
  if (p.data.eligibility.can_preview && (p.data.parent.status !== "DELIVERED" || p.data.parent.has_problem_followup)) remakeFail();
  return p.data;
};
export const validateRemakePreview = (response, actorId, restaurantId, parentId, draft) => {
  const p = remakePreviewSchema.safeParse(response?.data), d = remakeDraftSchema.safeParse(draft);
  if (response?.status !== 200 || !p.success || !d.success) remakeFail();
  const v = p.data;
  if (v.actor_id !== actorId || v.restaurant_id !== restaurantId || v.parent_order_id !== parentId || v.parent_order_version !== draft.expected_order_version
    || v.products_bani !== draft.financial.products_bani || v.tariff_version !== draft.financial.tariff_version || v.zone_id !== draft.financial.zone_id
    || v.collection_mode !== (draft.payment_type === "CASH" ? "cash" : "prepaid") || v.client_collection_bani !== draft.client_collection_bani
    || v.advance_required_bani !== draft.advance_required_bani) remakeFail();
  return v;
};
const rejectedStatus = { ORDER_NOT_FOUND: 404, ORDER_VERSION_CONFLICT: 409, ORDER_VERSION_REQUIRED: 409, ORDER_DATA_INVALID: 409,
  ORDER_VERSION_EXHAUSTED: 409, REMAKE_REQUIRES_DELIVERED: 409, REMAKE_ALREADY_EXISTS: 409, REMAKE_PARENT_CHANGED: 409,
  CUSTODY_RESOLUTION_REQUIRED: 409, RESTAURANT_NOT_FOUND: 404, RESTAURANT_UNAVAILABLE: 409, RESTAURANT_PAUSED: 409,
  RESTAURANT_INVALID: 409, FINANCIAL_SNAPSHOT_INVALID: 409, FINANCIAL_AMOUNT_INVALID: 409, FINANCIAL_INTENT_CLOSED: 409, FINANCIAL_QUOTE_CHANGED: 409 };
export const validateRemakeReceipt = (response, record) => {
  const p = remakeReceiptSchema.safeParse(response?.data); if (!p.success || p.data.client_operation_id !== record.client_operation_id) remakeFail();
  const r = p.data;
  if (remakeApplied(r)) {
    if (response.status !== (r.state === "applied" ? 201 : 200) || r.order_id === record.parent_id || r.order_id === null || r.order_version !== 0
      || r.parent_order_id !== record.parent_id || r.parent_order_version !== record.expected_order_version + 1 || r.error_code !== null || r.retry_after_seconds !== null) remakeFail();
  } else {
    if ([r.order_id, r.order_version, r.parent_order_id, r.parent_order_version].some((v) => v !== null)) remakeFail();
    if (r.state === "pending" ? response.status !== 202 || r.error_code !== null || r.retry_after_seconds !== 2 || String(response.headers?.["retry-after"] ?? response.headers?.get?.("retry-after")) !== "2"
      : !Object.hasOwn(rejectedStatus, r.error_code) || response.status !== rejectedStatus[r.error_code] || r.retry_after_seconds !== null) remakeFail();
  }
  return r;
};
export const storedRemakeReceipt = (receipt, record) => validateRemakeReceipt({ data: receipt,
  headers: { "retry-after": "2" }, status: receipt.state === "rejected" ? rejectedStatus[receipt.error_code] : { applied: 201, replayed: 200, pending: 202 }[receipt.state] }, record);
export const validateRemakeReadback = (response, record, receipt, saved) => {
  const p = readbackSchema.safeParse(response?.data); if (response?.status !== 200 || !p.success || !remakeApplied(receipt)) remakeFail();
  const v = p.data;
  validateRemakeReceipt({ status: 200, data: v.receipt }, record);
  if (v.actor_id !== record.actor_id || v.actor_role !== record.actor_role || v.restaurant_id !== record.restaurant_id
    || v.client_operation_id !== record.client_operation_id || canonical(v.quote_confirmation) !== canonical(record.quote_confirmation)
    || semanticRemakeReceipt(v.receipt) !== semanticRemakeReceipt(receipt) || v.parent.order_id !== record.parent_id
    || v.parent.order_version < receipt.parent_order_version || v.parent.problem_followup_order_id !== receipt.order_id
    || v.child.order_id !== receipt.order_id || v.child.order_version < receipt.order_version || v.child.linked_problem_order_id !== record.parent_id
    || v.financial.advance_required_bani !== v.financial.client_collection_bani
    || v.financial.client_collection_bani !== (v.child.payment_type === "CASH" ? v.financial.products_bani : 0)
    || v.financial.collection_mode !== (v.child.payment_type === "CASH" ? "cash" : "prepaid")) remakeFail();
  if (saved) {
    for (const name of Object.keys(publicRemakeFinancialSchema.shape)) if (v.financial[name] !== saved.preview[name]) remakeFail();
    if (v.child.payment_type !== saved.command.payment_type || v.child.source !== saved.parent_context.parent.source) remakeFail();
  }
  return v;
};

// Independent original-finance protocol: inspect only, never acknowledge or mutate it.
export const assertNoOriginalFinancialIntent = (storage, actor, parentId) => {
  const key = `prodelivery:order-financial-event:v1:${encodeURIComponent(actor.id)}:restaurant:${encodeURIComponent(actor.restaurant_id)}`;
  let raw, value;
  try { raw = storage.getItem(key); if (raw === null) return; if (raw.length > 8192 || unescape(encodeURIComponent(raw)).length > 8192) throw new Error(); value = JSON.parse(raw); }
  catch { remakeFail("ORIGINAL_FINANCE_STORAGE_INVALID", "Evidența financiară salvată necesită verificare înaintea refacerii."); }
  const schema = z.object({ version: z.literal(1), actor_id: financialIdentifier, role: z.literal("restaurant"), resource_id: financialIdentifier,
    order_id: financialIdentifier, event_type: z.literal("advance_shortfall_acknowledged"), amount_bani: financialMoney, declaration_id: financialOperationId,
    client_operation_id: financialOperationId, expected_order_version: financialInteger, receipt: z.unknown().nullable() }).strict();
  const parsed = schema.safeParse(value);
  if (!parsed.success || !Object.hasOwn(value, "receipt") || value.actor_id !== actor.id || value.resource_id !== actor.restaurant_id) remakeFail("ORIGINAL_FINANCE_STORAGE_INVALID");
  if (value.receipt !== null) {
    try { validateFinancialEventReceipt({ data: value.receipt, status: value.receipt.state === "pending" ? 202 : value.receipt.state === "rejected" ? financialEventRejectionStatus[value.receipt.error_code] : 200,
      headers: { "retry-after": "2" } }, value); } catch { remakeFail("ORIGINAL_FINANCE_STORAGE_INVALID"); }
  }
  if (value.order_id === parentId) remakeFail("ORIGINAL_FINANCE_PENDING", "Verifică și confirmă mai întâi încercarea financiară păstrată pentru original.");
};
