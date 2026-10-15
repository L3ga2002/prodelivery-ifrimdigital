import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { MAX_READ_CURSORS, ORDER_READ_TIMEOUT_MS, normalizeReadFilters, orderReadError, parseOrderDetail, parseOrderPage, validReadActor } from "../lib/orderReads";

// The render-time epoch also fences responses in the gap before effect cleanup.
const useBoundedRead = (context, request, parse, scope) => {
  const { actorId, role, token, apiUrl, isOnline = true } = context;
  const session = useMemo(() => ({ actorId, token, apiUrl, transport: axios.create({ withCredentials: true }) }), [actorId, token, apiUrl]);
  const transport = session.transport;
  const epoch = useMemo(() => ({ scope, isOnline, actorId, role, token, apiUrl }), [scope, isOnline, actorId, role, token, apiUrl]);
  const current = useRef(epoch);
  current.current = epoch;
  const [state, setState] = useState(null);
  useEffect(() => {
    let alive = true;
    const controller = new AbortController();
    const owns = () => alive && current.current === epoch;
    if (!isOnline || !validReadActor(actorId) || typeof apiUrl !== "string" ||
      (token != null && typeof token !== "string") || request.error) {
      setState({ epoch, phase: !isOnline ? "offline" : "error", data: null,
        error: request.error || "Sesiune de citire indisponibila." });
      return () => { alive = false; controller.abort(); };
    }
    setState({ epoch, phase: "loading", data: null, error: "" });
    const timer = setTimeout(() => {
      if (!owns()) return;
      alive = false; controller.abort();
      setState({ epoch, phase: "error", data: null, error: "Citirea a depasit 15 secunde. Reincarca manual." });
    }, ORDER_READ_TIMEOUT_MS);
    const hide = () => {
      if (!owns()) return;
      alive = false; clearTimeout(timer); controller.abort();
      setState({ epoch, phase: "error", data: null, error: "Sesiunea de citire trebuie reverificata. Reincarca manual." });
    };
    window.addEventListener("pagehide", hide);
    const headers = { "X-Expected-Actor-ID": actorId, ...(token ? { Authorization: `Bearer ${token}` } : {}) };
    Promise.resolve().then(() => {
      if (!owns()) return null;
      return transport.get(`${apiUrl.replace(/\/$/, "")}${request.path}`, {
        params: request.params, headers, timeout: ORDER_READ_TIMEOUT_MS, signal: controller.signal,
      });
    }).then((response) => {
      if (!owns()) return;
      const data = parse(response?.data);
      if (owns()) setState({ epoch, phase: "ready", data, error: "" });
    }).catch((error) => {
      if (owns()) setState({ epoch, phase: "error", data: null, error: orderReadError(error) });
    }).finally(() => clearTimeout(timer));
    return () => { window.removeEventListener("pagehide", hide); alive = false; clearTimeout(timer); controller.abort(); };
  }, [epoch, isOnline, actorId, token, apiUrl, request, parse, transport]);
  return state?.epoch === epoch ? state : { phase: !isOnline ? "offline" : "loading", data: null, error: "" };
};

const useCursorNavigation = (scope) => {
  const [navigation, setNavigation] = useState(null);
  const [reload, setReload] = useState(0);
  const current = useRef(scope), moving = useRef(false);
  if (current.current !== scope) { current.current = scope; moving.current = false; }
  const cursors = navigation?.scope === scope ? navigation.cursors : [null];
  const offset = navigation?.scope === scope ? navigation.offset : 0;
  const anchor = cursors[cursors.length - 1];
  const readScope = useMemo(() => ({ scope, anchor, reload }), [scope, anchor, reload]);
  useEffect(() => { moving.current = false; }, [readScope]);
  const move = (next) => {
    if (current.current !== scope || moving.current) return false;
    moving.current = true;
    const extra = next.length > MAX_READ_CURSORS ? 1 : 0;
    setNavigation({ scope, cursors: next.slice(-MAX_READ_CURSORS), offset: offset + extra });
    return true;
  };
  const next = (value) => value !== null && !cursors.includes(value) && move([...cursors, value]);
  const previous = () => cursors.length > 1 && move(cursors.slice(0, -1));
  const refresh = useCallback(() => {
    if (current.current !== scope) return;
    moving.current = true;
    setNavigation(null); setReload((n) => n + 1);
  }, [scope]);
  return { anchor, readScope, next, previous, refresh, canPrevious: cursors.length > 1,
    page: offset + cursors.length, repeated: (value) => value !== null && cursors.includes(value) };
};

export const useOrderReads = (context, filters = {}, reloadKey = 0) => {
  const { view, status, restaurant_id, driver_id, from_date, to_date, limit } = filters;
  const normalized = useMemo(() => {
    try { return { params: normalizeReadFilters({ view, status, restaurant_id, driver_id, from_date, to_date, limit }), error: "" }; }
    catch (error) { return { params: null, error: error.message }; }
  }, [view, status, restaurant_id, driver_id, from_date, to_date, limit]);
  const { actorId, role, token, apiUrl } = context;
  const scope = useMemo(() => ({ actorId, role, token, apiUrl, normalized, reloadKey }), [actorId, role, token, apiUrl, normalized, reloadKey]);
  const nav = useCursorNavigation(scope);
  const request = useMemo(() => ({ path: "/api/orders/read/page", error: normalized.error,
    params: { ...normalized.params, ...(nav.anchor !== null ? { cursor: nav.anchor } : {}) } }), [normalized, nav.anchor]);
  const parse = useCallback((data) => parseOrderPage(data, normalized.params?.limit), [normalized]);
  const [pollRevision, setPollRevision] = useState(0);
  const lastPoll = useRef(context.pollKey);
  const pageScope = useMemo(() => ({ navigation: nav.readScope, pollRevision }), [nav.readScope, pollRevision]);
  const read = useBoundedRead(context, request, parse, pageScope);
  const { pollKey, isOnline } = context;
  useEffect(() => {
    if (lastPoll.current === pollKey) return;
    lastPoll.current = pollKey;
    // A successful parent poll revalidates this anchor once; slow/failed reads wait for manual refresh.
    if (isOnline === false || read.phase !== "ready" || normalized.error) return;
    setPollRevision((value) => value + 1);
  }, [pollKey, isOnline, read.phase, normalized.error]);
  const repeated = nav.repeated(read.data?.next_cursor ?? null);
  return { ...read, ...nav, items: read.data?.items || [], warnings: read.data?.data_warnings || [],
    canNext: read.phase === "ready" && read.data.has_more && !repeated,
    cursorError: repeated ? "Cursor repetat. Reincarca prima pagina." : "",
    next: () => read.phase === "ready" && context.isOnline !== false && nav.next(read.data.next_cursor),
    previous: () => read.phase === "ready" && context.isOnline !== false && nav.previous() };
};

export const useOrderReadDetail = (context, orderId, reloadKey = 0) => {
  const { actorId, role, token, apiUrl } = context;
  const scope = useMemo(() => ({ actorId, role, token, apiUrl, orderId, reloadKey }), [actorId, role, token, apiUrl, orderId, reloadKey]);
  const nav = useCursorNavigation(scope);
  const request = useMemo(() => {
    const valid = validReadActor(orderId);
    return { path: valid ? `/api/orders/read/detail/${encodeURIComponent(orderId)}` : "",
      error: valid ? "" : "Identificatorul comenzii este invalid.",
      params: { history_limit: 25, ...(nav.anchor !== null ? { history_before: nav.anchor } : {}) } };
  }, [orderId, nav.anchor]);
  const parse = useCallback((data) => parseOrderDetail(data, orderId, nav.anchor), [orderId, nav.anchor]);
  const read = useBoundedRead(context, request, parse, nav.readScope);
  return { ...read, ...nav, warnings: read.data?.data_warnings || [],
    canNext: read.phase === "ready" && read.data.history_has_more,
    next: () => read.phase === "ready" && context.isOnline !== false && nav.next(read.data.next_history_before),
    previous: () => read.phase === "ready" && context.isOnline !== false && nav.previous() };
};
