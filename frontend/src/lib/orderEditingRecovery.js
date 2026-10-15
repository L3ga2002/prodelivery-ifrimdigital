import { z } from "zod";
import { verifyRecoverySession } from "./recoverySession";

export const EDIT_REQUEST_TIMEOUT_MS = 15000;
export const MAX_EDIT_RECOVERY_READS = 3;
const identifier = z.string().min(1).max(120).refine((v) => v === v.trim() &&
  Array.from(v).every((c) => c.charCodeAt(0) >= 32 && c.charCodeAt(0) !== 127));
const operationId = z.string().min(16).max(128).regex(/^[A-Za-z0-9_-]+$/);
const version = z.number().refine((v) => Number.isSafeInteger(v) && v >= 0 && v < Number.MAX_SAFE_INTEGER);
const text = (min, max) => z.string().trim().min(min).max(max);
const changesSchema = z.object({
  customer_name: text(2, 140).optional(), customer_phone: text(7, 24).optional(),
  customer_address: text(5, 300).optional(), notes: text(0, 1000).nullable().optional(),
  customer_latitude: z.number().finite().min(-90).max(90).nullable().optional(),
  customer_longitude: z.number().finite().min(-180).max(180).nullable().optional(),
}).strict().refine((v) => Object.keys(v).length > 0 && Object.values(v).every((x) => x !== undefined))
  .refine((v) => Object.hasOwn(v, "customer_latitude") === Object.hasOwn(v, "customer_longitude"))
  .refine((v) => (v.customer_latitude == null) === (v.customer_longitude == null));
const receiptSchema = z.object({
  client_operation_id: operationId, state: z.enum(["applied", "replayed", "pending", "rejected"]),
  order_id: identifier.nullable().optional(),
  order_version: z.number().refine((v) => Number.isSafeInteger(v) && v >= 0).nullable().optional(),
  error_code: z.string().nullable().optional(),
  retry_after_seconds: z.number().int().min(1).max(60).nullable().optional(),
}).strict();
const recordSchema = z.object({ actor_id: identifier, order_id: identifier,
  client_operation_id: operationId, expected_order_version: version, receipt: receiptSchema.nullable() }).strict();
const draftSchema = z.object({ actor_id: identifier, order_id: identifier,
  client_operation_id: operationId, expected_order_version: version, changes: changesSchema }).strict();
const rejectionCodes = {
  ORDER_NOT_FOUND: 404, ORDER_TARGET_CHANGED: 409, ORDER_DATA_INVALID: 409,
  ORDER_VERSION_REQUIRED: 409, ORDER_VERSION_INVALID: 409, ORDER_VERSION_CONFLICT: 409,
  ORDER_VERSION_EXHAUSTED: 409, ORDER_NOT_EDITABLE: 409, COORDINATES_REQUIRED: 409, NO_CHANGES: 409,
};
export class OrderEditingError extends Error {
  constructor(code, message) { super(message); this.name = "OrderEditingError"; this.code = code; }
}
const fail = (code, message) => { throw new OrderEditingError(code, message); };
const uncertain = () => fail("OPERATION_UNCERTAIN", "Rezultatul este neconfirmat. Verifica aceeasi corectie, fara o intentie noua.");
export const editTerminal = (r) => Boolean(r && r.state !== "pending");
const validPair = (lat, lng) => (lat == null && lng == null) ||
  (typeof lat === "number" && Number.isFinite(lat) && Math.abs(lat) <= 90 &&
   typeof lng === "number" && Number.isFinite(lng) && Math.abs(lng) <= 180);

export const isOrderEditable = (order) => Boolean(order && identifier.safeParse(order.id).success &&
  identifier.safeParse(order.restaurant_id).success && version.safeParse(order.order_version).success &&
  ["NEW", "PREPARING", "READY"].includes(order.status) && order.driver_id == null &&
  ["assigned_at", "accepted_at", "picked_up_at", "delivered_at", "cancelled_at", "cancelled_by", "cancellation_reason"].every((k) => order[k] == null) &&
  (!Object.hasOwn(order, "preparation_status") || order.preparation_status === order.status) &&
  validPair(order.customer_latitude, order.customer_longitude));

export const normalizeOrderCorrections = (order, changes) => {
  if (!isOrderEditable(order)) fail("ORDER_NOT_EDITABLE", "Comanda nu este eligibila pentru corectii versionate.");
  const parsed = changesSchema.safeParse(changes);
  if (!parsed.success) fail("INVALID_CHANGES", "Verifica numele, telefonul, adresa, notele si perechea de coordonate.");
  const c = parsed.data;
  if (c.customer_address !== undefined && c.customer_address !== order.customer_address && order.customer_latitude != null &&
    (!Object.hasOwn(c, "customer_latitude") || (c.customer_latitude === order.customer_latitude && c.customer_longitude === order.customer_longitude))) {
    fail("COORDINATES_REQUIRED", "Adresa noua necesita o pereche diferita de coordonate sau stergerea explicita a celei vechi.");
  }
  if (!Object.keys(c).some((k) => c[k] !== order[k])) fail("NO_CHANGES", "Nu exista corectii de salvat.");
  return c;
};

export const validateEditingReceipt = (response, record) => {
  const p = receiptSchema.safeParse(response?.data);
  const invalid = () => fail("INVALID_RESPONSE", "Raspuns neconfirmat. Pastreaza identitatea si verifica aceeasi corectie.");
  if (!p.success || p.data.client_operation_id !== record.client_operation_id) invalid();
  const r = p.data;
  if (r.state === "applied" || r.state === "replayed") {
    if (response.status !== 200 || r.order_id !== record.order_id || r.order_version !== record.expected_order_version + 1 ||
      r.error_code != null || r.retry_after_seconds != null) invalid();
  } else if (r.state === "pending") {
    const retry = response.headers?.get?.("Retry-After") ?? response.headers?.["retry-after"] ?? response.headers?.["Retry-After"];
    if (response.status !== 202 || r.order_id != null || r.order_version != null || r.error_code != null ||
      r.retry_after_seconds == null || String(retry) !== String(r.retry_after_seconds)) invalid();
  } else if (typeof r.error_code !== "string" || !Object.hasOwn(rejectionCodes, r.error_code) ||
    response.status !== rejectionCodes[r.error_code] || r.order_id != null || r.order_version != null || r.retry_after_seconds != null) invalid();
  return r;
};

export const createOrderEditingRecovery = ({ actorId, api, durableStorage, draftStorage, locks, crypto,
  isOnline = () => true, isOwnerActive = () => true,
  wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) }) => {
  if (!identifier.safeParse(actorId).success) fail("AUTH_REQUIRED", "Autentificarea este necesara.");
  const key = `prodelivery:order-edit:v1:${encodeURIComponent(actorId)}`;
  const draftKey = (id) => `${key}:draft:${id}`;
  const base = (r) => `/api/orders/operations/edit/${encodeURIComponent(r.order_id)}`;
  const lookup = (r) => `${base(r)}/${encodeURIComponent(r.client_operation_id)}`;
  let working = false, active = true, poisoned = false, memoryDraft = null;
  const observedDrafts = new Set();
  const deferredPayloads = new Set();
  let lifecycleEpoch = 0;
  const currentOwner = (epoch) => { if (epoch !== lifecycleEpoch || !isOwnerActive()) fail("SESSION_CHANGED", "Sesiunea s-a schimbat. Intentia ramane pastrata."); };
  const owner = (epoch = lifecycleEpoch) => { currentOwner(epoch); if (!active) fail("SESSION_CHANGED", "Sesiunea s-a schimbat. Rezultatul nu poate fi preluat aici."); };
  const storageError = () => { poisoned = true; fail("STORAGE_UNAVAILABLE", "Stocarea nu poate fi confirmata. Nu trimite o intentie noua."); };
  const removePayload = (r) => {
    if (memoryDraft?.client_operation_id === r.client_operation_id) memoryDraft = null;
    try {
      draftStorage.removeItem(draftKey(r.client_operation_id));
      if (draftStorage.getItem(draftKey(r.client_operation_id)) != null) storageError();
      deferredPayloads.delete(r.client_operation_id);
    } catch { storageError(); }
  };
  const read = (epoch = lifecycleEpoch, cleanup = true) => {
    let raw, p;
    try { raw = durableStorage.getItem(key); if (raw == null) return null; p = recordSchema.safeParse(JSON.parse(raw)); }
    catch { storageError(); }
    if (!p.success || p.data.actor_id !== actorId) storageError();
    const r = p.data;
    observedDrafts.add(r.client_operation_id);
    if (r.receipt) {
      try {
        validateEditingReceipt({ data: r.receipt,
          status: r.receipt.state === "pending" ? 202 : r.receipt.state === "rejected" ? rejectionCodes[r.receipt.error_code] : 200,
          headers: { "retry-after": String(r.receipt.retry_after_seconds) } }, r);
      } catch { storageError(); }
      // A different tab may have completed this intent. Remove only this tab's
      // payload; durable identity acknowledgment still requires the Web Lock.
      if (["applied", "replayed"].includes(r.receipt.state) && cleanup && active && isOwnerActive()) { owner(epoch); removePayload(r); }
    }
    return r;
  };
  const persist = (storage, storageKey, value, epoch = lifecycleEpoch) => {
    owner(epoch);
    try { const raw = JSON.stringify(value); storage.setItem(storageKey, raw); if (storage.getItem(storageKey) !== raw) storageError(); }
    catch { storageError(); }
  };
  const draft = (r) => {
    if (memoryDraft?.client_operation_id === r.client_operation_id) return memoryDraft;
    let raw, p;
    try { raw = draftStorage.getItem(draftKey(r.client_operation_id)); if (raw == null) return null; p = draftSchema.safeParse(JSON.parse(raw)); }
    catch { storageError(); }
    if (!p.success || ["actor_id", "order_id", "client_operation_id", "expected_order_version"].some((k) => p.data[k] !== r[k])) storageError();
    return p.data;
  };
  const clearDraft = (epoch = lifecycleEpoch) => {
    owner(epoch); memoryDraft = null;
    const r = read(epoch, false);
    if (r) removePayload(r);
  };
  const save = (r, receipt, epoch) => {
    owner(epoch); persist(durableStorage, key, { ...r, receipt }, epoch);
    // Rejected edits keep their form draft until an explicit fresh attempt.
    if (["applied", "replayed"].includes(receipt.state)) clearDraft(epoch);
    return receipt;
  };
  const request = async (method, path, body, epoch = lifecycleEpoch) => {
    owner(epoch);
    if (!isOnline()) fail("OFFLINE", "Fara internet. Corectia nu este confirmata; identitatea ramane pastrata.");
    let response;
    try { response = method === "get" ? await api.get(path, { timeout: EDIT_REQUEST_TIMEOUT_MS }) :
      await api.post(path, body, { timeout: EDIT_REQUEST_TIMEOUT_MS }); }
    catch (error) { owner(epoch); if (error?.response?.data?.state === "rejected") response = error.response; else throw error; }
    owner(epoch); return response;
  };
  const send = async (r, d, epoch) => save(r, validateEditingReceipt(await request("post", base(r), {
    client_operation_id: r.client_operation_id, expected_order_version: r.expected_order_version,
    changes: JSON.parse(JSON.stringify(d.changes)),
  }, epoch), r), epoch);
  const reconcile = async (initial, epoch) => {
    let r = initial, resent = false, resumed = false;
    if (editTerminal(r.receipt)) return r.receipt;
    for (let i = 0; i < MAX_EDIT_RECOVERY_READS; i++) {
      let response;
      try { response = await request("get", lookup(r), undefined, epoch); }
      catch (error) {
        owner(epoch);
        if (error?.response?.status !== 404 || error.response.data?.detail?.code !== "OPERATION_NOT_FOUND" || resent || resumed) throw error;
        const d = draft(r);
        if (!d) uncertain();
        resent = true;
        const receipt = await send(r, d, epoch);
        if (editTerminal(receipt)) return receipt;
        r = { ...r, receipt };
      }
      if (response) {
        let receipt = save(r, validateEditingReceipt(response, r), epoch);
        r = { ...r, receipt };
        if (editTerminal(receipt)) return receipt;
        if (!resumed) {
          resumed = true;
          receipt = save(r, validateEditingReceipt(await request("post", `${lookup(r)}/resume`, undefined, epoch), r), epoch);
          r = { ...r, receipt };
          if (editTerminal(receipt)) return receipt;
        }
      }
      if (i + 1 < MAX_EDIT_RECOVERY_READS) { await wait(r.receipt.retry_after_seconds * 1000); owner(epoch); }
    }
    return r.receipt;
  };
  const exclusive = async (action) => {
    const epoch = lifecycleEpoch;
    owner(epoch);
    if (working) fail("BUSY", "Corectia este deja in curs.");
    if (!locks?.request) fail("LOCK_UNAVAILABLE", "Browserul nu poate proteja corectia intre taburi. Operatia este blocata.");
    working = true;
    try {
      return await locks.request(key, { ifAvailable: true }, async (lock) => {
        owner(epoch); if (!lock) fail("BUSY", "Corectia este procesata in alt tab."); const result = await action(epoch); owner(epoch); return result;
      });
    } catch (error) { owner(epoch);
      if (error instanceof OrderEditingError) throw error;
      fail(error?.response?.status === 401 ? "AUTH_REQUIRED" : "RECOVERY_UNAVAILABLE",
        error?.response?.status === 401 ? "Sesiunea a expirat. Reconecteaza-te pentru aceeasi corectie." : "Serverul nu confirma corectia. Pastreaza formularul si verifica aceeasi operatie.");
    } finally { working = false; }
  };
  const successfulStorageIds = (event) => {
    const ids = [];
    if (event?.key !== key) return ids;
    // A terminal receipt can already be acknowledged before this tab handles
    // its queued storage event. oldValue still proves the successful outcome.
    for (const raw of [event.newValue, event.oldValue]) {
      if (typeof raw !== "string") continue;
      let parsed;
      try { parsed = recordSchema.safeParse(JSON.parse(raw)); } catch { continue; }
      if (!parsed.success || parsed.data.actor_id !== actorId || !["applied", "replayed"].includes(parsed.data.receipt?.state)) continue;
      const r = parsed.data;
      try { validateEditingReceipt({ status: 200, data: r.receipt }, r); } catch { storageError(); }
      ids.push(r.client_operation_id);
    }
    return ids;
  };
  return {
    snapshot: read, storageBlocked: () => poisoned,
    savedDraft: () => { const r = read(), d = r ? draft(r) : null; return d ? JSON.parse(JSON.stringify(d)) : null; },
    observeStorage: (event) => {
      owner();
      successfulStorageIds(event).forEach((id) => removePayload({ client_operation_id: id }));
    },
    rememberStorage: (event) => {
      currentOwner(lifecycleEpoch);
      successfulStorageIds(event).forEach((id) => { if (observedDrafts.has(id)) deferredPayloads.add(id); });
    },
    activate: () => { active = true; }, deactivate: ({ preserveDraft = false } = {}) => {
      active = false; lifecycleEpoch++; memoryDraft = null;
      if (preserveDraft) return;
      try { observedDrafts.forEach((id) => draftStorage.removeItem(draftKey(id))); } catch { storageError(); }
    },
    restoreSession: async () => {
      const epoch = lifecycleEpoch; currentOwner(epoch);
      await verifyRecoverySession({ api, actorId, roles: ["admin"], timeout: EDIT_REQUEST_TIMEOUT_MS, isOnline,
        currentOwner: () => currentOwner(epoch), fail });
      currentOwner(epoch); active = true;
      try { deferredPayloads.forEach((id) => { owner(epoch); removePayload({ client_operation_id: id }); }); }
      catch (error) { if (epoch === lifecycleEpoch) active = false; throw error; }
    },
    capability: async () => {
      const response = await request("get", "/api/orders/operations/edit/capabilities");
      if (response.status !== 200 || typeof response.data?.edit_recovery_enabled !== "boolean") fail("CAPABILITY_UNAVAILABLE", "Disponibilitatea corectiilor nu poate fi verificata.");
      return response.data.edit_recovery_enabled;
    },
    submit: ({ order, changes }) => exclusive(async (epoch) => {
      if (poisoned) storageError();
      if (read(epoch)) fail("INTENT_PENDING", "Verifica operatia existenta inaintea unei intentii noi.");
      const normalized = normalizeOrderCorrections(order, changes);
      const cap = await request("get", "/api/orders/operations/edit/capabilities", undefined, epoch);
      owner(epoch);
      if (cap.status !== 200 || cap.data?.edit_recovery_enabled !== true) fail("EDITING_DISABLED", "Corectiile operationale sunt indisponibile. Comanda nu a fost modificata.");
      let id;
      try { id = crypto.randomUUID(); } catch { fail("ID_UNAVAILABLE", "Nu pot genera identitatea corectiei."); }
      if (!operationId.safeParse(id).success) fail("ID_UNAVAILABLE", "Identitatea corectiei este invalida.");
      const r = { actor_id: actorId, order_id: order.id, client_operation_id: id, expected_order_version: order.order_version, receipt: null };
      const d = { ...r, changes: normalized }; delete d.receipt;
      observedDrafts.add(id);
      try { if (draftStorage.getItem(draftKey(id)) != null) storageError(); } catch { storageError(); }
      try {
        persist(draftStorage, draftKey(id), d, epoch);
        persist(durableStorage, key, r, epoch);
      } catch (error) {
        owner(epoch);
        try { draftStorage.removeItem(draftKey(id)); } catch { /* No request has been sent; new intents remain blocked. */ }
        throw error;
      }
      memoryDraft = JSON.parse(JSON.stringify(d));
      try {
        const result = await send(r, d, epoch);
        return editTerminal(result) ? result : reconcile(read(epoch), epoch);
      } catch (error) {
        owner(epoch);
        if (error instanceof OrderEditingError && error.code !== "INVALID_RESPONSE") throw error;
        if ([401, 403].includes(error?.response?.status)) throw error;
        return reconcile(read(epoch), epoch);
      }
    }),
    recover: () => exclusive(async (epoch) => { const r = read(epoch); return r ? reconcile(r, epoch) : null; }),
    refreshForNewAttempt: () => exclusive(async (epoch) => {
      if (poisoned) storageError();
      const r = read(epoch); if (!r || r.receipt?.state !== "rejected") uncertain();
      const response = await request("get", `/api/orders/${encodeURIComponent(r.order_id)}`, undefined, epoch);
      owner(epoch);
      if (response.status !== 200 || response.data?.id !== r.order_id || !isOrderEditable(response.data)) fail("ORDER_NOT_EDITABLE", "Comanda reincarcata nu este eligibila. Formularul este pastrat.");
      clearDraft(epoch);
      try { durableStorage.removeItem(key); if (durableStorage.getItem(key) != null) storageError(); } catch { storageError(); }
      return response.data;
    }),
    acknowledge: () => exclusive(async (epoch) => {
      owner(epoch);
      const r = read(epoch); if (r && !["applied", "replayed"].includes(r.receipt?.state)) uncertain();
      clearDraft(epoch);
      try { durableStorage.removeItem(key); if (durableStorage.getItem(key) != null) storageError(); } catch { storageError(); }
    }),
  };
};
