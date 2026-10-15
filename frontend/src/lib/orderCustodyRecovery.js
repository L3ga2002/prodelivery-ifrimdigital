import { z } from "zod";
import { custodyIdentifier as identifier, custodyOperationId as operationId, custodyVersion as safeNumber,
  custodyCommandSchema, custodyCommandRole, custodyCommandEligible, readCustodyActivity } from "./orderCustody";
import { readFinancialActivity } from "./orderFinancialActivity";
import { readOrderFinance } from "./orderFinance";

export const CUSTODY_TIMEOUT_MS = 15000;
const receiptSchema = z.object({ client_operation_id: operationId, state: z.enum(["applied", "replayed", "pending", "rejected"]),
  order_id: identifier.nullable(), order_version: safeNumber.nullable(), error_code: z.string().max(64).regex(/^[A-Z][A-Z0-9_]*$/).nullable(),
  retry_after_seconds: z.number().int().min(1).max(60).nullable() }).strict();
const recordSchema = z.object({ version: z.literal(1), actor_id: identifier, role: z.enum(["admin", "driver", "restaurant"]), resource_id: identifier.nullable(),
  order_id: identifier, order_restaurant_id: identifier, order_driver_id: identifier, command: custodyCommandSchema,
  client_operation_id: operationId, expected_order_version: safeNumber, receipt: receiptSchema.nullable() }).strict()
  .refine((r) => r.role === custodyCommandRole(r.command.event_type) && (r.role === "admin" ? r.resource_id === null : r.resource_id === r[`order_${r.role}_id`]));
export const custodyRejectionStatus = {
  ORDER_NOT_FOUND: 404, DRIVER_NOT_FOUND: 404, NOT_AUTHORIZED: 403,
  ORDER_TARGET_CHANGED: 409, ORDER_DATA_INVALID: 409, ORDER_VERSION_REQUIRED: 409, ORDER_VERSION_INVALID: 409,
  ORDER_VERSION_CONFLICT: 409, ORDER_VERSION_EXHAUSTED: 409, DRIVER_DATA_INVALID: 409, DRIVER_DISABLED: 409,
  ASSIGNMENT_INCONSISTENT: 409, ASSIGNMENT_REPRESENTATION_UNSUPPORTED: 409, FINANCIAL_SNAPSHOT_INVALID: 409,
  STATUS_TRANSITION_INVALID: 409, ORDER_NOT_READY: 409, FINANCIAL_AMOUNT_INVALID: 409, FINANCIAL_DRIVER_TOTAL_INVALID: 409, FINANCIAL_PICKUP_APPROVAL_REQUIRED: 409,
  FINANCIAL_ACTIVITY_INVALID: 409, CUSTODY_INVALID: 409, CUSTODY_REQUIRES_PICKUP: 409, CUSTODY_INCIDENT_INVALID: 409,
  CUSTODY_PREDECESSOR_CHANGED: 409, CUSTODY_STATE_CONFLICT: 409, CUSTODY_WAIT_REQUIRED: 409,
  CUSTODY_BINDING_CHANGED: 409, CUSTODY_RESOLUTION_REQUIRED: 409,
};
const intentFields = ["version", "actor_id", "role", "resource_id", "order_id", "order_restaurant_id", "order_driver_id", "command", "client_operation_id", "expected_order_version"];
export const custodyTerminal = (receipt) => Boolean(receipt && ["applied", "replayed", "rejected"].includes(receipt.state));
export const custodyApplied = (receipt) => Boolean(receipt && ["applied", "replayed"].includes(receipt.state));
export const validCustodyActor = (actor) => Boolean(actor && identifier.safeParse(actor.id).success &&
  ["admin", "driver", "restaurant"].includes(actor.role) && (actor.role === "admin" || identifier.safeParse(actor[`${actor.role}_id`]).success) &&
  ["account_disabled", "is_disabled"].every((k) => !Object.hasOwn(actor, k) || actor[k] === false));
export const validCustodyToken = (token) => token === null || (typeof token === "string" && token.length > 0 && token.length <= 16384 &&
  token === token.trim() && Array.from(token).every((c) => c.charCodeAt(0) > 32 && c.charCodeAt(0) < 127));
export const custodyFailureMessage = (code) => ({
  CUSTODY_WAIT_REQUIRED: "Serverul nu confirmă încă minimum zece minute de așteptare. Reîncarcă starea înainte de o nouă verificare.",
  CUSTODY_INCIDENT_INVALID: "Incidentul trebuie să fie o livrare blocată raportată de livratorul acestei comenzi după ridicare.",
  CUSTODY_PREDECESSOR_CHANGED: "Dovada anterioară s-a schimbat. Reîncarcă starea comenzii.",
  CUSTODY_STATE_CONFLICT: "Custodia s-a modificat. Verifică decizia actuală înainte de o nouă acțiune.",
  ORDER_VERSION_CONFLICT: "Comanda s-a modificat între timp. Reîncarcă înainte de o nouă decizie.",
  ORDER_NOT_FOUND: "Comanda nu mai este disponibilă.",
}[code] || "Încercarea a fost refuzată. Verifică starea actuală înainte de o nouă decizie.");
export class OrderCustodyError extends Error {
  constructor(code, message) { super(message); this.name = "OrderCustodyError"; this.code = code; }
}
const fail = (code, message) => { throw new OrderCustodyError(code, message); };
const uncertain = () => fail("OPERATION_UNCERTAIN", "Rezultatul nu este confirmat. Încercarea inițială rămâne păstrată.");
const comparable = (r) => JSON.stringify({ ...r, state: custodyApplied(r) ? "applied" : r.state });

export const validateCustodyReceipt = (response, record) => {
  const parsed = receiptSchema.safeParse(response?.data);
  const invalid = () => fail("INVALID_RESPONSE", "Răspunsul nu confirmă încercarea păstrată. Verifică aceeași încercare.");
  if (!parsed.success || parsed.data.client_operation_id !== record.client_operation_id) invalid();
  const r = parsed.data;
  if (custodyApplied(r)) {
    if (response.status !== 200 || r.order_id !== record.order_id || r.order_version !== record.expected_order_version + 1 ||
        r.error_code !== null || r.retry_after_seconds !== null) invalid();
  } else {
    if (r.order_id !== null || r.order_version !== null) invalid();
    if (r.state === "pending") {
      const retry = response.headers?.get?.("Retry-After") ?? response.headers?.["retry-after"] ?? response.headers?.["Retry-After"];
      if (response.status !== 202 || r.error_code !== null || r.retry_after_seconds !== 2 || String(retry) !== "2") invalid();
    } else if (!Object.hasOwn(custodyRejectionStatus, r.error_code) || response.status !== custodyRejectionStatus[r.error_code] || r.retry_after_seconds !== null) invalid();
  }
  return r;
};

export const createOrderCustodyRecovery = ({ actor, api, durableStorage, locks, crypto,
  isOnline = () => true, isOwnerActive = () => true }) => {
  if (!validCustodyActor(actor)) fail("AUTH_REQUIRED", "Sesiunea nu permite operațiile de custodie.");
  const scope = { actor_id: actor.id, role: actor.role, resource_id: actor.role === "admin" ? null : actor[`${actor.role}_id`] };
  const key = `prodelivery:order-custody:v1:${encodeURIComponent(actor.id)}:${actor.role}:${encodeURIComponent(scope.resource_id)}`;
  const base = (r) => `/api/orders/operations/custody/${encodeURIComponent(r.order_id)}`;
  const lookup = (r) => `${base(r)}/${encodeURIComponent(r.client_operation_id)}`;
  let active = true, epoch = 0, working = false, poisoned = false;
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
      try { validateCustodyReceipt({ data: r.receipt,
        status: r.receipt.state === "pending" ? 202 : r.receipt.state === "rejected" ? custodyRejectionStatus[r.receipt.error_code] : 200,
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
    if (!latest || intentFields.some((field) => JSON.stringify(latest[field]) !== JSON.stringify(r[field]))) storageError();
    if (custodyTerminal(latest.receipt)) {
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
      const config = { timeout: CUSTODY_TIMEOUT_MS, signal: abort.signal };
      const call = method === "get" ? api.get(path, config) : api[method](path, body, config);
      const response = await Promise.race([call, new Promise((_, reject) => {
        timer = setTimeout(() => { abort.abort(); reject(new OrderCustodyError("RECOVERY_UNAVAILABLE", "Serverul nu confirmă rezultatul. Verifică aceeași încercare.")); }, CUSTODY_TIMEOUT_MS);
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
    if (read()) fail("INTENT_PENDING", "Verifică încercarea existentă înainte de o acțiune nouă.");
    const response = await request("get", "/api/orders/operations/custody/capabilities", undefined, generation);
    if (response.status !== 200 || typeof response.data?.custody_recovery_enabled !== "boolean" ||
      Object.keys(response.data).length !== 1) fail("CAPABILITY_UNAVAILABLE", "Disponibilitatea operației de custodie nu poate fi confirmată. Reîncearcă verificarea.");
    owner(generation); if (read()) fail("INTENT_PENDING", "O încercare a apărut în alt tab. Verifică rezultatul ei.");
    return response.data.custody_recovery_enabled;
  };
  const readResult = async (r, generation) => {
    if (custodyTerminal(r.receipt)) return r.receipt;
    let response;
    try { response = await request("get", lookup(r), undefined, generation); }
    catch (error) {
      owner(generation);
      if (error?.response?.status === 404 && error.response.data?.detail?.code === "OPERATION_NOT_FOUND" && r.receipt === null) return { not_admitted: true };
      throw error;
    }
    return save(r, validateCustodyReceipt(response, r), generation);
  };
  const send = async (r, generation) => {
    const body = { client_operation_id: r.client_operation_id, expected_order_version: r.expected_order_version, ...r.command };
    return save(r, validateCustodyReceipt(await request("post", base(r), body, generation), r), generation);
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
      if (error instanceof OrderCustodyError) throw error;
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
      if (response.status !== 200 || !validCustodyActor(response.data) || response.data.id !== scope.actor_id || response.data.role !== scope.role ||
        (scope.role !== "admin" && response.data[`${scope.role}_id`] !== scope.resource_id)) fail("SESSION_CHANGED", "Legătura contului s-a schimbat. Încercarea rămâne păstrată.");
      active = true;
    },
    capability,
    submit: ({ order, command }) => exclusive(async (generation) => {
      if (read()) fail("INTENT_PENDING", "Verifică încercarea existentă înainte de o acțiune nouă.");
      if (!custodyCommandEligible(order, actor, command)) fail("ORDER_NOT_ELIGIBLE", "Comanda nu permite această operație. Reîncarcă datele.");
      if (!await capability(generation)) fail("CUSTODY_DISABLED", "Operațiile noi de custodie sunt dezactivate.");
      let id; try { id = crypto.randomUUID(); } catch { fail("ID_UNAVAILABLE", "Identitatea încercării nu poate fi generată."); }
      if (!operationId.safeParse(id).success) fail("ID_UNAVAILABLE", "Identitatea încercării este invalidă.");
      const r = { version: 1, ...scope, order_id: order.id, order_restaurant_id: order.restaurant_id, order_driver_id: order.driver_id, command: custodyCommandSchema.parse(command), client_operation_id: id,
        expected_order_version: order.order_version, receipt: null };
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
      return save(r, validateCustodyReceipt(await request("post", `${lookup(r)}/resume`, undefined, generation), r), generation);
    }),
    acknowledge: () => exclusive(async (generation) => {
      const r = read(); if (!r || !custodyTerminal(r.receipt)) uncertain();
      // Keep the saved result and admission gate until the current session has
      // successfully read the authoritative order. Failed/offline reads retain it.
      const proof = validateCustodyReceipt(await request("get", lookup(r), undefined, generation), r);
      if (comparable(proof) !== comparable(r.receipt)) storageError();
      const response = await request("get", `/api/orders/${encodeURIComponent(r.order_id)}`, undefined, generation);
      const fresh = response?.data;
      if (response.status !== 200 || fresh?.id !== r.order_id || !identifier.safeParse(fresh.restaurant_id).success ||
        (fresh.restaurant_id !== r.order_restaurant_id || fresh.driver_id !== r.order_driver_id) ||
        !["NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"].includes(fresh.status) ||
        !safeNumber.safeParse(fresh.order_version).success || (custodyApplied(r.receipt) && fresh.order_version < r.receipt.order_version)) {
        fail("INVALID_RESPONSE", "Starea actuală a comenzii nu poate fi confirmată. Rezultatul rămâne păstrat.");
      }
      const activity = readCustodyActivity(fresh);
      if (readOrderFinance(fresh).state === "invalid" || readFinancialActivity(fresh).state === "invalid" || activity.state === "invalid" || (custodyApplied(r.receipt) && activity.state !== "ready")) fail("INVALID_RESPONSE", "Evidența actuală a custodiei nu poate fi verificată. Încercarea rămâne păstrată.");
      if (custodyApplied(r.receipt)) {
        const v = activity.value, c = r.command;
        if (v.incident_id !== c.incident_id || (c.event_type === "delivery_wait_started" && v.reason !== c.reason) ||
          (c.event_type === "delivery_failure_reviewed" && (!v.review_id || v.wait_event_id !== c.predecessor_id)) ||
          (c.event_type === "products_disposition_decided" && (!v.decision_id || v.review_id !== c.predecessor_id || v.decision !== c.decision)) ||
          (c.event_type === "products_return_received" && (v.status !== "returned" || v.decision_id !== c.predecessor_id)) ||
          (c.event_type === "products_keep_acknowledged" && (v.status !== "kept" || v.decision_id !== c.predecessor_id))) fail("INVALID_RESPONSE", "Dovezile actuale nu corespund operației confirmate. Încercarea rămâne păstrată.");
      }
      clear(generation); return fresh;
    }),
  };
};
