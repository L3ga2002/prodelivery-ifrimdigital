import { z } from "zod";
import { isValid, parseISO } from "date-fns";
import { getPreparationStatus } from "./orderWorkflow";

export const PREPARATION_TIMEOUT_MS = 15000;
const identifier = z.string().min(1).max(120).refine((v) => v === v.trim() &&
  Array.from(v).every((c) => c.charCodeAt(0) >= 32 && c.charCodeAt(0) !== 127))
  .refine((v) => { try { encodeURIComponent(v); return true; } catch { return false; } });
const operationId = z.string().min(16).max(128).regex(/^[A-Za-z0-9_-]+$/);
const safeNumber = z.number().refine((v) => Number.isSafeInteger(v) && v >= 0);
const expectedVersion = safeNumber.refine((v) => v < Number.MAX_SAFE_INTEGER).nullable();
const minutes = z.number().int().min(1).max(240);
const timestamp = z.string().refine((v) => /^(?!0000)\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$/.test(v) && isValid(parseISO(v)));
const effectFields = ["order_id", "order_version", "preparation_status", "preparation_time", "preparation_started_at",
  "preparation_due_at", "preparation_ready_at", "preparation_estimated_seconds", "preparation_actual_seconds", "preparation_delay_seconds"];
const receiptSchema = z.object({
  client_operation_id: operationId, state: z.enum(["applied", "replayed", "pending", "rejected"]),
  order_id: identifier.nullable(), order_version: safeNumber.nullable(),
  preparation_status: z.enum(["PREPARING", "READY"]).nullable(), preparation_time: minutes.nullable(),
  preparation_started_at: timestamp.nullable(), preparation_due_at: timestamp.nullable(), preparation_ready_at: timestamp.nullable(),
  preparation_estimated_seconds: safeNumber.refine((v) => v <= 14400).nullable(), preparation_actual_seconds: safeNumber.nullable(), preparation_delay_seconds: safeNumber.nullable(),
  error_code: z.string().max(64).regex(/^[A-Z][A-Z0-9_]*$/).nullable(), retry_after_seconds: z.number().int().min(1).max(60).nullable(),
}).strict();
const recordSchema = z.object({ version: z.literal(1), actor_id: identifier, role: z.enum(["admin", "restaurant"]),
  restaurant_id: identifier.nullable(), order_id: identifier, action: z.enum(["preparing", "ready"]),
  client_operation_id: operationId, expected_order_version: expectedVersion, preparation_time: minutes.nullable(),
  receipt: receiptSchema.nullable(),
}).strict().refine((r) => r.role === "admin" ? r.restaurant_id === null : r.restaurant_id !== null)
  .refine((r) => r.action === "preparing" ? r.preparation_time !== null : r.preparation_time === null);
export const preparationRejectionStatus = {
  ORDER_NOT_FOUND: 404, ORDER_TARGET_CHANGED: 409, ORDER_DATA_INVALID: 409, ORDER_VERSION_REQUIRED: 409,
  ORDER_VERSION_INVALID: 409, ORDER_VERSION_CONFLICT: 409, ORDER_VERSION_EXHAUSTED: 409,
  PREPARATION_TRANSITION_INVALID: 409, PREPARATION_ALREADY_STARTED: 409,
  PREPARATION_ALREADY_READY: 409, PREPARATION_DRIVER_REQUIRED: 409,
};
const intentFields = ["version", "actor_id", "role", "restaurant_id", "order_id", "action", "client_operation_id", "expected_order_version", "preparation_time"];
export const preparationTerminal = (receipt) => Boolean(receipt && ["applied", "replayed", "rejected"].includes(receipt.state));
export const preparationApplied = (receipt) => Boolean(receipt && ["applied", "replayed"].includes(receipt.state));
export const validPreparationActor = (actor) => Boolean(actor && identifier.safeParse(actor.id).success &&
  ["admin", "restaurant"].includes(actor.role) && (actor.role !== "restaurant" || identifier.safeParse(actor.restaurant_id).success) &&
  ["account_disabled", "is_disabled"].every((k) => !Object.hasOwn(actor, k) || actor[k] === false));
export const validPreparationToken = (token) => token === null || (typeof token === "string" && token.length > 0 && token.length <= 16384 &&
  token === token.trim() && Array.from(token).every((c) => c.charCodeAt(0) > 32 && c.charCodeAt(0) < 127));
export const preparationFailureMessage = (code) => ({
  PREPARATION_ALREADY_STARTED: "Pregătirea a fost pornită prin altă încercare. Verifică timpul actual al comenzii.",
  PREPARATION_ALREADY_READY: "Comanda a fost marcată gata prin altă încercare.",
  PREPARATION_DRIVER_REQUIRED: "Nu există un livrator eligibil pentru timpul scurt ales.",
  ORDER_VERSION_CONFLICT: "Comanda s-a modificat între timp. Reîncarcă înainte de o nouă decizie.",
  ORDER_NOT_FOUND: "Comanda nu mai este disponibilă.",
}[code] || "Încercarea a fost refuzată. Verifică starea actuală înainte de o nouă decizie.");
export class OrderPreparationError extends Error {
  constructor(code, message) { super(message); this.name = "OrderPreparationError"; this.code = code; }
}
const fail = (code, message) => { throw new OrderPreparationError(code, message); };
const uncertain = () => fail("OPERATION_UNCERTAIN", "Rezultatul nu este confirmat. Încercarea inițială rămâne păstrată.");
const comparable = (r) => JSON.stringify({ ...r, state: preparationApplied(r) ? "applied" : r.state });

export const validatePreparationReceipt = (response, record) => {
  const parsed = receiptSchema.safeParse(response?.data);
  const invalid = () => fail("INVALID_RESPONSE", "Răspunsul nu confirmă încercarea păstrată. Verifică aceeași încercare.");
  if (!parsed.success || parsed.data.client_operation_id !== record.client_operation_id) invalid();
  const r = parsed.data;
  if (preparationApplied(r)) {
    if (response.status !== 200 || r.order_id !== record.order_id || r.error_code !== null || r.retry_after_seconds !== null ||
      r.order_version !== (record.expected_order_version === null ? null : record.expected_order_version + 1) ||
      r.preparation_status !== (record.action === "preparing" ? "PREPARING" : "READY")) invalid();
    if (record.action === "preparing" && (r.preparation_time !== record.preparation_time || !r.preparation_started_at || !r.preparation_due_at ||
      r.preparation_estimated_seconds !== record.preparation_time * 60 ||
      Date.parse(r.preparation_due_at) - Date.parse(r.preparation_started_at) !== record.preparation_time * 60000)) invalid();
    if (record.action === "ready" && (!r.preparation_ready_at || r.preparation_delay_seconds === null ||
      (r.preparation_started_at === null ? r.preparation_actual_seconds !== null : r.preparation_actual_seconds === null))) invalid();
  } else {
    if (effectFields.some((key) => r[key] !== null)) invalid();
    if (r.state === "pending") {
      const retry = response.headers?.get?.("Retry-After") ?? response.headers?.["retry-after"] ?? response.headers?.["Retry-After"];
      if (response.status !== 202 || r.error_code !== null || r.retry_after_seconds !== 2 || String(retry) !== "2") invalid();
    } else if (!Object.hasOwn(preparationRejectionStatus, r.error_code) || response.status !== preparationRejectionStatus[r.error_code] || r.retry_after_seconds !== null) invalid();
  }
  return r;
};

export const createOrderPreparationRecovery = ({ actor, api, durableStorage, locks, crypto,
  isOnline = () => true, isOwnerActive = () => true }) => {
  if (!validPreparationActor(actor)) fail("AUTH_REQUIRED", "Sesiunea nu permite pregătirea comenzilor.");
  const scope = { actor_id: actor.id, role: actor.role, restaurant_id: actor.role === "restaurant" ? actor.restaurant_id : null };
  const key = `prodelivery:order-preparation:v1:${encodeURIComponent(actor.id)}:${actor.role}:${encodeURIComponent(scope.restaurant_id || "")}`;
  const base = (r) => `/api/orders/operations/${r.action}/${encodeURIComponent(r.order_id)}`;
  const lookup = (r) => `${base(r)}/${encodeURIComponent(r.client_operation_id)}`;
  let active = true, epoch = 0, working = false, poisoned = false, lastCapability = null;
  const requests = new Set();
  const currentOwner = (generation) => { if (generation !== epoch || !isOwnerActive()) fail("SESSION_CHANGED", "Sesiunea s-a schimbat. Încercarea inițială rămâne păstrată."); };
  const owner = (generation = epoch) => { currentOwner(generation); if (!active) fail("SESSION_CHANGED", "Reverifică sesiunea înainte de reluare."); };
  const storageError = () => { poisoned = true; fail("STORAGE_UNAVAILABLE", "Încercarea salvată nu poate fi verificată. O acțiune nouă este blocată."); };
  const read = () => {
    owner();
    let raw, parsed;
    try { raw = durableStorage.getItem(key); if (raw === null) return null; parsed = recordSchema.safeParse(JSON.parse(raw)); }
    catch { storageError(); }
    if (!parsed.success || Object.keys(scope).some((field) => parsed.data[field] !== scope[field])) storageError();
    const r = parsed.data;
    if (r.receipt) {
      try { validatePreparationReceipt({ data: r.receipt,
        status: r.receipt.state === "pending" ? 202 : r.receipt.state === "rejected" ? preparationRejectionStatus[r.receipt.error_code] : 200,
        headers: { "retry-after": "2" } }, r); } catch { storageError(); }
    }
    return r;
  };
  const persist = (r, generation) => {
    owner(generation);
    try { const raw = JSON.stringify(r); durableStorage.setItem(key, raw); if (durableStorage.getItem(key) !== raw) storageError(); }
    catch { storageError(); }
  };
  const save = (r, receipt, generation) => {
    owner(generation);
    const latest = read();
    if (!latest || intentFields.some((field) => latest[field] !== r[field])) storageError();
    if (preparationTerminal(latest.receipt)) {
      if (comparable(latest.receipt) !== comparable(receipt)) storageError();
      return latest.receipt;
    }
    persist({ ...r, receipt }, generation); return receipt;
  };
  const request = async (method, path, body, generation = epoch, restoring = false) => {
    const check = () => restoring ? currentOwner(generation) : owner(generation);
    check();
    if (!isOnline()) fail("OFFLINE", "Fără internet. Încercarea inițială rămâne păstrată.");
    const abort = new AbortController(); requests.add(abort);
    let timer;
    try {
      const config = { timeout: PREPARATION_TIMEOUT_MS, signal: abort.signal };
      const call = method === "get" ? api.get(path, config) : api[method](path, body, config);
      const response = await Promise.race([call, new Promise((_, reject) => {
        timer = setTimeout(() => { abort.abort(); reject(new OrderPreparationError("RECOVERY_UNAVAILABLE", "Serverul nu confirmă rezultatul. Verifică aceeași încercare.")); }, PREPARATION_TIMEOUT_MS);
      })]);
      check(); return response;
    } catch (error) {
      check();
      if (error?.response?.status === 403 && error.response.data?.detail?.code === "AUTH_CONTEXT_CHANGED") fail("SESSION_CHANGED", "Contul autentificat s-a schimbat. Încercarea rămâne păstrată.");
      if (error?.response?.data?.state === "rejected") return error.response;
      throw error;
    } finally { clearTimeout(timer); requests.delete(abort); }
  };
  const capability = async (generation = epoch) => {
    lastCapability = null;
    if (read()) fail("INTENT_PENDING", "Verifică încercarea existentă înainte de o acțiune nouă.");
    const response = await request("get", "/api/orders/operations/preparation/capabilities", undefined, generation);
    if (response.status !== 200 || typeof response.data?.preparation_recovery_enabled !== "boolean" ||
      Object.keys(response.data).length !== 1) fail("CAPABILITY_UNAVAILABLE", "Disponibilitatea pregătirii nu poate fi confirmată. Reîncearcă verificarea.");
    owner(generation); if (read()) fail("INTENT_PENDING", "O încercare a apărut în alt tab. Verifică rezultatul ei.");
    lastCapability = { generation, enabled: response.data.preparation_recovery_enabled };
    return lastCapability.enabled;
  };
  const readResult = async (r, generation) => {
    if (preparationTerminal(r.receipt)) return r.receipt;
    let response;
    try { response = await request("get", lookup(r), undefined, generation); }
    catch (error) {
      owner(generation);
      if (error?.response?.status === 404 && error.response.data?.detail?.code === "OPERATION_NOT_FOUND" && r.receipt === null) return { not_admitted: true };
      throw error;
    }
    return save(r, validatePreparationReceipt(response, r), generation);
  };
  const send = async (r, generation) => {
    const body = { client_operation_id: r.client_operation_id, expected_order_version: r.expected_order_version,
      ...(r.action === "preparing" ? { preparation_time: r.preparation_time } : {}) };
    return save(r, validatePreparationReceipt(await request("put", base(r), body, generation), r), generation);
  };
  const exclusive = async (action) => {
    const generation = epoch; owner(generation);
    if (working) fail("BUSY", "O acțiune este deja în curs.");
    if (typeof locks?.request !== "function") fail("LOCK_UNAVAILABLE", "Browserul nu poate proteja această acțiune între taburi.");
    working = true;
    try {
      return await locks.request(key, { ifAvailable: true }, async (lock) => {
        owner(generation); if (!lock) fail("BUSY", "Aceeași încercare este verificată în alt tab.");
        if (poisoned) storageError();
        const result = await action(generation); owner(generation); return result;
      });
    } catch (error) {
      owner(generation);
      if (error instanceof OrderPreparationError) throw error;
      const status = error?.response?.status;
      fail(status === 401 ? "AUTH_REQUIRED" : status === 403 ? "NOT_AUTHORIZED" : status === 409 ? "INTENT_CONFLICT" : "RECOVERY_UNAVAILABLE",
        status === 401 ? "Sesiunea a expirat. Reconectează-te pentru aceeași încercare." : status === 403 ? "Contul nu mai are acces la această comandă." :
          status === 409 ? "Încercarea intră în conflict cu datele serverului. Păstrează identitatea și verifică rezultatul." : "Rezultatul nu este confirmat. Verifică aceeași încercare.");
    } finally { working = false; }
  };
  const clear = (generation) => {
    owner(generation);
    try { durableStorage.removeItem(key); if (durableStorage.getItem(key) !== null) storageError(); } catch { storageError(); }
  };
  return {
    snapshot: read, storageBlocked: () => poisoned,
    activate: () => { active = true; },
    deactivate: () => { active = false; epoch++; for (const abort of requests) abort.abort(); },
    restoreSession: async () => {
      const generation = epoch; currentOwner(generation);
      const response = await request("get", "/api/auth/me", undefined, generation, true);
      currentOwner(generation);
      if (response.status !== 200 || !validPreparationActor(response.data) || response.data.id !== scope.actor_id || response.data.role !== scope.role ||
        (scope.role === "restaurant" && response.data.restaurant_id !== scope.restaurant_id)) fail("SESSION_CHANGED", "Legătura contului s-a schimbat. Încercarea rămâne păstrată.");
      active = true;
    },
    capability,
    canUseLegacy: () => {
      owner();
      return !poisoned && isOnline() && lastCapability?.generation === epoch && lastCapability.enabled === false && read() === null;
    },
    submit: ({ order, action, preparationTime = null }) => exclusive(async (generation) => {
      if (read()) fail("INTENT_PENDING", "Verifică încercarea existentă înainte de o acțiune nouă.");
      if (!identifier.safeParse(order?.id).success || !["preparing", "ready"].includes(action) ||
        getPreparationStatus(order) !== (action === "preparing" ? "NEW" : "PREPARING") ||
        (scope.role === "restaurant" && order.restaurant_id !== scope.restaurant_id) ||
        (action === "preparing" && !minutes.safeParse(preparationTime).success)) fail("ORDER_NOT_ELIGIBLE", "Comanda nu mai permite acțiunea aleasă. Reîncarcă lista.");
      const revision = Object.hasOwn(order, "order_version") ? order.order_version : null;
      if ((Object.hasOwn(order, "order_version") && revision === null) || !expectedVersion.safeParse(revision).success) fail("ORDER_VERSION_INVALID", "Versiunea comenzii nu poate fi reprezentată exact. Acțiunea este blocată.");
      if (!await capability(generation)) fail("PREPARATION_DISABLED", "Recuperarea pregătirii este dezactivată. Nicio încercare nouă nu a fost trimisă.");
      let id; try { id = crypto.randomUUID(); } catch { fail("ID_UNAVAILABLE", "Identitatea încercării nu poate fi generată."); }
      if (!operationId.safeParse(id).success) fail("ID_UNAVAILABLE", "Identitatea încercării este invalidă.");
      const r = { version: 1, ...scope, order_id: order.id, action, client_operation_id: id,
        expected_order_version: revision, preparation_time: action === "preparing" ? preparationTime : null, receipt: null };
      owner(generation); if (read()) fail("INTENT_PENDING", "Verifică încercarea existentă.");
      persist(r, generation);
      try { return await send(r, generation); }
      catch (error) {
        owner(generation);
        if ([401, 403, 409, 422].includes(error?.response?.status) || error?.code === "SESSION_CHANGED" || poisoned) throw error;
        return readResult(r, generation);
      }
    }),
    recover: () => exclusive(async (generation) => { const r = read(); return r ? readResult(r, generation) : null; }),
    resend: () => exclusive(async (generation) => {
      const r = read(); if (!r || r.receipt) uncertain();
      const found = await readResult(r, generation);
      // This branch is reached only by an explicit user action. A lookup never sends.
      return found?.not_admitted === true ? send(r, generation) : found;
    }),
    resume: () => exclusive(async (generation) => {
      const r = read(); if (!r) uncertain();
      const found = await readResult(r, generation);
      if (found?.state !== "pending") return found;
      return save(r, validatePreparationReceipt(await request("post", `${lookup(r)}/resume`, undefined, generation), r), generation);
    }),
    acknowledge: () => exclusive(async (generation) => {
      const r = read(); if (!r || !preparationTerminal(r.receipt)) uncertain();
      // Keep the saved result and admission gate until the current session has
      // successfully read the authoritative order. Failed/offline reads retain it.
      const proof = validatePreparationReceipt(await request("get", lookup(r), undefined, generation), r);
      if (comparable(proof) !== comparable(r.receipt)) storageError();
      const response = await request("get", `/api/orders/${encodeURIComponent(r.order_id)}`, undefined, generation);
      const fresh = response?.data;
      if (response.status !== 200 || fresh?.id !== r.order_id || !identifier.safeParse(fresh.restaurant_id).success ||
        (scope.role === "restaurant" && fresh.restaurant_id !== scope.restaurant_id) ||
        !["NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"].includes(fresh.status) ||
        (Object.hasOwn(fresh, "order_version") && !safeNumber.safeParse(fresh.order_version).success)) {
        fail("INVALID_RESPONSE", "Starea actuală a comenzii nu poate fi confirmată. Rezultatul rămâne păstrat.");
      }
      clear(generation); return fresh;
    }),
  };
};
