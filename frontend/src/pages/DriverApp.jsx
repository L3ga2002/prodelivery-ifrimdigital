import { readCustodyActivity } from "../lib/orderCustody";
import { useOrderCustodyRecovery } from "../hooks/useOrderCustodyRecovery";
import { CustodyControls, CustodyRecoveryPanel, OrderCustodySummary } from "../components/OrderCustody";
import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "../context/AuthContext";
import { OperationalIncidentReporter, IncidentSummary } from "../components/OperationalIncidentReporter";
import { OrderFinancialSummary } from "../components/OrderFinancialSummary";
import { clientCollectionText } from "../lib/orderFinance";
import { FinancialEventControls, FinancialEventRecoveryPanel } from "../components/OrderFinancialActivity";
import { financialPickupBlocked } from "../lib/orderFinancialActivity";
import { useOrderFinancialEventRecovery } from "../hooks/useOrderFinancialEventRecovery";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import {
  CalendarDays,
  Camera,
  Check,
  LogOut,
  Package,
  MapPin,
  Phone,
  User,
  Navigation,
  CheckCircle2,
  Bike,
  RefreshCw,
  Clock,
  Download,
  XCircle,
  AlertTriangle,
  ShieldCheck,
  Home,
  ClipboardList,
  WalletCards,
  BarChart3,
  Store,
  Mail,
  IdCard,
  Cake,
  VenusAndMars,
  Menu,
} from "lucide-react";
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "../components/ui/dialog";
import { Textarea } from "../components/ui/textarea";
import { DriverSchedule } from "../components/DriverSchedule";
import { AvatarUploadCropper } from "../components/AvatarUploadCropper";
import { DriverAvatar } from "../components/DriverAvatar";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../components/ui/select";
import { getApiErrorMessage, normalizeArray, normalizeObject, retryApiCall } from "../lib/api";
import { useNetworkStatus } from "../hooks/useNetworkStatus";
import { getPreparationStatus, isActionableDriverOrder } from "../lib/orderWorkflow";
import { useOrderStatusRecovery, OrderStatusRecoveryPanel } from "../hooks/useOrderStatusRecovery";
import { hasStatusRevision, canChangeOrderStatus, statusApplied } from "../lib/orderStatusRecovery";

const API_URL = process.env.REACT_APP_BACKEND_URL;
const DRIVER_ORDER_POLL_INTERVAL_MS = 5000;
const NEW_ORDER_FLASH_MS = 5000;

// PWA Install prompt
let deferredPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  deferredPrompt = e;
});

const getStatusConfig = (status) => {
  const config = {
    ASSIGNED: { label: "Alocată", color: "bg-blue-500", textColor: "text-blue-800 dark:text-blue-100", bgColor: "bg-blue-100 dark:bg-blue-950/40" },
    ACCEPTED: { label: "Primire confirmată", color: "bg-purple-500", textColor: "text-purple-800 dark:text-purple-100", bgColor: "bg-purple-100 dark:bg-purple-950/40" },
    PICKED_UP: { label: "Ridicată", color: "bg-orange-500", textColor: "text-orange-800 dark:text-orange-100", bgColor: "bg-orange-100 dark:bg-orange-950/40" },
    DELIVERED: { label: "Livrată", color: "bg-green-500", textColor: "text-green-800 dark:text-green-100", bgColor: "bg-green-100 dark:bg-green-950/40" },
  };
  return config[status] || { label: status, color: "bg-gray-500", textColor: "text-gray-800 dark:text-slate-100", bgColor: "bg-gray-100 dark:bg-slate-800" };
};

const splitName = (name = "") => {
  const parts = name.trim().split(/\s+/).filter(Boolean);
  return { first_name: parts[0] || "", last_name: parts.slice(1).join(" ") || "" };
};

const isValidPhone = (phone = "") => /^(07\d{8}|\+407\d{8})$/.test(phone.replace(/\s/g, ""));
const isValidCnp = (cnp = "") => cnp === "" || /^\d{13}$/.test(cnp);
const validDriverDashboard = (response, driverId) => {
  const driver = response?.data?.driver;
  return response?.status === 200 && driver?.id === driverId &&
    ["active", "delivery", "break", "offline"].includes(driver.operational_status) &&
    typeof driver.operational_status_label === "string" && driver.operational_status_label.trim().length > 0 &&
    Number.isSafeInteger(driver.total_deliveries) && driver.total_deliveries >= 0 &&
    typeof driver.total_earnings === "number" && Number.isFinite(driver.total_earnings) && driver.total_earnings >= 0;
};

const formatScheduleDay = (date) => date.toLocaleDateString("ro-RO", { weekday: "short", day: "2-digit", month: "2-digit" });

const ProDeliveryMark = ({ dark = true, testId = "prodelivery-mark" }) => (
  <div className="inline-flex flex-col items-center" data-testid={testId}>
    <div className="relative h-14 w-24">
      <Bike className="absolute left-7 top-1 h-12 w-12 text-orange-500" strokeWidth={2.8} />
      <span className="absolute left-1 top-5 h-1 w-9 rounded-full bg-orange-500" />
      <span className="absolute left-4 top-9 h-1 w-6 rounded-full bg-orange-500" />
    </div>
    <div className="text-2xl font-black italic tracking-tight">
      <span className={dark ? "text-orange-500" : "text-slate-700"}>Pro</span><span className={dark ? "text-white" : "text-orange-600"}>Delivery</span>
    </div>
  </div>
);

export const getCurrentStepLabel = (order) => {
  if (!order) return "Fără comandă";
  const custody = readCustodyActivity(order);
  if (custody.state === "invalid") return "Verifică evidența produselor";
  if (custody.value?.status === "return_requested") return "Returnează produsele restaurantului";
  if (custody.value?.status === "keep_authorized") return "Confirmă instrucțiunea de păstrare";
  const labels = {
    ASSIGNED: "Comandă primită",
    ACCEPTED: "Mergi la restaurant",
    PICKED_UP: "Livrează clientului",
  };
  return labels[order.status] || "Finalizată";
};

const DriverApp = () => {
  const { user, token, logout } = useAuth();
  const { isOnline } = useNetworkStatus();
  const statusRecovery = useOrderStatusRecovery(user, API_URL, isOnline, token, false);
  const financialRecovery = useOrderFinancialEventRecovery(user, API_URL, isOnline, token);
  const custodyRecovery = useOrderCustodyRecovery(user, API_URL, isOnline, token);
  const custodyBusy = Boolean(custodyRecovery.record || custodyRecovery.storageInvalid || custodyRecovery.busy || custodyRecovery.sessionSuspended);
  const [custodyIncident, setCustodyIncident] = useState(null);
  const statusMutationRef = useRef(false), handledStatusReceipt = useRef(null), statusSession = useRef(null);
  const statusMounted = useRef(false);
  if (statusSession.current?.actor !== user?.id || statusSession.current?.token !== token || statusSession.current?.resource !== user?.driver_id) {
    statusSession.current = { actor: user?.id, token, resource: user?.driver_id };
  }
  useEffect(() => { statusMounted.current = true; return () => { statusMounted.current = false; }; }, []);
  const [currentOrder, setCurrentOrder] = useState(null);
  const verifyStatusCapability = statusRecovery.verifyCapability;
  const currentStatusVersioned = hasStatusRevision(currentOrder);
  useEffect(() => { if (currentStatusVersioned && isOnline) void verifyStatusCapability(); }, [currentStatusVersioned, currentOrder?.id, isOnline, verifyStatusCapability]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshingOrder, setIsRefreshingOrder] = useState(false);
  const [isUpdating, setIsUpdating] = useState(false);
  const [isSavingOperationalStatus, setIsSavingOperationalStatus] = useState(false);
  const [isCancellingOrder, setIsCancellingOrder] = useState(false);
  const [canInstall, setCanInstall] = useState(false);
  const [activeTab, setActiveTab] = useState("home");
  const lastOrderIdRef = useRef(null);
  const hasLoadedOrdersRef = useRef(false);
  const fetchOrderRequestRef = useRef(0);
  const fetchDriverProfileRequestRef = useRef(0);
  const profileFlightRef = useRef(null);
  const [newOrderFlash, setNewOrderFlash] = useState(false);
  const [emailCode, setEmailCode] = useState("");
  const [emailVerified, setEmailVerified] = useState(user?.email_verified !== false);
  const [isVerifyingEmail, setIsVerifyingEmail] = useState(false);
  const [confirmAction, setConfirmAction] = useState(null); // {status, label}
  const [cancelDialog, setCancelDialog] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [driverDashboard, setDriverDashboard] = useState(null);
  const [driverProfileState, setDriverProfileState] = useState({ fresh: false, busy: false, error: "" });
  const [driverStatusForm, setDriverStatusForm] = useState({ status: "active", break_minutes: 30 });
  const [avatarUploading, setAvatarUploading] = useState(false);
  const [savingProfile, setSavingProfile] = useState(false);
  const [profileForm, setProfileForm] = useState({
    first_name: "",
    last_name: "",
    birth_date: "",
    gender: "masculin",
    cnp: "",
    phone: "",
    email: "",
  });

  // Check if PWA can be installed
  useEffect(() => {
    const checkInstall = () => {
      setCanInstall(!!deferredPrompt);
    };
    checkInstall();
    window.addEventListener('beforeinstallprompt', checkInstall);
    return () => window.removeEventListener('beforeinstallprompt', checkInstall);
  }, []);

  const installPWA = async () => {
    if (!deferredPrompt) return;
    deferredPrompt.prompt();
    const { outcome } = await deferredPrompt.userChoice;
    if (outcome === 'accepted') {
      toast.success('Aplicație instalată cu succes!');
      setCanInstall(false);
    }
    deferredPrompt = null;
  };

  const fetchOrder = useCallback(async ({ manual = false, silent = false, isCurrent = () => true } = {}) => {
    const session = statusSession.current;
    if (!isCurrent()) return;
    if (!statusMounted.current || session?.actor !== user?.id || session?.token !== token || session?.resource !== user?.driver_id) return;
    if (!user?.driver_id) {
      setIsLoading(false);
      return;
    }

    const requestId = fetchOrderRequestRef.current + 1;
    fetchOrderRequestRef.current = requestId;
    if (manual) setIsRefreshingOrder(true);
    try {
      const response = await retryApiCall(() => {
        if (!isCurrent()) throw new Error("SESSION_CHANGED");
        return axios.get(`${API_URL}/api/orders/driver/${user.driver_id}`, { timeout: 15000 });
      });
      if (!isCurrent() || requestId !== fetchOrderRequestRef.current || statusMutationRef.current || statusSession.current !== session || !statusMounted.current) return;
      const orders = normalizeArray(response.data);
      const activeOrder = orders.find(isActionableDriverOrder);

      // Play notification sound for new order
      if (activeOrder && activeOrder.id !== lastOrderIdRef.current) {
        const prevId = lastOrderIdRef.current;
        lastOrderIdRef.current = activeOrder.id;
        if (prevId !== null || hasLoadedOrdersRef.current) {
          // Flash banner
          setNewOrderFlash(true);
          setTimeout(() => setNewOrderFlash(false), NEW_ORDER_FLASH_MS);
          try {
            const ctx = new (window.AudioContext || window.webkitAudioContext)();
            const playBeep = (freq, startTime, duration) => {
              const osc = ctx.createOscillator();
              const gain = ctx.createGain();
              osc.connect(gain);
              gain.connect(ctx.destination);
              osc.frequency.value = freq;
              osc.type = 'sine';
              gain.gain.value = 0.4;
              osc.start(ctx.currentTime + startTime);
              osc.stop(ctx.currentTime + startTime + duration);
            };
            playBeep(600, 0, 0.15);
            playBeep(800, 0.2, 0.15);
            playBeep(1000, 0.4, 0.25);
            if (navigator.vibrate) navigator.vibrate([200, 100, 200, 100, 300]);
          } catch {
            // Audio/vibration may be blocked until user interaction.
          }
        }
      }

      setCurrentOrder(activeOrder || null);
    } catch (error) {
      if (isCurrent() && requestId === fetchOrderRequestRef.current && statusSession.current === session && statusMounted.current) {
        if (!silent) {
          toast.error(getApiErrorMessage(error, "Nu am putut încărca livrarea curentă"));
        }
      }
    } finally {
      if (isCurrent() && requestId === fetchOrderRequestRef.current && statusSession.current === session && statusMounted.current) {
        setIsLoading(false);
        hasLoadedOrdersRef.current = true;
      }
      if (isCurrent() && manual && statusSession.current === session && statusMounted.current) setIsRefreshingOrder(false);
    }
  }, [user?.driver_id, user?.id, token]);

  const fetchDriverProfile = useCallback(async ({ silent = false, hydrateForms = true, manual = false } = {}) => {
    const session = statusSession.current;
    if (!statusMounted.current || !user?.driver_id || session?.actor !== user?.id || session?.token !== token || session?.resource !== user?.driver_id) return;
    if (manual && profileFlightRef.current?.session === session) return;
    const requestId = ++fetchDriverProfileRequestRef.current;
    const job = { session, requestId }; profileFlightRef.current = job;
    const ownsRequest = () => statusMounted.current && statusSession.current === session && requestId === fetchDriverProfileRequestRef.current;
    setDriverProfileState({ session, fresh: false, busy: true, error: "" });
    try {
      const response = await retryApiCall(() => {
        if (!ownsRequest()) throw new Error("SESSION_CHANGED");
        return axios.get(`${API_URL}/api/drivers/${session.resource}/dashboard`, { timeout: 15000,
          headers: { Authorization: token ? `Bearer ${token}` : null, "X-Expected-Actor-ID": session.actor } });
      });
      if (!ownsRequest()) return;
      if (!validDriverDashboard(response, session.resource)) throw new Error("INVALID_DRIVER_DASHBOARD");
      const dashboard = normalizeObject(response.data);
      const driver = normalizeObject(dashboard.driver);
      setDriverDashboard(dashboard);
      setDriverProfileState({ session, fresh: true, busy: false, error: "" });
      if (!hydrateForms) return;
      const fallback = splitName(driver.name || user?.name || "");
      setProfileForm({
        first_name: driver.first_name || fallback.first_name,
        last_name: driver.last_name || fallback.last_name,
        birth_date: driver.birth_date || "",
        gender: driver.gender || "masculin",
        cnp: driver.cnp || "",
        phone: driver.phone || user?.phone || "",
        email: driver.email || user?.email || "",
      });
      const status = driver.operational_status || "active";
      setDriverStatusForm((prev) => ({
        ...prev,
        status: status === "delivery" ? "active" : status,
      }));
    } catch (error) {
      if (ownsRequest()) {
        setDriverProfileState({ session, fresh: false, busy: false,
          error: error.message === "INVALID_DRIVER_DASHBOARD" ? "Raspunsul dashboard-ului este incomplet sau invalid." : "Dashboard-ul nu poate fi verificat." });
        if (!silent) toast.error(getApiErrorMessage(error, "Nu am putut încărca profilul livratorului"));
      }
    } finally {
      if (profileFlightRef.current === job) profileFlightRef.current = null;
    }
  }, [user?.driver_id, user?.id, token, user?.email, user?.name, user?.phone]);

  useEffect(() => {
    setEmailVerified(user?.email_verified !== false);
  }, [user?.email_verified]);

  const verifyEmailCode = async () => {
    if (isVerifyingEmail) return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }
    if (!emailCode.trim()) {
      toast.error("Introdu codul primit pe email");
      return;
    }
    setIsVerifyingEmail(true);
    try {
      await axios.post(`${API_URL}/api/drivers/${user.driver_id}/verify-email`, { code: emailCode.trim() });
      setEmailVerified(true);
      setEmailCode("");
      toast.success("Email verificat cu succes");
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Cod invalid sau expirat"));
    } finally {
      setIsVerifyingEmail(false);
    }
  };

  useEffect(() => {
    fetchOrder();
    fetchDriverProfile();
    const interval = setInterval(fetchOrder, DRIVER_ORDER_POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchDriverProfile, fetchOrder]);

  const updateDriverOperationalStatus = async () => {
    if (isSavingOperationalStatus) return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }
    setIsSavingOperationalStatus(true);
    try {
      await axios.put(`${API_URL}/api/drivers/${user.driver_id}/status`, driverStatusForm);
      toast.success("Status actualizat");
      await fetchDriverProfile();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut actualiza statusul"));
    } finally {
      setIsSavingOperationalStatus(false);
    }
  };

  const uploadDriverAvatar = async (blob, filename) => {
    if (avatarUploading) return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }
    setAvatarUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", blob, filename || "avatar.webp");
      await axios.post(`${API_URL}/api/drivers/${user.driver_id}/avatar`, formData, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Poza a fost trimisă la aprobare");
      await fetchDriverProfile();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut încărca poza"));
    } finally {
      setAvatarUploading(false);
    }
  };

  const saveProfile = async () => {
    if (savingProfile) return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }
    if (!isValidPhone(profileForm.phone)) {
      toast.error("Telefonul trebuie să fie 07xxxxxxxx sau +407xxxxxxxx");
      return;
    }
    if (!isValidCnp(profileForm.cnp)) {
      toast.error("CNP-ul trebuie să aibă 13 cifre");
      return;
    }
    setSavingProfile(true);
    try {
      const response = await axios.patch(`${API_URL}/api/drivers/${user.driver_id}/self-profile`, profileForm);
      const result = normalizeObject(response.data);
      setDriverDashboard((prev) => ({ ...prev, driver: result.driver }));
      toast.success(result.email_verification_sent ? "Profil salvat. Verifică emailul nou." : "Profil salvat");
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut salva profilul"));
    } finally {
      setSavingProfile(false);
    }
  };

  const updateStatus = useCallback(async (newStatus, cancellationReason) => {
    if (custodyBusy || !currentOrder || isUpdating || isCancellingOrder || statusMutationRef.current || financialRecovery.record || financialRecovery.storageInvalid || !statusRecovery.canSubmit(currentOrder)) return;
    if (!canChangeOrderStatus(currentOrder, newStatus, user)) return;
    if (newStatus === "PICKED_UP" && (currentOrder.status !== "ACCEPTED" || getPreparationStatus(currentOrder) !== "READY" || financialPickupBlocked(currentOrder))) return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }

    const session = statusSession.current;
    const ownsSession = () => statusMounted.current && statusSession.current === session;
    statusMutationRef.current = true; fetchOrderRequestRef.current += 1; fetchDriverProfileRequestRef.current += 1;
    profileFlightRef.current = null;
    setDriverProfileState((prev) => prev.session === session ? { ...prev, busy: false } : prev);
    setIsUpdating(true);
    if (newStatus === "CANCELLED") setIsCancellingOrder(true);
    try {
      const command = { order: currentOrder, status: newStatus,
        ...(newStatus === "CANCELLED" ? { cancellationReason } : {}) };
      const versioned = hasStatusRevision(currentOrder);
      const result = await (versioned ? statusRecovery.submit(command) : statusRecovery.submitLegacy(command));
      if (!ownsSession() || !result || (versioned && !statusApplied(result))) return;
      if (versioned) return;

      const statusLabels = {
        ACCEPTED: "Primirea comenzii a fost confirmată!",
        PICKED_UP: "Comandă ridicată!",
        DELIVERED: "Livrare finalizată!",
        CANCELLED: "Comanda a fost anulata",
      };

      toast.success(statusLabels[newStatus] || "Status actualizat!");
      setConfirmAction(null);
      setCancelDialog(false); setCancelReason("");

      if (["DELIVERED", "CANCELLED"].includes(newStatus)) {
        setCurrentOrder(null);
      }
      await fetchDriverProfile({ silent: true, hydrateForms: false });
    } catch (error) {
      if (ownsSession()) toast.error(getApiErrorMessage(error, "Eroare la actualizare status"));
    } finally {
      statusMutationRef.current = false;
      if (ownsSession()) {
        fetchOrderRequestRef.current += 1; setIsUpdating(false); setIsCancellingOrder(false);
        await fetchOrder({ silent: true });
      }
    }
  }, [currentOrder, fetchOrder, fetchDriverProfile, isOnline, isUpdating, isCancellingOrder, statusRecovery, financialRecovery, custodyBusy, user]);

  useEffect(() => {
    const r = statusRecovery.record;
    if (!r || !statusApplied(r.receipt)) return;
    const key = `${user?.id}:${token}:${r.client_operation_id}`;
    if (handledStatusReceipt.current === key) return;
    handledStatusReceipt.current = key; fetchOrderRequestRef.current += 1; fetchDriverProfileRequestRef.current += 1;
    toast.success({ ACCEPTED: "Primirea comenzii a fost confirmată!", PICKED_UP: "Comanda ridicata!", DELIVERED: "Livrare finalizata!", CANCELLED: "Comanda a fost anulata" }[r.status]);
    setConfirmAction(null); setCancelDialog(false); setCancelReason("");
    if (["DELIVERED", "CANCELLED"].includes(r.status)) setCurrentOrder((o) => o?.id === r.order_id ? null : o);
    void fetchDriverProfile({ silent: true, hydrateForms: false });
    if (!statusMutationRef.current) void fetchOrder({ silent: true });
  }, [statusRecovery.record, fetchOrder, fetchDriverProfile, user?.id, token]);

  useEffect(() => {
    fetchOrderRequestRef.current += 1; setCurrentOrder(null); setConfirmAction(null); setCancelDialog(false); setCancelReason("");
    setDriverDashboard(null);
    setIsUpdating(false); setIsCancellingOrder(false);
    void fetchOrder({ silent: true });
  }, [user?.id, user?.driver_id, token, fetchOrder]);

  const handleCancelOrder = useCallback(async () => {
    if (isCancellingOrder) return;
    if (!isOnline) {
      toast.error("Nu ai conexiune la internet. Încearcă după reconectare.");
      return;
    }
    if (!currentOrder?.id) {
      toast.error("Comanda nu mai este disponibilă pentru anulare.");
      return;
    }
    if (!cancelReason.trim()) {
      toast.error("Motivul anulării este obligatoriu!");
      return;
    }
    await updateStatus("CANCELLED", cancelReason.trim());
  }, [cancelReason, currentOrder?.id, isCancellingOrder, isOnline, updateStatus]);

  const openNavigation = (address) => {
    const encodedAddress = encodeURIComponent(address);
    // Try Google Maps first, fallback to generic maps
    window.open(`https://www.google.com/maps/search/?api=1&query=${encodedAddress}`, "_blank");
  };

  const callCustomer = (phone) => {
    window.open(`tel:${phone}`, "_self");
  };

  if (isLoading && !statusRecovery.record && !statusRecovery.storageInvalid && !financialRecovery.record && !financialRecovery.storageInvalid && !custodyRecovery.record && !custodyRecovery.storageInvalid) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-black">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500"></div>
      </div>
    );
  }

  const driver = driverDashboard?.driver || {};
  const profileFresh = driverProfileState.session === statusSession.current && driverProfileState.fresh;
  const profileBusy = driverProfileState.session === statusSession.current && driverProfileState.busy;
  const profileError = driverProfileState.session === statusSession.current ? driverProfileState.error : "";
  const today = new Date();
  const todaySummary = {
    deliveries: profileFresh ? driver.total_deliveries : "--",
    earnings: profileFresh ? driver.total_earnings.toFixed(2) : "--",
    activeTime: !profileFresh ? "--" : driver.schedule_today_hours ? `${driver.schedule_today_hours}h` : "0h",
  };
  const statusLabel = profileFresh ? driver.operational_status_label : "Neactualizat";
  const currentStepLabel = getCurrentStepLabel(currentOrder);

  const renderHome = () => (
    <div className="space-y-4" data-testid="driver-home-tab">
      <section className="rounded-[1.35rem] border border-orange-500/70 bg-black/30 p-4" data-testid="driver-order-volume-card">
        <div className="flex items-center justify-between">
          <p className="text-lg font-black text-white">Volum comenzi</p>
          <div className="flex items-end gap-1.5">
            {[30, 48, 32].map((height, index) => <span key={height} className={`w-3 rounded-full ${index === 1 ? "bg-orange-400" : "bg-zinc-600"}`} style={{ height }} />)}
          </div>
        </div>
      </section>

      <section className="rounded-[1.35rem] border border-white/10 bg-zinc-950 p-4 shadow-2xl" data-testid="driver-current-order-card">
        <div className="mb-4 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <Package className="h-6 w-6 text-orange-500" />
            <p className="text-lg font-black text-white">Comanda curentă</p>
          </div>
          {currentOrder && <Badge className="bg-orange-500/20 text-orange-300" data-testid="driver-current-order-number">{currentOrder.order_number}</Badge>}
        </div>
        {currentOrder ? (
          <div className="space-y-4">
            <div className="grid grid-cols-[54px_1fr] gap-3">
              <div className="flex flex-col items-center">
                <div className="grid h-12 w-12 place-items-center rounded-full bg-orange-500"><Store className="h-6 w-6 text-white" /></div>
                <div className="h-16 border-l-2 border-dashed border-white/50" />
                <div className="grid h-12 w-12 place-items-center rounded-full bg-orange-500"><MapPin className="h-6 w-6 text-white" /></div>
              </div>
              <div className="space-y-6 py-1">
                <div>
                  <p className="text-xs text-zinc-400">Locația de ridicare</p>
                  <p className="text-xl font-black text-white">{currentOrder.restaurant_name}</p>
                  <p className="text-sm text-zinc-400">{currentOrder.restaurant_address || "Adresă restaurant"}</p>
                </div>
                <div>
                  <p className="text-xs text-zinc-400">Livrare la</p>
                  <p className="text-base font-bold text-white">{currentOrder.customer_address}</p>
                </div>
              </div>
            </div>
            <button type="button" onClick={() => setActiveTab("delivery")} className="flex h-12 w-full items-center justify-between rounded-2xl border border-white/10 px-3 text-left text-white" data-testid="driver-open-delivery-tab-button">
              <span className="flex items-center gap-2"><Navigation className="h-5 w-5 text-orange-500" /> Vezi detalii comandă</span>
              <span className="text-2xl text-zinc-400">›</span>
            </button>
          </div>
        ) : (
          <div className="rounded-2xl border border-white/10 bg-white/[0.03] p-4 text-center" data-testid="driver-no-order-home">
            <p className="text-xl font-black text-white">Nu ai comandă acum</p>
            <p className="mt-1 text-sm text-zinc-400">Când dispeceratul îți alocă o comandă, apare aici instant.</p>
          </div>
        )}
      </section>

      <section className="rounded-[1.35rem] border border-white/10 bg-zinc-950 p-4" data-testid="driver-today-summary-card">
        <div className="mb-3 flex items-center gap-2"><BarChart3 className="h-5 w-5 text-orange-500" /><p className="font-black text-white">Sumar astăzi</p></div>
        <div className="grid grid-cols-3 divide-x divide-white/10 text-center">
          <div><ClipboardList className="mx-auto mb-1 h-6 w-6 text-orange-500" /><p className="text-2xl font-black text-white">{todaySummary.deliveries}</p><p className="text-xs text-zinc-400">comenzi</p></div>
          <div><Clock className="mx-auto mb-1 h-6 w-6 text-orange-500" /><p className="text-2xl font-black text-white">{todaySummary.activeTime}</p><p className="text-xs text-zinc-400">program azi</p></div>
          <div><WalletCards className="mx-auto mb-1 h-6 w-6 text-orange-500" /><p className="text-xl font-black text-white">{todaySummary.earnings}</p><p className="text-xs text-zinc-400">RON</p></div>
        </div>
      </section>
    </div>
  );

  const renderDelivery = () => (
    <div className="space-y-4" data-testid="driver-delivery-tab">
      <section className="rounded-[1.35rem] border border-white/10 bg-zinc-950 p-4">
        <p className="text-sm text-zinc-400">Status livrator</p>
        <h2 className="mt-1 text-2xl font-black text-white">{statusLabel}</h2>
        <div className="mt-4 grid gap-2">
          <Select value={driverStatusForm.status} onValueChange={(value) => setDriverStatusForm((prev) => ({ ...prev, status: value }))}>
            <SelectTrigger className="h-13 rounded-2xl border-white/10 bg-black text-white" data-testid="driver-operational-status-select"><SelectValue /></SelectTrigger>
            <SelectContent><SelectItem value="active">Activ</SelectItem><SelectItem value="break">În pauză</SelectItem><SelectItem value="offline">Offline</SelectItem></SelectContent>
          </Select>
          {driverStatusForm.status === "break" && <Input type="number" min="1" max="180" value={driverStatusForm.break_minutes} onChange={(event) => setDriverStatusForm((prev) => ({ ...prev, break_minutes: Number(event.target.value) || 30 }))} className="h-13 rounded-2xl border-white/10 bg-black text-white" data-testid="driver-break-minutes-input" />}
          <Button type="button" onClick={updateDriverOperationalStatus} disabled={isSavingOperationalStatus || !isOnline} className="h-13 rounded-2xl bg-orange-600 font-black hover:bg-orange-700" data-testid="driver-status-update-button"><ShieldCheck className="mr-2 h-5 w-5" /> {isSavingOperationalStatus ? "Se salvează..." : "Setează status"}</Button>
        </div>
      </section>

      {!currentOrder ? (
        <section className="rounded-[1.35rem] border border-white/10 bg-zinc-950 p-5 text-center" data-testid="driver-no-delivery-state">
          <Bike className="mx-auto h-14 w-14 text-orange-500" />
          <h2 className="mt-3 text-2xl font-black text-white">Aștepți livrare</h2>
          <p className="mt-2 text-sm text-zinc-400">Când ești în program și activ, comanda apare aici.</p>
          <Button type="button" onClick={() => fetchOrder({ manual: true })} disabled={isRefreshingOrder || !isOnline} className="mt-4 h-13 w-full rounded-2xl bg-orange-600 font-black" data-testid="driver-check-delivery-button"><RefreshCw className={`mr-2 h-5 w-5 ${isRefreshingOrder ? "animate-spin" : ""}`} /> Verifică</Button>
        </section>
      ) : (
        <section className="space-y-3" data-testid="active-order">
          <Card className="border-white/10 bg-zinc-950 text-white"><CardContent className="p-4"><div className="flex items-center justify-between"><div><p className="text-sm text-zinc-400">Pas curent</p><p className="text-xl font-black">{currentStepLabel}</p></div><Badge className="bg-orange-500 text-white">{getStatusConfig(currentOrder.status).label}</Badge></div></CardContent></Card>
          <Card className="border-white/10 bg-zinc-950 text-white" data-testid="customer-info-card"><CardHeader><CardTitle className="text-base">Client</CardTitle></CardHeader><CardContent className="space-y-3"><p className="text-xl font-black">{currentOrder.customer_name}</p><p className="text-zinc-300">{currentOrder.customer_address}</p><Button type="button" onClick={() => callCustomer(currentOrder.customer_phone)} className="h-13 w-full rounded-2xl bg-emerald-600 font-black" data-testid="call-customer-button"><Phone className="mr-2 h-5 w-5" /> Sună clientul</Button><Button type="button" variant="outline" onClick={() => openNavigation(currentOrder.customer_address)} className="h-13 w-full rounded-2xl border-white/10 bg-transparent text-white" data-testid="navigate-button"><Navigation className="mr-2 h-5 w-5" /> Navigație</Button></CardContent></Card>
          <Card className="border-white/10 bg-zinc-950 text-white" data-testid="order-details-card"><CardHeader><CardTitle className="text-base">Detalii comandă</CardTitle></CardHeader><CardContent className="space-y-3">{currentOrder.items?.map((item) => <div key={`${currentOrder.id}-${item.name}`} className="flex justify-between border-b border-white/10 pb-2"><span>{item.quantity}x {item.name}</span><span>{item.price * item.quantity} RON</span></div>)}<div className="rounded-2xl bg-white/5 p-3"><p className="text-sm text-zinc-400">De încasat</p><p className="text-2xl font-black">{clientCollectionText(currentOrder)}</p><p className="text-sm text-orange-300">{currentOrder.payment_type === "CASH" ? "Numerar" : "Card"}</p></div><OrderFinancialSummary order={currentOrder} role="driver" /></CardContent></Card>
        </section>
      )}
    </div>
  );

  const renderCalendar = () => (
    <div className="space-y-3" data-testid="driver-calendar-tab">
      <section className="rounded-[1.35rem] border border-white/10 bg-zinc-950 p-4" data-testid="driver-calendar-mobile-header">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-sm text-zinc-400">Alege/editează program</p>
            <h2 className="text-2xl font-black text-white">Programul meu</h2>
          </div>
          <div className="grid h-12 w-12 place-items-center rounded-2xl bg-orange-500/15 text-orange-300">
            <CalendarDays className="h-7 w-7" />
          </div>
        </div>
        <p className="mt-2 text-sm text-zinc-400">Azi: {formatScheduleDay(today)} · {driver.schedule_today_hours || 0} ore</p>
      </section>
      {user?.driver_id && <DriverSchedule driverId={user.driver_id} />}
    </div>
  );

  const renderProfile = () => (
    <div className="space-y-4" data-testid="driver-profile-tab">
      <section className="rounded-[1.35rem] border border-white/10 bg-zinc-950 p-4 text-white">
        <div className="flex items-center gap-4"><DriverAvatar driver={driver} size="lg" className="border-orange-400" testId="driver-profile-avatar" /><div className="min-w-0 flex-1"><p className="text-sm text-zinc-400">Profil livrator</p><h2 className="truncate text-2xl font-black">{driver.name || user?.name}</h2><div className="mt-2 flex flex-wrap gap-2"><Badge className="bg-orange-500 text-white" data-testid="driver-profile-status-badge">{statusLabel}</Badge>{driver.avatar_status === "pending" && <Badge className="bg-amber-200 text-amber-950" data-testid="driver-avatar-pending-badge">Poză în aprobare</Badge>}</div></div></div>
        <div className="mt-4 rounded-2xl border border-white/10 bg-white/5 p-3"><p className="mb-3 text-sm font-bold text-orange-100"><Camera className="mr-2 inline h-4 w-4" /> Poză profil</p><AvatarUploadCropper onUpload={uploadDriverAvatar} isUploading={avatarUploading} testIdPrefix="driver-self-avatar" /></div>
      </section>
      {!emailVerified && <Card className="border-amber-500/40 bg-amber-500/10 text-white" data-testid="driver-email-verification-card"><CardContent className="space-y-3 p-4"><p className="font-bold text-amber-100">Confirmă emailul</p><div className="grid grid-cols-[1fr_auto] gap-2"><Input value={emailCode} onChange={(event) => setEmailCode(event.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="Cod 6 cifre" inputMode="numeric" disabled={isVerifyingEmail} className="h-13 rounded-2xl bg-black text-white" data-testid="driver-email-code-input" /><Button type="button" onClick={verifyEmailCode} disabled={isVerifyingEmail || !emailCode.trim() || !isOnline} className="rounded-2xl bg-orange-600" data-testid="driver-email-verify-button">{isVerifyingEmail ? "..." : "Verifică"}</Button></div></CardContent></Card>}
      <section className="rounded-[1.35rem] border border-white/10 bg-zinc-950 p-4 text-white">
        <div className="grid gap-3">
          <div className="grid grid-cols-2 gap-3"><div><label className="text-xs font-bold text-zinc-400">Nume</label><Input value={profileForm.last_name} onChange={(e) => setProfileForm((p) => ({ ...p, last_name: e.target.value }))} className="mt-1 h-13 rounded-2xl border-white/10 bg-black text-white" data-testid="driver-profile-last-name-input" /></div><div><label className="text-xs font-bold text-zinc-400">Prenume</label><Input value={profileForm.first_name} onChange={(e) => setProfileForm((p) => ({ ...p, first_name: e.target.value }))} className="mt-1 h-13 rounded-2xl border-white/10 bg-black text-white" data-testid="driver-profile-first-name-input" /></div></div>
          <div><label className="text-xs font-bold text-zinc-400"><IdCard className="mr-1 inline h-3 w-3" /> CNP</label><Input value={profileForm.cnp} onChange={(e) => setProfileForm((p) => ({ ...p, cnp: e.target.value.replace(/\D/g, "").slice(0, 13) }))} className="mt-1 h-13 rounded-2xl border-white/10 bg-black text-white" inputMode="numeric" data-testid="driver-profile-cnp-input" />{!isValidCnp(profileForm.cnp) && <p className="mt-1 text-xs text-red-300" data-testid="driver-profile-cnp-error">CNP-ul trebuie să aibă 13 cifre.</p>}</div>
          <div className="grid grid-cols-2 gap-3"><div><label className="text-xs font-bold text-zinc-400"><Cake className="mr-1 inline h-3 w-3" /> Data nașterii</label><Input type="date" value={profileForm.birth_date} onChange={(e) => setProfileForm((p) => ({ ...p, birth_date: e.target.value }))} className="mt-1 h-13 rounded-2xl border-white/10 bg-black text-white" data-testid="driver-profile-birth-date-input" /></div><div><label className="text-xs font-bold text-zinc-400"><VenusAndMars className="mr-1 inline h-3 w-3" /> Sex</label><Select value={profileForm.gender} onValueChange={(value) => setProfileForm((p) => ({ ...p, gender: value }))}><SelectTrigger className="mt-1 h-13 rounded-2xl border-white/10 bg-black text-white" data-testid="driver-profile-gender-select"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="masculin">Masculin</SelectItem><SelectItem value="feminin">Feminin</SelectItem></SelectContent></Select></div></div>
          <div><label className="text-xs font-bold text-zinc-400"><Mail className="mr-1 inline h-3 w-3" /> Email</label><Input type="email" value={profileForm.email} onChange={(e) => setProfileForm((p) => ({ ...p, email: e.target.value }))} className="mt-1 h-13 rounded-2xl border-white/10 bg-black text-white" data-testid="driver-profile-email-input" /><div className="mt-2 flex items-center gap-2 text-xs">{driver.email_verified ? <span className="text-emerald-300"><Check className="mr-1 inline h-3 w-3" /> validat</span> : <span className="text-amber-300">nevalidat · se folosește codul pe email</span>}</div></div>
          <div><label className="text-xs font-bold text-zinc-400"><Phone className="mr-1 inline h-3 w-3" /> Telefon</label><Input value={profileForm.phone} onChange={(e) => setProfileForm((p) => ({ ...p, phone: e.target.value }))} className="mt-1 h-13 rounded-2xl border-white/10 bg-black text-white" data-testid="driver-profile-phone-input" />{!isValidPhone(profileForm.phone) && <p className="mt-1 text-xs text-red-300" data-testid="driver-profile-phone-error">Format acceptat: 07xxxxxxxx sau +407xxxxxxxx.</p>}<button type="button" onClick={() => toast.info("Validarea SMS reală va fi activată când clientul decide serviciul SMS.")} className="mt-2 text-xs font-bold text-orange-300 underline" data-testid="driver-phone-validation-info-button">Telefon neverificat · SMS se conectează ulterior</button></div>
          <Button type="button" onClick={saveProfile} disabled={savingProfile || !isOnline} className="mt-2 h-14 rounded-2xl bg-orange-600 text-lg font-black hover:bg-orange-700" data-testid="driver-profile-save-button">{savingProfile ? "Se salvează..." : "Salvează profil"}</Button>
        </div>
      </section>
    </div>
  );

  return (
    <div className="min-h-screen bg-neutral-950 text-white" data-testid="driver-app">
      <div
        className="mx-auto flex min-h-screen w-full max-w-md flex-col overflow-hidden bg-[#090b0f] shadow-2xl"
        style={{
          "--driver-navigation-height": "calc(5rem + env(safe-area-inset-bottom, 0px))",
          paddingBottom: "var(--driver-navigation-height)",
        }}
      >
        <header className="relative shrink-0 overflow-hidden px-5 pb-4 pt-4" data-testid="driver-mobile-header">
          <div className="absolute -left-16 -top-28 h-52 w-72 rounded-full bg-orange-600" />
          <div className="relative z-10 flex items-center justify-between">
            <button type="button" className="grid h-11 w-11 place-items-center rounded-full bg-black/20 text-white" data-testid="driver-menu-button"><Menu className="h-6 w-6" /></button>
            <div className="flex items-center gap-2">
              {canInstall && <button type="button" onClick={installPWA} className="grid h-11 w-11 place-items-center rounded-full bg-white/10" data-testid="install-pwa-button"><Download className="h-5 w-5" /></button>}
              <button type="button" onClick={() => fetchOrder({ manual: true })} disabled={isRefreshingOrder || !isOnline} className="grid h-11 w-11 place-items-center rounded-full bg-white/10 disabled:opacity-50" data-testid="refresh-button"><RefreshCw className={`h-5 w-5 ${isRefreshingOrder ? "animate-spin" : ""}`} /></button>
              <button type="button" onClick={logout} className="grid h-11 w-11 place-items-center rounded-full bg-white/10" data-testid="logout-button"><LogOut className="h-5 w-5" /></button>
            </div>
          </div>
          <div className="relative z-10 mt-2 text-center">
            <ProDeliveryMark dark testId="driver-header-logo" />
            <h1 className="mt-1 text-3xl font-black tracking-tight">Bun venit, {driver.first_name || user?.name?.split(" ")[0] || "Livrator"}!</h1>
            <p className="text-zinc-400">Hai să facem bani astăzi! 💰</p>
          </div>
        </header>

        <main className="flex-1 overflow-y-auto px-4 pb-28">
        <OrderStatusRecoveryPanel recovery={statusRecovery} isOnline={isOnline} order={currentOrder}
          onAcknowledged={() => fetchOrder({ silent: true })} onRetry={(fresh) => setCurrentOrder(fresh)} />
        <CustodyRecoveryPanel recovery={custodyRecovery} isOnline={isOnline} onAcknowledged={(fresh) => {
          setCurrentOrder((current) => current?.id === fresh.id ? (["DELIVERED", "CANCELLED"].includes(fresh.status) ? null : fresh) : current);
          void fetchOrder({ silent: true }); void fetchDriverProfile({ silent: true, hydrateForms: false });
        }} />
        <FinancialEventRecoveryPanel recovery={financialRecovery} isOnline={isOnline} onAcknowledged={(fresh) => {
          setCurrentOrder((current) => current?.id === fresh.id ? fresh : current);
          void fetchOrder({ silent: true });
        }} />
        {!profileFresh && <section className="my-3 space-y-2 border-y border-amber-500/40 py-3 text-sm text-amber-200" data-testid="driver-profile-freshness">
          <p role={profileError ? "alert" : "status"}>Status/incasari neactualizate.{profileBusy ? " Se verifica dashboard-ul." : profileError ? ` ${profileError}` : ""}</p>
          <Button variant="outline" className="h-auto min-h-9 whitespace-normal" onClick={() => { if (isOnline) void fetchDriverProfile({ silent: true, hydrateForms: false, manual: true }); }} disabled={!isOnline || profileBusy || isUpdating || isCancellingOrder} data-testid="driver-profile-refresh-button"><RefreshCw className="mr-2 h-4 w-4" />Actualizeaza statusul si incasarile</Button>
        </section>}
        {/* New Order Flash Banner */}
        {newOrderFlash && (
          <div
            className="mb-4 p-4 rounded-xl text-center animate-pulse shadow-lg"
            style={{
              background: 'linear-gradient(135deg, hsl(215 75% 22%), hsl(215 75% 35%))',
              color: 'white'
            }}
            data-testid="driver-new-order-flash"
          >
            <p className="text-lg font-bold tracking-wide">URMEAZĂ SĂ PRIMEȘTI O COMANDĂ</p>
            <p className="text-sm opacity-90 mt-1">Verifică detaliile și confirmă preluarea rapid.</p>
          </div>
        )}
        <IncidentSummary order={currentOrder} />
        <OperationalIncidentReporter actor={user} token={token} scope={`driver-incidents:${user?.driver_id}`} apiUrl={API_URL} isOnline={isOnline} order={currentOrder} selectionDisabled={custodyBusy} disabled={custodyBusy}
          onSelectBlockedIncident={(id) => setCustodyIncident({ id, actor: user?.id, resource: user?.driver_id, token, order: currentOrder?.id })} onReported={(receipt, guard) => fetchOrder({ silent: true, isCurrent: guard.isCurrent })} />
        {activeTab !== "delivery" && <OrderCustodySummary order={currentOrder} />}
        <CustodyControls order={currentOrder} actor={user} recovery={custodyRecovery} isOnline={isOnline}
          disabled={custodyBusy || isUpdating || isCancellingOrder || statusRecovery.blocked || financialRecovery.blocked}
          incidentId={custodyIncident?.actor === user?.id && custodyIncident?.resource === user?.driver_id && custodyIncident?.token === token && custodyIncident?.order === currentOrder?.id ? custodyIncident.id : null} />
        {activeTab === "home" && renderHome()}
        {activeTab === "delivery" && renderDelivery()}
        {activeTab === "calendar" && renderCalendar()}
        {activeTab === "profile" && renderProfile()}
      </main>

      {/* In-flow actions share the container's bottom navigation clearance. */}
      {currentOrder && activeTab === "delivery" && (
        <div className="border-t border-white/10 bg-black p-4 space-y-3" data-testid="action-buttons">
          <FinancialEventControls order={currentOrder} actor={user} recovery={financialRecovery} isOnline={isOnline}
            disabled={custodyBusy || isUpdating || isCancellingOrder || statusRecovery.blocked} />
          {currentOrder.status === "ASSIGNED" && (
            <Button
              className="driver-btn whitespace-normal leading-tight bg-orange-600 hover:bg-orange-700"
              onClick={() => updateStatus("ACCEPTED")}
              disabled={custodyBusy || isUpdating || !isOnline || !statusRecovery.canSubmit(currentOrder) || !canChangeOrderStatus(currentOrder, "ACCEPTED", user)}
              data-testid="accept-button"
            >
              <CheckCircle2 className="w-6 h-6 mr-3" />
              {isUpdating ? "SE PROCESEAZĂ..." : "CONFIRM PRIMIREA COMENZII"}
            </Button>
          )}

          {currentOrder.status === "ACCEPTED" && (
            <Button
              className="driver-btn bg-orange-500 hover:bg-orange-600"
              onClick={() => setConfirmAction({ status: "PICKED_UP", label: "Confirmați că ați ridicat comanda de la restaurant?" })}
              disabled={custodyBusy || isUpdating || !isOnline || financialRecovery.record || financialRecovery.storageInvalid || financialPickupBlocked(currentOrder) || !statusRecovery.canSubmit(currentOrder) || !canChangeOrderStatus(currentOrder, "PICKED_UP", user)}
              data-testid="pickup-button"
            >
              <Package className="w-6 h-6 mr-3" />
              {isUpdating ? "SE PROCESEAZĂ..." : "AM RIDICAT COMANDA"}
            </Button>
          )}

          {currentOrder.status === "PICKED_UP" && (
            <Button
              className="driver-btn bg-green-600 hover:bg-green-700"
              onClick={() => setConfirmAction({ status: "DELIVERED", label: "Confirmați că ați livrat comanda clientului?" })}
              disabled={custodyBusy || isUpdating || !isOnline || !statusRecovery.canSubmit(currentOrder) || !canChangeOrderStatus(currentOrder, "DELIVERED", user)}
              data-testid="deliver-button"
            >
              <CheckCircle2 className="w-6 h-6 mr-3" />
              {isUpdating ? "SE PROCESEAZĂ..." : "AM LIVRAT"}
            </Button>
          )}

          {/* Cancel Button */}
          {["ASSIGNED", "ACCEPTED"].includes(currentOrder.status) && canChangeOrderStatus(currentOrder, "CANCELLED", user) && (
            <Button
              variant="outline"
              className="w-full text-red-600 border-red-300 hover:bg-red-50 dark:hover:bg-red-950/30 h-12"
              onClick={() => { setCancelDialog(true); setCancelReason(""); }}
              disabled={custodyBusy || isUpdating || isCancellingOrder || !isOnline || !statusRecovery.canSubmit(currentOrder) || !canChangeOrderStatus(currentOrder, "CANCELLED", user)}
              data-testid="cancel-order-button"
            >
              <XCircle className="w-5 h-5 mr-2" />
              Anulează Comanda
            </Button>
          )}
        </div>
      )}

        <nav
          className="fixed bottom-0 left-1/2 z-50 grid h-20 w-full max-w-md -translate-x-1/2 grid-cols-4 rounded-t-[1.6rem] border-t border-white/10 bg-zinc-950 px-2 pb-2 pt-2"
          style={{
            height: "var(--driver-navigation-height)",
            paddingBottom: "calc(0.5rem + env(safe-area-inset-bottom, 0px))",
          }}
          data-testid="driver-bottom-navigation"
        >
          {[{ key: "home", label: "Acasă", icon: Home }, { key: "delivery", label: "Livrare", icon: Navigation }, { key: "calendar", label: "Calendar", icon: CalendarDays }, { key: "profile", label: "Profil", icon: User }].map((item) => {
            const Icon = item.icon;
            const active = activeTab === item.key;
            return <button key={item.key} type="button" onClick={() => setActiveTab(item.key)} className={`flex flex-col items-center justify-center gap-1 rounded-2xl text-xs font-bold transition-colors ${active ? "text-orange-400" : "text-zinc-500"}`} data-testid={`driver-nav-${item.key}-button`}><Icon className="h-6 w-6" /><span>{item.label}</span></button>;
          })}
        </nav>
      </div>

      {/* Confirm Action Dialog */}
      <Dialog open={!!confirmAction} onOpenChange={(open) => !open && setConfirmAction(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <AlertTriangle className="w-5 h-5 text-orange-500" />
              Confirmare Acțiune
            </DialogTitle>
          </DialogHeader>
          <div className="py-4">
            <p className="text-base">{confirmAction?.label}</p>
            <p className="text-sm text-muted-foreground mt-2">
              Comanda: <strong>{currentOrder?.order_number}</strong> - {currentOrder?.restaurant_name}
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setConfirmAction(null)} data-testid="cancel-confirm-action">
              Înapoi
            </Button>
            <Button
              onClick={() => updateStatus(confirmAction?.status)}
              disabled={custodyBusy || isUpdating || !isOnline || financialRecovery.record || financialRecovery.storageInvalid || (confirmAction?.status === "PICKED_UP" && financialPickupBlocked(currentOrder)) || !statusRecovery.canSubmit(currentOrder) || !canChangeOrderStatus(currentOrder, confirmAction?.status, user)}
              data-testid="confirm-action-btn"
            >
              <CheckCircle2 className="w-4 h-4 mr-2" />
              {isUpdating ? "Se procesează..." : "Da, Confirmă"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Cancel Order Dialog */}
      <Dialog open={cancelDialog && canChangeOrderStatus(currentOrder, "CANCELLED", user)} onOpenChange={setCancelDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-600">
              <XCircle className="w-5 h-5" />
              Anulare Comandă
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <p className="text-sm text-muted-foreground">
              Motivul anulării este obligatoriu.
            </p>
            <Textarea
              placeholder="Scrieți motivul anulării..."
              value={cancelReason}
              maxLength={500}
              disabled={custodyBusy || isCancellingOrder || statusRecovery.blocked}
              onChange={(e) => setCancelReason(e.target.value)}
              className="min-h-[100px]"
              data-testid="driver-cancel-reason-input"
            />
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setCancelDialog(false)}>
              Înapoi
            </Button>
            <Button
              variant="destructive"
              onClick={handleCancelOrder}
              disabled={custodyBusy || isCancellingOrder || !cancelReason.trim() || !isOnline || !statusRecovery.canSubmit(currentOrder) || !canChangeOrderStatus(currentOrder, "CANCELLED", user)}
              data-testid="driver-confirm-cancel-btn"
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

export default DriverApp;
