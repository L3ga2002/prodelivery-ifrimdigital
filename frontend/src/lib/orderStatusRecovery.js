import { custodyBlocksNormalMutation } from "./orderCustody";
import { z } from "zod";
import { getPreparationStatus } from "./orderWorkflow";
import { validAssignmentActor, validAssignmentToken } from "./orderAssignmentRecovery";
import { financialPickupBlocked } from "./orderFinancialActivity";

export const STATUS_REQUEST_TIMEOUT_MS = 15000;
export const MAX_STATUS_RECOVERY_READS = 3;
const identifier = z.string().refine(validAssignmentActor);
const operationId = z.string().min(16).max(128).regex(/^[A-Za-z0-9_-]+$/);
const version = z.number().refine((v) => Number.isSafeInteger(v) && v >= 0 && v < Number.MAX_SAFE_INTEGER);
const statusSchema = z.enum(["ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"]);
const receiptSchema = z.object({
  client_operation_id: operationId, state: z.enum(["applied", "replayed", "pending", "rejected"]),
  order_id: identifier.nullable().optional(),
  order_version: z.number().refine((v) => Number.isSafeInteger(v) && v >= 0).nullable().optional(),
  error_code: z.string().max(64).regex(/^[A-Z][A-Z0-9_]*$/).nullable().optional(),
  retry_after_seconds: z.number().int().min(1).max(60).nullable().optional(),
}).strict();
const metadata = { actor_id: identifier, actor_role: z.enum(["admin", "driver", "restaurant"]),
  actor_resource_id: identifier.nullable(), order_id: identifier, client_operation_id: operationId,
  expected_order_version: version, status: statusSchema };
const recordSchema = z.object({ ...metadata, receipt: receiptSchema.nullable() }).strict();
const draftSchema = z.object({ ...metadata, status: z.literal("CANCELLED"),
  cancellation_reason: z.string().min(1).max(500).refine((v) => v === v.trim()) }).strict();
const intentFields = Object.keys(metadata);
const rejectionCodes = {
  ORDER_NOT_FOUND: 404, DRIVER_NOT_FOUND: 404, ORDER_TARGET_CHANGED: 409,
  ORDER_DATA_INVALID: 409, ORDER_VERSION_REQUIRED: 409, ORDER_VERSION_INVALID: 409,
  ORDER_VERSION_CONFLICT: 409, ORDER_VERSION_EXHAUSTED: 409,
  STATUS_TRANSITION_INVALID: 409, ORDER_NOT_READY: 409, ASSIGNMENT_INCONSISTENT: 409,
  ASSIGNMENT_REPRESENTATION_UNSUPPORTED: 409, DRIVER_DATA_INVALID: 409,
  DRIVER_DISABLED: 409, CUSTODY_RESOLUTION_REQUIRED: 409,
  FINANCIAL_SNAPSHOT_INVALID: 409, FINANCIAL_AMOUNT_INVALID: 409,
  FINANCIAL_DRIVER_TOTAL_INVALID: 409, FINANCIAL_ACTIVITY_INVALID: 409,
  FINANCIAL_PICKUP_APPROVAL_REQUIRED: 409, CUSTODY_INVALID: 409, CUSTODY_STATE_CONFLICT: 409,
};
export const statusFailureMessage = (code) => ({
  ORDER_VERSION_CONFLICT: "Comanda s-a schimbat. Reincarca inaintea unei noi incercari.",
  ORDER_DATA_INVALID: "Datele comenzii necesita verificare.",
  STATUS_TRANSITION_INVALID: "Tranzitia nu mai este permisa.",
  ORDER_NOT_READY: "Restaurantul nu a confirmat comanda gata.",
  ASSIGNMENT_INCONSISTENT: "Alocarea necesita reconciliere.",
  DRIVER_DISABLED: "Contul livratorului este dezactivat.",
  CUSTODY_RESOLUTION_REQUIRED: "Comanda ridicata necesita rezolvarea custodiei; anularea directa este blocata.",
  FINANCIAL_PICKUP_APPROVAL_REQUIRED: "Restaurantul trebuie să aprobe declarația lipsei de numerar înainte de ridicare.",
  FINANCIAL_ACTIVITY_INVALID: "Evidența numerarului necesită verificare înainte de ridicare.",
  FINANCIAL_SNAPSHOT_INVALID: "Calculul financiar al comenzii necesită verificare.",
  FINANCIAL_AMOUNT_INVALID: "Sumele comenzii necesită verificare.",
  FINANCIAL_DRIVER_TOTAL_INVALID: "Remunerația livratorului necesită verificare.",
  NOT_AUTHORIZED: "Contul nu este autorizat pentru aceasta actiune.",
  STATUS_NOT_ENABLED: "Fluxul recuperabil este dezactivat.",
  SESSION_CHANGED: "Sesiunea s-a schimbat. Reia verificarea cu actorul initial.",
}[code] || "Operatia a fost respinsa. Reincarca si verifica datele comenzii.");
export class OrderStatusError extends Error {
  constructor(code, message) { super(message); this.name = "OrderStatusError"; this.code = code; }
}
const fail = (code, message) => { throw new OrderStatusError(code, message); };
const uncertain = () => fail("OPERATION_UNCERTAIN", "Statusul este neconfirmat. Verifica aceeasi operatie, fara o intentie noua.");
export const statusTerminal = (r) => Boolean(r && ["applied", "replayed", "rejected"].includes(r.state));
export const statusApplied = (r) => Boolean(r && ["applied", "replayed"].includes(r.state));
export const hasStatusRevision = (order) => Boolean(order && Object.hasOwn(order, "order_version"));
export const validStatusToken = validAssignmentToken;
export const validStatusActor = (actor) => Boolean(actor && validAssignmentActor(actor.id) &&
  ["admin", "driver", "restaurant"].includes(actor.role) &&
  ["is_disabled", "account_disabled"].every((k) => !Object.hasOwn(actor, k) || actor[k] === false) &&
  (actor.role === "admin" || validAssignmentActor(actor[`${actor.role}_id`])));
const resourceId = (actor) => actor.role === "admin" ? null : actor[`${actor.role}_id`];
const actorAllowsStatus = (actor, status) => validStatusActor(actor) && statusSchema.safeParse(status).success &&
  (actor.role === "admin" || (actor.role === "driver" && status !== "CANCELLED") ||
    (actor.role === "restaurant" && status === "CANCELLED"));
export const canChangeOrderStatus = (order, status, actor) => {
  if (custodyBlocksNormalMutation(order)) return false;
  if (!actorAllowsStatus(actor, status) || !validAssignmentActor(order?.id)) return false;
  if (hasStatusRevision(order) && (!version.safeParse(order.order_version).success || !validAssignmentActor(order.restaurant_id))) return false;
  if (actor.role === "driver" && order.driver_id !== actor.driver_id) return false;
  if (actor.role === "restaurant" && order.restaurant_id !== actor.restaurant_id) return false;
  if (status === "CANCELLED") return ["NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED"].includes(order.status);
  if (!validAssignmentActor(order.driver_id)) return false;
  if (status === "ACCEPTED") return order.status === "ASSIGNED";
  if (status === "PICKED_UP") return order.status === "ACCEPTED" && getPreparationStatus(order) === "READY" && !financialPickupBlocked(order);
  return order.status === "PICKED_UP";
};
export const validateStatusReceipt = (response, record) => {
  const parsed = receiptSchema.safeParse(response?.data);
  const invalid = () => fail("INVALID_RESPONSE", "Raspunsul statusului nu poate fi confirmat. Pastreaza identitatea operatiei.");
  if (!parsed.success || parsed.data.client_operation_id !== record.client_operation_id) invalid();
  const r = parsed.data;
  if (statusApplied(r)) {
    if (response.status !== 200 || r.order_id !== record.order_id || r.order_version !== record.expected_order_version + 1 ||
      r.error_code != null || r.retry_after_seconds != null) invalid();
  } else if (r.state === "pending") {
    const retry = response.headers?.get?.("Retry-After") ?? response.headers?.["retry-after"] ?? response.headers?.["Retry-After"];
    if (response.status !== 202 || r.order_id != null || r.order_version != null || r.error_code != null ||
      r.retry_after_seconds == null || String(retry) !== String(r.retry_after_seconds)) invalid();
  } else if (!Object.hasOwn(rejectionCodes, r.error_code) || response.status !== rejectionCodes[r.error_code] ||
    r.order_id != null || r.order_version != null || r.retry_after_seconds != null) invalid();
  return r;
};

export const createOrderStatusRecovery = ({ actor, api, durableStorage, draftStorage, locks, crypto,
  isOnline = () => true, isOwnerActive = () => true,
  onRecordChange = () => {},
  wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) }) => {
  if (!validStatusActor(actor)) fail("AUTH_REQUIRED", "Autentificarea este necesara.");
  const identity = { actor_id: actor.id, actor_role: actor.role, actor_resource_id: resourceId(actor) };
  const key = `prodelivery:order-status:v1:${encodeURIComponent(actor.id)}`;
  const draftKey = (id) => `${key}:draft:${id}`;
  const base = (r) => `/api/orders/operations/status/${encodeURIComponent(r.order_id)}`;
  const lookup = (r) => `${base(r)}/${encodeURIComponent(r.client_operation_id)}`;
  let working = false, active = true, poisoned = false, lifecycleEpoch = 0;
  const observedDrafts = new Set();
  const currentOwner = (epoch) => { if (epoch !== lifecycleEpoch || !isOwnerActive()) fail("SESSION_CHANGED", statusFailureMessage("SESSION_CHANGED")); };
  const owner = (epoch = lifecycleEpoch) => { currentOwner(epoch); if (!active) fail("SESSION_CHANGED", statusFailureMessage("SESSION_CHANGED")); };
  const validateSession = (auth) => {
    if (auth?.status !== 200 || !validStatusActor(auth.data) || auth.data.id !== actor.id || auth.data.role !== actor.role ||
      resourceId(auth.data) !== resourceId(actor)) fail("SESSION_CHANGED", statusFailureMessage("SESSION_CHANGED"));
  };
  const storageError = () => { poisoned = true; fail("STORAGE_UNAVAILABLE", "Stocarea statusului nu poate fi confirmata. O intentie noua este blocata."); };
  const removeDraft = (r) => {
    if (r.status !== "CANCELLED") return;
    if (!statusTerminal(r.receipt) && !actorAllowsStatus(actor, r.status)) return;
    try { draftStorage.removeItem(draftKey(r.client_operation_id));
      if (draftStorage.getItem(draftKey(r.client_operation_id)) != null) storageError(); }
    catch { storageError(); }
  };
  const read = () => {
    owner();
    let raw, parsed;
    try { raw = durableStorage.getItem(key); if (raw == null) return null; parsed = recordSchema.safeParse(JSON.parse(raw)); }
    catch { storageError(); }
    if (!parsed.success || Object.keys(identity).some((k) => parsed.data[k] !== identity[k])) storageError();
    const r = parsed.data; observedDrafts.add(r.client_operation_id);
    if (r.receipt) {
      try { validateStatusReceipt({ data: r.receipt,
        status: r.receipt.state === "pending" ? 202 : r.receipt.state === "rejected" ? rejectionCodes[r.receipt.error_code] : 200,
        headers: { "retry-after": String(r.receipt.retry_after_seconds) } }, r); }
      catch { storageError(); }
      // Once admitted, the durable server intent is sufficient; no reason is needed locally.
      removeDraft(r);
    }
    return r;
  };
  const persist = (storage, storageKey, value) => {
    owner();
    try { const raw = JSON.stringify(value); storage.setItem(storageKey, raw); if (storage.getItem(storageKey) !== raw) storageError(); }
    catch { storageError(); }
    if (storage === durableStorage && storageKey === key) onRecordChange(value);
  };
  const draft = (r) => {
    let raw, parsed;
    try { raw = draftStorage.getItem(draftKey(r.client_operation_id)); if (raw == null) return null; parsed = draftSchema.safeParse(JSON.parse(raw)); }
    catch { storageError(); }
    if (!parsed.success || intentFields.some((k) => parsed.data[k] !== r[k])) storageError();
    return parsed.data;
  };
  const save = (r, receipt, epoch) => {
    owner(epoch); const stored = read();
    if (!stored || intentFields.some((k) => stored[k] !== r[k])) storageError();
    const saved = { ...r, receipt };
    persist(durableStorage, key, saved); removeDraft(saved); return receipt;
  };
  const request = async (method, path, body, epoch = lifecycleEpoch) => {
    owner(epoch); if (!isOnline()) fail("OFFLINE", "Fara internet. Identitatea statusului ramane pastrata.");
    let response;
    try { response = method === "get" ? await api.get(path, { timeout: STATUS_REQUEST_TIMEOUT_MS }) :
      await api[method](path, body, { timeout: STATUS_REQUEST_TIMEOUT_MS }); }
    catch (error) {
      owner(epoch);
      if (error?.response?.status === 403 && error.response.data?.detail?.code === "AUTH_CONTEXT_CHANGED") fail("SESSION_CHANGED", statusFailureMessage("SESSION_CHANGED"));
      if (error?.response?.status === 503 && error.response.data?.detail?.code === "STATUS_NOT_ENABLED") fail("STATUS_NOT_ENABLED", statusFailureMessage("STATUS_NOT_ENABLED"));
      if (error?.response?.data?.state === "rejected") response = error.response; else throw error;
    }
    owner(epoch); return response;
  };
  const capability = async (epoch = lifecycleEpoch) => {
    const response = await request("get", "/api/orders/operations/status/capabilities", undefined, epoch);
    owner(epoch);
    if (response.status !== 200 || typeof response.data?.status_recovery_enabled !== "boolean") fail("CAPABILITY_UNAVAILABLE", "Disponibilitatea statusului nu poate fi verificata.");
    return response.data.status_recovery_enabled;
  };
  const send = async (r, epoch) => {
    owner(epoch);
    const body = { client_operation_id: r.client_operation_id, expected_order_version: r.expected_order_version, status: r.status };
    if (r.status === "CANCELLED") { const d = draft(r); if (!d) uncertain(); body.cancellation_reason = d.cancellation_reason; }
    if (!actorAllowsStatus(actor, r.status)) fail("NOT_AUTHORIZED", statusFailureMessage("NOT_AUTHORIZED"));
    return save(r, validateStatusReceipt(await request("post", base(r), body, epoch), r), epoch);
  };
  const reconcile = async (initial, epoch) => {
    owner(epoch);
    let r = initial, resent = false, resumed = false;
    if (statusTerminal(r.receipt)) return r.receipt;
    for (let i = 0; i < MAX_STATUS_RECOVERY_READS; i++) {
      let response;
      try { response = await request("get", lookup(r), undefined, epoch); }
      catch (error) {
        owner(epoch);
        if (error?.response?.status !== 404 || error.response.data?.detail?.code !== "OPERATION_NOT_FOUND") throw error;
        if (r.receipt || resent || resumed) uncertain();
        resent = true; const receipt = await send(r, epoch);
        owner(epoch);
        if (statusTerminal(receipt)) return receipt;
        r = { ...r, receipt };
      }
      if (response) {
        let receipt = save(r, validateStatusReceipt(response, r), epoch); r = { ...r, receipt };
        if (statusTerminal(receipt)) return receipt;
        if (!resumed) {
          if (!actorAllowsStatus(actor, r.status)) fail("NOT_AUTHORIZED", statusFailureMessage("NOT_AUTHORIZED"));
          resumed = true; receipt = save(r, validateStatusReceipt(await request("post", `${lookup(r)}/resume`, undefined, epoch), r), epoch);
          r = { ...r, receipt }; if (statusTerminal(receipt)) return receipt;
        }
      }
      if (i + 1 < MAX_STATUS_RECOVERY_READS) { await wait(r.receipt.retry_after_seconds * 1000); owner(epoch); }
    }
    return r.receipt;
  };
  const exclusive = async (action) => {
    const epoch = lifecycleEpoch;
    owner(epoch); if (working) fail("BUSY", "Statusul este deja in curs.");
    if (typeof locks?.request !== "function") fail("LOCK_UNAVAILABLE", "Browserul nu poate proteja statusul intre taburi.");
    working = true;
    try { return await locks.request(key, { ifAvailable: true }, async (lock) => {
      owner(epoch); if (!lock) fail("BUSY", "Statusul este procesat in alt tab."); if (poisoned) storageError();
      const result = await action(epoch); owner(epoch); return result;
    }); } catch (error) {
      owner(epoch);
      if (error instanceof OrderStatusError) throw error;
      const status = error?.response?.status;
      fail(status === 401 ? "AUTH_REQUIRED" : status === 403 ? "NOT_AUTHORIZED" : status === 409 ? "INTENT_CONFLICT" : "RECOVERY_UNAVAILABLE",
        status === 401 ? "Sesiunea a expirat. Reconecteaza-te pentru aceeasi operatie." :
          status === 403 ? statusFailureMessage("NOT_AUTHORIZED") : "Serverul nu confirma statusul. Verifica aceeasi operatie.");
    } finally { working = false; }
  };
  const clear = (r) => {
    owner(); removeDraft(r);
    try { durableStorage.removeItem(key); if (durableStorage.getItem(key) != null) storageError(); } catch { storageError(); }
    onRecordChange(null);
  };
  const validateIntent = ({ order, status, cancellationReason }) => {
    if (hasStatusRevision(order) && !version.safeParse(order.order_version).success) fail("ORDER_VERSION_INVALID", "Revizia comenzii este invalida.");
    if (hasStatusRevision(order) && status === "CANCELLED" && order.status === "PICKED_UP") fail("CUSTODY_RESOLUTION_REQUIRED", statusFailureMessage("CUSTODY_RESOLUTION_REQUIRED"));
    if (!canChangeOrderStatus(order, status, actor)) fail("STATUS_TRANSITION_INVALID", statusFailureMessage("STATUS_TRANSITION_INVALID"));
    const reason = typeof cancellationReason === "string" ? cancellationReason.trim() : "";
    if (status === "CANCELLED" ? !reason || reason.length > 500 : cancellationReason != null) fail("INVALID_COMMAND", "Motivul este obligatoriu numai la anulare, maximum 500 caractere.");
    return { order_id: order.id, expected_order_version: order.order_version, status, reason };
  };
  return {
    snapshot: read, storageBlocked: () => poisoned, activate: () => { active = true; },
    deactivate: ({ preserveDraft = false } = {}) => {
      active = false; lifecycleEpoch++;
      if (!preserveDraft) { try { observedDrafts.forEach((id) => draftStorage.removeItem(draftKey(id))); } catch { storageError(); } }
    },
    // BFCache keeps this instance alive, but its old requests remain permanently fenced.
    restoreSession: async () => {
      const epoch = lifecycleEpoch; currentOwner(epoch);
      if (!isOnline()) fail("OFFLINE", "Fara internet. Sesiunea trebuie reverificata inainte de reluare.");
      let auth;
      try { auth = await api.get("/api/auth/me", { timeout: STATUS_REQUEST_TIMEOUT_MS }); }
      catch (error) {
        currentOwner(epoch);
        fail(error?.response?.status === 401 ? "AUTH_REQUIRED" : error?.response?.status === 403 ? "SESSION_CHANGED" : "RECOVERY_UNAVAILABLE",
          error?.response?.status === 401 ? "Sesiunea a expirat. Reconecteaza-te pentru aceeasi operatie." :
            error?.response?.status === 403 ? statusFailureMessage("SESSION_CHANGED") : "Sesiunea nu poate fi verificata. Intentia ramane pastrata.");
      }
      currentOwner(epoch); validateSession(auth); active = true;
    },
    capability,
    submit: (command) => exclusive(async (epoch) => {
      if (read()) fail("INTENT_PENDING", "Verifica operatia existenta inaintea unei intentii noi.");
      const intent = validateIntent(command);
      if (!hasStatusRevision(command.order)) fail("ORDER_VERSION_REQUIRED", "Aceasta comanda foloseste fluxul legacy.");
      if (!await capability(epoch)) fail("STATUS_NOT_ENABLED", statusFailureMessage("STATUS_NOT_ENABLED"));
      owner(epoch);
      let id; try { id = crypto.randomUUID(); } catch { fail("ID_UNAVAILABLE", "Nu pot genera identitatea statusului."); }
      if (!operationId.safeParse(id).success) fail("ID_UNAVAILABLE", "Identitatea statusului este invalida.");
      if (read()) fail("INTENT_PENDING", "Verifica operatia existenta inaintea unei intentii noi.");
      const r = { ...identity, order_id: intent.order_id, expected_order_version: intent.expected_order_version,
        status: intent.status, client_operation_id: id, receipt: null };
      if (r.status === "CANCELLED") {
        observedDrafts.add(id); const d = { ...r, cancellation_reason: intent.reason }; delete d.receipt;
        persist(draftStorage, draftKey(id), d);
      }
      try { persist(durableStorage, key, r); }
      catch (error) { try { removeDraft(r); } catch { /* Storage failure keeps all mutation paths blocked. */ } throw error; }
      try { const result = await send(r, epoch); owner(epoch); return statusTerminal(result) ? result : reconcile(read(), epoch); }
      catch (error) {
        owner(epoch);
        if (error instanceof OrderStatusError && error.code !== "INVALID_RESPONSE") throw error;
        if ([401, 403, 409, 422].includes(error?.response?.status)) throw error;
        return reconcile(read(), epoch);
      }
    }),
    submitLegacy: (command) => exclusive(async (epoch) => {
      if (read()) fail("INTENT_PENDING", "Verifica statusul recuperabil existent; fluxul legacy este blocat.");
      const intent = validateIntent(command);
      if (hasStatusRevision(command.order)) fail("ORDER_VERSION_REQUIRED", "Comanda versionata necesita protocolul recuperabil activ. Fluxul legacy este blocat.");
      const auth = await request("get", "/api/auth/me", undefined, epoch);
      owner(epoch); validateSession(auth);
      if (read()) fail("INTENT_PENDING", "Verifica statusul recuperabil existent; fluxul legacy este blocat.");
      const body = { status: intent.status }; if (intent.status === "CANCELLED") body.cancellation_reason = intent.reason;
      const response = await request("put", `/api/orders/${encodeURIComponent(intent.order_id)}/status`, body, epoch);
      owner(epoch);
      if (response.status !== 200) fail("INVALID_RESPONSE", "Statusul legacy nu a fost confirmat.");
      return response;
    }),
    recover: () => exclusive(async (epoch) => { const r = read(); return r ? reconcile(r, epoch) : null; }),
    refreshForNewAttempt: () => exclusive(async (epoch) => {
      const r = read(); if (r?.receipt?.state !== "rejected") uncertain();
      const response = await request("get", `/api/orders/${encodeURIComponent(r.order_id)}`, undefined, epoch);
      owner(epoch);
      if (response.status !== 200 || response.data?.id !== r.order_id || !hasStatusRevision(response.data) || !canChangeOrderStatus(response.data, r.status, actor)) fail("STATUS_TRANSITION_INVALID", statusFailureMessage("STATUS_TRANSITION_INVALID"));
      clear(r); return response.data;
    }),
    acknowledge: () => exclusive(async () => { const r = read(); if (!r || !statusTerminal(r.receipt)) uncertain(); clear(r); }),
  };
};
