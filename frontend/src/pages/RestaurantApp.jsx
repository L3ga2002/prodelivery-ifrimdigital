import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useAuth } from "../context/AuthContext";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Card, CardContent } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Textarea } from "../components/ui/textarea";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { RestaurantAnalyticsPanel } from "../components/admin/RestaurantAnalyticsPanel";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "../components/ui/dialog";
import {
  LogOut,
  CheckCircle2,
  Truck,
  RefreshCw,
  ChefHat,
  Bell,
  BarChart3,
  CalendarDays,
  User,
  MapPin,
  XCircle,
  AlertTriangle,
  Utensils,
  Power,
  TimerReset,
  History,
  Phone,
  Search,
  PlusCircle,
  Settings,
  BookOpen,
  SlidersHorizontal,
} from "lucide-react";
import { getApiErrorMessage, normalizeArray, normalizeObject, retryApiCall } from "../lib/api";
import { useNetworkStatus } from "../hooks/useNetworkStatus";

const API_URL = process.env.REACT_APP_BACKEND_URL;
const ORDER_POLL_INTERVAL_MS = 5000;
const NEW_ORDER_FLASH_MS = 4000;
const TIMER_TICK_MS = 1000;
const PREPARATION_OPTIONS_MINUTES = [5, 10, 15, 20, 25, 30];
const RESTAURANT_DAYS = [
  { key: "monday", label: "Luni" },
  { key: "tuesday", label: "Marți" },
  { key: "wednesday", label: "Miercuri" },
  { key: "thursday", label: "Joi" },
  { key: "friday", label: "Vineri" },
  { key: "saturday", label: "Sâmbătă" },
  { key: "sunday", label: "Duminică" },
];

const formatSeconds = (totalSeconds) => {
  const absSeconds = Math.abs(totalSeconds);
  const minutes = Math.floor(absSeconds / 60);
  const seconds = absSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
};

const getPreparationTimer = (order, now) => {
  const dueAtRaw = order.preparation_due_at;
  if (!dueAtRaw) return null;
  const dueAt = new Date(dueAtRaw).getTime();
  if (Number.isNaN(dueAt)) return null;
  const remainingSeconds = Math.ceil((dueAt - now) / 1000);
  return {
    remainingSeconds,
    isLate: remainingSeconds <= 0,
    label: remainingSeconds > 0 ? formatSeconds(remainingSeconds) : `+${formatSeconds(remainingSeconds)}`,
  };
};

const getPauseSeconds = (restaurant, now) => {
  const pauseUntilRaw = restaurant?.pause_until;
  if (!pauseUntilRaw) return 0;
  const pauseUntil = new Date(pauseUntilRaw).getTime();
  if (Number.isNaN(pauseUntil)) return 0;
  return Math.max(Math.ceil((pauseUntil - now) / 1000), 0);
};

const defaultScheduleSettings = () => Object.fromEntries(
  RESTAURANT_DAYS.map((day) => [day.key, { enabled: true, open_time: "10:00", close_time: "22:00" }])
);

const splitRestaurantOrders = (orders) => {
  const groups = { active: [], inWork: [], delivered: [], newOrders: [] };
  orders.forEach((order) => {
    if (order.status === "NEW") groups.newOrders.push(order);
    if (order.status === "DELIVERED") groups.delivered.push(order);
    if (['PREPARING', 'READY', 'ASSIGNED', 'ACCEPTED', 'PICKED_UP'].includes(order.status)) groups.inWork.push(order);
    if (!['DELIVERED', 'PICKED_UP', 'CANCELLED'].includes(order.status)) groups.active.push(order);
  });
  return groups;
};

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

const getStatusConfig = (status) => {
  const config = {
    NEW: { label: "Nouă", color: "bg-amber-500", textColor: "text-amber-800 dark:text-amber-100", bgColor: "bg-amber-100 dark:bg-amber-950/40" },
    PREPARING: { label: "În Pregătire", color: "bg-indigo-500", textColor: "text-indigo-800 dark:text-indigo-100", bgColor: "bg-indigo-100 dark:bg-indigo-950/40" },
    READY: { label: "GATA", color: "bg-emerald-500", textColor: "text-emerald-800 dark:text-emerald-100", bgColor: "bg-emerald-100 dark:bg-emerald-950/40" },
    ASSIGNED: { label: "Alocată", color: "bg-blue-500", textColor: "text-blue-800 dark:text-blue-100", bgColor: "bg-blue-100 dark:bg-blue-950/40" },
    ACCEPTED: { label: "Acceptată", color: "bg-blue-500", textColor: "text-blue-800 dark:text-blue-100", bgColor: "bg-blue-100 dark:bg-blue-950/40" },
    PICKED_UP: { label: "Ridicată", color: "bg-orange-500", textColor: "text-orange-800 dark:text-orange-100", bgColor: "bg-orange-100 dark:bg-orange-950/40" },
    DELIVERED: { label: "Livrată", color: "bg-gray-500", textColor: "text-gray-800 dark:text-slate-100", bgColor: "bg-gray-100 dark:bg-slate-800" },
    CANCELLED: { label: "Anulată", color: "bg-red-500", textColor: "text-red-800 dark:text-red-100", bgColor: "bg-red-100 dark:bg-red-950/40" },
  };
  return config[status] || { label: status, color: "bg-gray-500", textColor: "text-gray-800 dark:text-slate-100", bgColor: "bg-gray-100 dark:bg-slate-800" };
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

const orderLaneMeta = {
  NEW: { title: "Nouă", className: "border-orange-500/40 bg-orange-500/10 text-orange-200", icon: Bell },
  PREPARING: { title: "În lucru", className: "border-blue-500/40 bg-blue-500/10 text-blue-200", icon: ChefHat },
  READY: { title: "Gata", className: "border-emerald-500/40 bg-emerald-500/10 text-emerald-200", icon: CheckCircle2 },
  ASSIGNED: { title: "Ridicare", className: "border-sky-500/40 bg-sky-500/10 text-sky-200", icon: Truck },
  ACCEPTED: { title: "Ridicare", className: "border-sky-500/40 bg-sky-500/10 text-sky-200", icon: Truck },
};

const RestaurantApp = () => {
  const { user, logout } = useAuth();
  const restaurantId = user?.restaurant_id;
  const { isOnline } = useNetworkStatus();
  const [orders, setOrders] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshingOrders, setIsRefreshingOrders] = useState(false);
  const [newOrderFlash, setNewOrderFlash] = useState(false);
  const [confirmReadyOrder, setConfirmReadyOrder] = useState(null);
  const [cancelOrder, setCancelOrder] = useState(null);
  const [cancelReason, setCancelReason] = useState("");
  const [now, setNow] = useState(Date.now());
  const [lateAlertedOrders, setLateAlertedOrders] = useState(new Set());
  const [acceptingOrders, setAcceptingOrders] = useState(true);
  const [restaurantPauseUntil, setRestaurantPauseUntil] = useState(null);
  const [activeView, setActiveView] = useState("new");
  const [moreDialogOpen, setMoreDialogOpen] = useState(false);
  const [manualPauseMinutes, setManualPauseMinutes] = useState(30);
  const [historySearch, setHistorySearch] = useState("");
  const [historyDetailOrder, setHistoryDetailOrder] = useState(null);
  const [scheduleDialogOpen, setScheduleDialogOpen] = useState(false);
  const [scheduleForm, setScheduleForm] = useState(defaultScheduleSettings);
  const [problemOrder, setProblemOrder] = useState(null);
  const [problemForm, setProblemForm] = useState({ problem_type: "missing_product", item_name: "", quantity: 1, price: 0, problem_description: "" });
  const [prepAvailability, setPrepAvailability] = useState({ available_drivers: 0, blocked_short_options: false, minimum_preparation_minutes: 5 });
  const [analytics, setAnalytics] = useState(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const [isUpdatingRestaurantStatus, setIsUpdatingRestaurantStatus] = useState(false);
  const [pendingOrderAction, setPendingOrderAction] = useState(null);
  const [isSavingSchedule, setIsSavingSchedule] = useState(false);
  const [isCreatingProblem, setIsCreatingProblem] = useState(false);
  const [isCancellingOrder, setIsCancellingOrder] = useState(false);
  const fetchOrdersRequestRef = useRef(0);

  const fetchRestaurantStatus = useCallback(async () => {
    if (!restaurantId) return;
    try {
      const response = await retryApiCall(() => axios.get(`${API_URL}/api/restaurants/${restaurantId}`));
      const restaurant = normalizeObject(response.data);
      setRestaurantPauseUntil(restaurant.pause_until || null);
      setAcceptingOrders(restaurant.accepting_orders !== false);
      setScheduleForm({ ...defaultScheduleSettings(), ...(restaurant.schedule_settings || {}) });
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut încărca statusul restaurantului"));
    }
  }, [restaurantId]);

  const fetchPrepAvailability = useCallback(async () => {
    if (!restaurantId) return;
    try {
      const response = await retryApiCall(() => axios.get(`${API_URL}/api/orders/restaurant/${restaurantId}/prep-availability`));
      setPrepAvailability(normalizeObject(response.data, { available_drivers: 0, blocked_short_options: false, minimum_preparation_minutes: 5 }));
    } catch {
      // Availability warning is non-blocking for the restaurant screen.
    }
  }, [restaurantId]);

  const fetchAnalytics = useCallback(async () => {
    if (!restaurantId) return;
    setAnalyticsLoading(true);
    try {
      const response = await retryApiCall(() => axios.get(`${API_URL}/api/restaurants/${restaurantId}/analytics`));
      setAnalytics(normalizeObject(response.data, null));
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut încărca analytics-ul restaurantului"));
    } finally {
      setAnalyticsLoading(false);
    }
  }, [restaurantId]);

  const fetchOrders = useCallback(async ({ manual = false, silent = false } = {}) => {
    if (!restaurantId) return;
    const requestId = fetchOrdersRequestRef.current + 1;
    fetchOrdersRequestRef.current = requestId;
    if (manual) setIsRefreshingOrders(true);
    try {
      const response = await retryApiCall(() => axios.get(`${API_URL}/api/orders/restaurant/${restaurantId}`));
      if (requestId !== fetchOrdersRequestRef.current) return;
      setOrders(normalizeArray(response.data));
    } catch (error) {
      if (requestId === fetchOrdersRequestRef.current) {
        if (!silent) {
          toast.error(getApiErrorMessage(error, "Nu am putut încărca comenzile restaurantului"));
        }
      }
    } finally {
      if (requestId === fetchOrdersRequestRef.current) {
        setIsLoading(false);
      }
      if (manual) setIsRefreshingOrders(false);
    }
  }, [restaurantId]);

  useEffect(() => {
    if (restaurantId) {
      fetchOrders();
      fetchRestaurantStatus();
      fetchPrepAvailability();
      const interval = setInterval(fetchOrders, ORDER_POLL_INTERVAL_MS);
      return () => clearInterval(interval);
    } else {
      setIsLoading(false);
    }
  }, [fetchOrders, fetchPrepAvailability, fetchRestaurantStatus, restaurantId]);

  const setRestaurantStatus = async ({ accepting, pauseMinutes = null, closedToday = false }) => {
    if (!restaurantId || isUpdatingRestaurantStatus) return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }
    setIsUpdatingRestaurantStatus(true);
    try {
      const response = await axios.patch(`${API_URL}/api/restaurants/${restaurantId}/status`, {
        accepting_orders: accepting,
        pause_minutes: pauseMinutes,
        closed_today: closedToday,
      });
      setAcceptingOrders(accepting);
      setRestaurantPauseUntil(response.data.pause_until || null);
      toast.success(accepting ? "Restaurant online pentru comenzi" : closedToday ? "Restaurant închis pentru azi" : `Restaurant pus pe pauză ${pauseMinutes} min`);
      await fetchOrders({ silent: true });
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut schimba statusul restaurantului"));
    } finally {
      setIsUpdatingRestaurantStatus(false);
    }
  };

  const toggleRestaurantStatus = async () => {
    await setRestaurantStatus({ accepting: !acceptingOrders, pauseMinutes: !acceptingOrders ? null : 30 });
  };

  // Play sound only once when NEW orders appear for the first time
  const seenOrderIdsRef = useRef(new Set());

  useEffect(() => {
    const newOrders = orders.filter(o => o.status === 'NEW');
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
      .filter((order) => order.status === "PREPARING")
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
    if (pendingOrderAction) return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }
    if (prepAvailability.blocked_short_options && minutes < prepAvailability.minimum_preparation_minutes) {
      toast.error(`Nu există livratori disponibili. Alege minimum ${prepAvailability.minimum_preparation_minutes} minute.`);
      return;
    }
    setPendingOrderAction(actionKey);
    try {
      await axios.put(`${API_URL}/api/orders/${orderId}/preparing`, {
        preparation_time: minutes
      });
      toast.success(`Timp pregătire setat: ${minutes} minute`);
      await fetchOrders({ silent: true });
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Eroare la setare timp"));
    } finally {
      setPendingOrderAction(null);
    }
  }, [fetchOrders, isOnline, pendingOrderAction, prepAvailability.blocked_short_options, prepAvailability.minimum_preparation_minutes]);

  const saveScheduleSettings = async () => {
    if (isSavingSchedule || !restaurantId) return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }
    setIsSavingSchedule(true);
    try {
      await axios.patch(`${API_URL}/api/restaurants/${restaurantId}/schedule-settings`, scheduleForm);
      toast.success("Programul de lucru a fost salvat");
      setScheduleDialogOpen(false);
      await fetchRestaurantStatus();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut salva programul"));
    } finally {
      setIsSavingSchedule(false);
    }
  };

  const createProblemOrder = async () => {
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
      });
      toast.success("Comandă legată creată pentru problemă");
      setProblemOrder(null);
      setProblemForm({ problem_type: "missing_product", item_name: "", quantity: 1, price: 0, problem_description: "" });
      await fetchOrders({ silent: true });
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut crea comanda legată"));
    } finally {
      setIsCreatingProblem(false);
    }
  };

  const markAsReady = useCallback(async (orderId) => {
    const actionKey = `ready:${orderId}`;
    if (!orderId || pendingOrderAction) return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }
    setPendingOrderAction(actionKey);
    try {
      await axios.put(`${API_URL}/api/orders/${orderId}/ready`);
      toast.success("Comanda este GATA pentru ridicare!");
      setConfirmReadyOrder(null);
      await fetchOrders({ silent: true });
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Eroare la marcare gata"));
    } finally {
      setPendingOrderAction(null);
    }
  }, [fetchOrders, isOnline, pendingOrderAction]);

  const handleCancelOrder = useCallback(async () => {
    if (isCancellingOrder) return;
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
    setIsCancellingOrder(true);
    try {
      await axios.put(`${API_URL}/api/orders/${cancelOrder.id}/status`, {
        status: "CANCELLED",
        cancellation_reason: cancelReason.trim()
      });
      toast.success("Comanda a fost anulată");
      setCancelOrder(null);
      setCancelReason("");
      await fetchOrders({ silent: true });
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Eroare la anulare"));
    } finally {
      setIsCancellingOrder(false);
    }
  }, [cancelOrder?.id, cancelReason, fetchOrders, isCancellingOrder, isOnline]);

  const orderGroups = useMemo(() => splitRestaurantOrders(orders), [orders]);
  const visibleOrders = useMemo(() => {
    if (activeView === "new") return orderGroups.newOrders;
    if (activeView === "work") return orderGroups.inWork;
    if (activeView === "delivered") return orderGroups.delivered;
    return orderGroups.active;
  }, [activeView, orderGroups]);
  const historyOrders = useMemo(() => {
    const term = historySearch.trim().toLowerCase();
    const base = orders.filter(o => ['DELIVERED', 'PICKED_UP', 'CANCELLED'].includes(o.status));
    if (!term) return base;
    return base.filter((order) => `${order.order_number || ""} ${order.customer_name || ""} ${order.customer_phone || ""} ${order.customer_address || ""} ${order.items?.map((item) => item.name).join(" ") || ""}`.toLowerCase().includes(term));
  }, [historySearch, orders]);
  const completedToday = orderGroups.delivered.length;
  const newCount = useMemo(() => orders.filter((order) => order.status === 'NEW').length, [orders]);
  const readyCount = useMemo(() => orders.filter((order) => order.status === 'READY').length, [orders]);
  const pauseSeconds = getPauseSeconds({ pause_until: restaurantPauseUntil }, now);

  const openMoreView = (view) => {
    setActiveView(view);
    setMoreDialogOpen(false);
    if (view === "analytics") fetchAnalytics();
  };

  if (isLoading) {
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
            <button
              type="button"
              onClick={toggleRestaurantStatus}
              disabled={isUpdatingRestaurantStatus || !isOnline}
              className={`inline-flex h-10 items-center gap-2 rounded-full border px-3 text-sm font-black transition-colors ${acceptingOrders ? "border-emerald-500/40 bg-emerald-500/15 text-emerald-300" : "border-red-500/40 bg-red-500/15 text-red-300"}`}
              data-testid="restaurant-operational-toggle"
            >
              <Power className="h-4 w-4" />
              <span className="hidden sm:inline">{acceptingOrders ? "Acceptă comenzi" : "Pauză"}</span>
            </button>
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
          <div className="flex items-center gap-2 text-sm text-zinc-300">
            <TimerReset className="h-4 w-4 text-orange-400" />
            <span className="font-black text-zinc-100">Pauză restaurant</span>
            {!acceptingOrders && pauseSeconds > 0 && <span className="rounded-full border border-amber-500/40 bg-amber-500/10 px-2 py-0.5 font-mono text-amber-200" data-testid="restaurant-compact-pause-countdown">{formatSeconds(pauseSeconds)}</span>}
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Button size="sm" className="bg-emerald-600 hover:bg-emerald-500" onClick={() => setRestaurantStatus({ accepting: true })} disabled={isUpdatingRestaurantStatus} data-testid="restaurant-compact-online-button">Online</Button>
            <Input type="number" min="1" max="720" value={manualPauseMinutes} onChange={(event) => setManualPauseMinutes(Number(event.target.value) || 30)} className="h-9 w-24 border-zinc-700 bg-zinc-950 text-zinc-50" data-testid="restaurant-compact-manual-pause-input" />
            <Button size="sm" className="bg-orange-500 font-black text-zinc-950 hover:bg-orange-400" onClick={() => setRestaurantStatus({ accepting: false, pauseMinutes: manualPauseMinutes })} disabled={isUpdatingRestaurantStatus} data-testid="restaurant-compact-manual-pause-button">Setează min</Button>
            <Button size="sm" variant="outline" className="border-red-500/40 bg-red-500/10 text-red-200 hover:bg-red-500/20" onClick={() => setRestaurantStatus({ accepting: false, closedToday: true })} disabled={isUpdatingRestaurantStatus} data-testid="restaurant-compact-close-today-button">Închide azi</Button>
          </div>
        </section>

        {prepAvailability.blocked_short_options && !["analytics", "history"].includes(activeView) && (
          <div className="rounded-xl border border-amber-500/40 bg-amber-500/10 p-3 text-sm text-amber-100" data-testid="restaurant-prep-driver-warning">
            <AlertTriangle className="mr-2 inline h-4 w-4" /> Nu există livratori disponibili acum. Timpii sub {prepAvailability.minimum_preparation_minutes} minute sunt blocați ca să nu genereze întârzieri.
          </div>
        )}

        {activeView === "history" && (
          <section className="rounded-2xl border border-zinc-800 bg-zinc-900 p-4" data-testid="restaurant-history-panel">
            <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
              <h2 className="flex items-center gap-2 text-xl font-black"><History className="h-5 w-5 text-orange-400" /> Istoric comenzi</h2>
              <div className="relative w-full sm:w-80"><Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-zinc-500" /><Input value={historySearch} onChange={(event) => setHistorySearch(event.target.value)} className="border-zinc-700 bg-zinc-950 pl-9 text-zinc-100" placeholder="Caută client, telefon, adresă, produs" data-testid="restaurant-history-search-input" /></div>
            </div>
            <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
              {historyOrders.map((order) => <button type="button" onClick={() => setHistoryDetailOrder(order)} key={order.id} className="rounded-xl border border-zinc-800 bg-black/20 p-3 text-left transition-colors hover:border-orange-500/40 hover:bg-orange-500/5" data-testid={`restaurant-history-order-${order.id}`}><div className="flex justify-between gap-3"><span className="font-mono text-sm font-black text-zinc-300">{order.order_number}</span>{getStatusConfig(order.status).label}</div><p className="mt-2 font-bold">{order.customer_name}</p><p className="text-sm text-zinc-400">{order.customer_phone} · {order.total_amount} RON</p><p className="mt-1 line-clamp-2 text-xs text-zinc-500">{order.customer_address}</p></button>)}
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
          <section className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4" data-testid="restaurant-kds-grid">
            {visibleOrders.map((order) => {
              const timer = getPreparationTimer(order, now);
              const lane = orderLaneMeta[order.status] || orderLaneMeta.NEW;
              const LaneIcon = lane.icon;
              return (
                <article key={order.id} className={`flex min-h-[420px] flex-col rounded-2xl border bg-zinc-900 p-4 shadow-xl transition-colors hover:border-zinc-700 ${order.status === "NEW" ? "border-orange-500/50" : "border-zinc-800"}`} data-testid={`order-card-${order.id}`}>
                  <div className="mb-3 flex items-start justify-between gap-3 border-b border-zinc-800 pb-3">
                    <div className="min-w-0">
                      <p className="font-mono text-sm font-black text-zinc-400">{order.order_number}</p>
                      <h3 className="mt-1 truncate text-xl font-black text-white">{order.customer_name}</h3>
                    </div>
                    <Badge className={`${lane.className} border`}><LaneIcon className="mr-1 h-3.5 w-3.5" />{lane.title}</Badge>
                  </div>

                  <div className="space-y-3">
                    <div className="rounded-xl border border-zinc-800 bg-black/30 p-3">
                      <div className="mb-2 flex items-center justify-between text-xs text-zinc-500"><span>Produse</span><span>{order.items?.length || 0} poziții</span></div>
                      <div className="space-y-2">
                        {order.items?.map((item) => (
                          <div key={`${order.id}-${item.name}-${item.price}-${item.quantity}`} className="flex items-start justify-between gap-3 border-b border-zinc-800/70 pb-2 last:border-0 last:pb-0">
                            <span className="text-sm font-semibold text-zinc-100">{item.quantity}× {item.name}</span>
                            <span className="font-mono text-sm text-zinc-400">{item.price * item.quantity}</span>
                          </div>
                        ))}
                      </div>
                      <div className="mt-3 flex items-center justify-between border-t border-zinc-800 pt-3 text-lg font-black"><span>Total</span><span className="text-orange-300">{order.total_amount} RON</span></div>
                    </div>

                    <div className="space-y-2 text-sm text-zinc-400">
                      <p className="flex gap-2"><User className="mt-0.5 h-4 w-4 text-zinc-500" /><span className="min-w-0 truncate">{order.customer_name}</span></p>
                      <p className="flex gap-2"><Phone className="mt-0.5 h-4 w-4 text-zinc-500" /><span className="font-mono text-zinc-200" data-testid={`restaurant-order-phone-${order.id}`}>{order.customer_phone}</span></p>
                      <p className="flex gap-2"><MapPin className="mt-0.5 h-4 w-4 shrink-0 text-zinc-500" /><span className="line-clamp-2">{order.customer_address}</span></p>
                      {order.notes && <p className="rounded-lg border border-orange-500/20 bg-orange-500/10 p-2 text-orange-200">📝 {order.notes}</p>}
                    </div>

                    {order.driver_name && <div className="flex items-center gap-2 rounded-xl border border-blue-500/20 bg-blue-500/10 p-2 text-sm font-semibold text-blue-200"><Truck className="h-4 w-4" /> Livrator: {order.driver_name}</div>}
                  </div>

                  <div className="mt-auto space-y-3 pt-4">
                    {order.status === 'NEW' && (
                      <div className="space-y-2" data-testid={`prep-options-${order.id}`}>
                        <p className="text-xs font-black uppercase tracking-[0.15em] text-zinc-500">Setează timp</p>
                        <div className="grid grid-cols-3 gap-2">
                          {PREPARATION_OPTIONS_MINUTES.map((minutes) => (
                            <Button key={minutes} variant="outline" disabled={!isOnline || pendingOrderAction !== null || (prepAvailability.blocked_short_options && minutes < prepAvailability.minimum_preparation_minutes)} onClick={() => setPreparationTime(order.id, minutes)} className="h-11 border-zinc-700 bg-zinc-800 text-zinc-100 hover:bg-orange-500 hover:text-zinc-950 disabled:opacity-40" data-testid={`prep-${minutes}-${order.id}`}>{minutes}m</Button>
                          ))}
                        </div>
                      </div>
                    )}

                    {order.status === 'PREPARING' && (
                      <div className={`rounded-xl border p-4 ${timer?.isLate ? "border-red-500/50 bg-red-500/10" : "border-orange-500/40 bg-orange-500/10"}`} data-testid={`preparation-timer-${order.id}`}>
                        <div className="flex items-center justify-between gap-3">
                          <div><p className="text-xs font-black uppercase tracking-[0.15em] text-zinc-500">Timer</p><p className="text-sm text-zinc-400">Estimare {order.preparation_time || "-"} min</p></div>
                          <p className={`font-mono text-4xl font-black ${timer?.isLate ? "animate-pulse text-red-300" : "text-orange-300"}`} data-testid={`restaurant-timer-display-${order.id}`}>{timer?.label || "--:--"}</p>
                        </div>
                        <Button className="mt-3 h-13 w-full bg-emerald-500 font-black text-emerald-950 hover:bg-emerald-400" onClick={() => setConfirmReadyOrder(order)} disabled={!isOnline || pendingOrderAction !== null} data-testid={`ready-${order.id}`}><CheckCircle2 className="mr-2 h-5 w-5" /> COMANDA GATA</Button>
                      </div>
                    )}

                    {order.status === 'READY' && <div className="rounded-xl border border-emerald-500/40 bg-emerald-500/10 p-4 text-center text-emerald-200"><CheckCircle2 className="mx-auto mb-1 h-8 w-8" /><p className="font-black">GATA PENTRU RIDICARE</p><p className="text-sm opacity-80">Așteptăm livratorul</p></div>}

                    {['ASSIGNED', 'ACCEPTED'].includes(order.status) && <div className="rounded-xl border border-sky-500/40 bg-sky-500/10 p-4 text-center text-sky-200"><Truck className="mx-auto mb-1 h-8 w-8" /><p className="font-black">LIVRATORUL VINE</p><p className="text-sm opacity-80">{order.driver_name} preia comanda</p></div>}

                    {order.status === 'DELIVERED' && <Button variant="outline" className="h-11 w-full border-amber-500/30 bg-amber-500/10 text-amber-200 hover:bg-amber-500/20" onClick={() => { setProblemOrder(order); setProblemForm({ problem_type: "missing_product", item_name: "", quantity: 1, price: 0, problem_description: "" }); }} data-testid={`problem-${order.id}`}><PlusCircle className="mr-2 h-4 w-4" /> Problemă comandă</Button>}
                    {['NEW', 'PREPARING', 'READY'].includes(order.status) && <Button variant="outline" className="h-11 w-full border-red-500/30 bg-red-500/10 text-red-300 hover:bg-red-500/20" onClick={() => { setCancelOrder(order); setCancelReason(""); }} disabled={!isOnline || pendingOrderAction !== null || isCancellingOrder} data-testid={`cancel-${order.id}`}><XCircle className="mr-2 h-4 w-4" /> Anulează</Button>}
                  </div>
                </article>
              );
            })}
          </section>
        )}
      </main>

      {/* Confirm Ready Dialog */}
      <Dialog open={!!confirmReadyOrder} onOpenChange={(open) => !open && setConfirmReadyOrder(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-orange-500" />
              Confirmare - Comanda Gata
            </DialogTitle>
            <DialogDescription>Confirmă trecerea comenzii în status gata pentru ridicare.</DialogDescription>
          </DialogHeader>
          <div className="py-4">
            <p className="text-base">
              Confirmați că comanda <strong>{confirmReadyOrder?.order_number}</strong> este gata pentru ridicare?
            </p>
            <p className="text-sm text-muted-foreground mt-2">
              După confirmare, livratorul va fi notificat să ridice comanda.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmReadyOrder(null)} data-testid="cancel-ready-confirm">
              Înapoi
            </Button>
            <Button
              className="bg-green-600 hover:bg-green-700"
              onClick={() => markAsReady(confirmReadyOrder?.id)}
              disabled={!isOnline || pendingOrderAction !== null}
              data-testid="confirm-ready-btn"
            >
              <CheckCircle2 className="w-4 h-4 mr-2" />
              {pendingOrderAction !== null ? "Se procesează..." : "Da, Comanda e Gata"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={scheduleDialogOpen} onOpenChange={setScheduleDialogOpen}>
        <DialogContent className="max-w-2xl" data-testid="restaurant-schedule-dialog">
          <DialogHeader><DialogTitle>Program de lucru restaurant</DialogTitle><DialogDescription>Setează zilele active și intervalele orare ale restaurantului.</DialogDescription></DialogHeader>
          <div className="max-h-[65vh] space-y-3 overflow-y-auto">
            {RESTAURANT_DAYS.map((day) => {
              const value = scheduleForm[day.key] || { enabled: true, open_time: "10:00", close_time: "22:00" };
              return <div key={day.key} className="grid items-center gap-2 rounded-lg border p-3 sm:grid-cols-[110px_1fr_1fr_1fr]" data-testid={`restaurant-schedule-day-${day.key}`}><Label className="font-black">{day.label}</Label><Button type="button" variant={value.enabled ? "default" : "outline"} onClick={() => setScheduleForm((prev) => ({ ...prev, [day.key]: { ...value, enabled: !value.enabled } }))} data-testid={`restaurant-schedule-enabled-${day.key}`}>{value.enabled ? "Deschis" : "Închis"}</Button><Input type="time" value={value.open_time} onChange={(event) => setScheduleForm((prev) => ({ ...prev, [day.key]: { ...value, open_time: event.target.value } }))} data-testid={`restaurant-schedule-open-${day.key}`} /><Input type="time" value={value.close_time} onChange={(event) => setScheduleForm((prev) => ({ ...prev, [day.key]: { ...value, close_time: event.target.value } }))} data-testid={`restaurant-schedule-close-${day.key}`} /></div>;
            })}
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setScheduleDialogOpen(false)} disabled={isSavingSchedule} data-testid="restaurant-schedule-cancel-button">Anulează</Button><Button onClick={saveScheduleSettings} disabled={isSavingSchedule || !isOnline} data-testid="restaurant-schedule-save-button">{isSavingSchedule ? "Se salvează..." : "Salvează program"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={moreDialogOpen} onOpenChange={setMoreDialogOpen}>
        <DialogContent className="max-w-xl border-zinc-800 bg-zinc-950 text-zinc-50" data-testid="restaurant-more-dialog">
          <DialogHeader><DialogTitle className="flex items-center gap-2"><SlidersHorizontal className="h-5 w-5 text-orange-400" /> Mai mult</DialogTitle><DialogDescription className="text-zinc-400">Setări operaționale și zone secundare, fără să aglomerăm dashboardul principal.</DialogDescription></DialogHeader>
          <div className="grid gap-3 sm:grid-cols-2">
            <button type="button" onClick={() => openMoreView("history")} className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 text-left hover:border-orange-500/40" data-testid="restaurant-more-history-button"><History className="mb-3 h-5 w-5 text-orange-400" /><p className="font-black">Istoric comenzi</p><p className="mt-1 text-sm text-zinc-400">Caută și deschide detalii complete.</p></button>
            <button type="button" onClick={() => openMoreView("analytics")} className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 text-left hover:border-orange-500/40" data-testid="restaurant-more-analytics-button"><BarChart3 className="mb-3 h-5 w-5 text-orange-400" /><p className="font-black">Analytics</p><p className="mt-1 text-sm text-zinc-400">Grafice și timpi operaționali.</p></button>
            <button type="button" onClick={() => { setScheduleDialogOpen(true); setMoreDialogOpen(false); }} className="rounded-xl border border-zinc-800 bg-zinc-900 p-4 text-left hover:border-orange-500/40" data-testid="restaurant-more-schedule-button"><CalendarDays className="mb-3 h-5 w-5 text-orange-400" /><p className="font-black">Program lucru</p><p className="mt-1 text-sm text-zinc-400">Zile și ore de funcționare.</p></button>
            <div className="rounded-xl border border-zinc-800 bg-zinc-900 p-4" data-testid="restaurant-more-pause-panel"><TimerReset className="mb-3 h-5 w-5 text-orange-400" /><p className="font-black">Pauză restaurant</p><div className="mt-3 flex items-center gap-2"><Input type="number" min="1" max="720" value={manualPauseMinutes} onChange={(event) => setManualPauseMinutes(Number(event.target.value) || 30)} className="border-zinc-700 bg-zinc-950 text-zinc-50" data-testid="restaurant-manual-pause-input" /><span className="text-sm text-zinc-400">min</span></div><div className="mt-3 flex flex-wrap gap-2"><Button size="sm" className="bg-emerald-600 hover:bg-emerald-500" onClick={() => setRestaurantStatus({ accepting: true })} disabled={isUpdatingRestaurantStatus || !isOnline} data-testid="restaurant-resume-orders-button">Online</Button><Button size="sm" className="bg-orange-500 font-black text-zinc-950 hover:bg-orange-400" onClick={() => setRestaurantStatus({ accepting: false, pauseMinutes: manualPauseMinutes })} disabled={isUpdatingRestaurantStatus || !isOnline} data-testid="restaurant-manual-pause-button">Setează pauză</Button><Button size="sm" variant="outline" className="border-red-500/40 bg-red-500/10 text-red-200 hover:bg-red-500/20" onClick={() => setRestaurantStatus({ accepting: false, closedToday: true })} disabled={isUpdatingRestaurantStatus || !isOnline} data-testid="restaurant-close-today-button">Închide azi</Button></div></div>
            <div className="rounded-xl border border-dashed border-zinc-700 bg-zinc-900/60 p-4 sm:col-span-2" data-testid="restaurant-more-future-catalog"><BookOpen className="mb-3 h-5 w-5 text-zinc-500" /><p className="font-black text-zinc-300">Catalog produse / meniu</p><p className="mt-1 text-sm text-zinc-500">Pregătit pentru viitoarea aplicație de client: produse, categorii, meniu și disponibilitate.</p></div>
          </div>
        </DialogContent>
      </Dialog>

      <Dialog open={!!historyDetailOrder} onOpenChange={(open) => !open && setHistoryDetailOrder(null)}>
        <DialogContent className="max-w-2xl border-zinc-800 bg-zinc-950 text-zinc-50" data-testid="restaurant-history-detail-dialog">
          <DialogHeader><DialogTitle>Detalii comandă · {historyDetailOrder?.order_number}</DialogTitle><DialogDescription className="text-zinc-400">Toate informațiile salvate pentru comanda selectată.</DialogDescription></DialogHeader>
          {historyDetailOrder && <div className="space-y-4"><div className="grid gap-3 sm:grid-cols-2"><div className="rounded-xl border border-zinc-800 bg-zinc-900 p-3"><p className="text-xs text-zinc-500">Client</p><p className="font-black">{historyDetailOrder.customer_name}</p><p className="font-mono text-sm text-zinc-300">{historyDetailOrder.customer_phone}</p></div><div className="rounded-xl border border-zinc-800 bg-zinc-900 p-3"><p className="text-xs text-zinc-500">Adresă</p><p className="text-sm text-zinc-300">{historyDetailOrder.customer_address}</p></div><div className="rounded-xl border border-zinc-800 bg-zinc-900 p-3"><p className="text-xs text-zinc-500">Status</p><p className="font-black">{getStatusConfig(historyDetailOrder.status).label}</p></div><div className="rounded-xl border border-zinc-800 bg-zinc-900 p-3"><p className="text-xs text-zinc-500">Total</p><p className="text-2xl font-black text-orange-300">{historyDetailOrder.total_amount} RON</p></div></div><div className="rounded-xl border border-zinc-800 bg-black/30 p-3"><p className="mb-2 font-black">Produse</p>{historyDetailOrder.items?.map((item) => <div key={`${historyDetailOrder.id}-${item.name}`} className="flex justify-between border-b border-zinc-800 py-2 text-sm last:border-0"><span>{item.quantity}× {item.name}</span><span className="font-mono text-zinc-400">{item.price * item.quantity} RON</span></div>)}</div>{historyDetailOrder.driver_name && <div className="rounded-xl border border-blue-500/30 bg-blue-500/10 p-3 text-blue-100"><Truck className="mr-2 inline h-4 w-4" /> Livrator: {historyDetailOrder.driver_name}</div>}{historyDetailOrder.notes && <div className="rounded-xl border border-orange-500/30 bg-orange-500/10 p-3 text-orange-100">Notă: {historyDetailOrder.notes}</div>}{historyDetailOrder.status === "DELIVERED" && <Button className="w-full bg-orange-500 font-black text-zinc-950 hover:bg-orange-400" onClick={() => { setProblemOrder(historyDetailOrder); setHistoryDetailOrder(null); }} data-testid="history-detail-problem-button"><PlusCircle className="mr-2 h-4 w-4" /> Produs lipsă / adaugă produs</Button>}</div>}
        </DialogContent>
      </Dialog>

      <Dialog open={!!problemOrder} onOpenChange={(open) => !open && setProblemOrder(null)}>
        <DialogContent data-testid="restaurant-problem-order-dialog">
          <DialogHeader><DialogTitle>Comandă cu problemă · {problemOrder?.order_number}</DialogTitle><DialogDescription>Creează o comandă nouă legată de comanda originală.</DialogDescription></DialogHeader>
          <div className="space-y-3">
            <div className="grid grid-cols-2 gap-2"><Button type="button" variant={problemForm.problem_type === "missing_product" ? "default" : "outline"} onClick={() => setProblemForm((prev) => ({ ...prev, problem_type: "missing_product" }))} data-testid="problem-type-missing-button">Produs lipsă</Button><Button type="button" variant={problemForm.problem_type === "new_product" ? "default" : "outline"} onClick={() => setProblemForm((prev) => ({ ...prev, problem_type: "new_product" }))} data-testid="problem-type-new-button">Produs nou</Button></div>
            <div><Label>Produs</Label><Input value={problemForm.item_name} onChange={(event) => setProblemForm((prev) => ({ ...prev, item_name: event.target.value }))} placeholder="Ex: Sos usturoi / Pizza extra" data-testid="problem-item-name-input" /></div>
            <div className="grid grid-cols-2 gap-3"><div><Label>Cantitate</Label><Input type="number" min="1" value={problemForm.quantity} onChange={(event) => setProblemForm((prev) => ({ ...prev, quantity: event.target.value }))} data-testid="problem-quantity-input" /></div><div><Label>Preț</Label><Input type="number" min="0" value={problemForm.price} onChange={(event) => setProblemForm((prev) => ({ ...prev, price: event.target.value }))} data-testid="problem-price-input" /></div></div>
            <div><Label>Descriere problemă</Label><Textarea value={problemForm.problem_description} onChange={(event) => setProblemForm((prev) => ({ ...prev, problem_description: event.target.value }))} placeholder="Ce trebuie să știe dispeceratul/livratorul?" data-testid="problem-description-input" /></div>
          </div>
          <DialogFooter><Button variant="outline" onClick={() => setProblemOrder(null)} disabled={isCreatingProblem} data-testid="problem-cancel-button">Anulează</Button><Button onClick={createProblemOrder} disabled={isCreatingProblem || !isOnline} data-testid="problem-submit-button">{isCreatingProblem ? "Se creează..." : "Creează comandă legată"}</Button></DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Cancel Order Dialog */}
      <Dialog open={!!cancelOrder} onOpenChange={(open) => !open && setCancelOrder(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-600">
              <XCircle className="w-5 h-5" />
              Anulare Comandă {cancelOrder?.order_number}
            </DialogTitle>
            <DialogDescription>Completează motivul anulării pentru trasabilitate.</DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <p className="text-sm text-muted-foreground">
              Motivul anulării este obligatoriu. Vă rugăm să specificați de ce anulați această comandă.
            </p>
            <Textarea
              placeholder="Scrieți motivul anulării..."
              value={cancelReason}
              onChange={(e) => setCancelReason(e.target.value)}
              className="min-h-[100px]"
              data-testid="cancel-reason-input"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCancelOrder(null)}>
              Înapoi
            </Button>
            <Button
              variant="destructive"
              onClick={handleCancelOrder}
              disabled={isCancellingOrder || !cancelReason.trim() || !isOnline}
              data-testid="confirm-cancel-btn"
            >
              <XCircle className="w-4 h-4 mr-2" />
              {isCancellingOrder ? "Se anulează..." : "Confirmă Anularea"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default RestaurantApp;
