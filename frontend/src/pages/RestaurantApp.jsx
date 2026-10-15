import { useOrderCustodyRecovery } from "../hooks/useOrderCustodyRecovery";
import { useOrderRemakeRecovery } from "../hooks/useOrderRemakeRecovery";
import { OrderRemakeRecoveryPanel } from "../components/OrderRemakeDialog";
import { pureLegacyRemake } from "../lib/orderRemakeFinance";
import { CustodyRecoveryPanel } from "../components/OrderCustody";
import { clientCollectionText, orderAmountLabel } from "../lib/orderFinance";
import { useOrderPreparationRecovery } from "../hooks/useOrderPreparationRecovery";
import { PreparationRecoveryPanel } from "../components/restaurant/PreparationRecoveryPanel";
import { preparationApplied } from "../lib/orderPreparationRecovery";
import { useRestaurantReads } from "../hooks/useRestaurantReads";
import { PREPARATION_OPTIONS_MINUTES, formatSeconds, getPreparationTimer, getPauseSeconds, defaultScheduleSettings, getStatusConfig } from "../lib/restaurantPresentation";
import { RestaurantOrderCard } from "../components/restaurant/RestaurantOrderCard";
import { RestaurantReadyDialog, RestaurantScheduleDialog, RestaurantMoreDialog, RestaurantHistoryDetailDialog, RestaurantProblemDialog, RestaurantCancelDialog } from "../components/restaurant/RestaurantDialogs";
import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useOrderStatusRecovery, OrderStatusRecoveryPanel } from "../hooks/useOrderStatusRecovery";
import { useOrderFinancialEventRecovery } from "../hooks/useOrderFinancialEventRecovery";
import { FinancialEventRecoveryPanel } from "../components/OrderFinancialActivity";
import { hasStatusRevision, canChangeOrderStatus, statusApplied } from "../lib/orderStatusRecovery";
import { useAuth } from "../context/AuthContext";
import { useOperationalReporting, OperationalReportingPanel } from "../hooks/useOperationalReporting";
import { reportApplied } from "../lib/operationalReporting";
import { OperationalIncidentReporter } from "../components/OperationalIncidentReporter";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Badge } from "../components/ui/badge";

import { Input } from "../components/ui/input";

import { RestaurantAnalyticsPanel } from "../components/admin/RestaurantAnalyticsPanel";

import { LogOut, RefreshCw, ChefHat, Bell, BarChart3, AlertTriangle, Utensils, Power, History, Search, Settings } from "lucide-react";
import { getApiErrorMessage } from "../lib/api";
import { useNetworkStatus } from "../hooks/useNetworkStatus";
import { getPreparationStatus, isNewRestaurantOrder, isShortPreparationBlocked, splitRestaurantOrders } from "../lib/orderWorkflow";

const API_URL = process.env.REACT_APP_BACKEND_URL;
const NEW_ORDER_FLASH_MS = 4000;
const TIMER_TICK_MS = 1000;
const playLatePreparationAlert = () => {
  try {
    const audioContext = new (window.AudioContext || window.webkitAudioContext)();
    const startedAt = audioContext.currentTime;
    [0, 0.45, 0.9, 1.35].forEach((offset) => {
      const osc = audioContext.createOscillator();
      const gain = audioContext.createGain();
      osc.connect(gain);
      gain.connect(audioContext.destination);
      osc.frequency.value = 620;
      osc.type = "square";
      gain.gain.setValueAtTime(0.0001, startedAt + offset);
      gain.gain.exponentialRampToValueAtTime(0.28, startedAt + offset + 0.03);
      gain.gain.exponentialRampToValueAtTime(0.0001, startedAt + offset + 0.36);
      osc.start(startedAt + offset);
      osc.stop(startedAt + offset + 0.38);
    });
    if (navigator.vibrate) navigator.vibrate([250, 80, 250, 80, 350]);
  } catch {
    // Browser audio can be unavailable until user interaction.
  }
};

const RestaurantStatTile = ({ label, value, tone, testId, active, onClick }) => {
  const tones = {
    amber: "border-orange-500/35 bg-orange-500/10 text-orange-100 hover:bg-orange-500/15",
    indigo: "border-blue-500/35 bg-blue-500/10 text-blue-100 hover:bg-blue-500/15",
    emerald: "border-emerald-500/35 bg-emerald-500/10 text-emerald-100 hover:bg-emerald-500/15",
  };
  return (
    <button type="button" onClick={onClick} className="text-left" data-testid={testId}>
    <Card className={`border transition-all ${tones[tone]} ${active ? "ring-2 ring-orange-400 shadow-[0_18px_45px_-28px_rgba(249,115,22,0.75)]" : "shadow-[0_18px_45px_-32px_rgba(0,0,0,0.9)]"}`}>
      <CardContent className="p-4 text-center">
        <p className="text-3xl font-black tracking-tight">{value}</p>
        <p className="mt-1 text-xs font-semibold uppercase tracking-[0.15em] opacity-70">{label}</p>
      </CardContent>
    </Card>
    </button>
  );
};

const RestaurantApp = () => {
  const { user, token, logout } = useAuth();
  const restaurantId = user?.restaurant_id;
  const { isOnline } = useNetworkStatus();
  const statusRecovery = useOrderStatusRecovery(user, API_URL, isOnline, token, false);
  const financialRecovery = useOrderFinancialEventRecovery(user, API_URL, isOnline, token);
  const custodyRecovery = useOrderCustodyRecovery(user, API_URL, isOnline, token);
  const custodyBusy = Boolean(custodyRecovery.record || custodyRecovery.storageInvalid || custodyRecovery.busy || custodyRecovery.sessionSuspended);
  const preparationRecovery = useOrderPreparationRecovery(user, API_URL, isOnline, token);
  const remakeRefresh = useRef(null);
  const remakeRecovery = useOrderRemakeRecovery(user, API_URL, isOnline, token,
    (guard) => remakeRefresh.current?.(guard));
  const remakeBusy = Boolean(remakeRecovery.record || remakeRecovery.storageInvalid || remakeRecovery.busy || remakeRecovery.sessionSuspended);
  const handledPreparationReceipt = useRef(null);
  const statusMutationRef = useRef(false), handledStatusReceipt = useRef(null), statusSession = useRef(null);
  const statusMounted = useRef(false);
  if (statusSession.current?.actor !== user?.id || statusSession.current?.token !== token || statusSession.current?.resource !== restaurantId) {
    statusSession.current = { actor: user?.id, token, resource: restaurantId };
  }
  useEffect(() => { statusMounted.current = true; return () => { statusMounted.current = false; }; }, []);
  const [newOrderFlash, setNewOrderFlash] = useState(false);
  const [confirmReadyOrder, setConfirmReadyOrder] = useState(null);
  const [cancelOrder, setCancelOrder] = useState(null);
  const verifyStatusCapability = statusRecovery.verifyCapability;
  const cancelStatusVersioned = hasStatusRevision(cancelOrder);
  useEffect(() => { if (cancelStatusVersioned && isOnline) void verifyStatusCapability(); }, [cancelStatusVersioned, cancelOrder?.id, isOnline, verifyStatusCapability]);
  const [cancelReason, setCancelReason] = useState("");
  const [now, setNow] = useState(Date.now());
  const [lateAlertedOrders, setLateAlertedOrders] = useState(new Set());
  const [activeView, setActiveView] = useState("new");
  const [moreDialogOpen, setMoreDialogOpen] = useState(false);
  const [incidentOrder, setIncidentOrder] = useState(null);
  const [historySearch, setHistorySearch] = useState("");
  const [historyDetailOrder, setHistoryDetailOrder] = useState(null);
  const [scheduleDialogOpen, setScheduleDialogOpen] = useState(false);
  const [problemOrder, setProblemOrder] = useState(null);
  const [problemForm, setProblemForm] = useState({ problem_type: "missing_product", item_name: "", quantity: 1, price: 0, problem_description: "" });
  const closeDayReporting = useOperationalReporting(user, restaurantId, API_URL, token, isOnline);
  const { captureLease: captureCloseLease, isCurrentLease: isCurrentCloseLease } = closeDayReporting;
  const isUpdatingRestaurantStatus = Boolean(closeDayReporting.busy);
  const [pendingOrderAction, setPendingOrderAction] = useState(null);
  const [isSavingSchedule, setIsSavingSchedule] = useState(false);
  const [isCreatingProblem, setIsCreatingProblem] = useState(false);
  const [isCancellingOrder, setIsCancellingOrder] = useState(false);
  const orderActionLockRef = useRef(false);
  const dialogSessionRef = useRef(statusSession.current);
  const ownsDialogSession = dialogSessionRef.current === statusSession.current;

  const { orders, setOrders, isLoading, setIsLoading, isRefreshingOrders, setIsRefreshingOrders,
    acceptingOrders, setAcceptingOrders, restaurantPauseUntil, setRestaurantPauseUntil,
    scheduleForm, setScheduleForm, prepAvailability, setPrepAvailability,
    analytics, setAnalytics, analyticsLoading, setAnalyticsLoading,
    fetchOrdersRequestRef, restaurantStatusRequestRef,
    fetchOrders, fetchRestaurantStatus, fetchAnalytics } = useRestaurantReads({
    restaurantId, actorId: user?.id, token, apiUrl: API_URL, statusSession, statusMounted, statusMutationRef,
    captureCloseLease, isCurrentCloseLease,
  });

  remakeRefresh.current = ({ isCurrent }) => fetchOrders({ silent: true, isCurrent });

  const closeRestaurantDay = async (recover = null) => {
    const session = statusSession.current, lease = captureCloseLease();
    const owns = () => statusMounted.current && statusSession.current === session;
    const ownsResult = () => owns() && isCurrentCloseLease(lease);
    if (!owns() || !restaurantId || !isOnline) return;
    restaurantStatusRequestRef.current += 1;
    const receipt = await (recover === null ? closeDayReporting.submit({ operation_type: "close_day", resource_id: restaurantId }) : closeDayReporting.recover(recover));
    if (!ownsResult()) return;
    if (reportApplied(receipt) && closeDayReporting.isCurrentReceipt(receipt)) {
      setAcceptingOrders(receipt.accepting_orders);
      setRestaurantPauseUntil(receipt.pause_until);
      toast.success("Ziua a fost marcată închisă. Primirea comenzilor păstrează statusul administrativ.");
    }
    // Lost ACK remains uncertain in its recovery panel; a read reconciles actual pause state.
    await fetchRestaurantStatus();
    if (ownsResult()) await fetchOrders({ silent: true, isCurrent: ownsResult });
  };

  // Notify once per order, including orders assigned before preparation starts.
  const seenOrderIdsRef = useRef(new Set());

  useEffect(() => {
    const newOrders = orders.filter(isNewRestaurantOrder);
    const unseenNewOrders = newOrders.filter(o => !seenOrderIdsRef.current.has(o.id));

    if (unseenNewOrders.length > 0) {
      unseenNewOrders.forEach(o => seenOrderIdsRef.current.add(o.id));

      // Flash banner
      setNewOrderFlash(true);
      setTimeout(() => setNewOrderFlash(false), NEW_ORDER_FLASH_MS);

      // Play notification sound — louder, triple beep
      try {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const playBeep = (freq, startTime, duration) => {
          const osc = audioContext.createOscillator();
          const gain = audioContext.createGain();
          osc.connect(gain);
          gain.connect(audioContext.destination);
          osc.frequency.value = freq;
          osc.type = 'sine';
          gain.gain.value = 0.4;
          osc.start(audioContext.currentTime + startTime);
          osc.stop(audioContext.currentTime + startTime + duration);
        };
        playBeep(800, 0, 0.15);
        playBeep(1000, 0.2, 0.15);
        playBeep(1200, 0.4, 0.25);
        // Vibrate
        if (navigator.vibrate) navigator.vibrate([200, 100, 200, 100, 300]);
      } catch {
        // Audio/vibration may be blocked by browser permissions.
      }
    }
  }, [orders]);

  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TIMER_TICK_MS);
    return () => clearInterval(timer);
  }, []);

  useEffect(() => {
    if (activeView === "analytics") fetchAnalytics();
  }, [activeView, fetchAnalytics]);

  useEffect(() => {
    orders
      .filter((order) => getPreparationStatus(order) === "PREPARING")
      .forEach((order) => {
        const timer = getPreparationTimer(order, now);
        if (timer?.isLate && !lateAlertedOrders.has(order.id)) {
          playLatePreparationAlert();
          setLateAlertedOrders((prev) => new Set(prev).add(order.id));
        }
      });
  }, [lateAlertedOrders, now, orders]);

  const setPreparationTime = useCallback(async (orderId, minutes) => {
    const actionKey = `prepare:${orderId}`;
    if (remakeBusy || custodyBusy || orderActionLockRef.current || pendingOrderAction || isCancellingOrder || statusRecovery.record || statusRecovery.busy || preparationRecovery.blocked) return;
    const order = orders.find((candidate) => candidate?.id === orderId);
    if (getPreparationStatus(order) !== "NEW" || !PREPARATION_OPTIONS_MINUTES.includes(minutes)) return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }
    if (isShortPreparationBlocked(order, minutes, prepAvailability)) {
      toast.error(`Nu există livratori disponibili. Alege minimum ${prepAvailability.minimum_preparation_minutes} minute.`);
      return;
    }
    orderActionLockRef.current = true;
    fetchOrdersRequestRef.current += 1;
    setPendingOrderAction(actionKey);
    const session = statusSession.current;
    const ownsSession = () => statusMounted.current && statusSession.current === session;
    try {
      const durable = await preparationRecovery.chooseProtocol();
      if (!ownsSession() || typeof durable !== "boolean") return;
      if (durable) {
        await preparationRecovery.submit({ order, action: "preparing", preparationTime: minutes });
        if (ownsSession()) await fetchOrders({ silent: true });
        return;
      }
      if (!preparationRecovery.canUseLegacy()) return;
      const response = await axios.put(`${API_URL}/api/orders/${orderId}/preparing`,  {
        preparation_time: minutes
      }, { timeout: 15000, headers: { Authorization: session.token ? `Bearer ${session.token}` : null, "X-Expected-Actor-ID": session.actor } });
      if (!ownsSession()) return;
      toast.success(response.data?.idempotent ? "Comanda era deja în pregătire. Am actualizat starea." : `Timp pregătire setat: ${minutes} minute`);
      await fetchOrders({ silent: true });
    } catch (error) {
      if (!ownsSession()) return;
      toast.error(getApiErrorMessage(error, "Eroare la setare timp"));
      await fetchOrders({ silent: true });
    } finally {
      if (ownsSession()) { orderActionLockRef.current = false; setPendingOrderAction(null); }
    }
  }, [fetchOrders, fetchOrdersRequestRef, isOnline, isCancellingOrder, orders, pendingOrderAction, prepAvailability, statusRecovery.record, statusRecovery.busy, preparationRecovery, custodyBusy, remakeBusy]);

  const saveScheduleSettings = async () => {
    const session = statusSession.current;
    const ownsSession = () => statusMounted.current && statusSession.current === session;
    if (!ownsSession() || session.actor !== user?.id || session.token !== token || session.resource !== restaurantId) return;
    if (isSavingSchedule || !restaurantId) return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }
    restaurantStatusRequestRef.current += 1;
    setIsSavingSchedule(true);
    try {
      await axios.patch(`${API_URL}/api/restaurants/${restaurantId}/schedule-settings`, scheduleForm, { timeout: 15000 });
      if (!ownsSession()) return;
      toast.success("Programul de lucru a fost salvat");
      setScheduleDialogOpen(false);
      await fetchRestaurantStatus();
    } catch (error) {
      if (ownsSession()) toast.error(getApiErrorMessage(error, "Nu am putut salva programul"));
    } finally {
      if (ownsSession()) setIsSavingSchedule(false);
    }
  };

  const createProblemOrder = async () => {
    const latestParent = orders.find((order) => order.id === problemOrder?.id) || problemOrder;
    if (!pureLegacyRemake(problemOrder) || !pureLegacyRemake(latestParent) || remakeBusy) return;
    const session = statusSession.current;
    const ownsSession = () => statusMounted.current && statusSession.current === session;
    if (!ownsSession() || session.actor !== user?.id || session.token !== token || session.resource !== restaurantId) return;
    if (isCreatingProblem) return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }
    if (!problemOrder || !problemForm.problem_description.trim()) {
      toast.error("Descrie problema înainte de salvare");
      return;
    }
    setIsCreatingProblem(true);
    try {
      await axios.post(`${API_URL}/api/orders/${problemOrder.id}/problem`, {
        ...problemForm,
        quantity: Number(problemForm.quantity) || 1,
        price: Number(problemForm.price) || 0,
      }, { timeout: 15000 });
      if (!ownsSession()) return;
      toast.success("Comandă legată creată pentru problemă");
      setProblemOrder(null);
      setProblemForm({ problem_type: "missing_product", item_name: "", quantity: 1, price: 0, problem_description: "" });
      await fetchOrders({ silent: true });
    } catch (error) {
      if (ownsSession()) toast.error(getApiErrorMessage(error, "Nu am putut crea comanda legată"));
    } finally {
      if (ownsSession()) setIsCreatingProblem(false);
    }
  };

  const markAsReady = useCallback(async (orderId) => {
    const actionKey = `ready:${orderId}`;
    if (remakeBusy || custodyBusy || !orderId || orderActionLockRef.current || pendingOrderAction || isCancellingOrder || statusRecovery.record || statusRecovery.busy || preparationRecovery.blocked) return;
    const order = orders.find((candidate) => candidate?.id === orderId);
    if (getPreparationStatus(order) !== "PREPARING") return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }
    orderActionLockRef.current = true;
    fetchOrdersRequestRef.current += 1;
    setPendingOrderAction(actionKey);
    const session = statusSession.current;
    const ownsSession = () => statusMounted.current && statusSession.current === session;
    try {
      const durable = await preparationRecovery.chooseProtocol();
      if (!ownsSession() || typeof durable !== "boolean") return;
      if (durable) {
        await preparationRecovery.submit({ order, action: "ready" });
        if (ownsSession()) await fetchOrders({ silent: true });
        return;
      }
      if (!preparationRecovery.canUseLegacy()) return;
      const response = await axios.put(`${API_URL}/api/orders/${orderId}/ready`,  undefined, { timeout: 15000, headers: { Authorization: session.token ? `Bearer ${session.token}` : null, "X-Expected-Actor-ID": session.actor } });
      if (!ownsSession()) return;
      toast.success(response.data?.idempotent ? "Comanda era deja gata. Am actualizat starea." : "Comanda este GATA pentru ridicare!");
      setConfirmReadyOrder(null);
      await fetchOrders({ silent: true });
    } catch (error) {
      if (!ownsSession()) return;
      toast.error(getApiErrorMessage(error, "Eroare la marcare gata"));
      await fetchOrders({ silent: true });
    } finally {
      if (ownsSession()) { orderActionLockRef.current = false; setPendingOrderAction(null); }
    }
  }, [fetchOrders, fetchOrdersRequestRef, isOnline, isCancellingOrder, orders, pendingOrderAction, statusRecovery.record, statusRecovery.busy, preparationRecovery, custodyBusy, remakeBusy]);

  const handleCancelOrder = useCallback(async () => {
    if (isCancellingOrder || orderActionLockRef.current || pendingOrderAction || preparationRecovery.blocked) return;
    const latestOrder = orders.find((o) => o.id === cancelOrder?.id) || cancelOrder;
    if (remakeBusy || custodyBusy || !statusRecovery.canSubmit(latestOrder) || !canChangeOrderStatus(latestOrder, "CANCELLED", user)) return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }
    if (!cancelOrder?.id) {
      toast.error("Comanda nu mai este disponibilă pentru anulare.");
      return;
    }
    if (!cancelReason.trim()) {
      toast.error("Motivul anulării este obligatoriu!");
      return;
    }
    orderActionLockRef.current = true;
    statusMutationRef.current = true;
    const session = statusSession.current;
    const ownsSession = () => statusMounted.current && statusSession.current === session;
    fetchOrdersRequestRef.current += 1;
    setIsCancellingOrder(true);
    try {
      const command = { order: latestOrder, status: "CANCELLED", cancellationReason: cancelReason.trim() };
      const versioned = hasStatusRevision(latestOrder);
      const result = await (versioned ? statusRecovery.submit(command) : statusRecovery.submitLegacy(command));
      if (!ownsSession() || !result || versioned) return;
      toast.success("Comanda a fost anulată");
      setCancelOrder(null);
      setCancelReason("");
    } catch (error) {
      if (ownsSession()) toast.error(getApiErrorMessage(error, "Eroare la anulare"));
    } finally {
      if (ownsSession()) {
        orderActionLockRef.current = false; statusMutationRef.current = false; fetchOrdersRequestRef.current += 1; setIsCancellingOrder(false); await fetchOrders({ silent: true }); }
    }
  }, [cancelOrder, cancelReason, fetchOrders, fetchOrdersRequestRef, isCancellingOrder, isOnline, pendingOrderAction, orders, statusRecovery, user, preparationRecovery.blocked, custodyBusy, remakeBusy]);

  useEffect(() => {
    const r = preparationRecovery.record;
    if (!r || !preparationApplied(r.receipt)) return;
    const key = `${user?.id}:${restaurantId}:${r.client_operation_id}`;
    if (handledPreparationReceipt.current === key) return;
    handledPreparationReceipt.current = key; fetchOrdersRequestRef.current += 1;
    if (r.action === "ready") { toast.success("Marcarea comenzii ca gata a fost confirmată."); setConfirmReadyOrder(null); }
    else toast.success(`Pregătire confirmată: ${r.receipt.preparation_time} minute`);
    void fetchOrders({ silent: true });
  }, [preparationRecovery.record, fetchOrders, fetchOrdersRequestRef, user?.id, restaurantId]);

  useEffect(() => {
    const r = statusRecovery.record;
    if (!r || !statusApplied(r.receipt)) return;
    const key = `${user?.id}:${token}:${r.client_operation_id}`;
    if (handledStatusReceipt.current === key) return;
    handledStatusReceipt.current = key; fetchOrdersRequestRef.current += 1;
    toast.success("Comanda a fost anulata"); setCancelOrder(null); setCancelReason("");
    if (!statusMutationRef.current) void fetchOrders({ silent: true });
  }, [statusRecovery.record, fetchOrders, fetchOrdersRequestRef, user?.id, token]);

  useEffect(() => {
    fetchOrdersRequestRef.current += 1; setOrders([]); setCancelOrder(null); setCancelReason(""); setIsCancellingOrder(false);
    dialogSessionRef.current = statusSession.current;
    setHistoryDetailOrder(null); setProblemOrder(null); setIncidentOrder(null); setConfirmReadyOrder(null); setHistorySearch("");
    setProblemForm({ problem_type: "missing_product", item_name: "", quantity: 1, price: 0, problem_description: "" });
    setAnalytics(null); setAnalyticsLoading(false); setScheduleDialogOpen(false); setMoreDialogOpen(false);
    setRestaurantPauseUntil(null); setAcceptingOrders(true); setScheduleForm(defaultScheduleSettings());
    setPrepAvailability({ available_drivers: 0, blocked_short_options: false, minimum_preparation_minutes: 5 });
    setIsSavingSchedule(false); setIsCreatingProblem(false);
    setPendingOrderAction(null); setIsLoading(true); setIsRefreshingOrders(false); setLateAlertedOrders(new Set());
    orderActionLockRef.current = false; statusMutationRef.current = false;
    void fetchOrders({ silent: true });
  }, [user?.id, restaurantId, token, fetchOrders, fetchOrdersRequestRef, setOrders, setAnalytics, setAnalyticsLoading,
    setRestaurantPauseUntil, setAcceptingOrders, setScheduleForm, setPrepAvailability, setIsLoading, setIsRefreshingOrders]);

  const orderGroups = useMemo(() => splitRestaurantOrders(orders), [orders]);
  const visibleOrders = useMemo(() => {
    if (activeView === "new") return orderGroups.newOrders;
    if (activeView === "work") return orderGroups.inWork;
    if (activeView === "delivered") return orderGroups.delivered;
    return orderGroups.active;
  }, [activeView, orderGroups]);
  const historyOrders = useMemo(() => {
    const term = historySearch.trim().toLowerCase();
    const base = orders.filter(o => ['DELIVERED', 'PICKED_UP', 'CANCELLED'].includes(o?.status));
    if (!term) return base;
    return base.filter((order) => `${order.order_number || ""} ${order.customer_name || ""} ${order.customer_phone || ""} ${order.customer_address || ""} ${order.items?.map((item) => item.name).join(" ") || ""}`.toLowerCase().includes(term));
  }, [historySearch, orders]);
  const completedToday = orderGroups.delivered.length;
  const newCount = orderGroups.newOrders.length;
  const readyCount = useMemo(() => orders.filter((order) => getPreparationStatus(order) === 'READY').length, [orders]);
  const canConfirmReady = getPreparationStatus(orders.find((order) => order?.id === confirmReadyOrder?.id)) === "PREPARING";
  const pauseSeconds = getPauseSeconds({ pause_until: restaurantPauseUntil }, now);

  const openMoreView = (view) => {
    setActiveView(view);
    setMoreDialogOpen(false);
    if (view === "analytics") fetchAnalytics();
  };

  const preparationRenderSession = statusSession.current;
  const applyAcknowledgedPreparation = useCallback((fresh) => {
    if (!statusMounted.current || statusSession.current !== preparationRenderSession) return;
    setOrders((all) => all.some((order) => order.id === fresh.id) ? all.map((order) => order.id === fresh.id ? fresh : order) : [...all, fresh]);
    void fetchOrders({ silent: true });
  }, [preparationRenderSession, setOrders, fetchOrders]);

  if (isLoading && !remakeRecovery.record && !remakeRecovery.storageInvalid && !statusRecovery.record && !statusRecovery.storageInvalid && !preparationRecovery.record && !preparationRecovery.storageInvalid && !financialRecovery.record && !financialRecovery.storageInvalid && !custodyRecovery.record && !custodyRecovery.storageInvalid) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen overflow-x-hidden bg-zinc-950 text-zinc-50" data-testid="restaurant-app">
      <header className="sticky top-0 z-50 border-b border-zinc-800 bg-zinc-950/90 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-3 px-4 py-3 lg:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <div className="grid h-11 w-11 shrink-0 place-items-center rounded-xl bg-orange-500 text-zinc-950 shadow-[0_0_22px_rgba(249,115,22,0.25)]">
              <ChefHat className="h-6 w-6" />
            </div>
            <div className="min-w-0">
              <p className="text-xs font-black uppercase tracking-[0.2em] text-orange-400">Kitchen Queue</p>
              <h1 className="truncate text-lg font-black tracking-tight sm:text-xl" style={{ fontFamily: 'var(--font-heading)' }}>
                {user?.restaurant_name || 'Restaurant'}
              </h1>
            </div>
            <Button variant="outline" size="sm" onClick={() => setMoreDialogOpen(true)} className="hidden border-zinc-700 bg-zinc-900 text-zinc-200 hover:bg-zinc-800 sm:inline-flex" data-testid="restaurant-more-left-button">
              <Settings className="mr-2 h-4 w-4" /> Mai mult
            </Button>
          </div>
          <div className="flex items-center gap-2">
            <Button variant="ghost" size="icon" onClick={() => setMoreDialogOpen(true)} className="text-zinc-300 hover:bg-zinc-800 hover:text-white sm:hidden" data-testid="restaurant-more-settings-button">
              <Settings className="h-5 w-5" />
            </Button>
            {!acceptingOrders && pauseSeconds > 0 && (
              <Badge className="border-amber-500/40 bg-amber-500/15 text-amber-200" data-testid="restaurant-pause-countdown">
                Pauză {formatSeconds(pauseSeconds)}
              </Badge>
            )}
            <span
              title="Pauza și reluarea sunt administrate de dispecerat"
              className={`inline-flex h-10 items-center gap-2 rounded-full border px-3 text-sm font-black transition-colors ${acceptingOrders ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" : "border-red-500/40 bg-red-500/15 text-red-300"}`}
              data-testid="restaurant-operational-toggle"
            >
              <Power className="h-4 w-4" />
              <span className="hidden sm:inline">{acceptingOrders ? "Acceptă comenzi" : "Pauză"}</span>
            </span>
            <Button
              variant="ghost"
              size="icon"
              onClick={() => fetchOrders({ manual: true })}
              disabled={isRefreshingOrders || !isOnline}
              className="text-zinc-300 hover:bg-zinc-800 hover:text-white"
              data-testid="refresh-button"
            >
              <RefreshCw className={`h-5 w-5 ${isRefreshingOrders ? "animate-spin" : ""}`} />
            </Button>
            <Button variant="ghost" size="icon" onClick={logout} className="text-zinc-300 hover:bg-zinc-800 hover:text-white" data-testid="logout-button">
              <LogOut className="h-5 w-5" />
            </Button>
          </div>
        </div>
      </header>

      {newOrderFlash && (
        <div className="mx-auto mt-3 max-w-[1600px] px-4 lg:px-6">
          <div className="rounded-xl border border-orange-500/40 bg-orange-500/15 p-4 text-center text-orange-100 shadow-lg" data-testid="new-order-flash">
            <p className="text-lg font-black tracking-wide">COMANDĂ NOUĂ PRIMITĂ!</p>
            <p className="text-sm opacity-80">Alege timpul de preparare.</p>
          </div>
        </div>
      )}

      <main className="mx-auto max-w-[1600px] space-y-5 px-4 py-5 lg:px-6">
        <OrderRemakeRecoveryPanel recovery={remakeRecovery} isOnline={isOnline} />
        <PreparationRecoveryPanel recovery={preparationRecovery} isOnline={isOnline} onAcknowledged={applyAcknowledgedPreparation} />
        <CustodyRecoveryPanel recovery={custodyRecovery} isOnline={isOnline} onAcknowledged={(fresh) => {
          setOrders((all) => all.map((order) => order.id === fresh.id ? fresh : order));
          setHistoryDetailOrder((order) => order?.id === fresh.id ? fresh : order);
          void fetchOrders({ silent: true });
        }} />
        <FinancialEventRecoveryPanel recovery={financialRecovery} isOnline={isOnline} onAcknowledged={(fresh) => {
          setOrders((all) => all.map((order) => order.id === fresh.id ? fresh : order));
          void fetchOrders({ silent: true });
        }} />
        <OrderStatusRecoveryPanel recovery={statusRecovery} isOnline={isOnline} order={cancelOrder}
          onAcknowledged={() => fetchOrders({ silent: true })} onRetry={(fresh) => { setOrders((all) => all.map((o) => o.id === fresh.id ? fresh : o)); setCancelOrder(fresh); }} />
        <section className="overflow-hidden rounded-2xl border border-zinc-800 bg-[radial-gradient(circle_at_top_left,rgba(249,115,22,0.22),transparent_32%),linear-gradient(135deg,#18181b,#09090b)] shadow-2xl" data-testid="restaurant-kitchen-hero">
          <div className="grid gap-5 p-5 lg:grid-cols-[1.35fr_0.9fr] lg:p-7">
            <div>
              <Badge className="mb-3 border-orange-500/30 bg-orange-500/15 text-orange-300 hover:bg-orange-500/15">
                <Utensils className="mr-1 h-3.5 w-3.5" /> KDS live
              </Badge>
              <h2 className="max-w-3xl text-3xl font-black tracking-tight sm:text-4xl">Bucătărie organizată, timer mare, decizii rapide.</h2>
              <p className="mt-2 max-w-2xl text-sm text-zinc-400">Comenzile sunt separate vizual pe status: nou, în lucru, gata și ridicare.</p>
            </div>
            <div className="grid grid-cols-2 gap-3 sm:grid-cols-4 lg:grid-cols-2">
              <div className="rounded-xl border border-white/10 bg-white/5 p-3"><p className="text-xs text-zinc-400">Ora curentă</p><p className="font-mono text-2xl font-black text-white">{new Date(now).toLocaleTimeString("ro-RO", { hour: "2-digit", minute: "2-digit" })}</p></div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-3"><p className="text-xs text-zinc-400">Active</p><p className="font-mono text-2xl font-black text-orange-300">{orderGroups.active.length}</p></div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-3"><p className="text-xs text-zinc-400">Gata</p><p className="font-mono text-2xl font-black text-emerald-300">{readyCount}</p></div>
              <div className="rounded-xl border border-white/10 bg-white/5 p-3"><p className="text-xs text-zinc-400">Status</p><p className={`text-sm font-black ${acceptingOrders ? "text-emerald-300" : "text-red-300"}`}>{acceptingOrders ? "ONLINE" : "PAUZĂ"}</p></div>
            </div>
          </div>
        </section>

        <div className="grid grid-cols-3 gap-3">
          <RestaurantStatTile label="Noi" value={newCount} tone="amber" active={activeView === "new"} onClick={() => setActiveView("new")} testId="restaurant-stat-new" />
          <RestaurantStatTile label="În lucru" value={orderGroups.inWork.length} tone="indigo" active={activeView === "work"} onClick={() => setActiveView("work")} testId="restaurant-stat-preparing" />
          <RestaurantStatTile label="Livrate" value={completedToday} tone="emerald" active={activeView === "delivered"} onClick={() => setActiveView("delivered")} testId="restaurant-stat-delivered" />
        </div>

        <section className="flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-zinc-800 bg-zinc-900/80 p-3" data-testid="restaurant-compact-pause-bar">
          <div className="text-sm text-zinc-300"><p>Pauza și reluarea comenzilor sunt administrate de dispecerat.</p><p>Închiderea zilei păstrează comenzile active și primirea comenzilor noi.</p>
            {!acceptingOrders && pauseSeconds > 0 && <span data-testid="restaurant-compact-pause-countdown">Pauză {formatSeconds(pauseSeconds)}</span>}
          </div>
          <Button size="sm" variant="outline" onClick={() => closeRestaurantDay()} disabled={!isOnline || !closeDayReporting.available || closeDayReporting.blocked || isUpdatingRestaurantStatus || closeDayReporting.pending} data-testid="restaurant-compact-close-today-button">{isUpdatingRestaurantStatus ? "Se verifică..." : "Închide azi"}</Button>
        </section>
        <OperationalReportingPanel reporting={closeDayReporting} onRecover={closeRestaurantDay} />
        <OperationalIncidentReporter actor={user} token={token} scope={`restaurant-incidents:${restaurantId}`} disabled={custodyBusy} apiUrl={API_URL} isOnline={isOnline} order={ownsDialogSession ? incidentOrder : null} showTrigger={false} onClose={() => setIncidentOrder(null)} onReported={(receipt, guard) => fetchOrders({ silent: true, isCurrent: guard.isCurrent })} />

        {prepAvailability.blocked_short_options && !["analytics", "history"].includes(activeView) && (
          <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-100" data-testid="restaurant-prep-driver-warning">
            <AlertTriangle className="mr-2 inline h-4 w-4" /> Nu există livratori liberi acum. Timpii sub {prepAvailability.minimum_preparation_minutes} minute necesită un livrator deja alocat disponibil.
          </div>
        )}

        {activeView === "history" && (
          <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-4" data-testid="restaurant-history-panel">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h2 className="flex items-center gap-2 text-xl font-black"><History className="h-5 w-5 text-orange-400" /> Istoric comenzi</h2>
              <div className="relative w-full sm:w-80"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" /><Input value={historySearch} onChange={(event) => setHistorySearch(event.target.value)} className="border-zinc-700 bg-zinc-950 pl-9 text-zinc-100" placeholder="Caută client, telefon, adresă, produs" data-testid="restaurant-history-search-input" /></div>
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {historyOrders.map((order) => <button type="button" onClick={() => setHistoryDetailOrder(order)} key={order.id} className="rounded-xl border border-zinc-800 bg-black/20 p-3 text-left transition-colors hover:border-orange-500/40 hover:bg-orange-500/5" data-testid={`restaurant-history-order-${order.id}`}><div className="flex justify-between gap-3"><span className="font-mono text-sm font-black text-zinc-300">{order.order_number}</span>{getStatusConfig(order.status).label}</div><p className="mt-2 font-bold">{order.customer_name}</p><p className="text-sm text-zinc-400">{order.customer_phone} · {orderAmountLabel(order)}: {clientCollectionText(order)}</p><p className="mt-1 line-clamp-2 text-xs text-zinc-500">{order.customer_address}</p></button>)}
              {historyOrders.length === 0 && <p className="text-sm text-zinc-500" data-testid="restaurant-history-empty">Nu am găsit comenzi.</p>}
            </div>
          </section>
        )}

        {activeView === "analytics" && (
          <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-4 text-zinc-50" data-testid="restaurant-self-analytics-panel">
            <div className="mb-4 flex items-center justify-between gap-3"><h2 className="flex items-center gap-2 text-xl font-black"><BarChart3 className="h-5 w-5 text-orange-400" /> Analytics restaurant</h2><Button variant="outline" className="border-zinc-700 bg-zinc-950 text-zinc-100 hover:bg-zinc-800" onClick={fetchAnalytics} data-testid="restaurant-refresh-analytics-button">Actualizează</Button></div>
            <RestaurantAnalyticsPanel analytics={analytics} isLoading={analyticsLoading} />
          </section>
        )}

        {!["history", "analytics"].includes(activeView) && visibleOrders.length === 0 ? (
          <section className="rounded-2xl border border-dashed border-zinc-700 bg-zinc-900/70 py-16 text-center" data-testid="restaurant-empty-state">
            <Bell className="mx-auto mb-4 h-16 w-16 text-zinc-600" />
            <h2 className="text-2xl font-black">Nicio comandă în filtrul ales</h2>
            <p className="mt-2 text-zinc-400">Vei primi alertă când apare o comandă nouă.</p>
          </section>
        ) : !["history", "analytics"].includes(activeView) && (
          <section className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-testid="restaurant-kds-grid">
            {visibleOrders.map((order) => <RestaurantOrderCard key={order.id} order={order}
              now={now} isOnline={isOnline} pendingOrderAction={pendingOrderAction}
              isCancellingOrder={isCancellingOrder} statusRecovery={statusRecovery} preparationBlocked={preparationRecovery.blocked || custodyBusy || remakeBusy} financialRecovery={financialRecovery} custodyRecovery={custodyRecovery}
              prepAvailability={prepAvailability} user={user} onPrepare={setPreparationTime}
              onReady={setConfirmReadyOrder} onIncident={setIncidentOrder}
              onProblem={(selected) => { setProblemOrder(selected); setProblemForm({ problem_type: "missing_product", item_name: "", quantity: 1, price: 0, problem_description: "" }); }}
              onCancel={(selected) => { setCancelOrder(selected); setCancelReason(""); }} />)}
          </section>
        )}
      </main>

      {/* Confirm Ready Dialog */}
      <RestaurantReadyDialog open={ownsDialogSession && !!confirmReadyOrder}
        confirmReadyOrder={confirmReadyOrder} setConfirmReadyOrder={setConfirmReadyOrder} markAsReady={markAsReady} isOnline={isOnline} pendingOrderAction={pendingOrderAction} isCancellingOrder={isCancellingOrder} statusRecovery={statusRecovery} preparationBlocked={preparationRecovery.blocked || custodyBusy || remakeBusy} canConfirmReady={canConfirmReady} />

      <RestaurantScheduleDialog open={ownsDialogSession && scheduleDialogOpen}
        setScheduleDialogOpen={setScheduleDialogOpen} scheduleForm={scheduleForm} setScheduleForm={setScheduleForm} isSavingSchedule={isSavingSchedule} saveScheduleSettings={saveScheduleSettings} isOnline={isOnline} />

      <RestaurantMoreDialog open={ownsDialogSession && moreDialogOpen}
        setMoreDialogOpen={setMoreDialogOpen} openMoreView={openMoreView} setScheduleDialogOpen={setScheduleDialogOpen} closeRestaurantDay={closeRestaurantDay} isOnline={isOnline} closeDayReporting={closeDayReporting} isUpdatingRestaurantStatus={isUpdatingRestaurantStatus} />

      <RestaurantHistoryDetailDialog open={ownsDialogSession && !!historyDetailOrder}
        historyDetailOrder={orders.find((order) => order.id === historyDetailOrder?.id) || historyDetailOrder} user={user} custodyRecovery={custodyRecovery} isOnline={isOnline} custodyDisabled={Boolean(remakeBusy || statusRecovery.record || statusRecovery.busy || financialRecovery.record || financialRecovery.busy)} onCustodyAcknowledged={(fresh) => {
          setOrders((all) => all.map((order) => order.id === fresh.id ? fresh : order));
          setHistoryDetailOrder((order) => order?.id === fresh.id ? null : order); void fetchOrders({ silent: true });
        }} setHistoryDetailOrder={setHistoryDetailOrder} setIncidentOrder={setIncidentOrder} setProblemOrder={setProblemOrder} />

      <RestaurantProblemDialog open={ownsDialogSession && !!problemOrder}
        problemOrder={!pureLegacyRemake(problemOrder) && pureLegacyRemake(orders.find((order) => order.id === problemOrder?.id)) ? problemOrder : orders.find((order) => order.id === problemOrder?.id) || problemOrder} setProblemOrder={setProblemOrder} problemForm={problemForm} setProblemForm={setProblemForm} isCreatingProblem={isCreatingProblem} createProblemOrder={createProblemOrder} isOnline={isOnline}
        actor={user} apiUrl={API_URL} token={token} remakeRecovery={remakeRecovery} financialRecovery={financialRecovery}
        remakeBlocked={Boolean(custodyBusy || statusRecovery.record || statusRecovery.busy || preparationRecovery.blocked || pendingOrderAction || isCancellingOrder)} />

      {/* Cancel Order Dialog */}
      <RestaurantCancelDialog open={ownsDialogSession && !!cancelOrder}
        cancelOrder={cancelOrder} setCancelOrder={setCancelOrder} cancelReason={cancelReason} setCancelReason={setCancelReason} cancelStatusVersioned={cancelStatusVersioned} statusRecovery={statusRecovery} preparationBlocked={preparationRecovery.blocked || custodyBusy || remakeBusy} isCancellingOrder={isCancellingOrder} handleCancelOrder={handleCancelOrder} pendingOrderAction={pendingOrderAction} isOnline={isOnline} orders={orders} user={user} />
    </div>
  );
};

export default RestaurantApp;
