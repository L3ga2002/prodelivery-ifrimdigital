// Financial snapshots are supplied by the server. Never derive payment evidence
// from an order status or replace an unknown amount with zero.
const amounts = ["products_bani", "client_collection_bani", "restaurant_transport_bani", "courier_remuneration_bani", "advance_required_bani"];
const evidence = ["advance_paid_bani", "refund_due_bani", "refund_paid_bani"];
const isMoney = (value) => Number.isSafeInteger(value) && value >= 0 && value <= 100000000;
const isId = (value) => typeof value === "string" && value.length > 0 && value.length <= 240 && value === value.trim() && !/[\u0000-\u001f\u007f]/.test(value);
const publicAmounts = amounts.filter((key) => key !== "courier_remuneration_bani");
const publicKeys = ["contract_version", "currency", "restaurant_id", "tariff_version", ...publicAmounts,
  "collection_mode", ...evidence, "basis", "snapshot_at"];
const publicId = (value) => {
  if (!isId(value) || Array.from(value).length > 120) return false;
  try { encodeURIComponent(value); return true; } catch { return false; }
};
const publicTime = (value) => {
  if (typeof value !== "string" || value.length > 40 || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(value)) return false;
  const date = new Date(value);
  return Number.isFinite(date.getTime()) && !value.startsWith("0000") && date.toISOString().slice(0, 19) === value.slice(0, 19);
};
const readPublicFinance = (order) => {
  const invalid = { state: "invalid", value: null }, value = order.financial;
  const driver = order.financial_read_visibility === "assigned_driver";
  const keys = driver ? [...publicKeys, "courier_remuneration_bani"] : publicKeys;
  if (order.financial_read_contract_version !== 1 || !["restaurant", "assigned_driver"].includes(order.financial_read_visibility) ||
    order.financial_contract_version !== 1 || value === null || typeof value !== "object" || Array.isArray(value) ||
    Object.keys(value).length !== keys.length || !keys.every((key) => Object.hasOwn(value, key)) ||
    value.contract_version !== 1 || value.currency !== "RON" || !publicAmounts.every((key) => isMoney(value[key])) ||
    (driver && !isMoney(value.courier_remuneration_bani)) || !evidence.every((key) => value[key] === null) ||
    !publicId(value.restaurant_id) || !publicId(value.tariff_version) || value.restaurant_id !== order.restaurant_id ||
    !["zone", "outside"].includes(value.basis) || !publicTime(value.snapshot_at) ||
    !["CASH", "CARD"].includes(order.payment_type) || value.collection_mode !== (order.payment_type === "CASH" ? "cash" : "prepaid") ||
    value.client_collection_bani !== (order.payment_type === "CASH" ? value.products_bani : 0) ||
    value.advance_required_bani !== value.client_collection_bani) return invalid;
  return { state: "ready", value: Object.fromEntries(keys.map((key) => [key, value[key]])) };
};

export const readOrderFinance = (order) => {
  if (!order) return { state: "legacy", value: null };
  if (order.read_financial_invalid === true) return { state: "invalid", value: null };
  if (Object.hasOwn(order, "financial_read_contract_version") || Object.hasOwn(order, "financial_read_visibility")) return readPublicFinance(order);
  const marked = Object.hasOwn(order, "financial_contract_version");
  if (!marked && !Object.hasOwn(order, "financial")) return { state: "legacy", value: null };
  const value = order.financial;
  if (order.financial_contract_version !== 1 || value === null || typeof value !== "object" || Array.isArray(value) || value.contract_version !== 1 || value.currency !== "RON" ||
    !amounts.every((key) => isMoney(value[key])) || !evidence.every((key) => value[key] === null || isMoney(value[key])) ||
    !isId(value.tariff_version) || !isId(value.restaurant_id) || value.restaurant_id !== order.restaurant_id ||
    !["zone", "outside"].includes(value.basis) || typeof value.snapshot_digest !== "string" || !/^[a-fA-F0-9]{64}$/.test(value.snapshot_digest) ||
    typeof value.snapshot_at !== "string" || !Number.isFinite(Date.parse(value.snapshot_at)) ||
    !["CASH", "CARD"].includes(order.payment_type) || value.collection_mode !== (order.payment_type === "CASH" ? "cash" : "prepaid") ||
    value.client_collection_bani !== (order.payment_type === "CASH" ? value.products_bani : 0) || value.advance_required_bani !== value.client_collection_bani) {
    return { state: "invalid", value: null };
  }
  // Whitelist the display contract; private routing/provenance details stay out
  // of view models and React markup.
  return { state: "ready", value: Object.fromEntries([
    "contract_version", "currency", "collection_mode", ...amounts, ...evidence, "tariff_version", "restaurant_id", "basis", "snapshot_at", "snapshot_digest",
  ].map((key) => [key, value[key]])) };
};

export const formatBani = (value) => isMoney(value)
  ? `${Math.floor(value / 100).toLocaleString("ro-RO")},${String(value % 100).padStart(2, "0")} RON`
  : "Neconsemnat";

export const clientCollectionText = (order) => {
  const finance = readOrderFinance(order);
  if (finance.state === "ready") return formatBani(finance.value.client_collection_bani);
  if (finance.state === "invalid") return "Sumă indisponibilă";
  return typeof order?.total_amount === "number" && Number.isFinite(order.total_amount)
    ? `${order.total_amount} RON` : "Sumă indisponibilă";
};

export const orderAmountLabel = (order) => readOrderFinance(order).state === "legacy" ? "Total" : "De încasat";
