import { useState, useEffect, useCallback, useReducer } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
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
  CalendarCheck,
  Clock,
  Truck,
  Save,
  Users,
  MapPin,
  Moon,
  AlertTriangle,
  Flame,
  Plus,
  Minus,
  Settings2,
  Trash2,
  Repeat,
} from "lucide-react";

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

// Admin editable: all hours 10:00-02:00 (16 intervals)
const ALL_HOURS = [
  ...Array.from({ length: 14 }, (_, i) => `${String(i + 10).padStart(2, "0")}:00`),
  "00:00", "01:00",
];
const NIGHT_HOURS = ["22:00", "23:00", "00:00", "01:00"];
// Emergency slots: ONLY 10:00-22:00
const EMERGENCY_HOURS = Array.from({ length: 12 }, (_, i) => `${String(i + 10).padStart(2, "0")}:00`);

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

const getCoverageToneClass = (count) => {
  if (count === 0) return "bg-amber-100";
  if (count <= 1) return "bg-yellow-100";
  if (count <= 2) return "bg-blue-100";
  return "bg-emerald-100";
};

const getCoverageTextClass = (count) => {
  if (count === 0) return "text-amber-700";
  if (count <= 1) return "text-yellow-600";
  if (count <= 2) return "text-blue-600";
  return "text-emerald-600";
};

const getQuickDeltaClass = (delta, mode) => {
  if (delta <= 0) return "";
  return mode === "emergency" ? "bg-red-600 hover:bg-red-700" : "bg-emerald-600 hover:bg-emerald-700";
};

const getSimpleStandardLabel = (slot) => {
  if (!slot) return "Liber";
  return slot.added_by === "admin" ? "Admin" : "Liv";
};

const getSimpleStandardClass = (slot) => {
  if (!slot) return "border-slate-200 bg-slate-50 text-slate-500 hover:bg-emerald-50 hover:text-emerald-700 dark:border-slate-800 dark:bg-slate-900 dark:text-slate-400 dark:hover:bg-emerald-950/30";
  return slot.added_by === "admin"
    ? "border-emerald-400 bg-emerald-600 text-white hover:bg-emerald-500"
    : "border-orange-400 bg-orange-500 text-white hover:bg-orange-400";
};

const weekStartReducer = (state, action) => {
  if (action.type !== "shift") return state;
  const next = new Date(state);
  next.setDate(next.getDate() + action.dir * 7);
  return next;
};

const ZONE_COLORS = {
  "Zona 1": "bg-blue-100 text-blue-700",
  "Zona 2": "bg-green-100 text-green-700",
  "Zona 3": "bg-purple-100 text-purple-700",
  "Zona 4": "bg-orange-100 text-orange-700",
  "Neatribuită": "bg-gray-100 text-gray-600",
};

export const AdminScheduleView = () => {
  const [weekStart, dispatchWeekStart] = useReducer(weekStartReducer, undefined, () => getMonday(new Date()));
  const [summary, setSummary] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editDriver, setEditDriver] = useState(null);
  const [editSlots, setEditSlots] = useState({});
  const [saving, setSaving] = useState(false);
  // Emergency slots
  const [emergencySlots, setEmergencySlots] = useState([]);
  const [emergencyMode, setEmergencyMode] = useState(false);
  const [emergencyDialog, setEmergencyDialog] = useState(null); // {day, hour}
  const [emergencySpots, setEmergencySpots] = useState(1);
  const [autoGenerating, setAutoGenerating] = useState(false);
  const [setupDialogOpen, setSetupDialogOpen] = useState(false);
  const [calendarMode, setCalendarMode] = useState("normal");
  const [quickSlotDialog, setQuickSlotDialog] = useState(null);
  const [quickManualAmount, setQuickManualAmount] = useState(4);
  const [clonePreview, setClonePreview] = useState(null);
  const [setupForm, setSetupForm] = useState({
    days: ["monday", "tuesday", "wednesday", "thursday", "friday"],
    start_hour: "10:00",
    end_hour: "18:00",
    total_slots: 3,
    slot_type: "normal",
    repeat_weeks: 1,
  });

  const fetchData = useCallback(async () => {
    setLoading(true);
    try {
      const [summaryRes, emergencyRes] = await Promise.all([
        axios.get(`${API_URL}/api/schedules/admin/summary?week_start=${toISODate(weekStart)}`),
        axios.get(`${API_URL}/api/schedules/emergency?week_start=${toISODate(weekStart)}`),
      ]);
      setSummary(summaryRes.data);
      setEmergencySlots(emergencyRes.data);
    } catch {
      toast.error("Eroare la încărcarea datelor");
    } finally {
      setLoading(false);
    }
  }, [weekStart]);

  useEffect(() => {
    fetchData();
  }, [fetchData]);

  const shiftWeek = useCallback((dir) => dispatchWeekStart({ type: "shift", dir }), []);

  // Driver schedule edit
  const openEdit = (driver) => {
    const sched = driver.schedules?.find((s) => s.week_start === toISODate(weekStart));
    setEditSlots(sched?.slots || {});
    setEditDriver(driver);
  };

  const buildAdminSlot = (hour, addedBy = "admin") => {
    const endH = (parseInt(hour, 10) + 1) % 24;
    return { start: hour, end: `${String(endH).padStart(2, "0")}:00`, added_by: addedBy };
  };

  const toggleHour = (dayKey, hour, type = "standard") => {
    setEditSlots((prev) => {
      const daySlots = prev[dayKey] || [];
      const isEmergencyToggle = type === "emergency";
      const exists = daySlots.find((s) => s.start === hour && (isEmergencyToggle ? s.added_by === "emergency" : s.added_by !== "emergency"));
      let newDaySlots;
      if (exists) {
        newDaySlots = daySlots.filter((s) => !(s.start === hour && (isEmergencyToggle ? s.added_by === "emergency" : s.added_by !== "emergency")));
      } else {
        newDaySlots = [...daySlots, buildAdminSlot(hour, isEmergencyToggle ? "emergency" : "admin")];
      }
      return { ...prev, [dayKey]: newDaySlots };
    });
  };

  const saveSchedule = async () => {
    setSaving(true);
    try {
      await axios.post(`${API_URL}/api/schedules`, {
        driver_id: editDriver.driver_id,
        week_start: toISODate(weekStart),
        slots: editSlots,
        source: "admin",
      });
      toast.success(`Program salvat pentru ${editDriver.driver_name}`);
      setEditDriver(null);
      fetchData();
    } catch {
      toast.error("Eroare la salvare");
    } finally {
      setSaving(false);
    }
  };

  // Emergency slot functions
  const getEmergencySlot = (day, hour) => {
    return emergencySlots.find((s) => s.day === day && s.hour === hour);
  };

  const handleEmergencyCellClick = (day, hour) => {
    const existing = getEmergencySlot(day, hour);
    setEmergencySpots(existing?.total_spots || 1);
    setEmergencyDialog({ day, hour, existing });
  };

  const saveEmergencySlot = async () => {
    try {
      await axios.post(`${API_URL}/api/schedules/emergency`, {
        week_start: toISODate(weekStart),
        day: emergencyDialog.day,
        hour: emergencyDialog.hour,
        total_spots: emergencySpots,
      });
      toast.success(`Slot urgență setat: ${emergencySpots} locuri`);
      setEmergencyDialog(null);
      fetchData();
    } catch {
      toast.error("Eroare la creare slot urgență");
    }
  };

  const deleteEmergencySlot = async (slotId) => {
    try {
      await axios.delete(`${API_URL}/api/schedules/emergency/${slotId}`);
      toast.success("Slot urgență șters");
      setEmergencyDialog(null);
      fetchData();
    } catch {
      toast.error("Eroare la ștergere");
    }
  };

  const autoGenerateEmergencySlots = async () => {
    setAutoGenerating(true);
    try {
      const response = await axios.post(`${API_URL}/api/schedules/emergency/auto-generate`, null, {
        params: { week_start: toISODate(weekStart) },
      });
      toast.success(response.data.message);
      fetchData();
    } catch {
      toast.error("Eroare la generarea automată a sloturilor");
    } finally {
      setAutoGenerating(false);
    }
  };

  const toggleSetupDay = (dayKey) => {
    setSetupForm((prev) => ({
      ...prev,
      days: prev.days.includes(dayKey)
        ? prev.days.filter((day) => day !== dayKey)
        : [...prev.days, dayKey],
    }));
  };

  const submitSetupGeneration = async () => {
    if (setupForm.days.length === 0) {
      toast.error("Alege cel puțin o zi");
      return;
    }
    setAutoGenerating(true);
    try {
      if (setupForm.slot_type === "emergency") {
        const response = await axios.post(`${API_URL}/api/schedules/emergency/setup-generate`, {
          ...setupForm,
          week_start: toISODate(weekStart),
        });
        toast.success(response.data.message);
      } else {
        const response = await axios.post(`${API_URL}/api/schedules/admin/auto-generate`, {
          ...setupForm,
          week_start: toISODate(weekStart),
        });
        toast.success(response.data.message);
      }
      setSetupDialogOpen(false);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Eroare la generarea sloturilor");
    } finally {
      setAutoGenerating(false);
    }
  };

  const deleteGeneratedSlots = async () => {
    setAutoGenerating(true);
    try {
      const payload = {
        week_start: toISODate(weekStart),
        days: setupForm.days.length ? setupForm.days : DAYS.map((day) => day.key),
        start_hour: setupForm.start_hour,
        end_hour: setupForm.end_hour,
      };
      const response = setupForm.slot_type === "emergency"
        ? await axios.post(`${API_URL}/api/schedules/emergency/bulk-delete`, { ...payload, created_by: "system" })
        : await axios.post(`${API_URL}/api/schedules/admin/bulk-delete`, { ...payload, added_by: "auto" });
      toast.success(response.data.message);
      fetchData();
    } catch {
      toast.error("Eroare la ștergerea sloturilor automate");
    } finally {
      setAutoGenerating(false);
    }
  };

  const openQuickSlotDialog = (day, hour) => {
    if (calendarMode === "emergency" && !EMERGENCY_HOURS.includes(hour)) {
      toast.warning("Sloturile de urgență se pot modifica doar între 10:00-22:00");
      return;
    }
    setQuickSlotDialog({ day, hour, mode: calendarMode });
  };

  const adjustQuickSlot = async (delta) => {
    if (!quickSlotDialog) return;
    setAutoGenerating(true);
    try {
      const response = await axios.post(`${API_URL}/api/schedules/admin/quick-adjust`, {
        week_start: toISODate(weekStart),
        day: quickSlotDialog.day,
        hour: quickSlotDialog.hour,
        delta,
        slot_type: quickSlotDialog.mode,
      });
      const requested = Math.abs(delta);
      const adjusted = Math.abs(response.data.adjusted || 0);
      if (quickSlotDialog.mode === "normal" && delta > 0 && adjusted < requested) {
        toast.warning(`Am adăugat ${adjusted} din ${requested}. Sloturile standard se pot lega doar de livratori existenți fără program pe ora aceea.`);
      } else {
        toast.success(response.data.message || "Slot ajustat");
      }
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Nu am putut ajusta slotul");
    } finally {
      setAutoGenerating(false);
    }
  };

  const openClonePreview = async () => {
    setAutoGenerating(true);
    try {
      const response = await axios.post(`${API_URL}/api/schedules/admin/clone-previous-week`, {
        week_start: toISODate(weekStart),
        preview_only: true,
      });
      setClonePreview(response.data.preview);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Nu am putut genera preview-ul");
    } finally {
      setAutoGenerating(false);
    }
  };

  const confirmClonePreviousWeek = async () => {
    setAutoGenerating(true);
    try {
      const response = await axios.post(`${API_URL}/api/schedules/admin/clone-previous-week`, {
        week_start: toISODate(weekStart),
        preview_only: false,
      });
      toast.success(response.data.message);
      setClonePreview(null);
      fetchData();
    } catch (error) {
      toast.error(error.response?.data?.detail || "Eroare la refacerea sloturilor");
    } finally {
      setAutoGenerating(false);
    }
  };

  const getDayHoursCount = (schedules, dayKey) => {
    const sched = schedules?.find((s) => s.week_start === toISODate(weekStart));
    return (sched?.slots?.[dayKey] || []).length;
  };

  const getCoverageAtHour = (hour) => {
    let count = 0;
    summary.forEach((driver) => {
      const sched = driver.schedules?.find((s) => s.week_start === toISODate(weekStart));
      if (!sched) return;
      DAYS.forEach((d) => {
        if ((sched.slots?.[d.key] || []).some((s) => s.start === hour)) count++;
      });
    });
    return Math.round(count / 7);
  };

  const getCalendarCellMetrics = (dayKey, hour) => {
    const standardSlots = [];
    summary.forEach((driver) => {
      const sched = driver.schedules?.find((s) => s.week_start === toISODate(weekStart));
      const match = (sched?.slots?.[dayKey] || []).find((slot) => slot.start === hour && slot.added_by !== "emergency");
      if (match) standardSlots.push({ ...match, driver_name: driver.driver_name });
    });
    const standardAdmin = standardSlots.filter((slot) => ["admin", "auto"].includes(slot.added_by)).length;
    const standardDriver = standardSlots.length - standardAdmin;
    const emergencySlot = getEmergencySlot(dayKey, hour);
    const emergencyOccupied = emergencySlot ? Math.max((emergencySlot.total_spots || 0) - (emergencySlot.remaining_spots || 0), 0) : 0;
    return {
      standardTotal: standardSlots.length,
      standardAdmin,
      standardDriver,
      emergencySlot,
      emergencyOccupied,
      emergencyRemaining: emergencySlot?.remaining_spots || 0,
      emergencyTotal: emergencySlot?.total_spots || 0,
      driverNames: standardSlots.map((slot) => slot.driver_name),
    };
  };

  const weeklyCalendarTotals = DAYS.reduce((totals, day) => {
    ALL_HOURS.forEach((hour) => {
      const metrics = getCalendarCellMetrics(day.key, hour);
      totals.standard += metrics.standardTotal;
      totals.emergencyTotal += metrics.emergencyTotal;
      totals.emergencyRemaining += metrics.emergencyRemaining;
    });
    return totals;
  }, { standard: 0, emergencyTotal: 0, emergencyRemaining: 0 });

  const editTotalHours = Object.values(editSlots).reduce((s, ds) => s + ds.length, 0);
  const editEmergencyHours = Object.values(editSlots).reduce((s, ds) => s + ds.filter((sl) => sl.added_by === "emergency").length, 0);
  const editDriverHours = Object.values(editSlots).reduce((s, ds) => s + ds.filter((sl) => sl.added_by !== "admin" && sl.added_by !== "emergency").length, 0);
  const editAdminHours = Object.values(editSlots).reduce((s, ds) => s + ds.filter((sl) => sl.added_by === "admin").length, 0);

  return (
    <div className="space-y-6" data-testid="admin-schedule-view">
      {/* Week Selector + Main Scheduling Controls */}
      <div className="flex items-center justify-between">
        <Button variant="ghost" size="icon" onClick={() => shiftWeek(-1)} data-testid="admin-prev-week">
          <ChevronLeft className="w-5 h-5" />
        </Button>
        <h3 className="font-bold text-lg" data-testid="admin-week-range">
          {formatWeekRange(weekStart)}
        </h3>
        <Button variant="ghost" size="icon" onClick={() => shiftWeek(1)} data-testid="admin-next-week">
          <ChevronRight className="w-5 h-5" />
        </Button>
      </div>

      <Card className="control-surface overflow-hidden border-indigo-100 bg-indigo-50/40 shadow-sm dark:border-indigo-900 dark:bg-indigo-950/10" data-testid="schedule-normal-control-panel">
        <CardContent className="p-5">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <h3 className="font-bold flex items-center gap-2">
                <CalendarCheck className="h-5 w-5 text-indigo-700 dark:text-indigo-100" />
                Intervale standard de muncă
              </h3>
              <p className="text-sm text-muted-foreground">Calendarul de mai jos rămâne deschis permanent pentru dispecerat.</p>
            </div>
            <div className="flex flex-wrap gap-2">
              <Button
                type="button"
                onClick={() => setSetupDialogOpen(true)}
                disabled={autoGenerating}
                data-testid="schedule-setup-generate-button"
              >
                <Settings2 className="w-4 h-4 mr-2" />
                Generează automat sloturi
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={openClonePreview}
                disabled={autoGenerating}
                data-testid="schedule-clone-previous-week-button"
              >
                <Repeat className="w-4 h-4 mr-2" />
                Refă sloturile săptămânii trecute
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={deleteGeneratedSlots}
                disabled={autoGenerating}
                data-testid="schedule-bulk-delete-auto-button"
              >
                <Trash2 className="w-4 h-4 mr-2" />
                Șterge automate/setup
              </Button>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card className="control-surface overflow-hidden" data-testid="schedule-permanent-calendar">
        <CardHeader className="border-b bg-slate-50/70 pb-4 dark:bg-slate-900/50">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-lg">
                <CalendarCheck className="h-5 w-5 text-emerald-600" />
                Calendar rapid dispecerat
              </CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">Click pe orice celulă pentru comenzi rapide: -3, -2, -1, +1, +2, +3.</p>
              <div className="mt-2 flex flex-wrap gap-2 text-xs" data-testid="schedule-calendar-week-summary">
                <Badge className="bg-emerald-100 text-emerald-800 dark:bg-emerald-950/50 dark:text-emerald-100">
                  Standard create: {weeklyCalendarTotals.standard}
                </Badge>
                <Badge className="bg-red-100 text-red-800 dark:bg-red-950/50 dark:text-red-100">
                  Urgență ocupate: {weeklyCalendarTotals.emergencyTotal - weeklyCalendarTotals.emergencyRemaining}/{weeklyCalendarTotals.emergencyTotal}
                </Badge>
                <Badge variant="outline">
                  Urgență libere: {weeklyCalendarTotals.emergencyRemaining}
                </Badge>
              </div>
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Button
                type="button"
                variant={calendarMode === "normal" ? "default" : "outline"}
                className={calendarMode === "normal" ? "bg-emerald-600 hover:bg-emerald-700" : ""}
                onClick={() => setCalendarMode("normal")}
                data-testid="schedule-mode-standard-button"
              >
                Standard
              </Button>
              <Button
                type="button"
                variant={calendarMode === "emergency" ? "default" : "outline"}
                className={calendarMode === "emergency" ? "bg-red-600 hover:bg-red-700" : "border-red-300 text-red-700 hover:bg-red-50 dark:hover:bg-red-950/20"}
                onClick={() => setCalendarMode("emergency")}
                data-testid="schedule-mode-emergency-button"
              >
                Urgență
              </Button>
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-4">
          <div className="overflow-x-auto">
            <div className="min-w-[720px] text-xs" role="table" aria-label="Calendar rapid sloturi admin">
              <div className="grid grid-cols-[86px_repeat(7,minmax(76px,1fr))] items-center" role="row">
                <div className="sticky left-0 z-10 bg-card p-2 font-semibold" role="columnheader">Interval</div>
                {DAYS.map((day) => (
                  <div key={day.key} className="p-2 text-center font-semibold" role="columnheader">{day.label}</div>
                ))}
              </div>
              {ALL_HOURS.map((hour) => {
                const isNight = NIGHT_HOURS.includes(hour);
                return (
                  <div key={hour} className={`grid grid-cols-[86px_repeat(7,minmax(76px,1fr))] items-center ${isNight ? "bg-indigo-50/60 dark:bg-indigo-950/20" : ""}`} role="row">
                    <div className={`sticky left-0 z-10 p-2 font-mono ${isNight ? "bg-indigo-50/90 text-indigo-700 dark:bg-indigo-950 dark:text-indigo-100" : "bg-card text-muted-foreground"}`} role="rowheader">
                      {isNight && <Moon className="mr-1 inline h-3 w-3" />}{formatInterval(hour)}
                    </div>
                    {DAYS.map((day) => {
                      const metrics = getCalendarCellMetrics(day.key, hour);
                      const hasStandard = metrics.standardTotal > 0;
                      const hasEmergency = metrics.emergencyTotal > 0;
                      const activeClass = hasStandard || hasEmergency
                        ? "border-slate-300 bg-card hover:bg-muted/40 dark:border-slate-700"
                        : "border-slate-200 bg-card hover:bg-muted dark:border-slate-800";
                      return (
                        <div key={day.key} className="p-1" role="cell">
                          <button
                            type="button"
                            onClick={() => openQuickSlotDialog(day.key, hour)}
                            title={metrics.driverNames.length ? `Click pentru +/−. Programați: ${metrics.driverNames.join(", ")}` : "Click pentru +/− rapid"}
                            className={`min-h-[82px] w-full overflow-hidden rounded border p-0 text-left text-[11px] font-semibold transition-colors ${activeClass}`}
                            data-testid={`schedule-calendar-cell-${day.key}-${hour}`}
                          >
                            <span className="grid min-h-[82px] grid-rows-2" data-testid={`schedule-split-cell-${day.key}-${hour}`}>
                              <span
                                className={`flex flex-col justify-center border-b px-2 py-1.5 leading-tight ${hasStandard ? "border-emerald-300 bg-emerald-50 text-emerald-950 dark:border-emerald-900 dark:bg-emerald-950/40 dark:text-emerald-100" : "border-slate-200 bg-slate-50/70 text-slate-500 dark:border-slate-800 dark:bg-slate-900/30 dark:text-slate-500"}`}
                                data-testid={`schedule-standard-count-${day.key}-${hour}`}
                              >
                                <span>{`Standard ${metrics.standardTotal}`}</span>
                                <span className="text-[10px] font-medium opacity-85">Admin {metrics.standardAdmin} · Liv {metrics.standardDriver}</span>
                              </span>
                              <span
                                className={`flex flex-col justify-center px-2 py-1.5 leading-tight ${hasEmergency ? "bg-red-50 text-red-950 dark:bg-red-950/40 dark:text-red-100" : "bg-slate-50/70 text-slate-500 dark:bg-slate-900/30 dark:text-slate-500"}`}
                                data-testid={`schedule-emergency-count-${day.key}-${hour}`}
                              >
                                <span>{`Urgență ${metrics.emergencyTotal}`}</span>
                                <span className="text-[10px] font-medium opacity-90">Ocupate {metrics.emergencyOccupied}/{metrics.emergencyTotal} · Libere {metrics.emergencyRemaining}</span>
                              </span>
                            </span>
                          </button>
                        </div>
                      );
                    })}
                  </div>
                );
              })}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Emergency Mode Toggle */}
      <div className="grid md:grid-cols-2 gap-3">
        <Button
          variant={emergencyMode ? "default" : "outline"}
          className={emergencyMode
            ? "w-full bg-amber-600 hover:bg-amber-700 text-white shadow-sm"
            : "w-full border-amber-300 text-amber-700 hover:bg-amber-50 dark:hover:bg-amber-950/20"
          }
          onClick={() => setEmergencyMode(!emergencyMode)}
          data-testid="emergency-mode-toggle"
        >
          <Flame className="w-5 h-5 mr-2" />
          {emergencyMode ? "Sloturi de urgență active - click pe oră pentru locuri" : "Sloturi de urgență"}
        </Button>
        <Button
          variant="outline"
          className="w-full border-indigo-200 text-indigo-700 hover:bg-indigo-50 dark:border-indigo-900 dark:text-indigo-200 dark:hover:bg-indigo-950/20"
          onClick={autoGenerateEmergencySlots}
          disabled={autoGenerating}
          data-testid="auto-generate-emergency-btn"
        >
          <AlertTriangle className="w-5 h-5 mr-2" />
          {autoGenerating ? "Generez automat..." : "Generează Automat Sloturi"}
        </Button>
      </div>

      {/* Emergency Slots Grid (when mode is active) */}
      {emergencyMode && (
        <Card className="border-amber-300 border-2 bg-amber-50/30 dark:bg-amber-950/10">
          <CardHeader className="pb-2">
            <CardTitle className="flex items-center gap-2 text-base text-amber-700 dark:text-amber-100">
              <AlertTriangle className="w-5 h-5" />
              Sloturi de urgență - click pe o celulă pentru a seta locuri
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="overflow-x-auto">
              <table className="w-full text-xs">
                <thead>
                  <tr>
                    <th className="text-left p-1 w-16"><Clock className="w-3 h-3 inline mr-1" />Ora</th>
                    {DAYS.map((d) => (
                      <th key={d.key} className="p-1 text-center min-w-[52px] font-semibold">{d.label.substring(0, 3)}</th>
                    ))}
                  </tr>
                </thead>
                <tbody>
                  {EMERGENCY_HOURS.map((hour) => (
                    <tr key={hour}>
                      <td className="p-1 font-mono text-muted-foreground">{formatInterval(hour)}</td>
                      {DAYS.map((d) => {
                        const eSlot = getEmergencySlot(d.key, hour);
                        return (
                          <td key={d.key} className="p-0.5 text-center">
                            <button
                              onClick={() => handleEmergencyCellClick(d.key, hour)}
                              className={`w-full h-8 rounded transition-all text-xs font-bold ${
                                eSlot
                                  ? eSlot.remaining_spots > 0
                                    ? "bg-amber-600 text-white hover:bg-amber-700"
                                    : "bg-amber-200 text-amber-900 hover:bg-amber-300"
                                  : "bg-muted/30 hover:bg-amber-100 border border-transparent hover:border-amber-300"
                              }`}
                              data-testid={`emergency-${d.key}-${hour}`}
                            >
                              {eSlot ? `${eSlot.remaining_spots}/${eSlot.total_spots}` : ""}
                            </button>
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </CardContent>
        </Card>
      )}

      {/* Emergency slots summary (always visible if there are any) */}
      {emergencySlots.length > 0 && !emergencyMode && (
        <Card className="border-amber-200 bg-amber-50/30 dark:border-amber-900 dark:bg-amber-950/10">
          <CardContent className="p-4">
            <div className="flex items-center gap-2 mb-3">
              <Flame className="w-5 h-5 text-amber-600" />
              <span className="font-bold text-sm">Sloturi de urgență active</span>
              <Badge className="bg-amber-100 text-amber-800 dark:bg-amber-950 dark:text-amber-100">{emergencySlots.length}</Badge>
            </div>
            <div className="flex flex-wrap gap-2">
              {emergencySlots.map((s) => {
                const dayLabel = DAYS.find((d) => d.key === s.day)?.label || s.day;
                return (
                  <Badge key={s.id} className={`text-xs ${s.remaining_spots > 0 ? "bg-amber-600 text-white" : "bg-amber-200 text-amber-900"}`}>
                    {dayLabel} {formatInterval(s.hour)}: {s.remaining_spots}/{s.total_spots}
                    {s.created_by === "system" && " · AUTO"}
                    {s.claimed_names?.length > 0 && ` (${s.claimed_names.join(", ")})`}
                  </Badge>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Driver Cards */}
      {loading ? (
        <div className="text-center py-8 text-muted-foreground">Se încarcă...</div>
      ) : (
        <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
          {summary.map((driver) => {
            const sched = driver.schedules?.find((s) => s.week_start === toISODate(weekStart));
            const weekHours = sched?.total_hours || 0;
            const zones = driver.orders_by_zone || {};
            return (
              <Card
                key={driver.driver_id}
                className={`premium-card cursor-pointer transition-shadow ${weekHours > 0 ? "border-emerald-200" : "border-amber-200"}`}
                onClick={() => openEdit(driver)}
                data-testid={`driver-schedule-card-${driver.driver_id}`}
              >
                <CardContent className="p-4">
                  <div className="flex items-center gap-3 mb-3">
                    <div className={`w-10 h-10 rounded-full flex items-center justify-center ${driver.is_active ? "bg-green-500" : "bg-gray-400"}`}>
                      <Truck className="w-5 h-5 text-white" />
                    </div>
                    <div className="flex-1">
                      <p className="font-bold">{driver.driver_name}</p>
                      <p className="text-xs text-muted-foreground font-mono">{driver.phone}</p>
                    </div>
                    <Badge className={weekHours > 0 ? "bg-emerald-100 text-emerald-700" : "bg-amber-100 text-amber-800"}>
                      {weekHours}h
                    </Badge>
                  </div>

                    <div className="flex items-center justify-between mb-2 text-xs">
                      <Badge variant="outline">{driver.ranking_priority || "Start"}</Badge>
                      <span className="text-muted-foreground">Scor {driver.ranking_score || 0}</span>
                    </div>

                  <div className="flex gap-1 mb-3">
                    {DAYS.map((d) => {
                      const h = getDayHoursCount(driver.schedules, d.key);
                      return (
                        <div key={d.key} className="flex-1 text-center">
                          <p className="text-[10px] text-muted-foreground">{d.label.substring(0, 2)}</p>
                          <div className={`text-xs font-bold rounded py-0.5 ${h > 0 ? "bg-green-100 text-green-700" : "bg-muted text-muted-foreground"}`}>
                            {h}h
                          </div>
                        </div>
                      );
                    })}
                  </div>

                  <div className="space-y-2 border-t pt-2">
                    <div className="flex justify-between text-xs">
                      <span className="text-muted-foreground">Total comenzi livrate:</span>
                      <span className="font-bold">{driver.total_orders_delivered}</span>
                    </div>
                    {Object.keys(zones).length > 0 && (
                      <div className="flex flex-wrap gap-1">
                        {Object.entries(zones).map(([zone, count]) => (
                          <Badge
                            key={zone}
                            variant="outline"
                            className={`text-[10px] px-1.5 py-0 ${ZONE_COLORS[zone] || "bg-gray-100 text-gray-600"}`}
                          >
                            <MapPin className="w-2.5 h-2.5 mr-0.5" />{zone}: {count}
                          </Badge>
                        ))}
                      </div>
                    )}
                  </div>
                </CardContent>
              </Card>
            );
          })}
        </div>
      )}

      {/* Hourly Coverage */}
      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="flex items-center gap-2 text-base">
            <Users className="w-5 h-5" />
            Livratori disponibili pe intervale
          </CardTitle>
        </CardHeader>
        <CardContent>
          <div className="flex gap-1 overflow-x-auto pb-2">
            {ALL_HOURS.map((hour) => {
              const avg = getCoverageAtHour(hour);
              const isNight = NIGHT_HOURS.includes(hour);
              const eCount = emergencySlots.filter((s) => s.hour === hour).reduce((sum, s) => sum + s.remaining_spots, 0);
              return (
                <div
                  key={hour}
                  className={`flex flex-col items-center p-1.5 rounded min-w-[48px] ${getCoverageToneClass(avg)} ${isNight ? "ring-1 ring-indigo-300" : ""}`}
                >
                  <span className="text-[10px] text-muted-foreground flex items-center gap-0.5">
                    {isNight && <Moon className="w-2.5 h-2.5" />}
                    {formatInterval(hour)}
                  </span>
                  <span className={`text-lg font-bold ${getCoverageTextClass(avg)}`}>{avg}</span>
                  {eCount > 0 && (
                    <span className="text-[9px] text-amber-700 font-bold">+{eCount} urgență</span>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>

      {/* Summary Stats */}
      <div className="grid grid-cols-4 gap-4">
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-green-600">
              {summary.filter((d) => {
                const s = d.schedules?.find((sc) => sc.week_start === toISODate(weekStart));
                return s && s.total_hours > 0;
              }).length}
            </p>
            <p className="text-sm text-muted-foreground">Cu program</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-red-600">
              {summary.filter((d) => {
                const s = d.schedules?.find((sc) => sc.week_start === toISODate(weekStart));
                return !s || s.total_hours === 0;
              }).length}
            </p>
            <p className="text-sm text-muted-foreground">Fără program</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-blue-600">
              {summary.reduce((sum, d) => {
                const s = d.schedules?.find((sc) => sc.week_start === toISODate(weekStart));
                return sum + (s?.total_hours || 0);
              }, 0)}
            </p>
            <p className="text-sm text-muted-foreground">Total ore</p>
          </CardContent>
        </Card>
        <Card>
          <CardContent className="p-4 text-center">
            <p className="text-3xl font-bold text-red-500">
              {emergencySlots.reduce((s, e) => s + e.remaining_spots, 0)}
            </p>
            <p className="text-sm text-muted-foreground">Urgență libere</p>
          </CardContent>
        </Card>
      </div>

      {/* Emergency Slot Dialog */}
      <Dialog open={setupDialogOpen} onOpenChange={setSetupDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Settings2 className="w-5 h-5 text-blue-700" />
              Setup generare sloturi
            </DialogTitle>
            <DialogDescription>
              Alege zilele, intervalul și numărul de sloturi pentru programul normal sau sloturile de urgență.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <div>
              <p className="text-sm font-medium mb-2">Tip slot</p>
              <div className="grid grid-cols-2 gap-2">
                <Button
                  type="button"
                  variant={setupForm.slot_type === "normal" ? "default" : "outline"}
                  onClick={() => setSetupForm((prev) => ({ ...prev, slot_type: "normal" }))}
                  data-testid="setup-slot-type-normal"
                >
                  Normal
                </Button>
                <Button
                  type="button"
                  variant={setupForm.slot_type === "emergency" ? "default" : "outline"}
                  onClick={() => setSetupForm((prev) => ({ ...prev, slot_type: "emergency" }))}
                  data-testid="setup-slot-type-emergency"
                >
                  Urgență
                </Button>
              </div>
            </div>
            <div>
              <p className="text-sm font-medium mb-2">Zile</p>
              <div className="grid grid-cols-4 gap-2" data-testid="setup-days-grid">
                {DAYS.map((day) => (
                  <Button
                    key={day.key}
                    type="button"
                    size="sm"
                    variant={setupForm.days.includes(day.key) ? "default" : "outline"}
                    onClick={() => toggleSetupDay(day.key)}
                    data-testid={`setup-day-${day.key}`}
                  >
                    {day.label.substring(0, 3)}
                  </Button>
                ))}
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-sm font-medium mb-1">Ora start</p>
                <Input
                  type="time"
                  value={setupForm.start_hour}
                  onChange={(event) => setSetupForm((prev) => ({ ...prev, start_hour: event.target.value }))}
                  data-testid="setup-start-hour-input"
                />
              </div>
              <div>
                <p className="text-sm font-medium mb-1">Ora final</p>
                <Input
                  type="time"
                  value={setupForm.end_hour}
                  onChange={(event) => setSetupForm((prev) => ({ ...prev, end_hour: event.target.value }))}
                  data-testid="setup-end-hour-input"
                />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-3">
              <div>
                <p className="text-sm font-medium mb-1">Câte sloturi/oră</p>
                <Input
                  type="number"
                  min="1"
                  value={setupForm.total_slots}
                  onChange={(event) => setSetupForm((prev) => ({ ...prev, total_slots: Number(event.target.value) || 1 }))}
                  data-testid="setup-total-slots-input"
                />
              </div>
              <div>
                <p className="text-sm font-medium mb-1">Repetare săptămâni</p>
                <Input
                  type="number"
                  min="1"
                  max="8"
                  value={setupForm.repeat_weeks}
                  onChange={(event) => setSetupForm((prev) => ({ ...prev, repeat_weeks: Number(event.target.value) || 1 }))}
                  disabled={setupForm.slot_type === "emergency"}
                  data-testid="setup-repeat-weeks-input"
                />
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setSetupDialogOpen(false)} data-testid="setup-cancel-button">Anulează</Button>
            <Button variant="outline" onClick={deleteGeneratedSlots} disabled={autoGenerating} data-testid="setup-bulk-delete-button">
              <Trash2 className="w-4 h-4 mr-2" />
              Șterge conform setup
            </Button>
            <Button onClick={submitSetupGeneration} disabled={autoGenerating} data-testid="setup-submit-button">
              {autoGenerating ? "Generez..." : "Generează"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!quickSlotDialog} onOpenChange={(open) => !open && setQuickSlotDialog(null)}>
        <DialogContent className="max-w-md !bg-white !opacity-100 dark:!bg-slate-950" data-testid="schedule-quick-adjust-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              {quickSlotDialog?.mode === "emergency" ? <Flame className="h-5 w-5 text-red-600" /> : <CalendarCheck className="h-5 w-5 text-emerald-600" />}
              Ajustare rapidă · {DAYS.find((d) => d.key === quickSlotDialog?.day)?.label} {quickSlotDialog?.hour ? formatInterval(quickSlotDialog.hour) : ""}
            </DialogTitle>
            <DialogDescription>
              Alege rapid câte locuri adaugi sau scoți din intervalul selectat.
            </DialogDescription>
          </DialogHeader>
          {quickSlotDialog && (() => {
            const metrics = getCalendarCellMetrics(quickSlotDialog.day, quickSlotDialog.hour);
            return (
              <div className="space-y-4">
                <div className="grid grid-cols-2 gap-3 text-sm">
                  <div className="rounded-lg border bg-emerald-50 p-3 text-emerald-900 dark:bg-emerald-950/20 dark:text-emerald-100" data-testid="quick-standard-current-count">
                    <p className="text-xs opacity-80">Standard acum</p>
                    <p className="text-2xl font-black">{metrics.standardTotal}</p>
                  </div>
                  <div className="rounded-lg border bg-red-50 p-3 text-red-900 dark:bg-red-950/20 dark:text-red-100" data-testid="quick-emergency-current-count">
                    <p className="text-xs opacity-80">Urgență acum</p>
                    <p className="text-2xl font-black">{metrics.emergencyTotal}</p>
                  </div>
                </div>
                <div className="grid grid-cols-3 gap-2">
                  {[-3, -2, -1, 1, 2, 3].map((delta) => (
                    <Button
                      key={delta}
                      type="button"
                      variant={delta < 0 ? "outline" : "default"}
                      className={getQuickDeltaClass(delta, quickSlotDialog.mode)}
                      onClick={() => adjustQuickSlot(delta)}
                      disabled={autoGenerating}
                      data-testid={`schedule-quick-adjust-${delta}`}
                    >
                      {delta > 0 ? `+${delta}` : delta}
                    </Button>
                  ))}
                </div>
                <div className="rounded-lg border bg-muted/30 p-3">
                  <label className="text-xs font-semibold text-muted-foreground" htmlFor="quick-manual-amount-input">
                    Scrie manual câte sloturi vrei să modifici
                  </label>
                  <div className="mt-2 grid grid-cols-[1fr_auto_auto] gap-2">
                    <Input
                      id="quick-manual-amount-input"
                      type="number"
                      min="1"
                      max="100"
                      value={quickManualAmount}
                      onChange={(event) => setQuickManualAmount(Math.max(1, Math.min(Number(event.target.value) || 1, 100)))}
                      data-testid="schedule-quick-manual-amount-input"
                    />
                    <Button
                      type="button"
                      variant="outline"
                      onClick={() => adjustQuickSlot(-Math.abs(quickManualAmount || 1))}
                      disabled={autoGenerating}
                      data-testid="schedule-quick-manual-minus-button"
                    >
                      Scade
                    </Button>
                    <Button
                      type="button"
                      className={quickSlotDialog.mode === "emergency" ? "bg-red-600 hover:bg-red-700" : "bg-emerald-600 hover:bg-emerald-700"}
                      onClick={() => adjustQuickSlot(Math.abs(quickManualAmount || 1))}
                      disabled={autoGenerating}
                      data-testid="schedule-quick-manual-plus-button"
                    >
                      Adaugă
                    </Button>
                  </div>
                </div>
                <p className="text-xs text-muted-foreground">
                  Standard = ore atribuite livratorilor existenți. Dacă ceri mai multe decât livratori disponibili pe ora aceea, sistemul adaugă doar câte poate. Urgență = capacitate liberă și poate fi crescută independent.
                </p>
              </div>
            );
          })()}
        </DialogContent>
      </Dialog>

      {/* Emergency Slot Dialog */}
      <Dialog open={!!emergencyDialog} onOpenChange={(open) => !open && setEmergencyDialog(null)}>
        <DialogContent className="max-w-sm">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2 text-amber-700">
              <Flame className="w-5 h-5" />
              Slot Urgență - {DAYS.find((d) => d.key === emergencyDialog?.day)?.label} {emergencyDialog?.hour ? formatInterval(emergencyDialog.hour) : ""}
            </DialogTitle>
            <DialogDescription>
              Configurează rapid locurile disponibile pentru acest slot suplimentar.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 py-2">
            <p className="text-sm text-muted-foreground">
              Setează câte locuri de urgență sunt disponibile pe această oră.
              Livatorii fără program vor fi notificați și pot lua locuri.
            </p>
            <div className="flex items-center justify-center gap-4">
              <Button
                variant="outline"
                size="icon"
                onClick={() => setEmergencySpots(Math.max(1, emergencySpots - 1))}
                data-testid="emergency-spots-minus"
              >
                <Minus className="w-4 h-4" />
              </Button>
              <span className="text-4xl font-bold text-amber-700 w-16 text-center" data-testid="emergency-spots-count">{emergencySpots}</span>
              <Button
                variant="outline"
                size="icon"
                onClick={() => setEmergencySpots(emergencySpots + 1)}
                data-testid="emergency-spots-plus"
              >
                <Plus className="w-4 h-4" />
              </Button>
            </div>
            <p className="text-center text-sm text-muted-foreground">
              locuri pentru livratori
            </p>
            {emergencyDialog?.existing?.claimed_names?.length > 0 && (
              <div className="bg-red-50 border border-red-200 rounded-lg p-3">
                <p className="text-xs font-bold text-amber-800 mb-1">Deja luate de:</p>
                {emergencyDialog.existing.claimed_names.map((name) => (
                  <Badge key={`${emergencyDialog.existing.id}-${name}`} variant="outline" className="text-xs mr-1">{name}</Badge>
                ))}
              </div>
            )}
          </div>
          <DialogFooter className="gap-2">
            {emergencyDialog?.existing && (
              <Button
                variant="destructive"
                size="sm"
                onClick={() => deleteEmergencySlot(emergencyDialog.existing.id)}
                data-testid="delete-emergency-slot"
              >
                Șterge Slot
              </Button>
            )}
            <Button
              className="bg-amber-600 hover:bg-amber-700"
              onClick={saveEmergencySlot}
              data-testid="save-emergency-slot"
            >
              <Flame className="w-4 h-4 mr-2" />
              Salvează
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!clonePreview} onOpenChange={(open) => !open && setClonePreview(null)}>
        <DialogContent className="max-w-md" data-testid="schedule-clone-preview-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Repeat className="h-5 w-5 text-indigo-600" />
              Preview refacere sloturi
            </DialogTitle>
            <DialogDescription>
              Verifică structura săptămânii precedente înainte de recreare.
            </DialogDescription>
          </DialogHeader>
          {clonePreview && (
            <div className="space-y-3">
              <div className="rounded-lg border bg-muted/40 p-3 text-sm">
                <p><strong>Săptămâna sursă:</strong> {clonePreview.previous_week_start}</p>
                <p><strong>Săptămâna țintă:</strong> {clonePreview.target_week_start}</p>
                <p><strong>Livratori copiați:</strong> {clonePreview.drivers_count}</p>
                <p><strong>Total ore:</strong> {clonePreview.total_hours}</p>
              </div>
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
                Confirmarea va suprascrie programul existent al livratorilor pentru săptămâna selectată cu structura săptămânii precedente.
              </div>
            </div>
          )}
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setClonePreview(null)} data-testid="schedule-clone-cancel-button">Anulează</Button>
            <Button type="button" onClick={confirmClonePreviousWeek} disabled={autoGenerating} data-testid="schedule-clone-confirm-button">
              Refă sloturile
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Edit Driver Schedule Dialog */}
      <Dialog open={!!editDriver} onOpenChange={(open) => !open && setEditDriver(null)}>
        <DialogContent className="max-w-4xl max-h-[88vh] overflow-y-auto !bg-white !opacity-100 dark:!bg-slate-950" data-testid="driver-simple-schedule-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <CalendarCheck className="w-5 h-5" />
              Program simplu · {editDriver?.driver_name}
            </DialogTitle>
            <DialogDescription>
              Fiecare oră este împărțită în Standard și Urgență. Click pe jumătatea dorită pentru activare/dezactivare.
            </DialogDescription>
          </DialogHeader>

          <div className="grid gap-3 rounded-lg border bg-muted/30 p-3 text-sm sm:grid-cols-5">
            <div data-testid="driver-simple-total-hours"><span className="text-muted-foreground">Total</span><br /><strong>{editTotalHours}h</strong></div>
            <div><span className="text-muted-foreground">Din aplicație</span><br /><strong className="text-orange-600">{editDriverHours}h</strong></div>
            <div><span className="text-muted-foreground">Adăugat admin</span><br /><strong className="text-emerald-600">{editAdminHours}h</strong></div>
            <div><span className="text-muted-foreground">Urgențe</span><br /><strong className="text-red-600">{editEmergencyHours}h</strong></div>
            <div className="flex items-center gap-2"><Moon className="h-4 w-4 text-indigo-500" /><span>Tura de noapte marcată discret</span></div>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full min-w-[760px] text-xs">
              <thead>
                <tr>
                  <th className="text-left p-2 w-20"><Clock className="w-3 h-3 inline mr-1" />Ora</th>
                  {DAYS.map((d) => (
                    <th key={d.key} className="p-2 text-center min-w-[104px] font-semibold">
                      <div>{d.label.substring(0, 3)}</div>
                      <div className="mt-1 grid grid-cols-2 overflow-hidden rounded border text-[10px] font-bold" data-testid={`driver-simple-day-header-${d.key}`}>
                        <span className="bg-emerald-50 px-1 py-0.5 text-emerald-700 dark:bg-emerald-950/30 dark:text-emerald-100">Std</span>
                        <span className="bg-red-50 px-1 py-0.5 text-red-700 dark:bg-red-950/30 dark:text-red-100">Urg</span>
                      </div>
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {ALL_HOURS.map((hour) => {
                  const isNight = NIGHT_HOURS.includes(hour);
                  return (
                    <tr key={hour} className={isNight ? "bg-indigo-50/50" : ""}>
                      <td className={`p-2 font-mono ${isNight ? "text-indigo-500" : "text-muted-foreground"}`}>
                        {isNight && <Moon className="w-2.5 h-2.5 inline mr-0.5" />}
                        {formatInterval(hour)}
                      </td>
                      {DAYS.map((d) => {
                        const standardSlot = (editSlots[d.key] || []).find((s) => s.start === hour && s.added_by !== "emergency");
                        const emergencySlot = (editSlots[d.key] || []).find((s) => s.start === hour && s.added_by === "emergency");
                        const standardLabel = getSimpleStandardLabel(standardSlot);
                        const emergencyLabel = emergencySlot ? "Urg" : "Liber";

                        return (
                          <td key={d.key} className="p-1 text-center">
                            <div className="grid h-[58px] w-full overflow-hidden rounded border border-slate-200 bg-white text-[10px] font-black shadow-sm dark:border-slate-800 dark:bg-slate-950" data-testid={`driver-simple-split-cell-${d.key}-${hour}`}>
                              <button
                                type="button"
                                onClick={() => toggleHour(d.key, hour, "standard")}
                                className={`min-h-[29px] border-b px-1 transition-colors ${getSimpleStandardClass(standardSlot)}`}
                                data-testid={`driver-simple-standard-cell-${d.key}-${hour}`}
                                title="Standard: click pentru adăugare/scoatere"
                              >
                                <span className="block leading-tight">Std</span>
                                <span className="block leading-tight opacity-90">{standardLabel}</span>
                              </button>
                              <button
                                type="button"
                                onClick={() => toggleHour(d.key, hour, "emergency")}
                                className={`min-h-[29px] px-1 transition-colors ${emergencySlot ? "bg-red-600 text-white hover:bg-red-500" : "bg-slate-50 text-slate-500 hover:bg-red-50 hover:text-red-700 dark:bg-slate-900 dark:text-slate-400 dark:hover:bg-red-950/30"}`}
                                data-testid={`driver-simple-emergency-cell-${d.key}-${hour}`}
                                title="Urgență: click pentru adăugare/scoatere"
                              >
                                <span className="block leading-tight">Urg</span>
                                <span className="block leading-tight opacity-90">{emergencyLabel}</span>
                              </button>
                            </div>
                          </td>
                        );
                      })}
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>

          <div className="flex items-center justify-end pt-2">
            <Button onClick={saveSchedule} disabled={saving} data-testid="admin-save-schedule-btn">
              <Save className="w-4 h-4 mr-2" />
              {saving ? "Se salvează..." : "Salvează"}
            </Button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
};
