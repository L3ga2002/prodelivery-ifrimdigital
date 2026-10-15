import { z } from "zod";
import { verifyRecoverySession } from "./recoverySession";
import { canonical, canonicalApiBase, createPreviewSchema, financeId, financialRequestSchema, FINANCE_PROTOCOL,
  quoteConfirmationSchema, validateCreatePreview, validateFinancialReadback } from "./orderFinancePreview";

export const CREATE_REQUEST_TIMEOUT_MS = 15000;
export const MAX_RECOVERY_READS = 3;
const ID = z.string().min(16).max(128).regex(/^[A-Za-z0-9_-]+$/);
const text = (min, max) => z.string().trim().min(min).max(max);
const amount = z.number().finite().min(0).max(1000000);
const optionalText = (max) => z.string().trim().max(max).nullable().optional();
const nullableNumber = (min, max) => z.number().finite().min(min).max(max).nullable().optional();
const orderSchema = z.object({
  restaurant_id: text(1, 120), customer_name: text(2, 140),
  customer_phone: text(7, 24), customer_address: text(5, 300),
  customer_latitude: nullableNumber(-90, 90), customer_longitude: nullableNumber(-180, 180),
  items: z.array(z.object({ name: text(1, 140), quantity: z.number().int().min(1).max(100),
    price: z.number().finite().min(0).max(100000) }).strict()).max(200).default([]),
  subtotal_amount: amount.nullable().optional(), delivery_fee: amount.nullable().optional(),
  total_amount: amount, payment_type: z.enum(["CASH", "CARD"]).default("CASH"),
  notes: optionalText(1000), source: text(1, 12).regex(/^[A-Za-z0-9_-]+$/).default("S"),
  delivery_zone_id: optionalText(120), delivery_zone_name: optionalText(160),
  delivery_sector: optionalText(80), delivery_zone_level: z.number().int().min(0).max(50).nullable().optional(),
  linked_problem_order_id: text(1, 120).nullable().optional(),
  problem_type: z.enum(["missing_product", "new_product"]).nullable().optional(),
  problem_description: optionalText(1000),
}).strict().refine((o) => (o.customer_latitude == null) === (o.customer_longitude == null))
  .refine((o) => !o.problem_type || Boolean(o.problem_description));
const receiptSchema = z.object({
  client_operation_id: ID, state: z.enum(["applied", "replayed", "pending", "rejected"]),
  order_id: z.string().min(1).max(120).refine((id) => id === id.trim()).nullable().optional(), order_version: z.number().int().nullable().optional(),
  error_code: z.string().max(64).regex(/^[A-Z][A-Z0-9_]*$/).nullable().optional(),
  retry_after_seconds: z.number().int().min(1).max(60).nullable().optional(),
}).strict();
const legacyRecordSchema = z.object({
  version: z.literal(1), actor_id: text(1, 120), client_operation_id: ID,
  created_at: z.number().int().nonnegative(), receipt: receiptSchema.nullable(),
}).strict();
const draftSchema = z.object({ actor_id: text(1, 120), client_operation_id: ID, order: orderSchema }).strict();
const financeBindingShape = { version: z.literal(2), protocol: z.literal(FINANCE_PROTOCOL), api_base: z.string().min(1).max(2048),
  actor_id: financeId, actor_role: z.literal("admin"), actor_restaurant_id: financeId.nullable(), restaurant_id: financeId,
  client_operation_id: ID, created_at: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER) };
const financialReceiptSchema = receiptSchema.extend({ order_id: financeId.nullable(), order_version: z.number().int().nullable(),
  error_code: z.string().max(64).regex(/^[A-Z][A-Z0-9_]*$/).nullable(), retry_after_seconds: z.number().int().min(1).max(60).nullable() });
const financialRecordSchema = z.object({ ...financeBindingShape, quote_confirmation: quoteConfirmationSchema, receipt: financialReceiptSchema.nullable() }).strict();
const recordSchema = z.union([legacyRecordSchema, financialRecordSchema]);
const financialCommandSchema = z.object({ client_operation_id: ID, order: orderSchema, financial: financialRequestSchema,
  quote_confirmation: quoteConfirmationSchema }).strict();
const financialDraftSchema = z.object({ ...financeBindingShape, command: financialCommandSchema, preview: createPreviewSchema }).strict();
const financeBinding = (record) => canonical(Object.fromEntries([...Object.keys(financeBindingShape), "quote_confirmation"].map((name) => [name, record[name]])));
const utf8Length = (value) => unescape(encodeURIComponent(value)).length;

export class OrderRecoveryError extends Error {
  constructor(code, message) { super(message); this.name = "OrderRecoveryError"; this.code = code; }
}
const fail = (code, message) => { throw new OrderRecoveryError(code, message); };
const storageError = () => fail("STORAGE_UNAVAILABLE", "Nu pot păstra identitatea comenzii. Verifică stocarea browserului înainte de a continua.");
const invalidResponse = () => fail("INVALID_RESPONSE", "Răspunsul serverului nu poate fi confirmat. Verifică aceeași comandă; nu crea un duplicat.");
const unresolved = () => fail("OPERATION_UNCERTAIN", "Rezultatul comenzii este încă neconfirmat. Păstrează această operație și reia verificarea.");
const isTerminal = (receipt) => receipt && receipt.state !== "pending";

export const normalizeCreateOrder = (value) => {
  // The current form has one unused product placeholder, not an actual item.
  const placeholder = value?.items?.length === 1 && value.items[0]?.name === ""
    && value.items[0]?.quantity === 1 && value.items[0]?.price === 0;
  const parsed = orderSchema.safeParse({ ...value, items: placeholder ? [] : value?.items });
  if (!parsed.success) fail("INVALID_ORDER", "Verifică numele, telefonul, adresa, coordonatele și valorile comenzii.");
  return parsed.data;
};

export const validateCreationReceipt = (response, id) => {
  const parsed = receiptSchema.safeParse(response?.data);
  if (!parsed.success || parsed.data.client_operation_id !== id) invalidResponse();
  const r = parsed.data;
  if (r.state === "applied" || r.state === "replayed") {
    if (response.status !== (r.state === "applied" ? 201 : 200) || !r.order_id
      || Array.from(r.order_id).some((c) => c.charCodeAt(0) < 32 || c.charCodeAt(0) === 127) || r.order_version !== 0
      || r.error_code != null || r.retry_after_seconds != null) invalidResponse();
  } else if (r.state === "pending") {
    if (response.status !== 202 || r.retry_after_seconds == null || r.order_id != null
      || r.order_version != null || r.error_code != null) invalidResponse();
  } else if (![404, 409].includes(response.status) || !r.error_code || r.order_id != null
    || r.order_version != null || r.retry_after_seconds != null) invalidResponse();
  return r;
};
const validateFinancialReceipt = (response, id) => {
  if (!financialReceiptSchema.safeParse(response?.data).success) invalidResponse();
  return validateCreationReceipt(response, id);
};

const readableError = (error) => {
  if (error instanceof OrderRecoveryError) return error;
  const status = error?.response?.status;
  if (status === 401) return new OrderRecoveryError("AUTH_REQUIRED", "Sesiunea a expirat. Reconectează-te pentru verificarea aceleiași comenzi.");
  if (status === 403) return new OrderRecoveryError("NOT_AUTHORIZED", "Accesul s-a schimbat. Comanda necesită verificare cu un cont autorizat.");
  if (status === 409) return new OrderRecoveryError("INTENT_CONFLICT", "Datele operației nu corespund. Nu trimite o comandă nouă până la clarificare.");
  if (status === 422) return new OrderRecoveryError("INVALID_ORDER", "Serverul a respins datele comenzii. Verifică aceeași operație înainte de a continua.");
  return new OrderRecoveryError("RECOVERY_UNAVAILABLE", "Serverul nu poate confirma acum comanda. Reia verificarea, fără o comandă nouă.");
};

export const createOrderRecovery = ({ actorId, api, durableStorage, draftStorage, locks, crypto,
  actorRole = null, actorRestaurantId = null, apiBase = null, financialApi = api,
  isOwnerActive = () => true,
  isOnline = () => true, wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) }) => {
  if (!text(1, 120).safeParse(actorId).success || actorId !== actorId.trim()) {
    fail("AUTH_REQUIRED", "Autentificarea este necesară.");
  }
  const key = `prodelivery:order-create:v1:${encodeURIComponent(actorId)}`;
  const draftKey = (id) => `${key}:draft:${id}`;
  const url = (id) => `/api/orders/operations/create/${encodeURIComponent(id)}`;
  let working = false;
  let memoryDraft = null;
  let active = true;
  const observedDrafts = new Set();
  const deferredPayloads = new Set();
  const removePayload = (id) => {
    if (memoryDraft?.client_operation_id === id) memoryDraft = null;
    try {
      draftStorage.removeItem(draftKey(id));
      if (draftStorage.getItem(draftKey(id)) != null) storageError();
      observedDrafts.delete(id);
      deferredPayloads.delete(id);
    } catch { storageError(); }
  };
  let lifecycleEpoch = 0;
  let intentGeneration = 0;
  const currentOwner = (epoch) => { if (epoch !== lifecycleEpoch || !isOwnerActive()) fail("SESSION_CHANGED", "Sesiunea s-a schimbat. Intentia ramane pastrata."); };
  const requireOwner = (epoch = lifecycleEpoch) => {
    currentOwner(epoch);
    if (!active) fail("SESSION_CHANGED", "Sesiunea s-a schimbat. Reconectează-te pentru verificarea comenzii.");
  };
  const read = (epoch = lifecycleEpoch, cleanup = true) => {
    let raw;
    try { raw = durableStorage.getItem(key); } catch { storageError(); }
    if (raw == null) return null;
    // Even the largest valid historical metadata is well below this bound.
    if (raw.length > 8192) storageError();
    let parsed;
    try { parsed = recordSchema.safeParse(JSON.parse(raw)); } catch { storageError(); }
    if (!parsed.success || parsed.data.actor_id !== actorId) storageError();
    const record = parsed.data;
    if (record.version === 2 && (utf8Length(raw) > 8192 || canonicalApiBase(record.api_base) !== record.api_base)) storageError();
    // V2 reads are observations, not ownership of another tab's/new intent.
    // Only our successful submission or a validated requested draft enrolls it.
    if (record.version === 1) observedDrafts.add(record.client_operation_id);
    if (record.receipt) validateCreationReceipt({ data: record.receipt,
      status: { applied: 201, replayed: 200, pending: 202, rejected: 409 }[record.receipt.state] }, record.client_operation_id);
    if (record.version === 1 && isTerminal(record.receipt) && cleanup && active && isOwnerActive()) {
      requireOwner(epoch);
      removePayload(record.client_operation_id);
    }
    return record;
  };
  const write = (record, epoch = lifecycleEpoch) => {
    requireOwner(epoch);
    const serialized = JSON.stringify(record);
    try {
      durableStorage.setItem(key, serialized);
      if (durableStorage.getItem(key) !== serialized) storageError();
    } catch { storageError(); }
  };
  const draft = (record) => {
    if (record.version === 1 && memoryDraft?.client_operation_id === record.client_operation_id) return memoryDraft;
    let raw;
    try { raw = draftStorage.getItem(draftKey(record.client_operation_id)); } catch { storageError(); }
    if (raw == null) return null;
    if (record.version === 2 && (raw.length > 98304 || utf8Length(raw) > 98304)) storageError();
    let p;
    try { p = (record.version === 2 ? financialDraftSchema : draftSchema).safeParse(JSON.parse(raw)); } catch { storageError(); }
    if (!p.success || p.data.actor_id !== actorId || p.data.client_operation_id !== record.client_operation_id) storageError();
    if (record.version === 2) {
      const value = p.data;
      if (utf8Length(JSON.stringify(value.command)) > 65536 || financeBinding({ ...value, quote_confirmation: value.command.quote_confirmation }) !== financeBinding(record)
          || value.command.client_operation_id !== record.client_operation_id || value.command.order.restaurant_id !== record.restaurant_id) storageError();
      validateCreatePreview({ status: 200, data: value.preview }, actorId, value.command);
      if (value.preview.quote_fingerprint !== record.quote_confirmation.quote_fingerprint) storageError();
      requireFinance(record);
      observedDrafts.add(record.client_operation_id);
    }
    memoryDraft = p.data;
    return memoryDraft;
  };
  const clearDraft = () => {
    // Explicit logout/ACK cleanup may run after retirement; this read stays pure.
    // A retired financial owner must not discover and clean a newer intent.
    let financial = false;
    try { financial = JSON.parse(durableStorage.getItem(key))?.version === 2; } catch { storageError(); }
    if (!financial || (active && isOwnerActive())) read(lifecycleEpoch, false);
    memoryDraft = null;
    // ACK in another tab may already have removed durable metadata.
    // Only identities validated by this controller are eligible for cleanup.
    observedDrafts.forEach(removePayload);
    deferredPayloads.forEach(removePayload);
  };
  const saveOutcome = (record, receipt, epoch) => {
    requireOwner(epoch);
    write({ ...record, receipt }, epoch);
    if (isTerminal(receipt)) clearDraft();
    return receipt;
  };
  const requireFinance = (record) => {
    if (actorRole !== "admin" || !apiBase || record.actor_id !== actorId || record.actor_role !== actorRole
      || record.actor_restaurant_id !== actorRestaurantId || record.api_base !== apiBase) {
      fail("FINANCIAL_CONTEXT_CHANGED", "Revino la contul și serverul inițial pentru verificarea aceleiași operații.");
    }
  };
  const leaseFor = (record, epoch = lifecycleEpoch) => {
    requireFinance(record);
    return { epoch, generation: intentGeneration, binding: financeBinding(record) };
  };
  const currentFinance = (lease, { inactive = false } = {}) => {
    if (inactive) currentOwner(lease.epoch); else requireOwner(lease.epoch);
    const current = read(lease.epoch, false);
    if (lease.generation !== intentGeneration || current?.version !== 2 || financeBinding(current) !== lease.binding) {
      fail("INTENT_CHANGED", "Operația curentă s-a schimbat. Răspunsul anterior a fost ignorat.");
    }
    requireFinance(current); return current;
  };
  const financialRequest = async (method, path, body, lease, inactive = false) => {
    currentFinance(lease, { inactive });
    let response;
    try { response = method === "get" ? await financialApi.get(path, { timeout: CREATE_REQUEST_TIMEOUT_MS })
      : await financialApi.post(path, body, { timeout: CREATE_REQUEST_TIMEOUT_MS }); }
    catch (error) {
      currentFinance(lease, { inactive });
      if (error?.response?.data?.state === "rejected") response = error.response;
      else throw error;
    }
    currentFinance(lease, { inactive }); return response;
  };
  const financialUrl = (id) => `/api/orders/operations/finance/create/${encodeURIComponent(id)}`;
  const semanticReceipt = (receipt) => canonical(receipt && { id: receipt.client_operation_id,
    state: ["applied", "replayed"].includes(receipt.state) ? "success" : receipt.state,
    order_id: receipt.order_id ?? null, order_version: receipt.order_version ?? null, error_code: receipt.error_code ?? null });
  const saveFinancialOutcome = (lease, receipt) => {
    const current = currentFinance(lease);
    if (isTerminal(current.receipt) && semanticReceipt(current.receipt) !== semanticReceipt(receipt)) unresolved();
    write({ ...current, receipt }, lease.epoch);
    return receipt;
  };
  const reconcileFinancial = async (record, epoch) => {
    const lease = leaseFor(record, epoch);
    if (!isOnline()) fail("OFFLINE", "Fără internet. Identitatea este păstrată.");
    const response = await financialRequest("get", financialUrl(record.client_operation_id), undefined, lease);
    return saveFinancialOutcome(lease, validateFinancialReceipt(response, record.client_operation_id));
  };
  const sendFinancial = async (record, saved, lease) => {
    const response = await financialRequest("post", "/api/orders/operations/finance/create", JSON.parse(JSON.stringify(saved.command)), lease);
    return saveFinancialOutcome(lease, validateFinancialReceipt(response, record.client_operation_id));
  };
  const submitFinancial = async (input, epoch) => {
    if (read(epoch, false)) fail("INTENT_PENDING", "Verifică operația existentă înaintea unei comenzi noi.");
    if (!isOnline()) fail("OFFLINE", "Fără internet. Comanda nu a fost trimisă.");
    const parsed = z.object({ order: orderSchema, financial: financialRequestSchema,
      quote_confirmation: quoteConfirmationSchema, preview: createPreviewSchema }).strict().safeParse(input);
    if (!parsed.success) fail("INVALID_FINANCIAL_DRAFT", "Confirmă o cotație validă pentru datele curente.");
    const value = parsed.data;
    validateCreatePreview({ status: 200, data: value.preview }, actorId, value);
    if (value.quote_confirmation.quote_fingerprint !== value.preview.quote_fingerprint || value.order.delivery_fee != null
      || value.order.total_amount !== value.financial.products_bani / 100 || value.order.subtotal_amount !== value.financial.products_bani / 100) invalidResponse();
    let id;
    try { id = crypto.randomUUID(); } catch { fail("ID_UNAVAILABLE", "Nu pot genera identitatea operației."); }
    if (!ID.safeParse(id).success) fail("ID_UNAVAILABLE", "Identitate invalidă.");
    const record = { version: 2, protocol: FINANCE_PROTOCOL, api_base: apiBase, actor_id: actorId, actor_role: actorRole,
      actor_restaurant_id: actorRestaurantId, restaurant_id: value.order.restaurant_id, client_operation_id: id,
      created_at: Date.now(), quote_confirmation: value.quote_confirmation, receipt: null };
    if (!financialRecordSchema.safeParse(record).success) fail("FINANCIAL_CONTEXT_CHANGED", "Verifică sesiunea financiară.");
    requireFinance(record);
    const { receipt, quote_confirmation, ...binding } = record;
    const saved = { ...binding, command: { client_operation_id: id, order: value.order, financial: value.financial,
      quote_confirmation }, preview: value.preview };
    const serialized = JSON.stringify(saved);
    if (utf8Length(serialized) > 98304 || utf8Length(JSON.stringify(saved.command)) > 65536 || utf8Length(JSON.stringify(record)) > 8192) storageError();
    try {
      if (draftStorage.getItem(draftKey(id)) != null) storageError();
      draftStorage.setItem(draftKey(id), serialized);
      if (draftStorage.getItem(draftKey(id)) !== serialized) storageError();
    } catch { storageError(); }
    try { write(record, epoch); }
    catch (error) { try { draftStorage.removeItem(draftKey(id)); } catch { /* No request sent. */ } throw error; }
    memoryDraft = saved; observedDrafts.add(id); intentGeneration++;
    const lease = leaseFor(record, epoch);
    try { return await sendFinancial(record, saved, lease); }
    catch (error) {
      currentFinance(lease);
      if (error instanceof OrderRecoveryError || [401, 403, 409, 422].includes(error?.response?.status)) throw error;
      return reconcileFinancial(currentFinance(lease), epoch);
    }
  };
  const request = async (method, path, body, epoch = lifecycleEpoch) => {
    requireOwner(epoch);
    let response;
    try {
      response = method === "get" ? await api.get(path, { timeout: CREATE_REQUEST_TIMEOUT_MS })
        : await api.post(path, body, { timeout: CREATE_REQUEST_TIMEOUT_MS });
    } catch (error) {
      requireOwner(epoch);
      if (error?.response?.data?.state === "rejected") response = error.response;
      else throw error;
    }
    requireOwner(epoch); return response;
  };
  const send = async (record, command, epoch) => {
    requireOwner(epoch);
    const response = await request("post", "/api/orders/operations/create", {
      client_operation_id: record.client_operation_id, order: JSON.parse(JSON.stringify(command.order)),
    }, epoch);
    return saveOutcome(record, validateCreationReceipt(response, record.client_operation_id), epoch);
  };
  const reconcile = async (record, epoch) => {
    if (record.version === 2) return reconcileFinancial(record, epoch);
    if (isTerminal(record.receipt)) return record.receipt;
    let resumed = false;
    for (let attempt = 0; attempt < MAX_RECOVERY_READS; attempt += 1) {
      requireOwner(epoch);
      if (!isOnline()) fail("OFFLINE", "Nu ai internet. Identitatea comenzii este păstrată pentru verificare.");
      let response;
      try { response = await request("get", url(record.client_operation_id), undefined, epoch); }
      catch (error) {
        requireOwner(epoch);
        if (error?.response?.status !== 404 || resumed) throw readableError(error);
        const command = draft(record);
        if (!command) unresolved();
        resumed = true;
        const result = await send(record, command, epoch);
        if (isTerminal(result)) return result;
        record = read(epoch);
        continue;
      }
      let receipt = validateCreationReceipt(response, record.client_operation_id);
      if (isTerminal(receipt)) return saveOutcome(record, receipt, epoch);
      record = { ...record, receipt };
      write(record, epoch);
      if (!resumed) {
        resumed = true;
        requireOwner(epoch);
        response = await request("post", `${url(record.client_operation_id)}/resume`, undefined, epoch);
        receipt = validateCreationReceipt(response, record.client_operation_id);
        if (isTerminal(receipt)) return saveOutcome(record, receipt, epoch);
        record = { ...record, receipt };
        write(record, epoch);
      }
      if (attempt + 1 < MAX_RECOVERY_READS) { await wait(Math.min(receipt.retry_after_seconds, 2) * 1000); requireOwner(epoch); }
    }
    return record.receipt;
  };
  const exclusive = async (action) => {
    const epoch = lifecycleEpoch;
    requireOwner(epoch);
    if (working) fail("BUSY", "Comanda este deja în curs de verificare.");
    if (!locks?.request) fail("LOCK_UNAVAILABLE", "Browserul nu poate proteja această operație între taburi. Folosește un browser compatibil.");
    working = true;
    try {
      return await locks.request(key, { ifAvailable: true }, async (lock) => {
        requireOwner(epoch);
        if (!lock) fail("BUSY", "Aceeași comandă este procesată în alt tab. Reia verificarea după finalizare.");
        const result = await action(epoch); requireOwner(epoch); return result;
      });
    } catch (error) { requireOwner(epoch); throw readableError(error); }
    finally { working = false; }
  };
  const terminalStorageIds = (event) => {
    const ids = [];
    if (event?.key !== key) return ids;
    // oldValue remains available when the terminal receipt was already ACKed.
    for (const raw of [event.newValue, event.oldValue]) {
      if (typeof raw !== "string") continue;
      let parsed;
      try { parsed = recordSchema.safeParse(JSON.parse(raw)); } catch { continue; }
      if (!parsed.success || parsed.data.version !== 1 || parsed.data.actor_id !== actorId || !isTerminal(parsed.data.receipt)) continue;
      const record = parsed.data;
      validateCreationReceipt({ data: record.receipt,
        status: { applied: 201, replayed: 200, rejected: 409 }[record.receipt.state] }, record.client_operation_id);
      ids.push(record.client_operation_id);
    }
    return ids;
  };
  return {
    snapshot: read, clearDraft,
    captureIntent: () => { const record = read(lifecycleEpoch, false); return { epoch: lifecycleEpoch, generation: intentGeneration, client_operation_id: record?.client_operation_id ?? null,
      binding: record?.version === 2 ? financeBinding(record) : record?.client_operation_id ?? null }; },
    isCurrentIntent: (proof, acknowledged = false) => {
      try { requireOwner(proof.epoch); const record = read(lifecycleEpoch, false);
        return acknowledged ? record === null && intentGeneration === proof.generation + 1
          : intentGeneration === proof.generation && (record?.version === 2 ? financeBinding(record) : record?.client_operation_id ?? null) === proof.binding;
      } catch { return false; }
    },
    observeStorage: (event) => {
      requireOwner();
      if (event?.key === key && [event.oldValue, event.newValue].some((raw) => { try { return JSON.parse(raw)?.version === 2; } catch { return false; } })) {
        intentGeneration++; read(lifecycleEpoch, false); return true;
      }
      terminalStorageIds(event).forEach(removePayload);
      return false;
    },
    rememberStorage: (event) => {
      // A suspended page may receive terminal+ACK events before auth completes.
      // Remember only validated own-operation IDs; defer all payload changes.
      currentOwner(lifecycleEpoch);
      terminalStorageIds(event).forEach((id) => { if (observedDrafts.has(id)) deferredPayloads.add(id); });
    },
    activate: () => { active = true; },
    deactivate: ({ preserveDraft = false } = {}) => { active = false; lifecycleEpoch++; if (!preserveDraft) clearDraft(); },
    restoreSession: async () => {
      const epoch = lifecycleEpoch; currentOwner(epoch);
      const record = read(epoch, false);
      if (record?.version === 2) {
        const lease = leaseFor(record, epoch);
        try {
          const response = await financialRequest("get", financialUrl(record.client_operation_id), undefined, lease, true);
          validateFinancialReceipt(response, record.client_operation_id);
        } catch (error) {
          currentFinance(lease, { inactive: true });
          if (error?.response?.status !== 404 || error?.response?.data?.detail?.code !== "OPERATION_NOT_FOUND") throw error;
        }
        currentFinance(lease, { inactive: true }); active = true; return;
      }
      await verifyRecoverySession({ api, actorId, roles: ["admin", "restaurant"], timeout: CREATE_REQUEST_TIMEOUT_MS, isOnline,
        currentOwner: () => currentOwner(epoch), fail });
      currentOwner(epoch); active = true;
      try { deferredPayloads.forEach((id) => { requireOwner(epoch); removePayload(id); }); }
      catch (error) { if (epoch === lifecycleEpoch) active = false; throw error; }
    },
    capability: () => request("get", "/api/orders/operations/capabilities"),
    submitLegacy: (order, postLegacy) => exclusive(async (epoch) => {
      // Read again under the same browser lock, not the rendered React snapshot.
      if (read(epoch)) fail("INTENT_PENDING", "Verifică operația existentă înainte de a crea o comandă nouă.");
      if (!isOnline()) fail("OFFLINE", "Nu ai internet. Comanda nu a fost trimisă.");
      const normalized = normalizeCreateOrder(order);
      requireOwner();
      const result = await (postLegacy ? postLegacy(JSON.parse(JSON.stringify(normalized))) : request("post", "/api/orders", JSON.parse(JSON.stringify(normalized)), epoch));
      requireOwner(epoch); return result;
    }),
    submit: (order) => exclusive(async (epoch) => {
      if (Object.hasOwn(order || {}, "financial")) return submitFinancial(order, epoch);
      const normalized = normalizeCreateOrder(order);
      const existing = read(epoch);
      if (existing) {
        if (isTerminal(existing.receipt)) return existing.receipt;
        const original = draft(existing);
        if (!original || JSON.stringify(original.order) !== JSON.stringify(normalized)) {
          fail("INTENT_PENDING", "Există o comandă neconfirmată. Verific-o înainte să modifici sau să trimiți alte date.");
        }
        return reconcile(existing, epoch);
      }
      if (!isOnline()) fail("OFFLINE", "Nu ai internet. Comanda nu a fost trimisă.");
      let id;
      try { id = crypto.randomUUID(); } catch { fail("ID_UNAVAILABLE", "Nu pot genera o identitate sigură pentru comandă."); }
      if (!ID.safeParse(id).success) fail("ID_UNAVAILABLE", "Nu pot genera o identitate sigură pentru comandă.");
      const record = { version: 1, actor_id: actorId, client_operation_id: id, created_at: Date.now(), receipt: null };
      try { if (draftStorage.getItem(draftKey(id)) != null) storageError(); } catch { storageError(); }
      memoryDraft = { actor_id: actorId, client_operation_id: id, order: normalized };
      try {
        const serialized = JSON.stringify(memoryDraft);
        draftStorage.setItem(draftKey(id), serialized);
        if (draftStorage.getItem(draftKey(id)) !== serialized) storageError();
      } catch {
        memoryDraft = null;
        try { draftStorage.removeItem(draftKey(id)); } catch { /* No request has been sent. */ }
        storageError();
      }
      try { write(record, epoch); }
      catch (error) {
        requireOwner(epoch);
        memoryDraft = null;
        try { draftStorage.removeItem(draftKey(id)); } catch { /* No request has been sent. */ }
        throw error;
      }
      try {
        const receipt = await send(record, memoryDraft, epoch);
        return isTerminal(receipt) ? receipt : reconcile(read(epoch), epoch);
      } catch (error) {
        requireOwner(epoch);
        const status = error?.response?.status;
        if (status === 422 && error.response.data?.detail?.code === "INVALID_REQUEST") {
          return saveOutcome(record, { client_operation_id: id, state: "rejected", error_code: "INVALID_REQUEST" }, epoch);
        }
        if (error instanceof OrderRecoveryError && error.code !== "INVALID_RESPONSE") throw error;
        if ([401, 403, 409, 422].includes(status)) throw readableError(error);
        return reconcile(read(epoch), epoch);
      }
    }),
    recover: () => exclusive(async (epoch) => {
      const record = read(epoch);
      if (!record) return null;
      return reconcile(record, epoch);
    }),
    retrySubmission: () => exclusive(async (epoch) => {
      const record = read(epoch, false); if (record?.version !== 2) unresolved();
      const lease = leaseFor(record, epoch), saved = draft(record);
      if (!saved) fail("DRAFT_UNAVAILABLE", "Datele private lipsesc. Verifică rezultatul sau cere închiderea identității.");
      if (isTerminal(record.receipt)) unresolved();
      return sendFinancial(record, saved, lease);
    }),
    resume: () => exclusive(async (epoch) => {
      const record = read(epoch, false); if (record?.version !== 2 || record.receipt?.state !== "pending") unresolved();
      const lease = leaseFor(record, epoch);
      const response = await financialRequest("post", `${financialUrl(record.client_operation_id)}/resume`, undefined, lease);
      return saveFinancialOutcome(lease, validateFinancialReceipt(response, record.client_operation_id));
    }),
    closeIntent: () => exclusive(async (epoch) => {
      const record = read(epoch, false); if (record?.version !== 2) unresolved();
      const lease = leaseFor(record, epoch);
      const response = await financialRequest("post", `${financialUrl(record.client_operation_id)}/close`, {
        restaurant_id: record.restaurant_id, quote_confirmation: record.quote_confirmation }, lease);
      return saveFinancialOutcome(lease, validateFinancialReceipt(response, record.client_operation_id));
    }),
    acknowledge: () => exclusive(async (epoch) => {
      requireOwner(epoch);
      const record = read(epoch);
      if (record?.version === 2) {
        if (!isTerminal(record.receipt)) unresolved();
        const lease = leaseFor(record, epoch);
        const response = await financialRequest("get", financialUrl(record.client_operation_id), undefined, lease);
        const receipt = validateFinancialReceipt(response, record.client_operation_id);
        if (!isTerminal(receipt) || semanticReceipt(receipt) !== semanticReceipt(record.receipt)) unresolved();
        if (["applied", "replayed"].includes(receipt.state)) {
          const response = await financialRequest("get", `/api/orders/read/detail/${encodeURIComponent(receipt.order_id)}`, undefined, lease);
          validateFinancialReadback(response, record, receipt, draft(record));
        }
        currentFinance(lease);
        removePayload(record.client_operation_id);
        currentFinance(lease);
        try { durableStorage.removeItem(key); if (durableStorage.getItem(key) != null) storageError(); } catch { storageError(); }
        intentGeneration++; return true;
      }
      if (record && !isTerminal(record.receipt)) unresolved();
      clearDraft();
      try { durableStorage.removeItem(key); } catch { storageError(); }
    }),
  };
};
