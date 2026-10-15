import { useCallback, useEffect, useRef, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { getApiErrorMessage, normalizeArray, normalizeObject, retryApiCall } from "../lib/api";
import { defaultScheduleSettings } from "../lib/restaurantPresentation";

const ORDER_POLL_INTERVAL_MS = 5000;

// Reads retain separate request IDs. Session, mutation and reporting-lease
// ownership are deliberately distinct gates; none is a last-response-wins rule.
export const useRestaurantReads = ({ restaurantId, actorId, token, apiUrl,
  statusSession, statusMounted, statusMutationRef, captureCloseLease, isCurrentCloseLease }) => {
  const [orders, setOrders] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshingOrders, setIsRefreshingOrders] = useState(false);
  const [acceptingOrders, setAcceptingOrders] = useState(true);
  const [restaurantPauseUntil, setRestaurantPauseUntil] = useState(null);
  const [scheduleForm, setScheduleForm] = useState(defaultScheduleSettings);
  const [prepAvailability, setPrepAvailability] = useState({ available_drivers: 0, blocked_short_options: false, minimum_preparation_minutes: 5 });
  const [analytics, setAnalytics] = useState(null);
  const [analyticsLoading, setAnalyticsLoading] = useState(false);
  const fetchOrdersRequestRef = useRef(0);
  const restaurantStatusRequestRef = useRef(0), prepAvailabilityRequestRef = useRef(0), analyticsRequestRef = useRef(0);

  const fetchRestaurantStatus = useCallback(async () => {
    const session = statusSession.current, lease = captureCloseLease(), requestId = ++restaurantStatusRequestRef.current;
    const owns = () => statusMounted.current && statusSession.current === session && restaurantStatusRequestRef.current === requestId && isCurrentCloseLease(lease);
    if (!restaurantId || !owns() || session.actor !== actorId || session.token !== token || session.resource !== restaurantId) return;
    try {
      const response = await retryApiCall(() => {
        if (!owns()) throw new Error("SESSION_CHANGED");
        return axios.get(`${apiUrl}/api/restaurants/${restaurantId}`, { timeout: 15000 });
      });
      if (!owns()) return;
      const restaurant = normalizeObject(response.data);
      setRestaurantPauseUntil(restaurant.pause_until || null);
      setAcceptingOrders(restaurant.accepting_orders !== false);
      setScheduleForm({ ...defaultScheduleSettings(), ...(restaurant.schedule_settings || {}) });
    } catch (error) {
      if (owns()) toast.error(getApiErrorMessage(error, "Nu am putut încărca statusul restaurantului"));
    }
  }, [restaurantId, actorId, token, apiUrl, statusSession, statusMounted, captureCloseLease, isCurrentCloseLease]);

  const fetchPrepAvailability = useCallback(async () => {
    const session = statusSession.current, requestId = ++prepAvailabilityRequestRef.current;
    const owns = () => statusMounted.current && statusSession.current === session && prepAvailabilityRequestRef.current === requestId;
    if (!restaurantId || !owns() || session.actor !== actorId || session.token !== token || session.resource !== restaurantId) return;
    try {
      const response = await retryApiCall(() => {
        if (!owns()) throw new Error("SESSION_CHANGED");
        return axios.get(`${apiUrl}/api/orders/restaurant/${restaurantId}/prep-availability`, { timeout: 15000 });
      });
      if (owns()) setPrepAvailability(normalizeObject(response.data, { available_drivers: 0, blocked_short_options: false, minimum_preparation_minutes: 5 }));
    } catch {
      // Availability warning is non-blocking for the restaurant screen.
    }
  }, [restaurantId, actorId, token, apiUrl, statusSession, statusMounted]);

  const fetchAnalytics = useCallback(async () => {
    const session = statusSession.current, requestId = ++analyticsRequestRef.current;
    const owns = () => statusMounted.current && statusSession.current === session && analyticsRequestRef.current === requestId;
    if (!restaurantId || !owns() || session.actor !== actorId || session.token !== token || session.resource !== restaurantId) return;
    setAnalyticsLoading(true);
    try {
      const response = await retryApiCall(() => {
        if (!owns()) throw new Error("SESSION_CHANGED");
        return axios.get(`${apiUrl}/api/restaurants/${restaurantId}/analytics`, { timeout: 15000 });
      });
      if (owns()) setAnalytics(normalizeObject(response.data, null));
    } catch (error) {
      if (owns()) toast.error(getApiErrorMessage(error, "Nu am putut încărca analytics-ul restaurantului"));
    } finally {
      if (owns()) setAnalyticsLoading(false);
    }
  }, [restaurantId, actorId, token, apiUrl, statusSession, statusMounted]);

  const fetchOrders = useCallback(async ({ manual = false, silent = false, isCurrent = () => true } = {}) => {
    const session = statusSession.current;
    if (!isCurrent()) return false;
    if (!statusMounted.current || session?.actor !== actorId || session?.token !== token || session?.resource !== restaurantId) return false;
    if (!restaurantId) return false;
    const requestId = fetchOrdersRequestRef.current + 1;
    fetchOrdersRequestRef.current = requestId;
    if (manual) setIsRefreshingOrders(true);
    try {
      const response = await retryApiCall(() => {
        if (!isCurrent()) throw new Error("SESSION_CHANGED");
        return axios.get(`${apiUrl}/api/orders/restaurant/${restaurantId}`, { timeout: 15000 });
      });
      if (!isCurrent() || requestId !== fetchOrdersRequestRef.current || statusMutationRef.current || statusSession.current !== session || !statusMounted.current) return false;
      if (!Array.isArray(response.data)) throw new Error("INVALID_ORDER_LIST");
      setOrders(normalizeArray(response.data));
      return true;
    } catch (error) {
      if (isCurrent() && requestId === fetchOrdersRequestRef.current && statusSession.current === session && statusMounted.current) {
        if (!silent) {
          toast.error(getApiErrorMessage(error, "Nu am putut încărca comenzile restaurantului"));
        }
      }
      return false;
    } finally {
      if (isCurrent() && requestId === fetchOrdersRequestRef.current && statusSession.current === session && statusMounted.current) {
        setIsLoading(false);
      }
      if (isCurrent() && manual && statusSession.current === session && statusMounted.current) setIsRefreshingOrders(false);
    }
  }, [restaurantId, actorId, token, apiUrl, statusSession, statusMounted, statusMutationRef]);

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

  return { orders, setOrders, isLoading, setIsLoading, isRefreshingOrders, setIsRefreshingOrders,
    acceptingOrders, setAcceptingOrders, restaurantPauseUntil, setRestaurantPauseUntil,
    scheduleForm, setScheduleForm, prepAvailability, setPrepAvailability,
    analytics, setAnalytics, analyticsLoading, setAnalyticsLoading,
    fetchOrdersRequestRef, restaurantStatusRequestRef,
    fetchOrders, fetchRestaurantStatus, fetchPrepAvailability, fetchAnalytics };
};
