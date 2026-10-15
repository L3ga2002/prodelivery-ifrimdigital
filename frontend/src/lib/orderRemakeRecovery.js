import { z } from "zod";
import { assertNoOriginalFinancialIntent, canonical, canonicalApiBase, financeId, operationIdSchema, parentContextSchema,
  quoteConfirmationSchema, remakeApplied, remakeDraftSchema, remakeFail, RemakeError, remakePreviewSchema, remakeReceiptSchema,
  REMAKE_PROTOCOL, REMAKE_TIMEOUT_MS, remakeTerminal, safeVersion, semanticRemakeReceipt, storedRemakeReceipt,
  validFinancialEventActor, validateFinanceCapabilities, validateRemakeParent, validateRemakePreview, validateRemakeReadback, validateRemakeReceipt } from "./orderRemakeFinance";

const bindingShape = { version: z.literal(2), protocol: z.literal(REMAKE_PROTOCOL), api_base: z.string().min(1).max(2048),
  actor_id: financeId, actor_role: z.literal("restaurant"), actor_restaurant_id: financeId, restaurant_id: financeId,
  parent_id: financeId, expected_order_version: safeVersion, client_operation_id: operationIdSchema, created_at: safeVersion,
  quote_confirmation: quoteConfirmationSchema };
const recordSchema = z.object({ ...bindingShape, receipt: remakeReceiptSchema.nullable() }).strict();
const commandSchema = z.object({ client_operation_id: operationIdSchema, quote_confirmation: quoteConfirmationSchema,
  // Draft parsing below owns the business policy; this object preserves exact wire keys.
  expected_order_version: safeVersion, problem_type: z.enum(["missing_product", "new_product"]), description: z.string(),
  items: z.array(z.unknown()), payment_type: z.enum(["CASH", "CARD"]), collection_basis: z.enum(["new_receipt", "prepaid_new_order"]),
  client_collection_bani: z.number(), advance_required_bani: z.number(), financial: z.unknown() }).strict();
const savedSchema = z.object({ ...bindingShape, command: commandSchema, preview: remakePreviewSchema, parent_context: parentContextSchema }).strict();
const binding = (record) => canonical(Object.fromEntries(Object.keys(bindingShape).map((name) => [name, record[name]])));
const bytes = (raw) => unescape(encodeURIComponent(raw)).length;
const withoutIdentity = ({ client_operation_id, quote_confirmation, ...draft }) => draft;
const message = "Rezultatul refacerii nu este confirmat. Verifică aceeași încercare; identitatea rămâne păstrată.";

export const createOrderRemakeRecovery = ({ actor, apiBase, api, durableStorage, draftStorage, locks, crypto,
  isOnline = () => true, isOwnerActive = () => true, refreshList = async () => false }) => {
  if (actor?.role !== "restaurant" || !validFinancialEventActor(actor)
    || canonicalApiBase(apiBase) !== apiBase) remakeFail("AUTH_REQUIRED", "Autentifică-te cu contul restaurantului.");
  const scope = { ...actor }, key = `prodelivery:order-remake:v2:${encodeURIComponent(actor.id)}`;
  const draftKey = (id) => `${key}:draft:${id}`;
  const base = (r) => `/api/orders/operations/finance/remake/${encodeURIComponent(r.parent_id)}`;
  const lookup = (r) => `${base(r)}/${encodeURIComponent(r.client_operation_id)}`;
  let active = true, epoch = 0, generation = 0, working = false, poisoned = false;
  const ownedDrafts = new Set(), requests = new Set();
  const owner = (captured = epoch, restoring = false) => {
    if (captured !== epoch || !isOwnerActive() || (!restoring && !active)) remakeFail("SESSION_CHANGED", "Sesiunea s-a schimbat. Încercarea este păstrată.");
  };
  const storageError = () => { poisoned = true; remakeFail("STORAGE_UNAVAILABLE", "Încercarea salvată nu poate fi verificată. O refacere nouă este blocată."); };
  const requireContext = (r) => {
    if (r.api_base !== apiBase || r.actor_id !== scope.id || r.actor_role !== scope.role || r.actor_restaurant_id !== scope.restaurant_id
      || r.restaurant_id !== scope.restaurant_id) remakeFail("FINANCIAL_CONTEXT_CHANGED", "Revino la contul, restaurantul și serverul inițial pentru verificare.");
  };
  const read = () => {
    let raw, parsed;
    try {
      raw = durableStorage.getItem(key); if (raw === null) return null;
      if (raw.length > 8192 || bytes(raw) > 8192) storageError();
      parsed = recordSchema.safeParse(JSON.parse(raw));
    } catch { storageError(); }
    if (!parsed.success || parsed.data.actor_id !== scope.id || canonicalApiBase(parsed.data.api_base) !== parsed.data.api_base) storageError();
    const r = parsed.data;
    if (r.expected_order_version >= Number.MAX_SAFE_INTEGER || r.actor_restaurant_id !== r.restaurant_id) storageError();
    if (r.receipt) { try { storedRemakeReceipt(r.receipt, r); } catch { storageError(); } }
    return r;
  };
  const lease = (record, captured = epoch) => { requireContext(record); return { epoch: captured, generation, binding: binding(record), id: record.client_operation_id }; };
  const current = (proof, restoring = false) => {
    owner(proof.epoch, restoring);
    if (proof.generation !== generation) remakeFail("INTENT_CHANGED");
    const r = read();
    if (!r || binding(r) !== proof.binding) remakeFail("INTENT_CHANGED");
    requireContext(r); return r;
  };
  const write = (r, captured) => {
    owner(captured); const raw = JSON.stringify(r);
    if (bytes(raw) > 8192) storageError();
    try { durableStorage.setItem(key, raw); if (durableStorage.getItem(key) !== raw) storageError(); } catch { storageError(); }
  };
  const saved = (r) => {
    requireContext(r); let raw, parsed;
    try {
      raw = draftStorage.getItem(draftKey(r.client_operation_id)); if (raw === null) return null;
      if (raw.length > 98304 || bytes(raw) > 98304) storageError();
      parsed = savedSchema.safeParse(JSON.parse(raw));
    } catch { storageError(); }
    if (!parsed.success) storageError();
    const value = parsed.data;
    if (binding(value) !== binding(r) || bytes(JSON.stringify(value.command)) > 65536
      || value.command.client_operation_id !== r.client_operation_id
      || canonical(value.command.quote_confirmation) !== canonical(r.quote_confirmation)
      || value.command.expected_order_version !== r.expected_order_version) storageError();
    try {
      validateRemakeParent({ status: 200, data: value.parent_context }, scope, r.parent_id);
      if (value.parent_context.parent.order_version !== r.expected_order_version || !value.parent_context.eligibility.can_preview) storageError();
      validateRemakePreview({ status: 200, data: value.preview }, scope.id, r.restaurant_id, r.parent_id, withoutIdentity(value.command));
      if (value.preview.quote_fingerprint !== r.quote_confirmation.quote_fingerprint) storageError();
    } catch { storageError(); }
    // Keep the persisted key order so an explicit resend uses the original wire bytes.
    ownedDrafts.add(r.client_operation_id); return { ...value, command: JSON.parse(raw).command };
  };
  const removeDraft = (id) => {
    try { draftStorage.removeItem(draftKey(id)); if (draftStorage.getItem(draftKey(id)) !== null) storageError(); ownedDrafts.delete(id); }
    catch { storageError(); }
  };
  const request = async (method, path, body, check) => {
    check(); if (!isOnline()) remakeFail("OFFLINE", "Fără internet. Încercarea este păstrată.");
    const abort = new AbortController(); requests.add(abort); let timer;
    try {
      const config = { timeout: REMAKE_TIMEOUT_MS, signal: abort.signal };
      const pending = method === "get" ? api.get(path, config) : api.post(path, body, config);
      const result = await Promise.race([pending, new Promise((_, reject) => { timer = setTimeout(() => {
        abort.abort(); reject(new RemakeError("RECOVERY_UNAVAILABLE", message)); }, REMAKE_TIMEOUT_MS); })]);
      check(); return result;
    } catch (error) {
      check();
      if (error?.response?.data?.state === "rejected") return error.response;
      if (error instanceof RemakeError) throw error;
      remakeFail(error?.response?.status === 401 ? "AUTH_REQUIRED" : error?.response?.status === 403 ? "NOT_AUTHORIZED"
        : error?.response?.status === 404 && error?.response?.data?.detail?.code === "OPERATION_NOT_FOUND" ? "OPERATION_NOT_FOUND" : "RECOVERY_UNAVAILABLE", message);
    } finally { clearTimeout(timer); requests.delete(abort); }
  };
  const publish = (proof, receipt) => {
    const r = current(proof);
    if (remakeTerminal(r.receipt) && semanticRemakeReceipt(r.receipt) !== semanticRemakeReceipt(receipt)) remakeFail("OPERATION_UNCERTAIN");
    write({ ...r, receipt }, proof.epoch); current(proof); return receipt;
  };
  const getReceipt = async (r, proof, restoring = false) => validateRemakeReceipt(
    await request("get", lookup(r), undefined, () => current(proof, restoring)), r);
  const send = async (r, value, proof) => publish(proof, validateRemakeReceipt(await request("post", base(r),
    JSON.parse(JSON.stringify(value.command)), () => current(proof)), r));
  const exclusive = async (action) => {
    const captured = epoch; owner(captured);
    if (poisoned) storageError();
    if (working) remakeFail("BUSY", "O verificare este deja în curs.");
    if (typeof locks?.request !== "function") remakeFail("LOCK_UNAVAILABLE", "Browserul nu poate proteja această încercare între file.");
    working = true;
    try {
      return await locks.request(key, { mode: "exclusive", ifAvailable: true }, async (lock) => {
        owner(captured); if (!lock) remakeFail("BUSY", "Această încercare este verificată în altă filă.");
        return action(captured);
      });
    } catch (error) { if (error instanceof RemakeError) throw error; remakeFail("RECOVERY_UNAVAILABLE", message); }
    finally { working = false; }
  };
  const captureIntent = () => { owner(); const r = read(); return r ? lease(r) : { epoch, generation, binding: null, id: null }; };
  const isCurrentIntent = (proof, acknowledged = false) => {
    try { owner(proof.epoch); const r = read(); if (r) requireContext(r);
      return acknowledged ? generation === proof.generation + 1 && r === null
        : generation === proof.generation && (r ? binding(r) : null) === proof.binding;
    } catch { return false; }
  };
  return {
    key, snapshot: read, storageBlocked: () => poisoned, captureIntent, isCurrentIntent,
    savedDraft: () => { owner(); const r = read(); return r ? saved(r) : null; },
    activate: () => { active = true; },
    deactivate: ({ preserveDraft = false } = {}) => { active = false; epoch++; requests.forEach((r) => r.abort()); if (!preserveDraft) [...ownedDrafts].forEach(removeDraft); },
    observeStorage: (event) => { owner(); if (event?.key !== key && event?.key !== null) return false; generation++; read(); return true; },
    rememberStorage: (event) => { owner(epoch, true); if (event?.key === key || event?.key === null) generation++; },
    restoreSession: async () => {
      const captured = epoch; owner(captured, true); const r = read();
      if (r) { const proof = lease(r, captured);
        try { await getReceipt(r, proof, true); } catch (error) { current(proof, true); if (error.code !== "OPERATION_NOT_FOUND") throw error; }
        current(proof, true);
      } else {
        const response = await request("get", `/api/orders/operations/finance/capabilities?${new URLSearchParams({ restaurant_id: scope.restaurant_id })}`, undefined, () => owner(captured, true));
        validateFinanceCapabilities(response, scope.id, scope.restaurant_id);
      }
      owner(captured, true); active = true;
    },
    capability: async () => {
      const captured = epoch; const r = read(); if (r) requireContext(r);
      const response = await request("get", `/api/orders/operations/finance/capabilities?${new URLSearchParams({ restaurant_id: scope.restaurant_id })}`, undefined, () => owner(captured));
      return validateFinanceCapabilities(response, scope.id, scope.restaurant_id).remake_quote_enabled;
    },
    submit: (input) => exclusive(async (captured) => {
      if (read()) remakeFail("INTENT_PENDING", "Verifică refacerea păstrată înaintea unei încercări noi.");
      const parsed = z.object({ parent_context: parentContextSchema, draft: remakeDraftSchema, preview: remakePreviewSchema, quote_confirmation: quoteConfirmationSchema }).strict().safeParse(input);
      if (!parsed.success) remakeFail("INVALID_REMAKE_DRAFT", "Confirmă o cotație pentru datele curente.");
      const value = parsed.data, parentId = value.parent_context.parent.order_id;
      validateRemakeParent({ status: 200, data: value.parent_context }, scope, parentId);
      if (!value.parent_context.eligibility.can_preview || value.parent_context.parent.order_version !== value.draft.expected_order_version
        || value.parent_context.parent.delivery_zone_id !== value.draft.financial.zone_id) remakeFail("INVALID_REMAKE_DRAFT");
      validateRemakePreview({ status: 200, data: value.preview }, scope.id, scope.restaurant_id, parentId, value.draft);
      if (value.preview.quote_fingerprint !== value.quote_confirmation.quote_fingerprint) remakeFail("INVALID_REMAKE_DRAFT");
      assertNoOriginalFinancialIntent(durableStorage, scope, parentId);
      if (!isOnline()) remakeFail("OFFLINE", "Fără internet. Refacerea nu a fost trimisă.");
      let id; try { id = crypto.randomUUID(); } catch { remakeFail("ID_UNAVAILABLE"); }
      if (!operationIdSchema.safeParse(id).success) remakeFail("ID_UNAVAILABLE");
      const r = { version: 2, protocol: REMAKE_PROTOCOL, api_base: apiBase, actor_id: scope.id, actor_role: scope.role,
        actor_restaurant_id: scope.restaurant_id, restaurant_id: scope.restaurant_id, parent_id: parentId,
        expected_order_version: value.draft.expected_order_version, client_operation_id: id, created_at: Date.now(),
        quote_confirmation: value.quote_confirmation, receipt: null };
      const { receipt, ...bound } = r;
      const privateValue = { ...bound, command: { client_operation_id: id, ...value.draft, quote_confirmation: value.quote_confirmation },
        preview: value.preview, parent_context: value.parent_context };
      const raw = JSON.stringify(privateValue);
      if (bytes(raw) > 98304 || bytes(JSON.stringify(privateValue.command)) > 65536) storageError();
      try { if (draftStorage.getItem(draftKey(id)) !== null) storageError(); draftStorage.setItem(draftKey(id), raw);
        if (draftStorage.getItem(draftKey(id)) !== raw) storageError(); } catch { storageError(); }
      ownedDrafts.add(id);
      write(r, captured); generation++;
      const proof = lease(r, captured); current(proof); saved(r);
      assertNoOriginalFinancialIntent(durableStorage, scope, parentId);
      return send(r, privateValue, proof);
    }),
    recover: () => exclusive(async (captured) => { const r = read(); if (!r) return null; const proof = lease(r, captured); return publish(proof, await getReceipt(r, proof)); }),
    retrySubmission: () => exclusive(async (captured) => {
      const r = read(); if (!r || remakeTerminal(r.receipt)) remakeFail("OPERATION_UNCERTAIN");
      const proof = lease(r, captured), value = saved(r); if (!value) remakeFail("DRAFT_UNAVAILABLE", "Datele private lipsesc. Verifică rezultatul sau închide identitatea păstrată.");
      assertNoOriginalFinancialIntent(durableStorage, scope, r.parent_id); return send(r, value, proof);
    }),
    resume: () => exclusive(async (captured) => {
      const r = read(); if (!r || r.receipt?.state !== "pending") remakeFail("OPERATION_UNCERTAIN"); const proof = lease(r, captured);
      return publish(proof, validateRemakeReceipt(await request("post", `${lookup(r)}/resume`, undefined, () => current(proof)), r));
    }),
    closeIntent: () => exclusive(async (captured) => {
      const r = read(); if (!r) remakeFail("OPERATION_UNCERTAIN"); const proof = lease(r, captured);
      return publish(proof, validateRemakeReceipt(await request("post", `${lookup(r)}/close`, { restaurant_id: r.restaurant_id,
        expected_order_version: r.expected_order_version, quote_confirmation: r.quote_confirmation }, () => current(proof)), r));
    }),
    acknowledge: () => exclusive(async (captured) => {
      const r = read(); if (!r || !remakeTerminal(r.receipt)) remakeFail("OPERATION_UNCERTAIN"); const proof = lease(r, captured);
      const receipt = await getReceipt(r, proof);
      if (!remakeTerminal(receipt) || semanticRemakeReceipt(receipt) !== semanticRemakeReceipt(r.receipt)) remakeFail("OPERATION_UNCERTAIN");
      if (remakeApplied(receipt)) {
        const response = await request("get", `${lookup(r)}/readback`, undefined, () => current(proof));
        validateRemakeReadback(response, r, receipt, saved(r));
      }
      current(proof);
      if (await refreshList({ isCurrent: () => isCurrentIntent(proof), receipt, record: r }) !== true) remakeFail("REFRESH_UNCONFIRMED", "Lista nu a fost reîncărcată. Încercarea rămâne păstrată; reia confirmarea.");
      current(proof); removeDraft(r.client_operation_id); current(proof);
      try { durableStorage.removeItem(key); if (durableStorage.getItem(key) !== null) storageError(); } catch { storageError(); }
      generation++; return true;
    }),
  };
};
