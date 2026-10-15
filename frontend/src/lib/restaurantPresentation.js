export const PREPARATION_OPTIONS_MINUTES = [5, 10, 15, 20, 25, 30];
export const RESTAURANT_DAYS = [
  { key: "monday", label: "Luni" },
  { key: "tuesday", label: "Marți" },
  { key: "wednesday", label: "Miercuri" },
  { key: "thursday", label: "Joi" },
  { key: "friday", label: "Vineri" },
  { key: "saturday", label: "Sâmbătă" },
  { key: "sunday", label: "Duminică" },
];

export const formatSeconds = (totalSeconds) => {
  const absSeconds = Math.abs(totalSeconds);
  const minutes = Math.floor(absSeconds / 60);
  const seconds = absSeconds % 60;
  return `${String(minutes).padStart(2, "0")}:${String(seconds).padStart(2, "0")}`;
};

export const getPreparationTimer = (order, now) => {
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

export const getPauseSeconds = (restaurant, now) => {
  const pauseUntilRaw = restaurant?.pause_until;
  if (!pauseUntilRaw) return 0;
  const pauseUntil = new Date(pauseUntilRaw).getTime();
  if (Number.isNaN(pauseUntil)) return 0;
  return Math.max(Math.ceil((pauseUntil - now) / 1000), 0);
};

export const defaultScheduleSettings = () => Object.fromEntries(
  RESTAURANT_DAYS.map((day) => [day.key, { enabled: true, open_time: "10:00", close_time: "22:00" }])
);

export const getStatusConfig = (status) => {
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

