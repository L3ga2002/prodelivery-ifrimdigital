import { useState, useEffect, useCallback, useRef } from "react";
import { useAuth } from "../context/AuthContext";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import {
  Bell,
  CalendarDays,
  Camera,
  Check,
  LogOut,
  Package,
  MapPin,
  Phone,
  User,
  CreditCard,
  Banknote,
  Navigation,
  CheckCircle2,
  Bike,
  RefreshCw,
  FileText,
  Clock,
  Download,
  XCircle,
  AlertTriangle,
  PauseCircle,
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
    ACCEPTED: { label: "Acceptată", color: "bg-purple-500", textColor: "text-purple-800 dark:text-purple-100", bgColor: "bg-purple-100 dark:bg-purple-950/40" },
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

const getCurrentStepLabel = (order) => {
  if (!order) return "Fără comandă";
  const labels = {
    ASSIGNED: "Comandă primită",
    ACCEPTED: "Mergi la restaurant",
    PICKED_UP: "Livrează clientului",
  };
  return labels[order.status] || "Finalizată";
};

const DriverApp = () => {
  const { user, logout } = useAuth();
  const [currentOrder, setCurrentOrder] = useState(null);
  const [isLoading, setIsLoading] = useState(true);
  const [isUpdating, setIsUpdating] = useState(false);
  const [canInstall, setCanInstall] = useState(false);
  const [activeTab, setActiveTab] = useState("home");
  const lastOrderIdRef = useRef(null);
  const hasLoadedOrdersRef = useRef(false);
  const [newOrderFlash, setNewOrderFlash] = useState(false);
  const [emailCode, setEmailCode] = useState("");
  const [emailVerified, setEmailVerified] = useState(user?.email_verified !== false);
  const [confirmAction, setConfirmAction] = useState(null); // {status, label}
  const [cancelDialog, setCancelDialog] = useState(false);
  const [cancelReason, setCancelReason] = useState("");
  const [driverDashboard, setDriverDashboard] = useState(null);
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

  const fetchOrder = useCallback(async () => {
    if (!user?.driver_id) {
      setIsLoading(false);
      return;
    }

    try {
      const response = await axios.get(`${API_URL}/api/orders/driver/${user.driver_id}`);
      const orders = response.data;
      // Get the first non-delivered order
      const activeOrder = orders.find((o) => o.status !== "DELIVERED");

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
    } catch {
      toast.error("Nu am putut încărca livrarea curentă");
    } finally {
      setIsLoading(false);
      hasLoadedOrdersRef.current = true;
    }
  }, [user?.driver_id]);

  const fetchDriverProfile = useCallback(async () => {
    if (!user?.driver_id) return;
    try {
      const response = await axios.get(`${API_URL}/api/drivers/${user.driver_id}/dashboard`);
      setDriverDashboard(response.data);
      const driver = response.data.driver || {};
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
      const status = response.data.driver?.operational_status || "active";
      setDriverStatusForm((prev) => ({
        ...prev,
        status: status === "delivery" ? "active" : status,
      }));
    } catch {
      toast.error("Nu am putut încărca profilul livratorului");
    }
  }, [user?.driver_id, user?.email, user?.name, user?.phone]);

  useEffect(() => {
    setEmailVerified(user?.email_verified !== false);
  }, [user?.email_verified]);

  const verifyEmailCode = async () => {
    if (!emailCode.trim()) {
      toast.error("Introdu codul primit pe email");
      return;
    }
    try {
      await axios.post(`${API_URL}/api/drivers/${user.driver_id}/verify-email`, { code: emailCode.trim() });
      setEmailVerified(true);
      setEmailCode("");
      toast.success("Email verificat cu succes");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Cod invalid sau expirat");
    }
  };

  useEffect(() => {
    fetchOrder();
    fetchDriverProfile();
    const interval = setInterval(fetchOrder, DRIVER_ORDER_POLL_INTERVAL_MS);
    return () => clearInterval(interval);
  }, [fetchDriverProfile, fetchOrder]);

  const updateDriverOperationalStatus = async () => {
    try {
      await axios.put(`${API_URL}/api/drivers/${user.driver_id}/status`, driverStatusForm);
      toast.success("Status actualizat");
      fetchDriverProfile();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Nu am putut actualiza statusul");
    }
  };

  const uploadDriverAvatar = async (blob, filename) => {
    setAvatarUploading(true);
    try {
      const formData = new FormData();
      formData.append("file", blob, filename || "avatar.webp");
      await axios.post(`${API_URL}/api/drivers/${user.driver_id}/avatar`, formData, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Poza a fost trimisă la aprobare");
      fetchDriverProfile();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Nu am putut încărca poza");
    } finally {
      setAvatarUploading(false);
    }
  };

  const saveProfile = async () => {
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
      setDriverDashboard((prev) => ({ ...prev, driver: response.data.driver }));
      toast.success(response.data.email_verification_sent ? "Profil salvat. Verifică emailul nou." : "Profil salvat");
    } catch (error) {
      toast.error(error.response?.data?.detail || "Nu am putut salva profilul");
    } finally {
      setSavingProfile(false);
    }
  };

  const updateStatus = useCallback(async (newStatus) => {
    if (!currentOrder) return;

    setIsUpdating(true);
    try {
      await axios.put(`${API_URL}/api/orders/${currentOrder.id}/status`, {
        status: newStatus,
      });

      const statusLabels = {
        ACCEPTED: "Comandă acceptată!",
        PICKED_UP: "Comandă ridicată!",
        DELIVERED: "Livrare finalizată!",
      };

      toast.success(statusLabels[newStatus] || "Status actualizat!");
      setConfirmAction(null);

      if (newStatus === "DELIVERED") {
        setCurrentOrder(null);
      } else {
        fetchOrder();
      }
    } catch {
      toast.error("Eroare la actualizare status");
    } finally {
      setIsUpdating(false);
    }
  }, [currentOrder, fetchOrder]);

  const handleCancelOrder = useCallback(async () => {
    if (!cancelReason.trim()) {
      toast.error("Motivul anulării este obligatoriu!");
      return;
    }
    try {
      await axios.put(`${API_URL}/api/orders/${currentOrder.id}/status`, {
        status: "CANCELLED",
        cancellation_reason: cancelReason.trim()
      });
      toast.success("Comanda a fost anulată");
      setCancelDialog(false);
      setCancelReason("");
      setCurrentOrder(null);
      fetchOrder();
    } catch {
      toast.error("Eroare la anulare");
    }
  }, [cancelReason, currentOrder?.id, fetchOrder]);

  const openNavigation = (address) => {
    const encodedAddress = encodeURIComponent(address);
    // Try Google Maps first, fallback to generic maps
    window.open(`https://www.google.com/maps/search/?api=1&query=${encodedAddress}`, "_blank");
  };

  const callCustomer = (phone) => {
    window.open(`tel:${phone}`, "_self");
  };

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-black">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-orange-500"></div>
      </div>
    );
  }

  const driver = driverDashboard?.driver || {};
  const today = new Date();
  const todaySummary = {
    deliveries: driver.total_deliveries || 0,
    earnings: Number(driver.total_earnings || 0).toFixed(2),
    activeTime: driver.schedule_today_hours ? `${driver.schedule_today_hours}h` : "0h",
  };
  const statusLabel = driver.operational_status_label || "Offline";
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
          <Button type="button" onClick={updateDriverOperationalStatus} className="h-13 rounded-2xl bg-orange-600 font-black hover:bg-orange-700" data-testid="driver-status-update-button"><ShieldCheck className="mr-2 h-5 w-5" /> Setează status</Button>
        </div>
      </section>

      {!currentOrder ? (
        <section className="rounded-[1.35rem] border border-white/10 bg-zinc-950 p-5 text-center" data-testid="driver-no-delivery-state">
          <Bike className="mx-auto h-14 w-14 text-orange-500" />
          <h2 className="mt-3 text-2xl font-black text-white">Aștepți livrare</h2>
          <p className="mt-2 text-sm text-zinc-400">Când ești în program și activ, comanda apare aici.</p>
          <Button type="button" onClick={fetchOrder} className="mt-4 h-13 w-full rounded-2xl bg-orange-600 font-black" data-testid="driver-check-delivery-button"><RefreshCw className="mr-2 h-5 w-5" /> Verifică</Button>
        </section>
      ) : (
        <section className="space-y-3" data-testid="active-order">
          <Card className="border-white/10 bg-zinc-950 text-white"><CardContent className="p-4"><div className="flex items-center justify-between"><div><p className="text-sm text-zinc-400">Pas curent</p><p className="text-xl font-black">{currentStepLabel}</p></div><Badge className="bg-orange-500 text-white">{getStatusConfig(currentOrder.status).label}</Badge></div></CardContent></Card>
          <Card className="border-white/10 bg-zinc-950 text-white" data-testid="customer-info-card"><CardHeader><CardTitle className="text-base">Client</CardTitle></CardHeader><CardContent className="space-y-3"><p className="text-xl font-black">{currentOrder.customer_name}</p><p className="text-zinc-300">{currentOrder.customer_address}</p><Button type="button" onClick={() => callCustomer(currentOrder.customer_phone)} className="h-13 w-full rounded-2xl bg-emerald-600 font-black" data-testid="call-customer-button"><Phone className="mr-2 h-5 w-5" /> Sună clientul</Button><Button type="button" variant="outline" onClick={() => openNavigation(currentOrder.customer_address)} className="h-13 w-full rounded-2xl border-white/10 bg-transparent text-white" data-testid="navigate-button"><Navigation className="mr-2 h-5 w-5" /> Navigație</Button></CardContent></Card>
          <Card className="border-white/10 bg-zinc-950 text-white" data-testid="order-details-card"><CardHeader><CardTitle className="text-base">Detalii comandă</CardTitle></CardHeader><CardContent className="space-y-3">{currentOrder.items?.map((item) => <div key={`${currentOrder.id}-${item.name}`} className="flex justify-between border-b border-white/10 pb-2"><span>{item.quantity}x {item.name}</span><span>{item.price * item.quantity} RON</span></div>)}<div className="rounded-2xl bg-white/5 p-3"><p className="text-sm text-zinc-400">De încasat</p><p className="text-2xl font-black">{currentOrder.total_amount} RON</p><p className="text-sm text-orange-300">{currentOrder.payment_type === "CASH" ? "Numerar" : "Card"}</p></div></CardContent></Card>
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
      {!emailVerified && <Card className="border-amber-500/40 bg-amber-500/10 text-white" data-testid="driver-email-verification-card"><CardContent className="space-y-3 p-4"><p className="font-bold text-amber-100">Confirmă emailul</p><div className="grid grid-cols-[1fr_auto] gap-2"><Input value={emailCode} onChange={(event) => setEmailCode(event.target.value.replace(/\D/g, "").slice(0, 6))} placeholder="Cod 6 cifre" inputMode="numeric" className="h-13 rounded-2xl bg-black text-white" data-testid="driver-email-code-input" /><Button type="button" onClick={verifyEmailCode} className="rounded-2xl bg-orange-600" data-testid="driver-email-verify-button">Verifică</Button></div></CardContent></Card>}
      <section className="rounded-[1.35rem] border border-white/10 bg-zinc-950 p-4 text-white">
        <div className="grid gap-3">
          <div className="grid grid-cols-2 gap-3"><div><label className="text-xs font-bold text-zinc-400">Nume</label><Input value={profileForm.last_name} onChange={(e) => setProfileForm((p) => ({ ...p, last_name: e.target.value }))} className="mt-1 h-13 rounded-2xl border-white/10 bg-black text-white" data-testid="driver-profile-last-name-input" /></div><div><label className="text-xs font-bold text-zinc-400">Prenume</label><Input value={profileForm.first_name} onChange={(e) => setProfileForm((p) => ({ ...p, first_name: e.target.value }))} className="mt-1 h-13 rounded-2xl border-white/10 bg-black text-white" data-testid="driver-profile-first-name-input" /></div></div>
          <div><label className="text-xs font-bold text-zinc-400"><IdCard className="mr-1 inline h-3 w-3" /> CNP</label><Input value={profileForm.cnp} onChange={(e) => setProfileForm((p) => ({ ...p, cnp: e.target.value.replace(/\D/g, "").slice(0, 13) }))} className="mt-1 h-13 rounded-2xl border-white/10 bg-black text-white" inputMode="numeric" data-testid="driver-profile-cnp-input" />{!isValidCnp(profileForm.cnp) && <p className="mt-1 text-xs text-red-300" data-testid="driver-profile-cnp-error">CNP-ul trebuie să aibă 13 cifre.</p>}</div>
          <div className="grid grid-cols-2 gap-3"><div><label className="text-xs font-bold text-zinc-400"><Cake className="mr-1 inline h-3 w-3" /> Data nașterii</label><Input type="date" value={profileForm.birth_date} onChange={(e) => setProfileForm((p) => ({ ...p, birth_date: e.target.value }))} className="mt-1 h-13 rounded-2xl border-white/10 bg-black text-white" data-testid="driver-profile-birth-date-input" /></div><div><label className="text-xs font-bold text-zinc-400"><VenusAndMars className="mr-1 inline h-3 w-3" /> Sex</label><Select value={profileForm.gender} onValueChange={(value) => setProfileForm((p) => ({ ...p, gender: value }))}><SelectTrigger className="mt-1 h-13 rounded-2xl border-white/10 bg-black text-white" data-testid="driver-profile-gender-select"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="masculin">Masculin</SelectItem><SelectItem value="feminin">Feminin</SelectItem></SelectContent></Select></div></div>
          <div><label className="text-xs font-bold text-zinc-400"><Mail className="mr-1 inline h-3 w-3" /> Email</label><Input type="email" value={profileForm.email} onChange={(e) => setProfileForm((p) => ({ ...p, email: e.target.value }))} className="mt-1 h-13 rounded-2xl border-white/10 bg-black text-white" data-testid="driver-profile-email-input" /><div className="mt-2 flex items-center gap-2 text-xs">{driver.email_verified ? <span className="text-emerald-300"><Check className="mr-1 inline h-3 w-3" /> validat</span> : <span className="text-amber-300">nevalidat · se folosește codul pe email</span>}</div></div>
          <div><label className="text-xs font-bold text-zinc-400"><Phone className="mr-1 inline h-3 w-3" /> Telefon</label><Input value={profileForm.phone} onChange={(e) => setProfileForm((p) => ({ ...p, phone: e.target.value }))} className="mt-1 h-13 rounded-2xl border-white/10 bg-black text-white" data-testid="driver-profile-phone-input" />{!isValidPhone(profileForm.phone) && <p className="mt-1 text-xs text-red-300" data-testid="driver-profile-phone-error">Format acceptat: 07xxxxxxxx sau +407xxxxxxxx.</p>}<button type="button" onClick={() => toast.info("Validarea SMS reală va fi activată când clientul decide serviciul SMS.")} className="mt-2 text-xs font-bold text-orange-300 underline" data-testid="driver-phone-validation-info-button">Telefon neverificat · SMS se conectează ulterior</button></div>
          <Button type="button" onClick={saveProfile} disabled={savingProfile} className="mt-2 h-14 rounded-2xl bg-orange-600 text-lg font-black hover:bg-orange-700" data-testid="driver-profile-save-button">{savingProfile ? "Se salvează..." : "Salvează profil"}</Button>
        </div>
      </section>
    </div>
  );

  return (
    <div className="min-h-screen bg-neutral-950 text-white" data-testid="driver-app">
      <div className="mx-auto flex min-h-screen w-full max-w-md flex-col overflow-hidden bg-[#090b0f] shadow-2xl">
        <header className="relative shrink-0 overflow-hidden px-5 pb-4 pt-4" data-testid="driver-mobile-header">
          <div className="absolute -left-16 -top-28 h-52 w-72 rounded-full bg-orange-600" />
          <div className="relative z-10 flex items-center justify-between">
            <button type="button" className="grid h-11 w-11 place-items-center rounded-full bg-black/20 text-white" data-testid="driver-menu-button"><Menu className="h-6 w-6" /></button>
            <div className="flex items-center gap-2">
              {canInstall && <button type="button" onClick={installPWA} className="grid h-11 w-11 place-items-center rounded-full bg-white/10" data-testid="install-pwa-button"><Download className="h-5 w-5" /></button>}
              <button type="button" onClick={fetchOrder} className="grid h-11 w-11 place-items-center rounded-full bg-white/10" data-testid="refresh-button"><RefreshCw className="h-5 w-5" /></button>
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
        {activeTab === "home" && renderHome()}
        {activeTab === "delivery" && renderDelivery()}
        {activeTab === "calendar" && renderCalendar()}
        {activeTab === "profile" && renderProfile()}
      </main>

      {/* Action Buttons - Fixed at Bottom */}
      {currentOrder && activeTab === "delivery" && (
        <div className="border-t border-white/10 bg-black p-4 space-y-3" data-testid="action-buttons">
          {currentOrder.status === "ASSIGNED" && (
            <Button
              className="driver-btn bg-orange-600 hover:bg-orange-700"
              onClick={() => updateStatus("ACCEPTED")}
              disabled={isUpdating}
              data-testid="accept-button"
            >
              <CheckCircle2 className="w-6 h-6 mr-3" />
              {isUpdating ? "SE PROCESEAZĂ..." : "ACCEPT COMANDA"}
            </Button>
          )}

          {currentOrder.status === "ACCEPTED" && (
            <Button
              className="driver-btn bg-orange-500 hover:bg-orange-600"
              onClick={() => setConfirmAction({ status: "PICKED_UP", label: "Confirmați că ați ridicat comanda de la restaurant?" })}
              disabled={isUpdating}
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
              disabled={isUpdating}
              data-testid="deliver-button"
            >
              <CheckCircle2 className="w-6 h-6 mr-3" />
              {isUpdating ? "SE PROCESEAZĂ..." : "AM LIVRAT"}
            </Button>
          )}

          {/* Cancel Button */}
          {["ASSIGNED", "ACCEPTED"].includes(currentOrder.status) && (
            <Button
              variant="outline"
              className="w-full text-red-600 border-red-300 hover:bg-red-50 dark:hover:bg-red-950/30 h-12"
              onClick={() => { setCancelDialog(true); setCancelReason(""); }}
              data-testid="cancel-order-button"
            >
              <XCircle className="w-5 h-5 mr-2" />
              Anulează Comanda
            </Button>
          )}
        </div>
      )}

        <nav className="fixed bottom-0 left-1/2 z-50 grid h-20 w-full max-w-md -translate-x-1/2 grid-cols-4 rounded-t-[1.6rem] border-t border-white/10 bg-zinc-950 px-2 pb-2 pt-2" data-testid="driver-bottom-navigation">
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
              disabled={isUpdating}
              data-testid="confirm-action-btn"
            >
              <CheckCircle2 className="w-4 h-4 mr-2" />
              {isUpdating ? "Se procesează..." : "Da, Confirmă"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Cancel Order Dialog */}
      <Dialog open={cancelDialog} onOpenChange={setCancelDialog}>
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
              disabled={!cancelReason.trim()}
              data-testid="driver-confirm-cancel-btn"
            >
              <XCircle className="w-4 h-4 mr-2" />
              Confirmă Anularea
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default DriverApp;
