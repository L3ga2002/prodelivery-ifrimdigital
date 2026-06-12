import { useCallback, useEffect, useMemo, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import {
  AlertTriangle,
  CalendarCheck,
  CheckCircle2,
  Clock,
  KeyRound,
  Package,
  PauseCircle,
  Save,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UserCog,
  XCircle,
} from "lucide-react";
import { AvatarUploadCropper } from "../AvatarUploadCropper";
import { DriverAvatar } from "../DriverAvatar";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "../ui/dialog";
import { Input } from "../ui/input";
import { Label } from "../ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "../ui/select";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "../ui/tabs";
import { Textarea } from "../ui/textarea";
import { getApiErrorMessage, normalizeArray, normalizeObject, retryApiCall } from "../../lib/api";

const API_URL = process.env.REACT_APP_BACKEND_URL;
const DAYS = [
  { key: "monday", label: "Luni" },
  { key: "tuesday", label: "Marți" },
  { key: "wednesday", label: "Miercuri" },
  { key: "thursday", label: "Joi" },
  { key: "friday", label: "Vineri" },
  { key: "saturday", label: "Sâmbătă" },
  { key: "sunday", label: "Duminică" },
];
const ALL_HOURS = [...Array.from({ length: 14 }, (_, i) => `${String(i + 10).padStart(2, "0")}:00`), "00:00", "01:00"];
const RECOMMENDED_WEEKLY_HOURS = 40;
const RECOMMENDED_DAILY_HOURS = 8;

const getMonday = (date) => {
  const d = new Date(date);
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  d.setDate(diff);
  d.setHours(0, 0, 0, 0);
  return d;
};

const toISODate = (date) => date.toISOString().split("T")[0];

const formatInterval = (hour) => {
  const h = Number.parseInt(hour, 10);
  const next = (h + 1) % 24;
  return `${String(h).padStart(2, "0")}-${String(next).padStart(2, "0")}`;
};

const buildSlot = (hour, forced = false, slotType = "normal") => ({
  start: hour,
  end: `${String((Number.parseInt(hour, 10) + 1) % 24).padStart(2, "0")}:00`,
  added_by: slotType === "emergency" ? "emergency" : "admin",
  forced,
  warning: forced ? "Acest interval depășește limita recomandată" : null,
});

const countSlots = (slots) => Object.values(slots || {}).reduce((sum, daySlots) => sum + daySlots.length, 0);

const statusClasses = {
  active: "bg-emerald-100 text-emerald-800 border-emerald-200 dark:bg-emerald-950/40 dark:text-emerald-100",
  delivery: "bg-blue-100 text-blue-800 border-blue-200 dark:bg-blue-950/40 dark:text-blue-100",
  break: "bg-amber-100 text-amber-800 border-amber-200 dark:bg-amber-950/40 dark:text-amber-100",
  offline: "bg-slate-100 text-slate-700 border-slate-200 dark:bg-slate-900 dark:text-slate-100",
};

const statusLabels = {
  active: "Activ",
  delivery: "În livrare",
  break: "În pauză",
  offline: "Offline",
};

const BreakCountdown = ({ seconds }) => {
  const [remaining, setRemaining] = useState(seconds || 0);
  useEffect(() => {
    setRemaining(seconds || 0);
  }, [seconds]);
  useEffect(() => {
    if (remaining <= 0) return;
    const timer = setInterval(() => setRemaining((value) => Math.max(value - 1, 0)), 1000);
    return () => clearInterval(timer);
  }, [remaining]);
  const minutes = Math.floor(remaining / 60);
  const secs = remaining % 60;
  return <span data-testid="driver-break-countdown">{minutes}:{String(secs).padStart(2, "0")}</span>;
};

export const DriverManagementDialog = ({ driver, open, onOpenChange, onChanged }) => {
  const [dashboard, setDashboard] = useState(null);
  const [loading, setLoading] = useState(false);
  const [profileForm, setProfileForm] = useState({ name: "", phone: "", email: "", new_password: "" });
  const [rankForm, setRankForm] = useState({ manual_ranking_score: "", manual_rank_note: "" });
  const [statusForm, setStatusForm] = useState({ status: "active", break_minutes: 30 });
  const [deleteText, setDeleteText] = useState("");
  const [disableReason, setDisableReason] = useState("");
  const [calendarSlotMode, setCalendarSlotMode] = useState("normal");
  const [editSlots, setEditSlots] = useState({});
  const [savingSchedule, setSavingSchedule] = useState(false);
  const [uploadingAvatar, setUploadingAvatar] = useState(false);
  const [actionLoading, setActionLoading] = useState(null);
  const weekStart = useMemo(() => toISODate(getMonday(new Date())), []);

  const activeDriver = dashboard?.driver || driver;

  const refreshDashboard = useCallback(async () => {
    if (!driver?.id) return;
    setLoading(true);
    try {
      const response = await retryApiCall(() => axios.get(`${API_URL}/api/drivers/${driver.id}/dashboard`));
      const dashboardData = normalizeObject(response.data);
      setDashboard(dashboardData);
      const freshDriver = normalizeObject(dashboardData.driver);
      setProfileForm({
        name: freshDriver.name || "",
        phone: freshDriver.phone || "",
        email: freshDriver.email || "",
        new_password: "",
      });
      setRankForm({
        manual_ranking_score: freshDriver.manual_ranking_score ?? freshDriver.ranking_score ?? "",
        manual_rank_note: freshDriver.manual_rank_note || "",
      });
      setStatusForm({
        status: freshDriver.operational_status === "delivery" ? "active" : freshDriver.operational_status || "active",
        break_minutes: 30,
      });
      const currentSchedule = normalizeArray(dashboardData.schedules).find((schedule) => schedule.week_start === weekStart);
      setEditSlots(currentSchedule?.slots || {});
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut încărca profilul livratorului"));
    } finally {
      setLoading(false);
    }
  }, [driver?.id, weekStart]);

  useEffect(() => {
    if (open && driver?.id) {
      refreshDashboard();
      setDeleteText("");
    }
  }, [driver?.id, open, refreshDashboard]);

  const profileWarnings = useMemo(() => {
    const total = countSlots(editSlots);
    const dailyOver = DAYS.filter((day) => (editSlots[day.key] || []).length > RECOMMENDED_DAILY_HOURS).map((day) => day.label);
    return {
      total,
      weekOver: total > RECOMMENDED_WEEKLY_HOURS,
      dailyOver,
      hasWarning: total > RECOMMENDED_WEEKLY_HOURS || dailyOver.length > 0,
    };
  }, [editSlots]);

  const saveProfile = async () => {
    if (actionLoading) return;
    setActionLoading("profile");
    try {
      await axios.patch(`${API_URL}/api/drivers/${activeDriver.id}/profile`, {
        ...profileForm,
        new_password: profileForm.new_password.trim() || null,
      });
      toast.success("Datele livratorului au fost actualizate");
      setProfileForm((prev) => ({ ...prev, new_password: "" }));
      await refreshDashboard();
      onChanged?.();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut salva profilul"));
    } finally {
      setActionLoading(null);
    }
  };

  const updateStatus = async () => {
    if (actionLoading) return;
    setActionLoading("status");
    try {
      await axios.put(`${API_URL}/api/drivers/${activeDriver.id}/status`, statusForm);
      toast.success("Status livrator actualizat");
      await refreshDashboard();
      onChanged?.();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut actualiza statusul"));
    } finally {
      setActionLoading(null);
    }
  };

  const saveRanking = async () => {
    const numericScore = Number(rankForm.manual_ranking_score);
    if (Number.isNaN(numericScore) || numericScore < 0 || numericScore > 100) {
      toast.error("Scorul trebuie să fie între 0 și 100");
      return;
    }
    if (actionLoading) return;
    setActionLoading("rank");
    try {
      await axios.patch(`${API_URL}/api/drivers/${activeDriver.id}/ranking`, {
        manual_ranking_score: numericScore,
        manual_rank_note: rankForm.manual_rank_note,
      });
      toast.success("Scorul de rank a fost salvat");
      await refreshDashboard();
      onChanged?.();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut salva scorul"));
    } finally {
      setActionLoading(null);
    }
  };

  const clearRanking = async () => {
    if (actionLoading) return;
    setActionLoading("rank");
    try {
      await axios.patch(`${API_URL}/api/drivers/${activeDriver.id}/ranking`, { manual_ranking_score: null, manual_rank_note: "" });
      toast.success("Scorul manual a fost eliminat");
      await refreshDashboard();
      onChanged?.();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut elimina scorul manual"));
    } finally {
      setActionLoading(null);
    }
  };

  const deleteDriver = async () => {
    if (deleteText !== "STERGE") {
      toast.error("Scrie STERGE pentru confirmare");
      return;
    }
    if (actionLoading) return;
    setActionLoading("delete");
    try {
      await axios.delete(`${API_URL}/api/drivers/${activeDriver.id}`, { params: { confirm_delete: true } });
      toast.success("Livrator șters din baza de date");
      onOpenChange(false);
      onChanged?.();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut șterge livratorul"));
    } finally {
      setActionLoading(null);
    }
  };

  const disableDriver = async () => {
    if (actionLoading) return;
    setActionLoading("disable");
    try {
      await axios.patch(`${API_URL}/api/drivers/${activeDriver.id}/disable`, { reason: disableReason.trim() || "Dezactivat manual de admin" });
      toast.success("Contul livratorului a fost dezactivat");
      onOpenChange(false);
      onChanged?.();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut dezactiva contul"));
    } finally {
      setActionLoading(null);
    }
  };

  const toggleHour = (dayKey, hour) => {
    setEditSlots((prev) => {
      const daySlots = prev[dayKey] || [];
      const exists = daySlots.some((slot) => slot.start === hour);
      const nextDaySlots = exists
        ? daySlots.filter((slot) => slot.start !== hour)
        : [...daySlots, buildSlot(hour, countSlots(prev) >= RECOMMENDED_WEEKLY_HOURS || daySlots.length >= RECOMMENDED_DAILY_HOURS, calendarSlotMode)];
      return { ...prev, [dayKey]: nextDaySlots.sort((a, b) => ALL_HOURS.indexOf(a.start) - ALL_HOURS.indexOf(b.start)) };
    });
  };

  const saveSchedule = async () => {
    if (savingSchedule) return;
    setSavingSchedule(true);
    try {
      await axios.post(`${API_URL}/api/schedules`, {
        driver_id: activeDriver.id,
        week_start: weekStart,
        slots: editSlots,
        source: "admin",
        force_override: true,
      });
      toast.success(profileWarnings.hasWarning ? "Program salvat cu avertizare de supraîncărcare" : "Program livrator salvat");
      await refreshDashboard();
      onChanged?.();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut salva programul"));
    } finally {
      setSavingSchedule(false);
    }
  };

  const uploadAvatar = async (blob, filename) => {
    if (uploadingAvatar) return;
    setUploadingAvatar(true);
    try {
      const formData = new FormData();
      formData.append("file", blob, filename || "avatar.webp");
      await axios.post(`${API_URL}/api/drivers/${activeDriver.id}/avatar`, formData, { headers: { "Content-Type": "multipart/form-data" } });
      toast.success("Poza livratorului a fost setată direct de admin");
      await refreshDashboard();
      onChanged?.();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut încărca poza"));
    } finally {
      setUploadingAvatar(false);
    }
  };

  const moderateAvatar = async (avatarId, action) => {
    if (actionLoading) return;
    setActionLoading(`avatar:${avatarId}`);
    try {
      await axios.patch(`${API_URL}/api/drivers/${activeDriver.id}/avatars/${avatarId}`, { action });
      toast.success(action === "approve" ? "Avatar aprobat" : "Avatar respins");
      await refreshDashboard();
      onChanged?.();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut modera poza"));
    } finally {
      setActionLoading(null);
    }
  };

  const pendingAvatars = normalizeArray(dashboard?.avatars).filter((avatar) => avatar.status === "pending");
  const recentOrders = normalizeArray(dashboard?.recent_orders);
  const auditLogs = normalizeArray(dashboard?.audit_logs);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-h-[90vh] max-w-5xl overflow-y-auto" data-testid="driver-management-dialog">
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <SlidersHorizontal className="h-5 w-5 text-orange-600" />
            Dashboard livrator · {activeDriver?.name || "Livrator"}
          </DialogTitle>
          <DialogDescription>
            Profil, status operațional, program vizual, avatar și istoric securizat.
          </DialogDescription>
        </DialogHeader>

        {loading && <div className="rounded-lg border bg-muted/30 p-4 text-sm" data-testid="driver-dashboard-loading">Se încarcă profilul...</div>}
        {activeDriver && (
          <div className="space-y-5">
            <div className="grid gap-3 lg:grid-cols-[1.1fr_2fr]">
              <Card className="border-orange-100 bg-gradient-to-br from-orange-50 to-slate-50 dark:from-orange-950/20 dark:to-slate-950">
                <CardContent className="flex items-center gap-4 p-4">
                  <DriverAvatar driver={activeDriver} size="lg" testId="driver-dashboard-avatar" />
                  <div className="min-w-0">
                    <p className="truncate text-xl font-black">{activeDriver.name}</p>
                    <p className="truncate text-sm text-muted-foreground">{activeDriver.email}</p>
                    <div className="mt-2 flex flex-wrap gap-2">
                      <Badge className={statusClasses[activeDriver.operational_status] || statusClasses.offline} data-testid="driver-dashboard-status-badge">
                        {activeDriver.operational_status_label || statusLabels[activeDriver.operational_status] || "Offline"}
                      </Badge>
                      {activeDriver.operational_status === "break" && (
                        <Badge variant="outline" className="border-amber-300 text-amber-700" data-testid="driver-dashboard-break-timer">
                          Pauză: <BreakCountdown seconds={activeDriver.break_remaining_seconds} />
                        </Badge>
                      )}
                    </div>
                  </div>
                </CardContent>
              </Card>
              <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                <div className="rounded-lg border bg-card p-3" data-testid="driver-dashboard-score-card"><p className="text-xs text-muted-foreground">Scor</p><p className="text-2xl font-black">{activeDriver.ranking_score || 0}</p></div>
                <div className="rounded-lg border bg-card p-3" data-testid="driver-dashboard-rank-card"><p className="text-xs text-muted-foreground">Rank</p><p className="text-2xl font-black">{activeDriver.ranking_tier || "Start"}</p></div>
                <div className="rounded-lg border bg-card p-3" data-testid="driver-dashboard-deliveries-card"><p className="text-xs text-muted-foreground">Livrări</p><p className="text-2xl font-black">{activeDriver.total_deliveries || 0}</p></div>
                <div className="rounded-lg border bg-card p-3" data-testid="driver-dashboard-week-hours-card"><p className="text-xs text-muted-foreground">Ore săptămână</p><p className="text-2xl font-black">{profileWarnings.total}h</p></div>
              </div>
            </div>

            <Tabs defaultValue="profile" className="space-y-4">
              <TabsList className="flex h-auto flex-wrap justify-start">
                <TabsTrigger value="profile" data-testid="driver-tab-profile">Profil</TabsTrigger>
                <TabsTrigger value="schedule" data-testid="driver-tab-schedule">Calendar</TabsTrigger>
                <TabsTrigger value="avatar" data-testid="driver-tab-avatar">Avatar</TabsTrigger>
                <TabsTrigger value="history" data-testid="driver-tab-history">Istoric</TabsTrigger>
                <TabsTrigger value="danger" data-testid="driver-tab-danger">Dezactivare</TabsTrigger>
              </TabsList>

              <TabsContent value="profile" className="space-y-4">
                <div className="grid gap-4 lg:grid-cols-2">
                  <Card>
                    <CardHeader><CardTitle className="flex items-center gap-2 text-base"><UserCog className="h-5 w-5 text-orange-600" /> Date livrator</CardTitle></CardHeader>
                    <CardContent className="space-y-3">
                      <div><Label>Nume</Label><Input value={profileForm.name} onChange={(event) => setProfileForm((prev) => ({ ...prev, name: event.target.value }))} data-testid="driver-profile-name-input" /></div>
                      <div><Label>Telefon</Label><Input value={profileForm.phone} onChange={(event) => setProfileForm((prev) => ({ ...prev, phone: event.target.value }))} data-testid="driver-profile-phone-input" /></div>
                      <div><Label>Email</Label><Input type="email" value={profileForm.email} onChange={(event) => setProfileForm((prev) => ({ ...prev, email: event.target.value }))} data-testid="driver-profile-email-input" /></div>
                      <div><Label>Parolă nouă manuală</Label><Input type="password" value={profileForm.new_password} onChange={(event) => setProfileForm((prev) => ({ ...prev, new_password: event.target.value }))} placeholder="Lasă gol dacă nu schimbi parola" data-testid="driver-profile-password-input" /></div>
                      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/20 dark:text-amber-100">
                        <KeyRound className="mr-2 inline h-4 w-4" /> Schimbările de email/parolă sunt logate în audit.
                      </div>
                      <Button onClick={saveProfile} disabled={actionLoading !== null} className="bg-orange-600 hover:bg-orange-700" data-testid="driver-profile-save-button"><Save className="mr-2 h-4 w-4" /> {actionLoading === "profile" ? "Se salvează..." : "Salvează profil"}</Button>
                    </CardContent>
                  </Card>
                  <Card>
                    <CardHeader><CardTitle className="flex items-center gap-2 text-base"><PauseCircle className="h-5 w-5 text-amber-600" /> Status operațional</CardTitle></CardHeader>
                    <CardContent className="space-y-3">
                      <div><Label>Status</Label><Select value={statusForm.status} onValueChange={(value) => setStatusForm((prev) => ({ ...prev, status: value }))}><SelectTrigger data-testid="driver-status-select"><SelectValue /></SelectTrigger><SelectContent><SelectItem value="active">Activ</SelectItem><SelectItem value="break">În pauză</SelectItem><SelectItem value="offline">Offline</SelectItem></SelectContent></Select></div>
                      {statusForm.status === "break" && <div><Label>Durată pauză (minute)</Label><Input type="number" min="1" max="180" value={statusForm.break_minutes} onChange={(event) => setStatusForm((prev) => ({ ...prev, break_minutes: Number(event.target.value) || 30 }))} data-testid="driver-break-minutes-input" /></div>}
                      <div className="rounded-lg border bg-muted/30 p-3 text-sm"><strong>Regulă:</strong> în pauză rămâne vizibil pe hartă cu timer; offline nu apare pe hartă.</div>
                      <Button onClick={updateStatus} disabled={actionLoading !== null} data-testid="driver-status-save-button"><ShieldCheck className="mr-2 h-4 w-4" /> {actionLoading === "status" ? "Se salvează..." : "Actualizează status"}</Button>
                    </CardContent>
                  </Card>
                </div>
                <Card>
                  <CardHeader><CardTitle className="text-base">Rank manual</CardTitle></CardHeader>
                  <CardContent className="grid gap-3 md:grid-cols-[180px_1fr_auto_auto]">
                    <div><Label>Scor 0-100</Label><Input type="number" min="0" max="100" step="0.1" value={rankForm.manual_ranking_score} onChange={(event) => setRankForm((prev) => ({ ...prev, manual_ranking_score: event.target.value }))} data-testid="driver-manual-score-input" /></div>
                    <div><Label>Notă internă</Label><Textarea value={rankForm.manual_rank_note} onChange={(event) => setRankForm((prev) => ({ ...prev, manual_rank_note: event.target.value }))} data-testid="driver-rank-note-input" /></div>
                    <Button onClick={saveRanking} disabled={actionLoading !== null} className="self-end" data-testid="driver-save-rank-button"><Save className="mr-2 h-4 w-4" /> {actionLoading === "rank" ? "Se salvează..." : "Salvează"}</Button>
                    <Button variant="outline" onClick={clearRanking} disabled={actionLoading !== null} className="self-end" data-testid="driver-clear-manual-rank-button">Automat</Button>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="schedule" className="space-y-4">
                {profileWarnings.hasWarning && (
                  <div className="rounded-lg border border-amber-300 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/20 dark:text-amber-100" data-testid="driver-schedule-overload-warning">
                    <AlertTriangle className="mr-2 inline h-4 w-4" /> Acest program depășește limita recomandată{profileWarnings.weekOver ? ` de ${RECOMMENDED_WEEKLY_HOURS}h/săptămână` : ""}{profileWarnings.dailyOver.length ? `: ${profileWarnings.dailyOver.join(", ")}` : ""}. Sistemul avertizează, adminul decide final.
                  </div>
                )}
                <Card>
                  <CardHeader><CardTitle className="flex items-center gap-2 text-base"><CalendarCheck className="h-5 w-5 text-emerald-600" /> Calendar vizual livrator · săptămâna curentă</CardTitle></CardHeader>
                  <CardContent className="space-y-4">
                    <div className="flex flex-wrap items-center justify-between gap-3 text-xs">
                      <div className="flex flex-wrap gap-3"><span className="flex items-center gap-1"><span className="h-3 w-3 rounded bg-emerald-500" /> Normal</span><span className="flex items-center gap-1"><span className="h-3 w-3 rounded bg-red-500" /> Urgență</span><span className="flex items-center gap-1"><span className="h-3 w-3 rounded bg-slate-200" /> Liber</span></div>
                      <div className="flex rounded-lg border p-1" data-testid="driver-calendar-slot-mode">
                        <button type="button" onClick={() => setCalendarSlotMode("normal")} className={`rounded px-3 py-1 font-bold ${calendarSlotMode === "normal" ? "bg-emerald-600 text-white" : "text-muted-foreground"}`} data-testid="driver-calendar-mode-normal-button">Normal</button>
                        <button type="button" onClick={() => setCalendarSlotMode("emergency")} className={`rounded px-3 py-1 font-bold ${calendarSlotMode === "emergency" ? "bg-red-600 text-white" : "text-muted-foreground"}`} data-testid="driver-calendar-mode-emergency-button">Urgență</button>
                      </div>
                    </div>
                    <div className="overflow-x-auto">
                      <div className="min-w-[760px] text-xs" role="table" aria-label="Calendar livrator individual">
                        <div className="grid grid-cols-[90px_repeat(7,minmax(80px,1fr))]" role="row">
                          <div className="p-2 font-bold" role="columnheader">Interval</div>
                          {DAYS.map((day) => (
                            <div key={day.key} className="p-2 text-center font-bold" role="columnheader">
                              {day.label}
                            </div>
                          ))}
                        </div>
                        {ALL_HOURS.map((hour) => (
                          <div key={hour} className="grid grid-cols-[90px_repeat(7,minmax(80px,1fr))]" role="row">
                            <div className="p-2 font-mono text-muted-foreground" role="rowheader"><Clock className="mr-1 inline h-3 w-3" />{formatInterval(hour)}</div>
                            {DAYS.map((day) => {
                              const slot = (editSlots[day.key] || []).find((item) => item.start === hour);
                              const isEmergency = slot?.added_by === "emergency";
                              const className = slot ? (isEmergency ? "border-red-300 bg-red-500 text-white" : "border-emerald-300 bg-emerald-500 text-white") : "border-slate-200 bg-slate-100 text-slate-400 hover:bg-slate-200 dark:bg-slate-900";
                              return (
                                <div key={day.key} className="p-1" role="cell">
                                  <button type="button" onClick={() => toggleHour(day.key, hour)} className={`h-9 w-full rounded border text-[11px] font-bold transition-colors ${className}`} data-testid={`driver-calendar-cell-${day.key}-${hour}`} title={slot?.warning || (slot ? "Slot rezervat" : "Liber")}>{slot ? (isEmergency ? "URG" : slot.forced ? "FORȚAT" : "OK") : "liber"}</button>
                                </div>
                              );
                            })}
                          </div>
                        ))}
                      </div>
                    </div>
                    <div className="flex flex-wrap items-center justify-between gap-3"><div className="text-sm text-muted-foreground">Click pe o celulă pentru a adăuga sau scoate ora. Total selectat: <strong>{profileWarnings.total}h</strong></div><Button onClick={saveSchedule} disabled={savingSchedule} className="bg-orange-600 hover:bg-orange-700" data-testid="driver-save-forced-schedule-button"><Save className="mr-2 h-4 w-4" /> {savingSchedule ? "Se salvează..." : "Salvează program"}</Button></div>
                  </CardContent>
                </Card>
              </TabsContent>

              <TabsContent value="avatar" className="grid gap-4 lg:grid-cols-2">
                <Card><CardHeader><CardTitle className="text-base">Setează avatar ca admin</CardTitle></CardHeader><CardContent><AvatarUploadCropper onUpload={uploadAvatar} isUploading={uploadingAvatar} testIdPrefix="admin-driver-avatar" /><p className="mt-3 text-sm text-muted-foreground">Pozele încărcate de admin devin active imediat, fără aprobare.</p></CardContent></Card>
                <Card><CardHeader><CardTitle className="text-base">Poze trimise de livrator</CardTitle></CardHeader><CardContent className="space-y-3">{pendingAvatars.length === 0 && <p className="text-sm text-muted-foreground" data-testid="driver-avatar-no-pending">Nu există poze în așteptare.</p>}{pendingAvatars.map((avatar) => (<div key={avatar.id} className="flex items-center gap-3 rounded-lg border p-3" data-testid={`driver-avatar-pending-${avatar.id}`}><img src={`${API_URL}${avatar.image_url}`} alt="Avatar pending" className="h-16 w-16 rounded-full object-cover" /><div className="flex-1"><Badge className="bg-amber-100 text-amber-800">În așteptare aprobare</Badge><p className="mt-1 text-xs text-muted-foreground">Încărcat la {new Date(avatar.uploaded_at).toLocaleString("ro-RO")}</p></div><Button size="sm" onClick={() => moderateAvatar(avatar.id, "approve")} disabled={actionLoading !== null} data-testid={`driver-avatar-approve-${avatar.id}`}><CheckCircle2 className="mr-1 h-4 w-4" /> Aprobă</Button><Button size="sm" variant="destructive" onClick={() => moderateAvatar(avatar.id, "reject")} disabled={actionLoading !== null} data-testid={`driver-avatar-reject-${avatar.id}`}><XCircle className="mr-1 h-4 w-4" /> Respinge</Button></div>))}</CardContent></Card>
              </TabsContent>

              <TabsContent value="history" className="grid gap-4 lg:grid-cols-2">
                <Card><CardHeader><CardTitle className="flex items-center gap-2 text-base"><Package className="h-5 w-5" /> Ultimele comenzi</CardTitle></CardHeader><CardContent className="max-h-72 space-y-2 overflow-y-auto">{recentOrders.map((order) => (<div key={order.id} className="flex justify-between rounded-lg border p-2 text-sm" data-testid={`driver-recent-order-${order.id}`}><span><strong>{order.order_number}</strong><br /><span className="text-muted-foreground">{order.restaurant_name}</span></span><Badge variant="outline">{order.status}</Badge></div>))}{recentOrders.length === 0 && <p className="text-sm text-muted-foreground">Nu există comenzi recente.</p>}</CardContent></Card>
                <Card><CardHeader><CardTitle className="flex items-center gap-2 text-base"><ShieldCheck className="h-5 w-5" /> Audit securitate</CardTitle></CardHeader><CardContent className="max-h-72 space-y-2 overflow-y-auto">{auditLogs.map((log) => (<div key={log.id} className="rounded-lg border p-2 text-xs" data-testid={`driver-audit-log-${log.id}`}><p className="font-bold">{log.action}</p><p className="text-muted-foreground">{new Date(log.created_at).toLocaleString("ro-RO")} · {log.performed_by_email}</p></div>))}{auditLogs.length === 0 && <p className="text-sm text-muted-foreground">Nu există acțiuni logate încă.</p>}</CardContent></Card>
              </TabsContent>

              <TabsContent value="danger">
                <div className="space-y-4">
                  <Card className="border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/20"><CardContent className="space-y-3 p-4"><p className="font-bold text-amber-950 dark:text-amber-100">Dezactivează cont</p><p className="text-sm text-amber-900/80 dark:text-amber-100/80">Recomandat pentru plecări temporare: livratorul nu se mai poate autentifica, nu apare în flotă și rămâne istoricul intact. Sistemul blochează dacă are comenzi active.</p><Textarea value={disableReason} onChange={(event) => setDisableReason(event.target.value)} placeholder="Motiv intern opțional" data-testid="driver-disable-reason-input" /><Button variant="outline" onClick={disableDriver} disabled={actionLoading !== null} className="border-amber-400 text-amber-800 hover:bg-amber-100" data-testid="driver-disable-account-button"><PauseCircle className="mr-2 h-4 w-4" /> {actionLoading === "disable" ? "Se dezactivează..." : "Dezactivează cont"}</Button></CardContent></Card>
                  <Card className="border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/20"><CardContent className="space-y-3 p-4"><p className="font-bold text-red-900 dark:text-red-100">Ștergere definitivă din baza de date</p><p className="text-sm text-red-800/80 dark:text-red-100/80">Ștergerea elimină contul, profilul și programările. Folosește doar când e sigur că nu mai ai nevoie de cont.</p><div className="grid gap-2 sm:grid-cols-[1fr_auto]"><Input value={deleteText} onChange={(event) => setDeleteText(event.target.value)} placeholder="Scrie STERGE pentru confirmare" data-testid="driver-delete-confirm-input" /><Button variant="destructive" onClick={deleteDriver} disabled={deleteText !== "STERGE" || actionLoading !== null} data-testid="driver-delete-button"><Trash2 className="mr-2 h-4 w-4" /> {actionLoading === "delete" ? "Se șterge..." : "Șterge"}</Button></div></CardContent></Card>
                </div>
              </TabsContent>
            </Tabs>
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
};
