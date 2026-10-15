import { useEffect, useMemo, useRef, useState } from "react";
import { createRecoveryTransport } from "../lib/recoveryTransport";
import { assertNoOriginalFinancialIntent, buildRemakeDraft, canonical, canonicalApiBase, financeId, REMAKE_TIMEOUT_MS,
  validFinancialEventActor, validFinancialEventToken, validateFinanceCapabilities, validateFinanceTariffs, validateRemakeParent, validateRemakePreview } from "../lib/orderRemakeFinance";

export const useOrderRemakeFinancePreview = ({ actor, apiUrl, token, parentId, parentVersion, form, enabled = true, isOnline = true }) => {
  const [discovery, setDiscovery] = useState(null), [selection, setSelection] = useState(null), [quotation, setQuotation] = useState(null);
  const [confirmation, setConfirmation] = useState(null), [activity, setActivity] = useState(null), [refreshIndex, setRefreshIndex] = useState(0);
  const latest = useRef(null), alive = useRef(false), number = useRef(0), revision = useRef({ value: null, count: 0 });
  const tokenRef = useRef(token); tokenRef.current = token;
  const tag = canonical({ actorId: actor?.id, role: actor?.role, restaurantId: actor?.restaurant_id, apiUrl, token, parentId, parentVersion, enabled, refreshIndex, disabled: actor?.is_disabled, accountDisabled: actor?.account_disabled });
  const data = discovery?.tag === tag ? discovery : null;
  const tariffVersion = selection?.tag === tag ? selection.value : "";
  let draft = null, draftError = "";
  try { draft = buildRemakeDraft(data?.context, form, tariffVersion); } catch (error) { draftError = error.message; }
  const work = canonical({ tag, form, tariffVersion, context: data?.context ?? null, enabled });
  if (revision.current.value !== work) revision.current = { value: work, count: revision.current.count + 1 };
  const workTag = `${revision.current.count}:${work}`;
  latest.current = { tag, workTag, draft, enabled, isOnline };
  const api = useMemo(() => {
    if (!enabled || actor?.role !== "restaurant" || !validFinancialEventActor(actor) || !validFinancialEventToken(token)) return null;
    try { return createRecoveryTransport({ apiUrl: canonicalApiBase(apiUrl), actorId: actor.id, getToken: () => tokenRef.current }); } catch { return null; }
  }, [apiUrl, actor?.id, actor?.role, actor?.restaurant_id, actor?.is_disabled, actor?.account_disabled, token, enabled]);
  useEffect(() => { alive.current = true; return () => { alive.current = false; number.current++; }; }, []);
  useEffect(() => {
    let disposed = false;
    const current = () => !disposed && alive.current && latest.current.tag === tag && latest.current.enabled;
    if (!enabled || !isOnline || !api || !financeId.safeParse(parentId).success) return undefined;
    setDiscovery({ tag, state: "loading" });
    const load = async () => {
      try {
        assertNoOriginalFinancialIntent(window.localStorage, actor, parentId);
        const context = validateRemakeParent(await api.get(`/api/orders/operations/finance/remake-parent/${encodeURIComponent(parentId)}`, { timeout: REMAKE_TIMEOUT_MS }), actor, parentId);
        if (!current()) return;
        assertNoOriginalFinancialIntent(window.localStorage, actor, parentId);
        const query = new URLSearchParams({ restaurant_id: actor.restaurant_id });
        const capability = validateFinanceCapabilities(await api.get(`/api/orders/operations/finance/capabilities?${query}`, { timeout: REMAKE_TIMEOUT_MS }), actor.id, actor.restaurant_id);
        if (!current()) return;
        assertNoOriginalFinancialIntent(window.localStorage, actor, parentId);
        if (!context.eligibility.can_preview || !capability.remake_quote_enabled) { setDiscovery({ tag, state: "blocked", context, capability, tariffs: [] }); return; }
        const tariffs = validateFinanceTariffs(await api.get(`/api/orders/operations/finance/tariffs?${query}`, { timeout: REMAKE_TIMEOUT_MS }), actor.id, actor.restaurant_id).tariffs;
        if (current()) { assertNoOriginalFinancialIntent(window.localStorage, actor, parentId); setDiscovery({ tag, state: "ready", context, capability, tariffs }); }
      } catch { if (current()) setDiscovery({ tag, state: "error", error: "Originalul sau disponibilitatea financiară nu poate fi verificată. Reia verificarea." }); }
    };
    void load(); return () => { disposed = true; };
  }, [tag, api, actor?.id, actor?.role, actor?.restaurant_id, parentId, enabled, isOnline]);
  const selected = data?.tariffs?.find((entry) => entry.version === tariffVersion && entry.zone_ids.includes(data.context.parent.delivery_zone_id));
  const quote = quotation?.tag === workTag ? quotation.preview : null;
  const confirmed = Boolean(quote && confirmation?.tag === workTag && confirmation.fingerprint === quote.quote_fingerprint);
  const requestQuote = async () => {
    const captured = latest.current, serial = ++number.current;
    const current = () => alive.current && latest.current.enabled && latest.current.workTag === captured.workTag && serial === number.current;
    setQuotation(null); setConfirmation(null);
    if (!captured.enabled || !captured.isOnline || !captured.draft || data?.state !== "ready" || !selected || !api) {
      setActivity({ tag: captured.workTag, error: draftError || "Completează datele și alege grila înaintea cotației." }); return null;
    }
    setActivity({ tag: captured.workTag, loading: true });
    try {
      assertNoOriginalFinancialIntent(window.localStorage, actor, parentId);
      const response = await api.post(`/api/orders/operations/finance/quote/remake/${encodeURIComponent(parentId)}`, captured.draft, { timeout: REMAKE_TIMEOUT_MS });
      if (!current()) return null;
      assertNoOriginalFinancialIntent(window.localStorage, actor, parentId);
      const preview = validateRemakePreview(response, actor.id, actor.restaurant_id, parentId, captured.draft);
      setQuotation({ tag: captured.workTag, draft: captured.draft, context: data.context, preview });
      setActivity({ tag: captured.workTag }); return preview;
    } catch { if (current()) setActivity({ tag: captured.workTag, error: "Cotația nu poate fi confirmată. Reîncarcă originalul și cere o cotație nouă." }); return null; }
  };
  return { context: data?.context ?? null, tariffs: data?.tariffs || [], tariffVersion, quote, confirmed,
    setTariffVersion: (value) => { if (data?.tariffs?.some((entry) => entry.version === value)) { setSelection({ tag, value }); setConfirmation(null); } },
    confirm: (checked) => setConfirmation(checked && quote ? { tag: workTag, fingerprint: quote.quote_fingerprint } : null), requestQuote,
    refresh: () => { number.current++; setRefreshIndex((n) => n + 1); },
    readyToQuote: Boolean(enabled && isOnline && data?.state === "ready" && draft && selected),
    readyToSubmit: Boolean(enabled && isOnline && data?.state === "ready" && confirmed && draft && selected),
    submission: confirmed && quotation?.tag === workTag ? { parent_context: quotation.context, draft: quotation.draft, preview: quotation.preview,
      quote_confirmation: { contract_version: 1, quote_fingerprint: quotation.preview.quote_fingerprint } } : null,
    state: data?.state || (enabled ? "loading" : "idle"),
    loading: data?.state === "loading" || activity?.tag === workTag && activity.loading === true,
    error: data?.error || (data?.state === "blocked" ? "Refacerea nu este disponibilă pentru starea actuală a originalului." : "")
      || (data?.context && !data.context.parent.delivery_zone_id ? "Zona originalului nu este verificată. Refacerea financiară este blocată." : "")
      || (activity?.tag === workTag ? activity.error : "") || "" };
};
