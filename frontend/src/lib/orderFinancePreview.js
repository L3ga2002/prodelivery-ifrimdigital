import { z } from "zod";
import { readOrderFinance } from "./orderFinance";
import { parseOrderDetail } from "./orderReads";

export const FINANCE_PROTOCOL = "financial_create_v1";
export const FINANCE_TIMEOUT_MS = 15000;
export const financeId = z.string().min(1).max(240).refine((v) => Array.from(v).length <= 120 && v === v.trim() && !/[\u0000-\u001f\u007f]/.test(v));
const money = z.number().int().min(0).max(100000000);
export const quoteConfirmationSchema = z.object({ contract_version: z.literal(1), quote_fingerprint: z.string().regex(/^[a-f0-9]{64}$/) }).strict();
export const financialRequestSchema = z.object({ contract_version: z.literal(1), tariff_version: financeId,
  products_bani: money, basis: z.literal("zone"), zone_id: financeId }).strict();
const capabilities = z.object({ contract_version: z.literal(1), actor_id: financeId, restaurant_id: financeId,
  finance_enabled: z.boolean(), create_quote_enabled: z.boolean(), remake_quote_enabled: z.boolean(),
  quote_informational: z.literal(true), supported_basis: z.tuple([z.literal("zone")]) }).strict();
const tariffs = z.object({ contract_version: z.literal(1), actor_id: financeId, restaurant_id: financeId,
  tariffs: z.array(z.object({ version: financeId, currency: z.literal("RON"), zone_ids: z.array(financeId).max(500) }).strict()).max(50) }).strict();
export const createPreviewSchema = z.object({ contract_version: z.literal(1), kind: z.literal("create"), informational: z.literal(true),
  fingerprint_scope: z.literal("server_key_v1"), quote_fingerprint: quoteConfirmationSchema.shape.quote_fingerprint,
  actor_id: financeId, restaurant_id: financeId, parent_order_id: z.null(), parent_order_version: z.null(), currency: z.literal("RON"),
  tariff_version: financeId, products_bani: money, collection_mode: z.enum(["cash", "prepaid"]), client_collection_bani: money,
  restaurant_transport_bani: money, courier_remuneration_bani: money, advance_required_bani: money,
  advance_paid_bani: z.null(), refund_due_bani: z.null(), refund_paid_bani: z.null(), basis: z.literal("zone"),
  zone_id: financeId, zone_name: z.string().min(1).max(160), zone_sector: z.string().max(80).nullable(),
  zone_level: z.number().int().min(0).max(50).nullable() }).strict();

export class FinancePreviewError extends Error {
  constructor(code, message) { super(message); this.name = "FinancePreviewError"; this.code = code; }
}
const invalid = (code = "FINANCIAL_RESPONSE_INVALID", message = "Datele financiare nu pot fi confirmate. Reia verificarea.") => { throw new FinancePreviewError(code, message); };
export const canonical = (value) => JSON.stringify(value, (_, v) => v && typeof v === "object" && !Array.isArray(v)
  ? Object.fromEntries(Object.keys(v).sort().map((key) => [key, v[key]])) : v);
export const canonicalApiBase = (value, origin = globalThis.location?.origin) => {
  try {
    const url = new URL(value || origin, origin);
    if (!["http:", "https:"].includes(url.protocol) || url.username || url.password || url.search || url.hash) invalid();
    const result = url.origin + url.pathname.replace(/\/+$/, "");
    if (result.length > 2048) invalid();
    return result;
  } catch { return invalid("API_CONTEXT_INVALID", "Adresa serverului nu poate fi verificată."); }
};
export const parseProductsRon = (raw) => {
  if (typeof raw !== "string" || raw.length > 32 || !/^\d+(?:[.,]\d{1,2})?$/.test(raw.trim())) {
    return invalid("INVALID_PRODUCTS_AMOUNT", "Introdu suma produselor în RON, cu maximum două zecimale; zero trebuie introdus explicit.");
  }
  const [whole, fraction = ""] = raw.trim().replace(",", ".").split(".");
  const bani = BigInt(whole) * BigInt(100) + BigInt(fraction.padEnd(2, "0"));
  if (bani > BigInt(100000000)) return invalid("INVALID_PRODUCTS_AMOUNT", "Suma depășește limita permisă.");
  return Number(bani);
};
export const buildFinancialCreateDraft = (form, rawProducts, tariffVersion, normalizeOrder) => {
  const products = parseProductsRon(rawProducts);
  if (!financeId.safeParse(tariffVersion).success || !financeId.safeParse(form?.delivery_zone_id).success) invalid("FINANCIAL_SELECTION_REQUIRED", "Selectează explicit grila și o locație din zona restaurantului.");
  const clean = { ...form, total_amount: products / 100, subtotal_amount: products / 100 };
  ["delivery_fee", "delivery_zone_id", "delivery_zone_name", "delivery_sector", "delivery_zone_level"].forEach((key) => delete clean[key]);
  const order = normalizeOrder(clean);
  if (!Number.isFinite(order.customer_latitude) || !Number.isFinite(order.customer_longitude) || order.linked_problem_order_id != null || order.problem_type != null) invalid("INVALID_FINANCIAL_DRAFT", "Verifică locația și datele comenzii.");
  order.items.forEach((item) => { if (Math.round(item.price * 100) / 100 !== item.price) invalid("INVALID_PRODUCTS_AMOUNT", "Prețul produsului trebuie exprimat în bani exacți."); });
  return { order, financial: financialRequestSchema.parse({ contract_version: 1, tariff_version: tariffVersion,
    products_bani: products, basis: "zone", zone_id: form.delivery_zone_id }) };
};
const scoped = (schema, response, actorId, restaurantId) => {
  const parsed = schema.safeParse(response?.data);
  if (response?.status !== 200 || !parsed.success || parsed.data.actor_id !== actorId || parsed.data.restaurant_id !== restaurantId) invalid();
  return parsed.data;
};
export const validateFinanceCapabilities = (response, actorId, restaurantId) => scoped(capabilities, response, actorId, restaurantId);
export const validateFinanceTariffs = (response, actorId, restaurantId) => {
  const data = scoped(tariffs, response, actorId, restaurantId);
  if (new Set(data.tariffs.map((entry) => entry.version)).size !== data.tariffs.length || data.tariffs.some((entry) => new Set(entry.zone_ids).size !== entry.zone_ids.length)) invalid();
  return data;
};
export const validateCreatePreview = (response, actorId, draft) => {
  const value = scoped(createPreviewSchema, response, actorId, draft.order.restaurant_id);
  const cash = draft.order.payment_type === "CASH";
  if (value.tariff_version !== draft.financial.tariff_version || value.zone_id !== draft.financial.zone_id || value.products_bani !== draft.financial.products_bani
    || value.collection_mode !== (cash ? "cash" : "prepaid") || value.client_collection_bani !== (cash ? value.products_bani : 0)
    || value.advance_required_bani !== value.client_collection_bani) invalid();
  return value;
};
export const validateFinancialReadback = (response, record, receipt, draft) => {
  if (response?.status !== 200) invalid();
  const parsed = parseOrderDetail(response.data, receipt.order_id);
  const order = response.data.order, snapshot = order?.financial;
  if (parsed.order.id !== receipt.order_id || order.restaurant_id !== record.restaurant_id || readOrderFinance(order).state !== "ready"
      || snapshot.basis !== "zone" || !financeId.safeParse(snapshot.zone_id).success
      || typeof snapshot.operation_ref !== "string" || !/^create:[a-f0-9]{64}$/.test(snapshot.operation_ref)
      || order.creation_operation_ref !== snapshot.operation_ref) invalid();
  if (draft) {
    const preview = draft.preview;
    for (const field of ["products_bani", "collection_mode", "client_collection_bani", "restaurant_transport_bani", "courier_remuneration_bani",
      "advance_required_bani", "tariff_version", "zone_id", "basis", "advance_paid_bani", "refund_due_bani", "refund_paid_bani"]) {
      if (snapshot[field] !== preview[field]) invalid();
    }
  }
  return parsed.order;
};
