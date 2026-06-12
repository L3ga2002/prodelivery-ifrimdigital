import { useState, useEffect, useCallback, useMemo, useReducer } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "../components/ui/dialog";
import {
  ChevronLeft,
  ChevronRight,
  Save,
  CalendarCheck,
  Lock,
  Info,
  Flame,
  CheckCircle2,
} from "lucide-react";
import { getApiErrorMessage, normalizeArray, normalizeObject, retryApiCall } from "../lib/api";

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

// Driver editable: 10:00-22:00 (12 intervals: 10-11, 11-12, ..., 21-22)
const DRIVER_HOURS = Array.from({ length: 12 }, (_, i) => `${String(i + 10).padStart(2, "0")}:00`);
// Night: 22-23, 23-00, 00-01, 01-02 (admin only, read-only for driver)
const NIGHT_HOURS = ["22:00", "23:00", "00:00", "01:00"];
const isScheduleNightHour = (hour) => NIGHT_HOURS.includes(hour);
const driverWeekStartReducer = (state, action) => {
  if (action.type !== "shift") return state;
  const next = new Date(state);
  next.setDate(next.getDate() + action.dir * 7);
  return next;
};
const ALL_HOURS = [...DRIVER_HOURS, ...NIGHT_HOURS];

function formatInterval(hour) {
  const h = parseInt(hour);
  const next = (h + 1) % 24;
  return `${String(h).padStart(2, "0")}-${String(next).padStart(2, "0")}`;
}

function getMonday(date) {
  const d = new Date(date);
  const day = d.getDay();
  const diff = d.getDate() - day + (day === 0 ? -6 : 1);
  d.setDate(diff);
  d.setHours(0, 0, 0, 0);
  return d;
}

function formatWeekRange(monday) {
  const sun = new Date(monday);
  sun.setDate(sun.getDate() + 6);
  const opts = { day: "numeric", month: "short" };
  return `${monday.toLocaleDateString("ro-RO", opts)} - ${sun.toLocaleDateString("ro-RO", opts)}`;
}

function toISODate(d) {
  return d.toISOString().split("T")[0];
}

export const DriverSchedule = ({ driverId }) => {
  const [weekStart, dispatchWeekStart] = useReducer(driverWeekStartReducer, undefined, () => getMonday(new Date()));
  const [slots, setSlots] = useState({});
  const [selectedDay, setSelectedDay] = useState("monday");
  const [saving, setSaving] = useState(false);
  const [totalHours, setTotalHours] = useState(0);
  const [windowOpen, setWindowOpen] = useState(true);
  const [scheduleWindowInfo, setScheduleWindowInfo] = useState(null);
  const [emergencySlots, setEmergencySlots] = useState([]);
  const [claimDialog, setClaimDialog] = useState(null);
  const [claiming, setClaiming] = useState(false);
  const [rankDialogOpen, setRankDialogOpen] = useState(false);

  const fetchSchedule = useCallback(async () => {
    if (!driverId) return;
    try {
      const [schedRes, windowRes, emergencyRes] = await retryApiCall(() => Promise.all([
        axios.get(`${API_URL}/api/schedules/driver/${driverId}?year=${weekStart.getFullYear()}`),
        axios.get(`${API_URL}/api/schedules/scheduling-window`),
        axios.get(`${API_URL}/api/schedules/emergency?week_start=${toISODate(weekStart)}`),
      ]));
      const wsKey = toISODate(weekStart);
      const schedules = normalizeArray(schedRes.data);
      const windowData = normalizeObject(windowRes.data);
      const found = schedules.find((s) => s.week_start === wsKey);
      if (found) {
        setSlots(found.slots || {});
        setTotalHours(found.total_hours || 0);
      } else {
        setSlots({});
        setTotalHours(0);
      }
      setWindowOpen(windowData.can_select_schedule ?? windowData.is_open);
      setScheduleWindowInfo(windowData);
      setEmergencySlots(normalizeArray(emergencyRes.data));
    } catch (error) {
      setSlots({});
      setTotalHours(0);
      toast.error(getApiErrorMessage(error, "Nu am putut încărca programul"));
    }
  }, [driverId, weekStart]);

  useEffect(() => {
    fetchSchedule();
  }, [fetchSchedule]);

  const getAvailableEmergency = (dayKey, hour) => {
    // Only show emergency slots where driver has NO schedule at this hour
    const hasSchedule = (slots[dayKey] || []).some((s) => s.start === hour);
    if (hasSchedule) return null;
    return emergencySlots.find((s) => s.day === dayKey && s.hour === hour && s.remaining_spots > 0 && !(s.claimed_by || []).includes(driverId));
  };

  const toggleHour = (dayKey, hour) => {
    const daySlots = slots[dayKey] || [];
    if (isScheduleNightHour(hour)) return;
    if (daySlots.some((slot) => slot.start === hour && slot.added_by === "admin")) return;
    if (daySlots.some((slot) => slot.start === hour && slot.added_by === "emergency")) return;
    if (!windowOpen) return;

    setSlots((prev) => {
      const daySlots = prev[dayKey] || [];
      const exists = daySlots.find((s) => s.start === hour && s.added_by !== "admin" && s.added_by !== "emergency");
      let newDaySlots;
      if (exists) {
        newDaySlots = daySlots.filter((s) => !(s.start === hour && s.added_by !== "admin" && s.added_by !== "emergency"));
      } else {
        const endH = (parseInt(hour) + 1) % 24;
        newDaySlots = [...daySlots, { start: hour, end: `${String(endH).padStart(2, "0")}:00`, added_by: "driver" }];
      }
      const newSlots = { ...prev, [dayKey]: newDaySlots };
      let total = 0;
      Object.values(newSlots).forEach((ds) => { total += ds.length; });
      setTotalHours(total);
      return newSlots;
    });
  };

  const getSlotType = (dayKey, hour) => {
    const daySlots = slots[dayKey] || [];
    const slot = daySlots.find((s) => s.start === hour);
    const availableEmergency = getAvailableEmergency(dayKey, hour);
    if (slot?.added_by === "emergency") return { key: "emergency", label: "Urgență luată", tone: "bg-red-500 text-white border-red-400", dot: "bg-red-300", interactive: false };
    if (slot?.added_by === "admin") return { key: "admin", label: "Admin", tone: "bg-blue-500 text-white border-blue-400", dot: "bg-blue-200", interactive: false };
    if (slot) return { key: "driver", label: "Ora ta", tone: "bg-orange-500 text-white border-orange-400", dot: "bg-orange-200", interactive: windowOpen };
    if (availableEmergency) return { key: "available-emergency", label: `${availableEmergency.remaining_spots} locuri urgență`, tone: "bg-red-500/15 text-red-100 border-red-500/60", dot: "bg-red-400", interactive: true, emergency: availableEmergency };
    if (isScheduleNightHour(hour)) return { key: "night", label: "Noapte blocată", tone: "bg-slate-800 text-slate-400 border-slate-700", dot: "bg-slate-500", interactive: false };
    if (!windowOpen) return { key: "closed", label: "Liber", tone: "bg-white/[0.04] text-zinc-500 border-white/10", dot: "bg-zinc-700", interactive: false };
    return { key: "free", label: "Liber", tone: "bg-white/[0.04] text-zinc-300 border-white/10", dot: "bg-zinc-600", interactive: true };
  };

  const getDayCounts = (dayKey) => {
    const daySlots = slots[dayKey] || [];
    return {
      driver: daySlots.filter((slot) => slot.added_by === "driver" || !slot.added_by).length,
      admin: daySlots.filter((slot) => slot.added_by === "admin").length,
      emergency: daySlots.filter((slot) => slot.added_by === "emergency").length,
      total: daySlots.length,
    };
  };

  const claimEmergencySlot = async () => {
    if (!claimDialog || claiming) return;
    setClaiming(true);
    try {
      const res = await axios.post(`${API_URL}/api/schedules/emergency/${claimDialog.id}/claim`);
      toast.success(normalizeObject(res.data).message || "Slot preluat");
      setClaimDialog(null);
      await fetchSchedule();
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Eroare la preluare slot"));
    } finally {
      setClaiming(false);
    }
  };

  const saveSchedule = async () => {
    if (saving) return;
    if (!windowOpen) {
      toast.error("Programul poate fi modificat doar Duminică 22:00 - Luni 10:00");
      return;
    }
    setSaving(true);
    try {
      await axios.post(`${API_URL}/api/schedules`, {
        driver_id: driverId,
        week_start: toISODate(weekStart),
        slots,
        source: "driver",
      });
      toast.success("Program salvat cu succes!");
      await fetchSchedule();
    } catch (err) {
      toast.error(getApiErrorMessage(err, "Eroare la salvare"));
    } finally {
      setSaving(false);
    }
  };

  const shiftWeek = useCallback((dir) => dispatchWeekStart({ type: "shift", dir }), []);

  const selectFullDay = (dayKey) => {
    if (!windowOpen) return;
    setSlots((prev) => {
      const daySlots = prev[dayKey] || [];
      const adminSlots = daySlots.filter((s) => s.added_by === "admin" || s.added_by === "emergency");
      const driverSlots = daySlots.filter((s) => s.added_by !== "admin" && s.added_by !== "emergency");

      let newSlots;
      if (driverSlots.length === DRIVER_HOURS.length) {
        newSlots = { ...prev, [dayKey]: adminSlots };
      } else {
        const fullDriverSlots = DRIVER_HOURS.map((h) => {
          const endH = (parseInt(h) + 1) % 24;
          return { start: h, end: `${String(endH).padStart(2, "0")}:00`, added_by: "driver" };
        });
        newSlots = { ...prev, [dayKey]: [...fullDriverSlots, ...adminSlots] };
      }
      let total = 0;
      Object.values(newSlots).forEach((ds) => { total += ds.length; });
      setTotalHours(total);
      return newSlots;
    });
  };

  const driverHoursCount = useMemo(
    () => Object.values(slots).reduce((sum, ds) => sum + ds.filter((s) => s.added_by === "driver" || !s.added_by).length, 0),
    [slots],
  );
  const adminHoursCount = useMemo(
    () => Object.values(slots).reduce((sum, ds) => sum + ds.filter((s) => s.added_by === "admin").length, 0),
    [slots],
  );
  const emergencyCount = useMemo(
    () => Object.values(slots).reduce((sum, ds) => sum + ds.filter((s) => s.added_by === "emergency").length, 0),
    [slots],
  );
  const availableEmergencyCount = useMemo(
    () => emergencySlots.filter((slot) => {
      const hasSchedule = (slots[slot.day] || []).some((scheduledSlot) => scheduledSlot.start === slot.hour);
      return !hasSchedule && slot.remaining_spots > 0 && !(slot.claimed_by || []).includes(driverId);
    }).length,
    [driverId, emergencySlots, slots],
  );

  return (
    <Card className="overflow-hidden border-white/10 bg-[#0d1118] text-white shadow-2xl" data-testid="driver-schedule-card">
      <CardHeader className="space-y-4 pb-3">
        <div className="flex items-start justify-between gap-3">
          <CardTitle className="flex items-center gap-2 text-lg text-white">
            <CalendarCheck className="h-5 w-5 text-orange-400" />
            Program săptămânal
          </CardTitle>
          <Button variant="ghost" size="icon" onClick={() => setRankDialogOpen(true)} className="h-9 w-9 rounded-full bg-white/5 text-zinc-300 hover:bg-white/10" data-testid="driver-schedule-info-button">
            <Info className="h-4 w-4" />
          </Button>
        </div>

        <div className="grid grid-cols-3 gap-2" data-testid="driver-schedule-summary-chips">
          <div className="rounded-2xl border border-orange-500/30 bg-orange-500/10 p-2 text-center"><p className="text-lg font-black text-orange-200">{driverHoursCount}h</p><p className="text-[10px] font-bold text-orange-100/80">ale tale</p></div>
          <div className="rounded-2xl border border-blue-500/30 bg-blue-500/10 p-2 text-center"><p className="text-lg font-black text-blue-200">{adminHoursCount}h</p><p className="text-[10px] font-bold text-blue-100/80">admin</p></div>
          <div className="rounded-2xl border border-red-500/30 bg-red-500/10 p-2 text-center"><p className="text-lg font-black text-red-200">{emergencyCount}h</p><p className="text-[10px] font-bold text-red-100/80">urgență</p></div>
        </div>

        {/* Scheduling window info */}
        <div className={`flex items-start gap-2 rounded-2xl px-3 py-2 text-xs ${
          windowOpen ? "border border-emerald-500/30 bg-emerald-500/10 text-emerald-100" : "border border-amber-500/40 bg-amber-500/12 text-amber-100"
        }`}>
          {windowOpen ? (
            <>
              <CalendarCheck className="w-4 h-4 shrink-0" />
              <span className="font-medium">Fereastra de program este DESCHISĂ.</span>
            </>
          ) : (
            <>
              <Lock className="w-4 h-4 shrink-0" />
              <span className="font-medium">Editare: Duminică 22:00 - Luni 10:00</span>
            </>
          )}
        </div>

        {scheduleWindowInfo?.tier && (
          <div className="flex flex-wrap gap-2 text-xs" data-testid="driver-ranking-access-info">
            <button type="button" onClick={() => setRankDialogOpen(true)} data-testid="driver-rank-info-button">
              <Badge className="border border-amber-500/30 bg-amber-500/15 text-amber-100">Tier {scheduleWindowInfo.tier}</Badge>
            </button>
            <button type="button" onClick={() => setRankDialogOpen(true)} data-testid="driver-score-info-button">
              <Badge className="border border-white/10 bg-white/5 text-white">Scor {scheduleWindowInfo.score}</Badge>
            </button>
            {!windowOpen && <Badge className="border border-blue-500/30 bg-blue-500/10 text-blue-100">Acces {scheduleWindowInfo.opens_at_label || scheduleWindowInfo.opens_at}</Badge>}
        </div>
        )}

        {/* Emergency slots notification */}
        {availableEmergencyCount > 0 && (
          <div className="flex items-center gap-2 mt-2 px-3 py-2 rounded-lg text-xs bg-red-50 text-red-700 border border-red-200 animate-pulse">
            <Flame className="w-4 h-4 shrink-0" />
            <span className="font-bold">{availableEmergencyCount} sloturi de urgență disponibile! Apasă pe celulele roșii pentru a le lua.</span>
          </div>
        )}

        <div className="flex items-center justify-between rounded-2xl border border-white/10 bg-black/20 px-2 py-1">
          <Button variant="ghost" size="icon" onClick={() => shiftWeek(-1)} className="text-zinc-300 hover:bg-white/10" data-testid="prev-week-btn">
            <ChevronLeft className="w-5 h-5" />
          </Button>
          <span className="font-black text-sm text-white" data-testid="week-range">{formatWeekRange(weekStart)}</span>
          <Button variant="ghost" size="icon" onClick={() => shiftWeek(1)} className="text-zinc-300 hover:bg-white/10" data-testid="next-week-btn">
            <ChevronRight className="w-5 h-5" />
          </Button>
        </div>
      </CardHeader>
      <CardContent className="space-y-4">
        {/* Legend */}
        <div className="grid grid-cols-2 gap-2 text-[11px] font-bold sm:grid-cols-4" data-testid="driver-schedule-legend">
          <div className="flex items-center gap-1.5 rounded-full bg-white/5 px-2 py-1"><div className="h-3 w-3 rounded bg-orange-500" /><span>Orele tale</span></div>
          <div className="flex items-center gap-1.5 rounded-full bg-white/5 px-2 py-1"><div className="h-3 w-3 rounded bg-blue-500" /><span>Admin</span></div>
          <div className="flex items-center gap-1.5 rounded-full bg-white/5 px-2 py-1"><div className="h-3 w-3 rounded bg-red-500" /><span>Urgență</span></div>
          <div className="flex items-center gap-1.5 rounded-full bg-white/5 px-2 py-1"><Lock className="h-3 w-3 text-slate-400" /><span>Noapte</span></div>
          </div>

        <div className="grid grid-cols-7 gap-1" data-testid="driver-schedule-day-selector">
          {DAYS.map((day) => {
            const counts = getDayCounts(day.key);
            const active = selectedDay === day.key;
            return (
              <button
                key={day.key}
                type="button"
                onClick={() => setSelectedDay(day.key)}
                className={`rounded-2xl border px-1 py-2 text-center transition-colors ${active ? "border-orange-400 bg-orange-500 text-black" : "border-white/10 bg-white/[0.04] text-zinc-300 hover:bg-white/10"}`}
                data-testid={`driver-schedule-day-button-${day.key}`}
              >
                <span className="block text-[11px] font-black">{day.label.slice(0, 3)}</span>
                <span className="mt-1 block text-[10px] font-bold opacity-80">{counts.total}h</span>
              </button>
            );
          })}
        </div>

        <div className="rounded-3xl border border-white/10 bg-black/20 p-3" data-testid={`driver-schedule-selected-day-${selectedDay}`}>
          <div className="mb-3 flex items-center justify-between gap-3">
            <div>
              <p className="text-xs font-bold uppercase tracking-[0.16em] text-zinc-500">Zi selectată</p>
              <h3 className="text-xl font-black text-white">{DAYS.find((day) => day.key === selectedDay)?.label}</h3>
            </div>
            <Button type="button" size="sm" variant="outline" disabled={!windowOpen} onClick={() => selectFullDay(selectedDay)} className="border-white/10 bg-white/5 text-white hover:bg-white/10 disabled:opacity-40" data-testid="driver-select-full-day-button">Toată ziua</Button>
          </div>

          <div className="space-y-2" data-testid="driver-schedule-mobile-hour-list">
            {ALL_HOURS.map((hour) => {
              const slotType = getSlotType(selectedDay, hour);
              const canClick = slotType.interactive;
              return (
                <button
                  key={`${selectedDay}-${hour}`}
                  type="button"
                  onClick={() => {
                    if (slotType.emergency) {
                      setClaimDialog(slotType.emergency);
                    } else if (canClick && !isScheduleNightHour(hour)) {
                      toggleHour(selectedDay, hour);
                    }
                  }}
                  disabled={!canClick}
                  className={`flex min-h-[54px] w-full items-center justify-between gap-3 rounded-2xl border px-3 py-2 text-left transition-all disabled:cursor-not-allowed disabled:opacity-75 ${slotType.tone}`}
                  data-testid={`slot-${selectedDay}-${hour}`}
                >
                  <span className="flex items-center gap-3">
                    <span className={`h-3 w-3 rounded-full ${slotType.dot}`} />
                    <span>
                      <span className="block font-mono text-sm font-black">{formatInterval(hour)}</span>
                      <span className="block text-[11px] font-bold opacity-80">{isScheduleNightHour(hour) ? "Interval de noapte" : "Interval standard"}</span>
                    </span>
                  </span>
                  <span className="rounded-full bg-black/20 px-2 py-1 text-xs font-black">{slotType.label}</span>
                </button>
              );
            })}
          </div>
        </div>

        {windowOpen ? (
          <Button
            className="w-full mt-4 h-12 text-base font-bold"
            style={{ background: "hsl(24 95% 53%)" }}
            onClick={saveSchedule}
            disabled={saving}
            data-testid="save-schedule-btn"
          >
            <Save className="w-5 h-5 mr-2" />
            {saving ? "Se salvează..." : "SALVEAZĂ PROGRAMUL"}
          </Button>
        ) : (
          <div className="mt-4 p-3 bg-muted/50 rounded-lg text-center text-sm text-muted-foreground flex items-center justify-center gap-2">
            <Info className="w-4 h-4" />
            Programul se modifică doar Duminică 22:00 - Luni 10:00
          </div>
        )}
      </CardContent>

      {/* Claim Emergency Slot Dialog */}
      <Dialog open={!!claimDialog} onOpenChange={(open) => !open && setClaimDialog(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-red-600">
              <Flame className="w-5 h-5" />
              Slot de Urgență
            </DialogTitle>
          </DialogHeader>
          <div className="space-y-3 py-2">
            <p className="text-sm">
              <strong>{DAYS.find((d) => d.key === claimDialog?.day)?.label}</strong> intervalul <strong>{claimDialog?.hour ? formatInterval(claimDialog.hour) : ""}</strong>
            </p>
            <div className="text-center p-4 bg-red-50 rounded-lg border border-red-200">
              <p className="text-3xl font-bold text-red-600">{claimDialog?.remaining_spots}</p>
              <p className="text-sm text-red-700">locuri rămase din {claimDialog?.total_spots}</p>
            </div>
            <p className="text-sm text-muted-foreground">
              Vrei să iei acest slot de urgență? Vei fi adăugat la program pe această oră.
            </p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setClaimDialog(null)}>Înapoi</Button>
            <Button
              className="bg-red-600 hover:bg-red-700"
              onClick={claimEmergencySlot}
              disabled={claiming}
              data-testid="claim-emergency-btn"
            >
              <CheckCircle2 className="w-4 h-4 mr-2" />
              {claiming ? "Se procesează..." : "Ia Slotul"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={rankDialogOpen} onOpenChange={setRankDialogOpen}>
        <DialogContent className="max-w-md" data-testid="driver-rank-dialog">
          <DialogHeader>
            <DialogTitle>Scor și rank</DialogTitle>
            <DialogDescription>
              Detaliu transparent pentru prioritizarea accesului la calendar.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-3">
              <div className="rounded-lg border bg-muted/40 p-3">
                <p className="text-xs text-muted-foreground">Rank curent</p>
                <p className="text-2xl font-bold">{scheduleWindowInfo?.tier || "Start"}</p>
              </div>
              <div className="rounded-lg border bg-muted/40 p-3">
                <p className="text-xs text-muted-foreground">Scor total</p>
                <p className="text-2xl font-bold">{scheduleWindowInfo?.score || 0}</p>
              </div>
            </div>
            <div className="space-y-2 text-sm">
              {Object.entries(scheduleWindowInfo?.breakdown || {}).map(([key, value]) => {
                const labels = { deliveries: "Livrări", cancellations: "Anulări", punctuality: "Punctualitate", seniority: "Vechime" };
                return (
                  <div key={key} className="flex items-center justify-between rounded-md border p-2">
                    <span>{labels[key] || key}</span>
                    <strong>{value} pct</strong>
                  </div>
                );
              })}
            </div>
            <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-sm text-indigo-900 dark:border-indigo-900 dark:bg-indigo-950/30 dark:text-indigo-100">
              <p><strong>Ore selectate săptămâna asta:</strong> {totalHours}h</p>
              <p><strong>Livrări totale:</strong> {scheduleWindowInfo?.metrics?.total_deliveries || 0}</p>
              <p><strong>Punctualitate:</strong> {Math.round((scheduleWindowInfo?.metrics?.punctuality_rate || 0) * 100)}%</p>
              {scheduleWindowInfo?.next_tier ? (
                <p><strong>Următorul rank:</strong> încă {scheduleWindowInfo.points_to_next_tier} puncte până la {scheduleWindowInfo.next_tier.label}</p>
              ) : (
                <p><strong>Următorul rank:</strong> ești deja la nivelul maxim.</p>
              )}
            </div>
          </div>
        </DialogContent>
      </Dialog>
    </Card>
  );
};
