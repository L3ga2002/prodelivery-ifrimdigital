import { useEffect, useMemo, useRef, useState } from "react";
import { createRecoveryTransport } from "../lib/recoveryTransport";
import { buildFinancialCreateDraft, canonical, canonicalApiBase, financeId, FINANCE_TIMEOUT_MS,
  validateCreatePreview, validateFinanceCapabilities, validateFinanceTariffs } from "../lib/orderFinancePreview";

export const useOrderFinancePreview = ({ actorId, apiUrl, token, role, actorRestaurantId = null,
  form, rawProducts, normalizeOrder, isOnline = true, zonePending = false, enabled = true }) => {
  const [discovery, setDiscovery] = useState(null), [version, setVersion] = useState({ tag: "", value: "" });
  const [quotation, setQuotation] = useState(null), [confirmation, setConfirmation] = useState(null);
  const [activity, setActivity] = useState(null), [refreshIndex, setRefreshIndex] = useState(0);
  const engaged = useRef(false), alive = useRef(false), requestNumber = useRef(0), latest = useRef(null), tokenRef = useRef(token);
  const workRevision = useRef({ value: null, revision: 0 });
  tokenRef.current = token;
  const tag = canonical({ actorId, apiUrl, token, role, actorRestaurantId, restaurantId: form.restaurant_id, refreshIndex });
  const tariffVersion = version.tag === tag ? version.value : "";
  let draft = null;
  try { draft = buildFinancialCreateDraft(form, rawProducts, tariffVersion, normalizeOrder); } catch { /* User may still be editing. */ }
  const workValue = canonical({ tag, form, rawProducts, tariffVersion, zonePending, enabled });
  if (workRevision.current.value !== workValue) workRevision.current = { value: workValue, revision: workRevision.current.revision + 1 };
  // Monotonic revision prevents A -> B -> A from reviving an old confirmation.
  const workTag = `${workRevision.current.revision}:${workValue}`;
  latest.current = { tag, workTag, draft, enabled, isOnline, zonePending };
  const api = useMemo(() => {
    if (!enabled || role !== "admin" || !financeId.safeParse(actorId).success) return null;
    try { return createRecoveryTransport({ apiUrl: canonicalApiBase(apiUrl), actorId, getToken: () => tokenRef.current }); }
    catch { return null; }
  }, [apiUrl, actorId, enabled, role]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; requestNumber.current++; }; }, []);
  useEffect(() => {
    let disposed = false;
    const current = () => !disposed && alive.current && latest.current.tag === tag && latest.current.enabled;
    if (!enabled || !isOnline || !form.restaurant_id || role !== "admin") return undefined;
    setDiscovery({ tag, state: "loading" });
    const load = async () => {
      try {
        if (!api) throw new Error("API_CONTEXT_INVALID");
        const query = new URLSearchParams({ restaurant_id: form.restaurant_id }).toString();
        const capability = validateFinanceCapabilities(await api.get(`/api/orders/operations/finance/capabilities?${query}`, { timeout: FINANCE_TIMEOUT_MS }), actorId, form.restaurant_id);
        if (!current()) return;
        if (capability.finance_enabled) engaged.current = true;
        if (!capability.finance_enabled) { setDiscovery({ tag, state: "ready", capability, tariffs: [] }); return; }
        const data = validateFinanceTariffs(await api.get(`/api/orders/operations/finance/tariffs?${query}`, { timeout: FINANCE_TIMEOUT_MS }), actorId, form.restaurant_id);
        if (current()) setDiscovery({ tag, state: "ready", capability, tariffs: data.tariffs });
      } catch { if (current()) setDiscovery({ tag, state: "unavailable", error: "Disponibilitatea financiară nu poate fi verificată. Reîncearcă; datele nu au fost trimise." }); }
    };
    void load(); return () => { disposed = true; };
  }, [tag, api, actorId, form.restaurant_id, role, enabled, isOnline]);
  const currentDiscovery = discovery?.tag === tag ? discovery : null;
  const capability = currentDiscovery?.capability ?? null;
  const mode = engaged.current || capability?.finance_enabled ? "financial"
    : currentDiscovery?.state === "ready" && capability.finance_enabled === false ? "legacy" : "unknown";
  const ready = currentDiscovery?.state === "ready" && capability?.create_quote_enabled === true;
  const quote = quotation?.tag === workTag && !zonePending ? quotation.preview : null;
  const confirmed = Boolean(quote && confirmation?.tag === workTag && confirmation.fingerprint === quote.quote_fingerprint);
  const requestQuote = async () => {
    const captured = latest.current, number = ++requestNumber.current;
    const current = () => alive.current && latest.current.workTag === captured.workTag && latest.current.enabled && number === requestNumber.current;
    setConfirmation(null); setQuotation(null);
    if (!ready || !captured.isOnline || captured.zonePending || !captured.draft || !api) {
      setActivity({ tag: captured.workTag, state: "error", error: "Verifică datele, suma exactă, grila aleasă și locația înainte de cotație." }); return null;
    }
    engaged.current = true; setActivity({ tag: captured.workTag, state: "loading" });
    try {
      const response = await api.post("/api/orders/operations/finance/quote/create", captured.draft, { timeout: FINANCE_TIMEOUT_MS });
      if (!current()) return null;
      const preview = validateCreatePreview(response, actorId, captured.draft);
      setQuotation({ tag: captured.workTag, draft: captured.draft, preview }); setActivity({ tag: captured.workTag, state: "ready" });
      return preview;
    } catch { if (current()) setActivity({ tag: captured.workTag, state: "error", error: "Cotația nu poate fi confirmată. Verifică datele și solicită din nou." }); return null; }
  };
  const reset = () => { requestNumber.current++; engaged.current = false; setQuotation(null); setConfirmation(null); setActivity(null); setVersion({ tag: "", value: "" }); };
  return { mode, capability, tariffs: currentDiscovery?.tariffs || [], tariffVersion,
    setTariffVersion: (value) => { if (currentDiscovery?.tariffs?.some((entry) => entry.version === value)) { engaged.current = true; setVersion({ tag, value }); setConfirmation(null); } },
    quote, confirmed, confirm: (value) => setConfirmation(value && quote ? { tag: workTag, fingerprint: quote.quote_fingerprint } : null),
    requestQuote, reset, refresh: () => { requestNumber.current++; setRefreshIndex((n) => n + 1); },
    readyToSubmit: Boolean(enabled && isOnline && ready && confirmed && draft && !zonePending),
    submission: confirmed && quotation?.tag === workTag ? { ...quotation.draft, preview: quotation.preview,
      quote_confirmation: { contract_version: 1, quote_fingerprint: quotation.preview.quote_fingerprint } } : null,
    loading: currentDiscovery?.state === "loading" || activity?.tag === workTag && activity.state === "loading",
    discoveryState: currentDiscovery?.state || (form.restaurant_id ? "loading" : "idle"),
    error: currentDiscovery?.error || (activity?.tag === workTag ? activity.error : "") || "" };
};
