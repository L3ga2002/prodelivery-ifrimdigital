import { z } from "zod";
import { financialIdentifier as identifier, financialOperationId as operationId, financialInteger as safeNumber,
  financialMoney, financialEventEligibility, readFinancialActivity } from "./orderFinancialActivity";
import { readOrderFinance } from "./orderFinance";

export const FINANCIAL_EVENT_TIMEOUT_MS = 15000;
const receiptSchema = z.object({ client_operation_id: operationId, state: z.enum(["applied", "replayed", "pending", "rejected"]),
  order_id: identifier.nullable(), order_version: safeNumber.nullable(), error_code: z.string().max(64).regex(/^[A-Z][A-Z0-9_]*$/).nullable(),
  retry_after_seconds: z.number().int().min(1).max(60).nullable() }).strict();
const recordSchema = z.object({ version: z.literal(1), actor_id: identifier, role: z.enum(["driver", "restaurant"]), resource_id: identifier,
  order_id: identifier, event_type: z.enum(["advance_not_paid_declared", "advance_shortfall_acknowledged"]), amount_bani: financialMoney,
  declaration_id: operationId.nullable(), client_operation_id: operationId, expected_order_version: safeNumber, receipt: receiptSchema.nullable() }).strict()
  .refine((r) => r.role === "driver" ? r.event_type === "advance_not_paid_declared" && r.declaration_id === null :
    r.event_type === "advance_shortfall_acknowledged" && r.declaration_id !== null);
export const financialEventRejectionStatus = {
  ORDER_NOT_FOUND: 404, ORDER_TARGET_CHANGED: 409, ORDER_DATA_INVALID: 409, ORDER_VERSION_REQUIRED: 409, ORDER_VERSION_INVALID: 409,
  ORDER_VERSION_CONFLICT: 409, ORDER_VERSION_EXHAUSTED: 409, STATUS_TRANSITION_INVALID: 409, ORDER_NOT_READY: 409,
  CUSTODY_RESOLUTION_REQUIRED: 409, DRIVER_NOT_FOUND: 404, DRIVER_DATA_INVALID: 409, DRIVER_DISABLED: 409,
  ASSIGNMENT_INCONSISTENT: 409, ASSIGNMENT_REPRESENTATION_UNSUPPORTED: 409, FINANCIAL_SNAPSHOT_INVALID: 409,
  FINANCIAL_AMOUNT_INVALID: 409, FINANCIAL_DRIVER_TOTAL_INVALID: 409, FINANCIAL_PICKUP_APPROVAL_REQUIRED: 409,
  FINANCIAL_EVENT_NOT_ELIGIBLE: 409, FINANCIAL_ACTIVITY_INVALID: 409, FINANCIAL_DECLARATION_EXISTS: 409,
  FINANCIAL_DECLARATION_REQUIRED: 409, FINANCIAL_DECLARATION_CHANGED: 409, FINANCIAL_APPROVAL_EXISTS: 409,
  FINANCIAL_EVENT_REQUIRES_ACCEPTED: 409, FINANCIAL_EVENT_AMOUNT_MISMATCH: 409,
};
const intentFields = ["version", "actor_id", "role", "resource_id", "order_id", "event_type", "amount_bani", "declaration_id", "client_operation_id", "expected_order_version"];
export const financialEventTerminal = (receipt) => Boolean(receipt && ["applied", "replayed", "rejected"].includes(receipt.state));
export const financialEventApplied = (receipt) => Boolean(receipt && ["applied", "replayed"].includes(receipt.state));
export const validFinancialEventActor = (actor) => Boolean(actor && identifier.safeParse(actor.id).success &&
  ["driver", "restaurant"].includes(actor.role) && identifier.safeParse(actor.role === "driver" ? actor.driver_id : actor.restaurant_id).success &&
  ["account_disabled", "is_disabled"].every((k) => !Object.hasOwn(actor, k) || actor[k] === false));
export const validFinancialEventToken = (token) => token === null || (typeof token === "string" && token.length > 0 && token.length <= 16384 &&
  token === token.trim() && Array.from(token).every((c) => c.charCodeAt(0) > 32 && c.charCodeAt(0) < 127));
export const financialEventFailureMessage = (code) => ({
  FINANCIAL_DECLARATION_EXISTS: "Lipsa numerarului a fost deja declarată. Reîncarcă evidența comenzii.",
  FINANCIAL_APPROVAL_EXISTS: "Restaurantul a aprobat deja această declarație.",
  FINANCIAL_DECLARATION_CHANGED: "Declarația s-a schimbat. Reîncarcă înainte de aprobare.",
  ORDER_VERSION_CONFLICT: "Comanda s-a modificat între timp. Reîncarcă înainte de o nouă decizie.",
  ORDER_NOT_FOUND: "Comanda nu mai este disponibilă.",
}[code] || "Încercarea a fost refuzată. Verifică starea actuală înainte de o nouă decizie.");
export class OrderFinancialEventError extends Error {
  constructor(code, message) { super(message); this.name = "OrderFinancialEventError"; this.code = code; }
}
const fail = (code, message) => { throw new OrderFinancialEventError(code, message); };
const uncertain = () => fail("OPERATION_UNCERTAIN", "Rezultatul nu este confirmat. Încercarea inițială rămâne păstrată.");
const comparable = (r) => JSON.stringify({ ...r, state: financialEventApplied(r) ? "applied" : r.state });

export const validateFinancialEventReceipt = (response, record) => {
  const parsed = receiptSchema.safeParse(response?.data);
  const invalid = () => fail("INVALID_RESPONSE", "Răspunsul nu confirmă încercarea păstrată. Verifică aceeași încercare.");
  if (!parsed.success || parsed.data.client_operation_id !== record.client_operation_id) invalid();
  const r = parsed.data;
  if (financialEventApplied(r)) {
    if (response.status !== 200 || r.order_id !== record.order_id || r.order_version !== record.expected_order_version + 1 ||
        r.error_code !== null || r.retry_after_seconds !== null) invalid();
  } else {
    if (r.order_id !== null || r.order_version !== null) invalid();
    if (r.state === "pending") {
      const retry = response.headers?.get?.("Retry-After") ?? response.headers?.["retry-after"] ?? response.headers?.["Retry-After"];
      if (response.status !== 202 || r.error_code !== null || r.retry_after_seconds !== 2 || String(retry) !== "2") invalid();
    } else if (!Object.hasOwn(financialEventRejectionStatus, r.error_code) || response.status !== financialEventRejectionStatus[r.error_code] || r.retry_after_seconds !== null) invalid();
  }
  return r;
};

export const createOrderFinancialEventRecovery = ({ actor, api, durableStorage, locks, crypto,
  isOnline = () => true, isOwnerActive = () => true }) => {
  if (!validFinancialEventActor(actor)) fail("AUTH_REQUIRED", "Sesiunea nu permite operațiile de numerar.");
  const scope = { actor_id: actor.id, role: actor.role, resource_id: actor.role === "restaurant" ? actor.restaurant_id : actor.driver_id };
  const key = `prodelivery:order-financial-event:v1:${encodeURIComponent(actor.id)}:${actor.role}:${encodeURIComponent(scope.resource_id)}`;
  const base = (r) => `/api/orders/operations/financial-event/${encodeURIComponent(r.order_id)}`;
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
      try { validateFinancialEventReceipt({ data: r.receipt,
        status: r.receipt.state === "pending" ? 202 : r.receipt.state === "rejected" ? financialEventRejectionStatus[r.receipt.error_code] : 200,
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
    if (financialEventTerminal(latest.receipt)) {
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
      const config = { timeout: FINANCIAL_EVENT_TIMEOUT_MS, signal: abort.signal };
      const call = method === "get" ? api.get(path, config) : api[method](path, body, config);
      const response = await Promise.race([call, new Promise((_, reject) => {
        timer = setTimeout(() => { abort.abort(); reject(new OrderFinancialEventError("RECOVERY_UNAVAILABLE", "Serverul nu confirmă rezultatul. Verifică aceeași încercare.")); }, FINANCIAL_EVENT_TIMEOUT_MS);
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
    const response = await request("get", "/api/orders/operations/financial-event/capabilities", undefined, generation);
    if (response.status !== 200 || typeof response.data?.financial_event_recovery_enabled !== "boolean" ||
      Object.keys(response.data).length !== 1) fail("CAPABILITY_UNAVAILABLE", "Disponibilitatea operației de numerar nu poate fi confirmată. Reîncearcă verificarea.");
    owner(generation); if (read()) fail("INTENT_PENDING", "O încercare a apărut în alt tab. Verifică rezultatul ei.");
    return response.data.financial_event_recovery_enabled;
  };
  const readResult = async (r, generation) => {
    if (financialEventTerminal(r.receipt)) return r.receipt;
    let response;
    try { response = await request("get", lookup(r), undefined, generation); }
    catch (error) {
      owner(generation);
      if (error?.response?.status === 404 && error.response.data?.detail?.code === "OPERATION_NOT_FOUND" && r.receipt === null) return { not_admitted: true };
      throw error;
    }
    return save(r, validateFinancialEventReceipt(response, r), generation);
  };
  const send = async (r, generation) => {
    const body = { client_operation_id: r.client_operation_id, expected_order_version: r.expected_order_version,
      event_type: r.event_type, amount_bani: r.amount_bani, declaration_id: r.declaration_id };
    return save(r, validateFinancialEventReceipt(await request("post", base(r), body, generation), r), generation);
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
      if (error instanceof OrderFinancialEventError) throw error;
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
      if (response.status !== 200 || !validFinancialEventActor(response.data) || response.data.id !== scope.actor_id || response.data.role !== scope.role ||
        (scope.role === "restaurant" ? response.data.restaurant_id !== scope.resource_id : response.data.driver_id !== scope.resource_id)) fail("SESSION_CHANGED", "Legătura contului s-a schimbat. Încercarea rămâne păstrată.");
      active = true;
    },
    capability,
    submit: ({ order }) => exclusive(async (generation) => {
      if (read()) fail("INTENT_PENDING", "Verifică încercarea existentă înainte de o acțiune nouă.");
      const command = financialEventEligibility(order, actor);
      if (!command) fail("ORDER_NOT_ELIGIBLE", "Comanda nu permite această operație. Reîncarcă datele.");
      if (!await capability(generation)) fail("FINANCIAL_EVENT_DISABLED", "Declararea numerarului insuficient este dezactivată.");
      let id; try { id = crypto.randomUUID(); } catch { fail("ID_UNAVAILABLE", "Identitatea încercării nu poate fi generată."); }
      if (!operationId.safeParse(id).success) fail("ID_UNAVAILABLE", "Identitatea încercării este invalidă.");
      const r = { version: 1, ...scope, order_id: order.id, ...command, client_operation_id: id,
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
      return save(r, validateFinancialEventReceipt(await request("post", `${lookup(r)}/resume`, undefined, generation), r), generation);
    }),
    acknowledge: () => exclusive(async (generation) => {
      const r = read(); if (!r || !financialEventTerminal(r.receipt)) uncertain();
      // Keep the saved result and admission gate until the current session has
      // successfully read the authoritative order. Failed/offline reads retain it.
      const proof = validateFinancialEventReceipt(await request("get", lookup(r), undefined, generation), r);
      if (comparable(proof) !== comparable(r.receipt)) storageError();
      const response = await request("get", `/api/orders/${encodeURIComponent(r.order_id)}`, undefined, generation);
      const fresh = response?.data;
      if (response.status !== 200 || fresh?.id !== r.order_id || !identifier.safeParse(fresh.restaurant_id).success ||
        (scope.role === "restaurant" ? fresh.restaurant_id !== scope.resource_id : fresh.driver_id !== scope.resource_id) ||
        !["NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED", "PICKED_UP", "DELIVERED", "CANCELLED"].includes(fresh.status) ||
        !safeNumber.safeParse(fresh.order_version).success || (financialEventApplied(r.receipt) && fresh.order_version < r.receipt.order_version)) {
        fail("INVALID_RESPONSE", "Starea actuală a comenzii nu poate fi confirmată. Rezultatul rămâne păstrat.");
      }
      const activity = readFinancialActivity(fresh);
      if (readOrderFinance(fresh).state !== "ready" || activity.state === "invalid" || (financialEventApplied(r.receipt) && activity.state !== "ready")) fail("INVALID_RESPONSE", "Evidența financiară actuală nu poate fi verificată. Încercarea rămâne păstrată.");
      clear(generation); return fresh;
    }),
  };
};
