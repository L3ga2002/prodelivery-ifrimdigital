const ACTIVE_STATUSES = ["NEW", "PREPARING", "READY", "ASSIGNED", "ACCEPTED", "PICKED_UP"];
const PREPARATION_STATUSES = ["NEW", "PREPARING", "READY"];
const DISPATCH_STATUSES = ["ASSIGNED", "ACCEPTED"];

const hasId = (id) => typeof id === "string" && id.trim().length > 0;
const isOrderRecord = (order) => Boolean(
  order && typeof order === "object" && !Array.isArray(order) && hasId(order.id)
);
const isPresent = (value) => value !== undefined && value !== null;
const LEGACY_TIMESTAMP_RE = /^(\d{4})-(\d{2})-(\d{2})[T ](\d{2}):(\d{2}):(\d{2})(?:\.\d{1,6})?(?:Z|[+-](\d{2}):(\d{2}))?$/;
const isValidLegacyTimestamp = (value) => {
  if (typeof value !== "string") return false;
  const parts = LEGACY_TIMESTAMP_RE.exec(value);
  if (!parts || parts[0] !== value) return false;
  const [year, month, day, hour, minute, second] = parts.slice(1, 7).map(Number);
  const isLeapYear = year % 4 === 0 && (year % 100 !== 0 || year % 400 === 0);
  const daysInMonth = [31, isLeapYear ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][month - 1];
  // Date.parse normalizes impossible dates, so validate calendar/time components first.
  return year > 0 && month >= 1 && month <= 12 && day >= 1 && day <= daysInMonth
    && hour <= 23 && minute <= 59 && second <= 59
    && (parts[7] === undefined || (Number(parts[7]) <= 23 && Number(parts[8]) <= 59))
    && Number.isFinite(Date.parse(value.replace(" ", "T")));
};

export const isActiveOrder = (order) => isOrderRecord(order) && ACTIVE_STATUSES.includes(order.status);

export const isActionableDriverOrder = (order) => isActiveOrder(order)
  && ["ASSIGNED", "ACCEPTED", "PICKED_UP"].includes(order.status);

export const getPreparationStatus = (order) => {
  if (!isActiveOrder(order) || order.status === "PICKED_UP") return null;
  const preparationStatus = order.preparation_status;
  const hasExplicitStatus = isPresent(preparationStatus);
  if (hasExplicitStatus && !PREPARATION_STATUSES.includes(preparationStatus)) return null;
  if (PREPARATION_STATUSES.includes(order.status)) return order.status;
  // Dispatch states use the additive field; only absent/null values use legacy timestamps.
  if (hasExplicitStatus) return preparationStatus;
  const timestamps = [order.preparation_started_at, order.preparation_ready_at];
  if (timestamps.some((value) => isPresent(value) && !isValidLegacyTimestamp(value))) return null;
  if (isPresent(order.preparation_ready_at)) return "READY";
  if (isPresent(order.preparation_started_at)) return "PREPARING";
  return "NEW";
};

export const isNewRestaurantOrder = (order) => getPreparationStatus(order) === "NEW";

export const isShortPreparationBlocked = (order, minutes, availability) => Boolean(
  availability.blocked_short_options
  && minutes < availability.minimum_preparation_minutes
  && !(isActiveOrder(order) && DISPATCH_STATUSES.includes(order.status) && hasId(order.driver_id))
);

export const splitRestaurantOrders = (orders) => {
  const groups = { active: [], inWork: [], delivered: [], newOrders: [] };
  orders.forEach((order) => {
    if (!isOrderRecord(order)) return;
    if (isNewRestaurantOrder(order)) groups.newOrders.push(order);
    if (order.status === "DELIVERED") groups.delivered.push(order);
    if (isActiveOrder(order)) {
      if (order.status !== "NEW") groups.inWork.push(order);
      if (order.status !== "PICKED_UP") groups.active.push(order);
    }
  });
  return groups;
};
