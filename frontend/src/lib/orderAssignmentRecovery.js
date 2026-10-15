import { z } from "zod";
import { verifyRecoverySession } from "./recoverySession";
import { isValid, parseISO } from "date-fns";

export const ASSIGN_REQUEST_TIMEOUT_MS = 15000;
export const MAX_ASSIGN_RECOVERY_READS = 3;
const identifier = z.string().min(1).max(120).refine((v) => v === v.trim() &&
  Array.from(v).every((c) => c.charCodeAt(0) >= 32 && c.charCodeAt(0) !== 127))
  .refine((v) => { try { encodeURIComponent(v); return true; } catch { return false; } });
const operationId = z.string().min(16).max(128).regex(/^[A-Za-z0-9_-]+$/);
const version = z.number().refine((v) => Number.isSafeInteger(v) && v >= 0 && v < Number.MAX_SAFE_INTEGER);
const receiptSchema = z.object({
  client_operation_id: operationId, state: z.enum(["applied", "replayed", "pending", "rejected"]),
  order_id: identifier.nullable().optional(),
  order_version: z.number().refine((v) => Number.isSafeInteger(v) && v >= 0).nullable().optional(),
  error_code: z.string().max(64).regex(/^[A-Z][A-Z0-9_]*$/).nullable().optional(),
  retry_after_seconds: z.number().int().min(1).max(60).nullable().optional(),
}).strict();
const recordSchema = z.object({ actor_id: identifier, order_id: identifier,
  client_operation_id: operationId, expected_order_version: version, driver_id: identifier,
  receipt: receiptSchema.nullable() }).strict();
const rejectionCodes = {
  ORDER_NOT_FOUND: 404, DRIVER_NOT_FOUND: 404,
  ORDER_TARGET_CHANGED: 409, ORDER_DATA_INVALID: 409, ORDER_VERSION_REQUIRED: 409,
  ORDER_VERSION_INVALID: 409, ORDER_VERSION_CONFLICT: 409, ORDER_VERSION_EXHAUSTED: 409,
  ORDER_NOT_ASSIGNABLE: 409, DRIVER_DATA_INVALID: 409, DRIVER_NOT_AVAILABLE: 409,
  DRIVER_DISABLED: 409, DRIVER_BUSY: 409, ASSIGNMENT_INCONSISTENT: 409,
  ASSIGNMENT_REPRESENTATION_UNSUPPORTED: 409, NO_CHANGES: 409,
};
const intentFields = ["actor_id", "order_id", "client_operation_id", "expected_order_version", "driver_id"];
export class OrderAssignmentError extends Error {
  constructor(code, message) { super(message); this.name = "OrderAssignmentError"; this.code = code; }
}
const fail = (code, message) => { throw new OrderAssignmentError(code, message); };
const uncertain = () => fail("OPERATION_UNCERTAIN", "Alocarea este neconfirmata. Verifica aceeasi operatie, fara o intentie noua.");
export const assignmentTerminal = (receipt) => Boolean(receipt && ["applied", "replayed", "rejected"].includes(receipt.state));
export const validAssignmentActor = (actor) => identifier.safeParse(actor).success;
export const validAssignmentToken = (token) => token === null || (typeof token === "string" && token.length > 0 &&
  token.length <= 16384 && token === token.trim() && Array.from(token).every((c) => c.charCodeAt(0) > 32 && c.charCodeAt(0) < 127));
export const hasAssignmentRevision = (order) => Boolean(order && Object.hasOwn(order, "order_version"));
const noMultiAssignment = (value) => ["current_order_ids", "active_order_ids", "assigned_order_ids", "reserved_order_ids",
  "current_orders", "active_orders", "assigned_orders", "reserved_orders", "pending_order_ids", "order_ids", "driver_ids",
  "assignments", "assignment_ids", "active_assignment_ids", "reserved_assignment_ids", "active_assignments", "reserved_assignments",
  "pending_assignments", "current_assignment_id", "assignment_id", "assignment_version", "dispatch_version", "route_version",
  "active_count", "reserved_count"].every((k) => !Object.hasOwn(value, k));
const preCustody = (order) => ["accepted_at", "picked_up_at", "delivered_at", "cancelled_at", "cancelled_by", "cancellation_reason"].every((k) => order[k] == null);
export const validAssignmentDate = (v) => typeof v === "string" &&
  /^(?!0000)\d{4}-(?:0[1-9]|1[0-2])-(?:0[1-9]|[12]\d|3[01])T(?:[01]\d|2[0-3]):[0-5]\d:[0-5]\d(?:\.\d{1,6})?(?:Z|[+-](?:[01]\d|2[0-3]):[0-5]\d)$/.test(v) &&
  isValid(parseISO(v));
const preparationValid = (order) => {
  const prep = order.preparation_status ?? (order.status === "ASSIGNED"
    ? order.preparation_ready_at != null ? "READY" : order.preparation_started_at != null ? "PREPARING" : "NEW" : order.status);
  if (!["NEW", "PREPARING", "READY"].includes(prep) || (order.status !== "ASSIGNED" && prep !== order.status)) return false;
  if (["preparation_started_at", "preparation_due_at", "preparation_ready_at"].some((k) => order[k] != null && !validAssignmentDate(order[k]))) return false;
  if (prep === "NEW" && ["preparation_started_at", "preparation_due_at", "preparation_ready_at"].some((k) => order[k] != null)) return false;
  if (prep === "PREPARING" && order.preparation_ready_at != null) return false;
  return [["preparation_time", 240], ["preparation_estimated_seconds", 14400],
    ["preparation_actual_seconds", Number.MAX_SAFE_INTEGER], ["preparation_delay_seconds", Number.MAX_SAFE_INTEGER]]
    .every(([k, max]) => order[k] == null || (Number.isSafeInteger(order[k]) && order[k] >= (k === "preparation_time" ? 1 : 0) && order[k] <= max));
};
export const isOrderAssignable = (order) => {
  if (!order || !identifier.safeParse(order.id).success || !preCustody(order) || !noMultiAssignment(order)) return false;
  const versioned = hasAssignmentRevision(order);
  if (versioned && (!version.safeParse(order.order_version).success || !identifier.safeParse(order.restaurant_id).success)) return false;
  if (versioned && (!preparationValid(order) || (Object.hasOwn(order, "audit_trail") &&
    (!Array.isArray(order.audit_trail) || order.audit_trail.some((v) => !v || typeof v !== "object" || Array.isArray(v)))))) return false;
  if (["NEW", "PREPARING", "READY"].includes(order.status)) {
    return order.driver_id == null && order.driver_name == null && order.assigned_at == null;
  }
  return order.status === "ASSIGNED" && identifier.safeParse(order.driver_id).success &&
    validAssignmentDate(order.assigned_at);
};
export const isAssignmentDriverAvailable = (driver) => Boolean(driver && identifier.safeParse(driver.id).success &&
  driver.is_active === true && driver.is_disabled !== true && driver.disabled !== true && driver.disabled_at == null &&
  (!Object.hasOwn(driver, "account_disabled") || driver.account_disabled === false) &&
  driver.current_order_id == null && noMultiAssignment(driver) &&
  (driver.operational_status === "active" || (driver.operational_status == null && (driver.driver_status == null || driver.driver_status === "active"))) &&
  (driver.driver_status == null || driver.driver_status === "active") &&
  (driver.break_started_at == null || validAssignmentDate(driver.break_started_at)) &&
  (driver.break_until == null || (validAssignmentDate(driver.break_until) &&
    (driver.driver_status === "active" || driver.operational_status === "active" || Date.parse(driver.break_until) <= Date.now()))));

export const validateAssignmentReceipt = (response, record) => {
  const parsed = receiptSchema.safeParse(response?.data);
  const invalid = () => fail("INVALID_RESPONSE", "Raspunsul alocarii nu poate fi confirmat. Pastreaza identitatea operatiei.");
  if (!parsed.success || parsed.data.client_operation_id !== record.client_operation_id) invalid();
  const r = parsed.data;
  if (["applied", "replayed"].includes(r.state)) {
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

export const createOrderAssignmentRecovery = ({ actorId, api, durableStorage, locks, crypto,
  isOnline = () => true, isOwnerActive = () => true,
  wait = (ms) => new Promise((resolve) => setTimeout(resolve, ms)) }) => {
  if (!validAssignmentActor(actorId)) fail("AUTH_REQUIRED", "Autentificarea este necesara.");
  const key = `prodelivery:order-assign:v1:${encodeURIComponent(actorId)}`;
  const base = (r) => `/api/orders/operations/assign/${encodeURIComponent(r.order_id)}`;
  const lookup = (r) => `${base(r)}/${encodeURIComponent(r.client_operation_id)}`;
  let working = false, active = true, poisoned = false;
  let lifecycleEpoch = 0;
  const currentOwner = (epoch) => { if (epoch !== lifecycleEpoch || !isOwnerActive()) fail("SESSION_CHANGED", "Sesiunea s-a schimbat. Intentia ramane pastrata."); };
  const owner = (epoch = lifecycleEpoch) => { currentOwner(epoch); if (!active) fail("SESSION_CHANGED", "Sesiunea s-a schimbat. Verifica alocarea cu sesiunea curenta."); };
  const storageError = () => { poisoned = true; fail("STORAGE_UNAVAILABLE", "Stocarea alocarii nu poate fi confirmata. O intentie noua este blocata."); };
  const read = () => {
    owner();
    let raw, parsed;
    try { raw = durableStorage.getItem(key); if (raw == null) return null; parsed = recordSchema.safeParse(JSON.parse(raw)); }
    catch { storageError(); }
    if (!parsed.success || parsed.data.actor_id !== actorId) storageError();
    const r = parsed.data;
    if (r.receipt) {
      try { validateAssignmentReceipt({ data: r.receipt,
        status: r.receipt.state === "pending" ? 202 : r.receipt.state === "rejected" ? rejectionCodes[r.receipt.error_code] : 200,
        headers: { "retry-after": String(r.receipt.retry_after_seconds) } }, r); }
      catch { storageError(); }
    }
    return r;
  };
  const persist = (r, epoch = lifecycleEpoch) => {
    owner(epoch);
    try { const raw = JSON.stringify(r); durableStorage.setItem(key, raw); if (durableStorage.getItem(key) !== raw) storageError(); }
    catch { storageError(); }
  };
  const save = (r, receipt, epoch) => {
    owner(epoch);
    const stored = read();
    if (!stored || intentFields.some((k) => stored[k] !== r[k])) storageError();
    persist({ ...r, receipt }, epoch); return receipt;
  };
  const request = async (method, path, body, epoch = lifecycleEpoch) => {
    owner(epoch);
    if (!isOnline()) fail("OFFLINE", "Fara internet. Identitatea alocarii ramane pastrata.");
    let response;
    try { response = method === "get" ? await api.get(path, { timeout: ASSIGN_REQUEST_TIMEOUT_MS }) :
      await api[method](path, body, { timeout: ASSIGN_REQUEST_TIMEOUT_MS }); }
    catch (error) {
      owner(epoch);
      if (error?.response?.status === 403 && error.response.data?.detail?.code === "AUTH_CONTEXT_CHANGED") {
        fail("SESSION_CHANGED", "Actorul autentificat s-a schimbat. Pastreaza alocarea si reconecteaza-te cu actorul initial.");
      }
      if (error?.response?.data?.state === "rejected") response = error.response; else throw error;
    }
    owner(epoch); return response;
  };
  const send = async (r, epoch) => save(r, validateAssignmentReceipt(await request("post", base(r), {
    client_operation_id: r.client_operation_id, expected_order_version: r.expected_order_version, driver_id: r.driver_id,
  }, epoch), r), epoch);
  const reconcile = async (initial, epoch) => {
    let r = initial, resent = false, resumed = false;
    if (assignmentTerminal(r.receipt)) return r.receipt;
    for (let i = 0; i < MAX_ASSIGN_RECOVERY_READS; i++) {
      let response;
      try { response = await request("get", lookup(r), undefined, epoch); }
      catch (error) {
        owner(epoch);
        if (error?.response?.status !== 404 || error.response.data?.detail?.code !== "OPERATION_NOT_FOUND") throw error;
        if (r.receipt || resent || resumed) uncertain();
        // Pre-admission uncertainty retains the entire small, non-customer intent.
        resent = true;
        const receipt = await send(r, epoch);
        if (assignmentTerminal(receipt)) return receipt;
        r = { ...r, receipt };
      }
      if (response) {
        let receipt = save(r, validateAssignmentReceipt(response, r), epoch);
        r = { ...r, receipt };
        if (assignmentTerminal(receipt)) return receipt;
        if (!resumed) {
          resumed = true;
          receipt = save(r, validateAssignmentReceipt(await request("post", `${lookup(r)}/resume`, undefined, epoch), r), epoch);
          r = { ...r, receipt };
          if (assignmentTerminal(receipt)) return receipt;
        }
      }
      if (i + 1 < MAX_ASSIGN_RECOVERY_READS) { await wait(r.receipt.retry_after_seconds * 1000); owner(epoch); }
    }
    return r.receipt;
  };
  const exclusive = async (action) => {
    const epoch = lifecycleEpoch;
    owner(epoch);
    if (working) fail("BUSY", "Alocarea este deja in curs.");
    if (typeof locks?.request !== "function") fail("LOCK_UNAVAILABLE", "Browserul nu poate proteja alocarea intre taburi. Operatia este blocata.");
    working = true;
    try {
      return await locks.request(key, { ifAvailable: true }, async (lock) => {
        owner(epoch); if (!lock) fail("BUSY", "Alocarea este procesata in alt tab.");
        if (poisoned) storageError();
        const result = await action(epoch); owner(epoch); return result;
      });
    } catch (error) { owner(epoch);
      if (error instanceof OrderAssignmentError) throw error;
      const status = error?.response?.status;
      fail(status === 401 ? "AUTH_REQUIRED" : status === 403 ? "NOT_AUTHORIZED" : status === 409 ? "INTENT_CONFLICT" : "RECOVERY_UNAVAILABLE",
        status === 401 ? "Sesiunea a expirat. Reconecteaza-te pentru aceeasi alocare." :
          status === 403 ? "Accesul s-a schimbat. Alocarea necesita un cont autorizat." :
            status === 409 ? "Conflict de alocare. Verifica operatia existenta; nu trimite o intentie noua." :
              "Serverul nu confirma alocarea. Verifica aceeasi operatie.");
    } finally { working = false; }
  };
  const clear = (epoch = lifecycleEpoch) => {
    owner(epoch);
    try { durableStorage.removeItem(key); if (durableStorage.getItem(key) != null) storageError(); }
    catch { storageError(); }
  };
  const validateIntent = (order, driverId, driver) => {
    if (!isOrderAssignable(order)) fail("ORDER_NOT_ASSIGNABLE", "Comanda nu este eligibila pentru alocare sau reasignare inainte de acceptare.");
    if (!identifier.safeParse(driverId).success || driverId === order.driver_id || driver?.id !== driverId || !isAssignmentDriverAvailable(driver)) {
      fail("INVALID_DRIVER", "Selecteaza un alt livrator disponibil, cu date operationale confirmate.");
    }
    return { order_id: order.id, expected_order_version: order.order_version, driver_id: driverId };
  };
  return {
    snapshot: read, storageBlocked: () => poisoned,
    activate: () => { active = true; }, deactivate: () => { active = false; lifecycleEpoch++; },
    restoreSession: async () => {
      const epoch = lifecycleEpoch; currentOwner(epoch);
      await verifyRecoverySession({ api, actorId, roles: ["admin"], timeout: ASSIGN_REQUEST_TIMEOUT_MS, isOnline,
        currentOwner: () => currentOwner(epoch), fail });
      currentOwner(epoch); active = true;
    },
    capability: async () => {
      const response = await request("get", "/api/orders/operations/assign/capabilities");
      if (response.status !== 200 || typeof response.data?.assign_recovery_enabled !== "boolean") fail("CAPABILITY_UNAVAILABLE", "Disponibilitatea alocarii nu poate fi verificata.");
      return response.data.assign_recovery_enabled;
    },
    submit: ({ order, driverId, driver }) => exclusive(async (epoch) => {
      if (read()) fail("INTENT_PENDING", "Verifica operatia existenta inaintea unei intentii noi.");
      const intent = validateIntent(order, driverId, driver);
      if (!hasAssignmentRevision(order)) fail("ORDER_VERSION_REQUIRED", "Aceasta comanda foloseste fluxul legacy.");
      const cap = await request("get", "/api/orders/operations/assign/capabilities", undefined, epoch);
      owner(epoch);
      if (cap.status !== 200 || cap.data?.assign_recovery_enabled !== true) fail("ASSIGNMENT_DISABLED", "Alocarea versionata este indisponibila. Comanda nu a fost modificata.");
      let id;
      try { id = crypto.randomUUID(); } catch { fail("ID_UNAVAILABLE", "Nu pot genera identitatea alocarii."); }
      if (!operationId.safeParse(id).success) fail("ID_UNAVAILABLE", "Identitatea alocarii este invalida.");
      if (read()) fail("INTENT_PENDING", "Verifica operatia existenta inaintea unei intentii noi.");
      const r = { actor_id: actorId, ...intent, client_operation_id: id, receipt: null };
      persist(r, epoch);
      try { const result = await send(r, epoch); return assignmentTerminal(result) ? result : reconcile(read(), epoch); }
      catch (error) {
        owner(epoch);
        if (error instanceof OrderAssignmentError && error.code !== "INVALID_RESPONSE") throw error;
        if ([401, 403, 409, 422].includes(error?.response?.status)) throw error;
        return reconcile(read(), epoch);
      }
    }),
    submitLegacy: ({ order, driverId, driver }) => exclusive(async (epoch) => {
      if (read()) fail("INTENT_PENDING", "Verifica alocarea recuperabila existenta; fluxul legacy este blocat.");
      const intent = validateIntent(order, driverId, driver);
      if (hasAssignmentRevision(order)) fail("ORDER_VERSION_REQUIRED", "Comanda versionata necesita protocolul recuperabil.");
      const auth = await request("get", "/api/auth/me", undefined, epoch);
      owner(epoch);
      if (auth.status !== 200 || auth.data?.id !== actorId || auth.data?.role !== "admin" ||
        ["account_disabled", "is_disabled"].some((k) => Object.hasOwn(auth.data, k) && auth.data[k] !== false)) {
        fail("SESSION_CHANGED", "Actorul autentificat s-a schimbat. Alocarea legacy nu a fost trimisa.");
      }
      // The PUT also carries the server-checked owner header: cookies can change
      // after this preflight, so this read alone is not an atomic session fence.
      if (read()) fail("INTENT_PENDING", "Verifica alocarea recuperabila existenta; fluxul legacy este blocat.");
      return request("put", `/api/orders/${encodeURIComponent(intent.order_id)}/assign`, { driver_id: intent.driver_id }, epoch);
    }),
    recover: () => exclusive(async (epoch) => { const r = read(); return r ? reconcile(r, epoch) : null; }),
    refreshForNewAttempt: () => exclusive(async (epoch) => {
      const r = read(); if (r?.receipt?.state !== "rejected") uncertain();
      const response = await request("get", `/api/orders/${encodeURIComponent(r.order_id)}`, undefined, epoch);
      owner(epoch);
      if (response.status !== 200 || response.data?.id !== r.order_id || !hasAssignmentRevision(response.data) || !isOrderAssignable(response.data)) {
        fail("ORDER_NOT_ASSIGNABLE", "Comanda reincarcata nu este eligibila. Rezultatul respins ramane pastrat.");
      }
      clear(epoch); return response.data;
    }),
    acknowledge: () => exclusive(async (epoch) => { const r = read(); if (!r || !assignmentTerminal(r.receipt)) uncertain(); clear(epoch); }),
  };
};
