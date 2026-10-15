// Immutable operational intents. These reports never calculate money or change custody.
export const REPORT_TIMEOUT = 15000;
export const reportTerminal = (receipt) => ["applied", "replayed", "rejected"].includes(receipt?.state);
export const reportApplied = (receipt) => ["applied", "replayed"].includes(receipt?.state);
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;
const types = ["missing_product", "damaged_product", "pickup_blocked", "delivery_blocked", "other"];
const rejectedStatuses = { TARGET_NOT_FOUND: 404, TARGET_CHANGED: 409, ORDER_DATA_INVALID: 409, ORDER_VERSION_CONFLICT: 409, ORDER_VERSION_EXHAUSTED: 409 };
const id = (value) => {
  if (typeof value !== "string" || !value.length || Array.from(value).length > 120 || value.trim() !== value || Array.from(value).some((char) => char.charCodeAt(0) < 32 || char.charCodeAt(0) === 127)) return false;
  try { encodeURIComponent(value); return true; } catch { return false; }
};
const fail = (code, message) => { const error = new Error(message); error.code = code; throw error; };
const copy = (value) => value ? JSON.parse(JSON.stringify(value)) : null;
export const reportStorageKey = (actorId, scope) => `pd.operational-report.v1:${encodeURIComponent(actorId)}:${encodeURIComponent(scope)}`;
export const reportPaths = (command) => {
  const target = encodeURIComponent(command.resource_id), operation = encodeURIComponent(command.client_operation_id);
  const base = command.operation_type === "close_day" ? `/api/restaurants/${target}/close-day` : `/api/orders/operations/incident/${target}`;
  const lookup = command.operation_type === "close_day" ? `${base}/operations/${operation}` : `${base}/${operation}`;
  return { base, lookup, resume: `${lookup}/resume`, capability: command.operation_type === "close_day" ? `${base}/capabilities` : "/api/orders/operations/incident/capabilities" };
};
const body = (command) => command.operation_type === "close_day" ? { client_operation_id: command.client_operation_id } : {
  client_operation_id: command.client_operation_id, expected_order_version: command.expected_order_version,
  incident_type: command.incident_type, description: command.description,
};
const validCommand = (command) => command && id(command.resource_id) && uuid.test(command.client_operation_id) && (
  command.operation_type === "close_day" || (command.operation_type === "incident" && types.includes(command.incident_type) &&
    typeof command.description === "string" && command.description.trim() === command.description && command.description.length > 0 &&
    command.description.length <= 500 && (command.expected_order_version === null || (Number.isSafeInteger(command.expected_order_version) && command.expected_order_version >= 0)))
);
export const createOperationalReporting = ({ actor, scope, api, storage, crypto, isOnline, isOwnerActive, onChange, timeout = REPORT_TIMEOUT }) => {
  if (!id(actor?.id) || typeof scope !== "string" || !scope.length || scope.length > 512 || !["admin", "restaurant", "driver"].includes(actor.role)) return null;
  const key = reportStorageKey(actor.id, scope);
  let record = null, blocked = false, busy = false, epoch = 0, suspended = false;
  const requests = new Set();
  const owner = (generation = epoch) => { if (!isOwnerActive() || generation !== epoch || suspended) fail("SESSION_CHANGED", "Sesiunea trebuie reverificată. Intenția rămâne păstrată."); };
  const notify = () => { if (isOwnerActive()) onChange?.(copy(record)); };
  const persist = (next) => {
    try { storage.setItem(key, JSON.stringify(next)); if (storage.getItem(key) !== JSON.stringify(next)) throw Error("READBACK"); }
    catch { blocked = true; fail("STORAGE_UNAVAILABLE", "Intenția sau confirmarea nu poate fi păstrată sigur. Verifică rezultatul înainte de o operație nouă."); }
    record = copy(next); notify();
  };
  const load = () => {
    try {
      const raw = storage.getItem(key);
      if (!raw) { record = null; return; }
      const candidate = JSON.parse(raw);
      if (candidate.schema !== 1 || candidate.actor_id !== actor.id || candidate.role !== actor.role || candidate.scope !== scope || !validCommand(candidate.command)) throw Error("INVALID_DRAFT");
      if (candidate.command.operation_type === "close_day" && actor.role === "restaurant" && candidate.command.resource_id !== actor.restaurant_id) throw Error("FOREIGN_RESTAURANT");
      if (candidate.receipt) validateReceipt(candidate.receipt, candidate.command);
      record = candidate;
    } catch { blocked = true; fail("STORAGE_UNAVAILABLE", "Intenția salvată nu poate fi verificată. Datele au fost păstrate."); }
  };
  const validateReceipt = (receipt, command) => {
    if (!receipt || receipt.client_operation_id !== command.client_operation_id || receipt.operation_type !== command.operation_type ||
      !["pending", "applied", "replayed", "rejected"].includes(receipt.state)) fail("INVALID_RECEIPT", "Răspunsul nu confirmă această intenție.");
    if (receipt.state === "pending" && (!Number.isFinite(receipt.retry_after_seconds) || receipt.retry_after_seconds < 0 || receipt.retry_after_seconds > 60)) fail("INVALID_RECEIPT", "Termenul de recuperare este invalid.");
    if (receipt.state === "rejected" && !Object.hasOwn(rejectedStatuses, receipt.error_code)) fail("INVALID_RECEIPT", "Refuzul operației este invalid.");
    if (reportApplied(receipt)) {
      if (command.operation_type === "close_day") {
        if (receipt.restaurant_id !== command.resource_id || receipt.close_day_operation_id !== command.client_operation_id || receipt.closed_today !== true ||
          typeof receipt.accepting_orders !== "boolean" || !(receipt.pause_until === null || (typeof receipt.pause_until === "string" && Number.isFinite(Date.parse(receipt.pause_until))))) fail("INVALID_RECEIPT", "Închiderea zilei nu este confirmată de server.");
      } else if (receipt.order_id !== command.resource_id || !id(receipt.incident_id) ||
        receipt.order_version !== (command.expected_order_version === null ? null : command.expected_order_version + 1)) fail("INVALID_RECEIPT", "Raportarea incidentului nu este confirmată de server.");
    }
    return receipt;
  };
  const request = async (method, path, data, generation) => {
    owner(generation); if (!isOnline()) fail("OFFLINE", "Fără internet. Intenția rămâne păstrată.");
    const abort = new AbortController(); requests.add(abort); let timer;
    try { return await Promise.race([
      api[method](path, ...(method === "get" ? [{ timeout, signal: abort.signal }] : [data, { timeout, signal: abort.signal }])),
      new Promise((_, reject) => { timer = setTimeout(() => { abort.abort(); const error = new Error("Răspunsul nu a sosit. Verifică aceeași intenție."); error.code = "UNCERTAIN"; reject(error); }, timeout); }),
    ]); } finally { clearTimeout(timer); requests.delete(abort); }
  };
  const verify = async (generation) => {
    const response = await request("get", "/api/auth/me", undefined, generation); owner(generation);
    const actual = response?.data;
    if (response?.status !== 200 || actual?.id !== actor.id || actual?.role !== actor.role ||
      (actor.role === "restaurant" && actual.restaurant_id !== actor.restaurant_id) ||
      (actor.role === "driver" && actual.driver_id !== actor.driver_id) || actual.account_disabled === true || actual.is_disabled === true) fail("SESSION_CHANGED", "Contul autentificat s-a schimbat. Nu s-a retrimis intenția.");
  };
  const takeReceipt = (response, generation) => {
    owner(generation);
    if (![200, 202, 409, 404].includes(response?.status)) fail("INVALID_RECEIPT", "Serverul nu a confirmat operația.");
    const receipt = validateReceipt(response.data, record.command);
    if ((reportApplied(receipt) && response.status !== 200) || (receipt.state === "pending" && response.status !== 202) ||
      (receipt.state === "rejected" && response.status !== rejectedStatuses[receipt.error_code])) fail("INVALID_RECEIPT", "Starea operației este inconsistentă.");
    persist({ ...record, receipt }); return copy(receipt);
  };
  const receiptRequest = async (method, path, data, generation) => {
    let response;
    try { response = await request(method, path, data, generation); }
    catch (error) {
      owner(generation);
      if (error?.response?.data?.state === "rejected") response = error.response;
      else throw error;
    }
    return takeReceipt(response, generation);
  };
  const run = async (action) => {
    owner(); if (blocked) fail("STORAGE_UNAVAILABLE", "Intenția salvată necesită verificare.");
    if (busy) return null;
    busy = true; const generation = epoch;
    try { await verify(generation); owner(generation); return await action(generation); } finally { busy = false; }
  };
  return {
    activate: () => { suspended = false; load(); notify(); },
    snapshot: () => copy(record), blocked: () => blocked,
    suspend: () => { epoch++; suspended = true; for (const request of requests) request.abort(); },
    revalidate: async () => { const generation = epoch; suspended = false; try { await verify(generation); owner(generation); load(); notify(); return true; } catch (error) { suspended = true; throw error; } },
    capability: (kind, resourceId) => run(async (generation) => {
      const response = await request("get", reportPaths({ operation_type: kind, resource_id: resourceId }).capability, undefined, generation); owner(generation);
      if (response?.status !== 200 || typeof response.data?.[kind === "close_day" ? "close_day_enabled" : "incident_reporting_enabled"] !== "boolean") fail("INVALID_CAPABILITY", "Disponibilitatea operației nu poate fi verificată.");
      return response.data[kind === "close_day" ? "close_day_enabled" : "incident_reporting_enabled"];
    }),
    submit: (input) => run(async (generation) => {
      if (record && !reportTerminal(record.receipt)) fail("PENDING_INTENT", "Recuperează intenția existentă înaintea unei operații noi.");
      const command = { ...input, client_operation_id: crypto.randomUUID() };
      if (!validCommand(command)) fail("INVALID_REQUEST", "Completează datele raportării.");
      if (command.operation_type === "close_day" && actor.role === "restaurant" && command.resource_id !== actor.restaurant_id) fail("INVALID_REQUEST", "Restaurant invalid.");
      const enabled = await request("get", reportPaths(command).capability, undefined, generation); owner(generation);
      if (enabled?.status !== 200 || enabled.data?.[command.operation_type === "close_day" ? "close_day_enabled" : "incident_reporting_enabled"] !== true) fail("NOT_ENABLED", "Operația nu este activată. Intenția nu a fost trimisă.");
      persist({ schema: 1, actor_id: actor.id, role: actor.role, scope, command, receipt: null });
      return receiptRequest(command.operation_type === "close_day" ? "patch" : "post", reportPaths(command).base, body(command), generation);
    }),
    recover: (retryUnadmitted = false) => run(async (generation) => {
      if (!record) return null;
      const paths = reportPaths(record.command);
      let receipt;
      try { receipt = await receiptRequest("get", paths.lookup, undefined, generation); }
      catch (error) {
        owner(generation);
        if (error.response?.status !== 404 || error.response?.data?.state === "rejected") throw error;
        if (!retryUnadmitted) fail("NOT_ADMITTED", "Intenția nu a fost admisă. Poți retrimite explicit aceeași intenție.");
        return receiptRequest(record.command.operation_type === "close_day" ? "patch" : "post", paths.base, body(record.command), generation);
      }
      if (receipt.state === "pending") return receiptRequest("post", paths.resume, undefined, generation);
      return receipt;
    }),
    acknowledge: () => { owner(); if (record && !reportTerminal(record.receipt)) fail("PENDING_INTENT", "Operația este încă neconfirmată.");
      try { storage.removeItem(key); if (storage.getItem(key) !== null) throw Error("READBACK"); } catch { fail("STORAGE_UNAVAILABLE", "Confirmarea nu poate fi păstrată."); }
      record = null; notify(); },
  };
};
