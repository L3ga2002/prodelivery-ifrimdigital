import { useState, useEffect, useCallback, useMemo, useRef } from "react";
import { useAuth } from "../context/AuthContext";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "../components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../components/ui/card";
import { Badge } from "../components/ui/badge";
import { Input } from "../components/ui/input";
import { Label } from "../components/ui/label";
import { Textarea } from "../components/ui/textarea";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "../components/ui/dialog";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "../components/ui/select";
import {
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "../components/ui/tabs";
import { MapContainer, TileLayer, Marker, Popup, useMap, useMapEvents } from "react-leaflet";
import "leaflet/dist/leaflet.css";
import {
  LogOut,
  Users,
  RefreshCw,
  Truck,
  Store,
  BarChart3,
  TrendingUp,
  Play,
  CheckCircle2,
  Loader2,
  Circle,
  XCircle,
  Moon,
  Sun,
  Search,
  Info,
  SlidersHorizontal,
} from "lucide-react";
import { AdminScheduleView } from "../components/AdminScheduleView";
import { AdminCommandCenter } from "../components/admin/AdminCommandCenter";
import { LiveMapPanel } from "../components/admin/LiveMapPanel";
import { OrdersTab } from "../components/admin/OrdersTab";
import { RestaurantsTab } from "../components/admin/RestaurantsTab";
import { SettingsTab } from "../components/admin/SettingsTab";
import { DriverManagementDialog } from "../components/admin/DriverManagementDialog";
import { DriverAvatar } from "../components/DriverAvatar";
import { restaurantIcon } from "../components/admin/MapMarkerIcons";
import { LocationAutocomplete } from "../components/LocationAutocomplete";
import { useTheme } from "../context/ThemeContext";
import { getApiErrorMessage, normalizeArray, normalizeObject, retryApiCall } from "../lib/api";
import { useNetworkStatus } from "../hooks/useNetworkStatus";
import {
  BarChart,
  Bar,
  XAxis,
  YAxis,
  CartesianGrid,
  Tooltip,
  ResponsiveContainer,
} from "recharts";

const API_URL = process.env.REACT_APP_BACKEND_URL;

const getDriverStatusMeta = (driver) => {
  let status = driver.operational_status;
  if (!status && driver.current_order_id) status = "delivery";
  if (!status && driver.is_active) status = "active";
  if (!status) status = "offline";
  const meta = {
    active: { label: "Activ", className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100" },
    delivery: { label: "În livrare", className: "bg-blue-100 text-blue-800 dark:bg-blue-950/40 dark:text-blue-100" },
    break: { label: "În pauză", className: "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-100" },
    offline: { label: "Offline", className: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-100" },
  };
  return meta[status] || meta.offline;
};

const getAssignDriverRowClass = ({ selected, assignable }) => {
  if (selected) return "border-emerald-400 bg-emerald-50 dark:bg-emerald-950/30";
  if (assignable) return "bg-card hover:bg-muted/60";
  return "bg-muted/40";
};

const OrderLocationMapEvents = ({ onChange }) => {
  useMapEvents({
    click(event) {
      onChange({
        customer_latitude: Number(event.latlng.lat.toFixed(6)),
        customer_longitude: Number(event.latlng.lng.toFixed(6)),
      });
    },
  });
  return null;
};

const MapAutoCenter = ({ position, zoom = 15 }) => {
  const map = useMap();

  useEffect(() => {
    if (position?.lat && position?.lng) {
      map.setView([position.lat, position.lng], zoom, { animate: true });
    }
  }, [map, position, zoom]);

  return null;
};

const RestaurantLocationMapInteractions = ({ onLocationChange }) => {
  useMapEvents({
    click(event) {
      onLocationChange?.({
        latitude: Number(event.latlng.lat.toFixed(6)),
        longitude: Number(event.latlng.lng.toFixed(6)),
        location_source: "manual_adjusted",
      });
    },
  });
  return null;
};

const OrderLocationPicker = ({ value, onChange }) => {
  const orderMapCenter = useMemo(() => [46.567, 26.913], []);
  const selectedPosition = useMemo(() => {
    if (!value.customer_latitude || !value.customer_longitude) return null;
    return [value.customer_latitude, value.customer_longitude];
  }, [value.customer_latitude, value.customer_longitude]);

  return (
    <div className="space-y-2" data-testid="order-location-picker">
      <div className="h-64 rounded-lg overflow-hidden border">
        <MapContainer center={orderMapCenter} zoom={13} className="h-full w-full">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <OrderLocationMapEvents onChange={onChange} />
          {selectedPosition && (
            <Marker position={selectedPosition}>
              <Popup>Locație livrare selectată</Popup>
            </Marker>
          )}
        </MapContainer>
      </div>
      <p className="text-xs text-muted-foreground">
        Click pe hartă pentru a seta locația clientului. Sistemul verifică zona restaurantului selectat.
      </p>
    </div>
  );
};

const RestaurantLocationPreview = ({ restaurant, onLocationChange }) => {
  const position = useMemo(() => ({
    lat: restaurant.latitude || 46.567,
    lng: restaurant.longitude || 26.913,
  }), [restaurant.latitude, restaurant.longitude]);
  const markerPosition = useMemo(() => [position.lat, position.lng], [position.lat, position.lng]);

  const handleDragEnd = useCallback((event) => {
    const marker = event.target;
    const nextPosition = marker.getLatLng();
    onLocationChange?.({
      latitude: Number(nextPosition.lat.toFixed(6)),
      longitude: Number(nextPosition.lng.toFixed(6)),
      location_source: "manual_adjusted",
    });
  }, [onLocationChange]);

  return (
    <div className="space-y-2">
      <div className="relative h-64 overflow-hidden rounded-lg border border-slate-200 shadow-sm" data-testid="new-restaurant-location-map">
        <MapContainer center={markerPosition} zoom={15} className="h-full w-full">
          <TileLayer
            attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
            url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
          />
          <MapAutoCenter position={position} />
          <RestaurantLocationMapInteractions onLocationChange={onLocationChange} />
          <Marker
            position={markerPosition}
            icon={restaurantIcon}
            draggable
            eventHandlers={{ dragend: handleDragEnd }}
          >
            <Popup>{restaurant.name || "Restaurant nou"}</Popup>
          </Marker>
        </MapContainer>
        <div className="pointer-events-none absolute left-3 top-3 z-[500] rounded-lg border border-slate-200 bg-white/95 px-3 py-2 text-xs font-medium text-slate-700 shadow-sm dark:border-slate-800 dark:bg-slate-950/90 dark:text-slate-100">
          Mută pinul prin drag sau click pe hartă
        </div>
      </div>
      <p className="text-xs text-muted-foreground" data-testid="new-restaurant-pin-help-text">
        După geocoding, poziția poate fi ajustată manual înainte de salvarea restaurantului.
      </p>
    </div>
  );
};

const AdminDashboard = () => {
  const { user, logout } = useAuth();
  const { isDark, toggleTheme } = useTheme();
  const { isOnline } = useNetworkStatus();
  const [orders, setOrders] = useState([]);
  const [drivers, setDrivers] = useState([]);
  const [restaurants, setRestaurants] = useState([]);
  const [stats, setStats] = useState({});
  const [isLoading, setIsLoading] = useState(true);
  const [isRefreshingData, setIsRefreshingData] = useState(false);

  // Dialogs
  const [selectedOrder, setSelectedOrder] = useState(null);
  const [selectedDriver, setSelectedDriver] = useState("");
  const [assignDriverSearch, setAssignDriverSearch] = useState("");
  const [debouncedAssignDriverSearch, setDebouncedAssignDriverSearch] = useState("");
  const [assignOrderSearch, setAssignOrderSearch] = useState("");
  const [isOrderSelectionLocked, setIsOrderSelectionLocked] = useState(false);
  const [isAssignDialogOpen, setIsAssignDialogOpen] = useState(false);
  const [isNewOrderDialogOpen, setIsNewOrderDialogOpen] = useState(false);
  const [isNewDriverDialogOpen, setIsNewDriverDialogOpen] = useState(false);
  const [isNewRestaurantDialogOpen, setIsNewRestaurantDialogOpen] = useState(false);
  const [driverVerificationFallback, setDriverVerificationFallback] = useState(null);
  const [isRestaurantPickerOpen, setIsRestaurantPickerOpen] = useState(false);
  const [activeAdminTab, setActiveAdminTab] = useState("orders");
  const [isAssigning, setIsAssigning] = useState(false);
  const [isCreatingOrder, setIsCreatingOrder] = useState(false);
  const [isCreatingDriver, setIsCreatingDriver] = useState(false);
  const [isCreatingRestaurant, setIsCreatingRestaurant] = useState(false);
  const [isDetectingOrderZone, setIsDetectingOrderZone] = useState(false);

  // Hourly data for charts
  const [hourlyData, setHourlyData] = useState({ hourly_orders: [] });
  const [analyticsData, setAnalyticsData] = useState(null);
  const [restaurantAnalytics, setRestaurantAnalytics] = useState(null);
  const [restaurantAnalyticsLoading, setRestaurantAnalyticsLoading] = useState(false);

  // Demo simulation
  const [isSimDialogOpen, setIsSimDialogOpen] = useState(false);
  const [simSteps, setSimSteps] = useState([]);
  const [isSimRunning, setIsSimRunning] = useState(false);
  const simAbort = useRef(false);
  const fetchDataRequestRef = useRef(0);
  const detectZoneRequestRef = useRef(0);

  const [selectedRestaurantId, setSelectedRestaurantId] = useState(null);

  // New order form
  const [newOrder, setNewOrder] = useState({
    restaurant_id: "",
    customer_name: "",
    customer_phone: "",
    customer_address: "",
    customer_latitude: null,
    customer_longitude: null,
    items: [{ name: "", quantity: 1, price: 0 }],
    subtotal_amount: 0,
    delivery_fee: 0,
    total_amount: 0,
    delivery_zone_id: null,
    delivery_zone_name: "",
    delivery_sector: "",
    delivery_zone_level: null,
    payment_type: "CASH",
    notes: "",
    source: "S"
  });

  // New driver form
  const [newDriver, setNewDriver] = useState({ name: "", phone: "", email: "", vehicle_type: "scooter" });
  const [scoreDialogDriver, setScoreDialogDriver] = useState(null);
  const [driverManagement, setDriverManagement] = useState(null);

  // New restaurant form
  const [newRestaurant, setNewRestaurant] = useState({
    name: "",
    address: "",
    phone: "",
    contact_name: "",
    email: "",
    latitude: 46.567,
    longitude: 26.913,
    location_source: "manual",
  });

  // Settings (demo)
  const [settings, setSettings] = useState({
    autoAssign: false,
    timeout: 60,
    maxRadius: 5,
  });

  // Simulare mișcare livratori pe hartă
  const [driverPositions, setDriverPositions] = useState({});

  useEffect(() => {
    // Inițializare poziții livratori
    const initialPositions = {};
    drivers.forEach(d => {
      initialPositions[d.id] = { lat: d.latitude, lng: d.longitude };
    });
    setDriverPositions(initialPositions);

    // Animație mișcare livratori activi
    const moveInterval = setInterval(() => {
      setDriverPositions(prev => {
        const newPositions = { ...prev };
        drivers.forEach(d => {
          if (d.is_active && prev[d.id]) {
            // Mișcare aleatorie mică
            newPositions[d.id] = {
              lat: prev[d.id].lat + (Math.random() - 0.5) * 0.002,
              lng: prev[d.id].lng + (Math.random() - 0.5) * 0.002
            };
          }
        });
        return newPositions;
      });
    }, 3000);

    return () => clearInterval(moveInterval);
  }, [drivers]);

  const fetchData = useCallback(async ({ manual = false, silent = false } = {}) => {
    const requestId = fetchDataRequestRef.current + 1;
    fetchDataRequestRef.current = requestId;
    if (manual) setIsRefreshingData(true);
    try {
      const [ordersRes, driversRes, restaurantsRes, statsRes, hourlyRes, analyticsRes] = await retryApiCall(() => Promise.all([
        axios.get(`${API_URL}/api/orders`),
        axios.get(`${API_URL}/api/drivers`),
        axios.get(`${API_URL}/api/restaurants`),
        axios.get(`${API_URL}/api/stats`),
        axios.get(`${API_URL}/api/stats/hourly`),
        axios.get(`${API_URL}/api/stats/analytics`).catch(() => ({ data: null })),
      ]));
      if (requestId !== fetchDataRequestRef.current) return;
      setOrders(normalizeArray(ordersRes.data));
      setDrivers(normalizeArray(driversRes.data));
      setRestaurants(normalizeArray(restaurantsRes.data));
      setStats(normalizeObject(statsRes.data));
      setHourlyData(normalizeObject(hourlyRes.data, { hourly_orders: [] }));
      if (analyticsRes.data) setAnalyticsData(normalizeObject(analyticsRes.data, null));
    } catch (error) {
      if (requestId === fetchDataRequestRef.current) {
        if (!silent) {
          toast.error(getApiErrorMessage(error, "Eroare la încărcarea datelor"));
        }
      }
    } finally {
      if (requestId === fetchDataRequestRef.current) {
        setIsLoading(false);
      }
      if (manual) setIsRefreshingData(false);
    }
  }, []);

  useEffect(() => {
    fetchData();
    const interval = setInterval(fetchData, 10000);
    return () => clearInterval(interval);
  }, [fetchData]);

  const effectiveRestaurantId = selectedRestaurantId || restaurants[0]?.id;

  useEffect(() => {
    if (!effectiveRestaurantId) return;
    let cancelled = false;
    setRestaurantAnalyticsLoading(true);
    retryApiCall(() => axios.get(`${API_URL}/api/restaurants/${effectiveRestaurantId}/analytics`))
      .then((response) => {
        if (!cancelled) setRestaurantAnalytics(normalizeObject(response.data, null));
      })
      .catch(() => {
        if (!cancelled) {
          setRestaurantAnalytics((previous) => (
            previous?.restaurant?.id === effectiveRestaurantId ? null : previous
          ));
        }
      })
      .finally(() => {
        if (!cancelled) setRestaurantAnalyticsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [effectiveRestaurantId]);

  const handleAssignOrder = (order) => {
    setSelectedOrder(order);
    setSelectedDriver("");
    setAssignDriverSearch("");
    setAssignOrderSearch(order?.order_number || "");
    setIsOrderSelectionLocked(true);
    setIsAssignDialogOpen(true);
  };

  const handleAssignDriverFromMap = (driver) => {
    setSelectedOrder(null);
    setSelectedDriver(driver.id);
    setAssignDriverSearch(driver.name || "");
    setAssignOrderSearch("");
    setIsOrderSelectionLocked(false);
    setActiveAdminTab("map");
    setIsAssignDialogOpen(true);
  };

  useEffect(() => {
    const timeout = setTimeout(() => setDebouncedAssignDriverSearch(assignDriverSearch.trim().toLowerCase()), 180);
    return () => clearTimeout(timeout);
  }, [assignDriverSearch]);

  const confirmAssign = async () => {
    if (isAssigning) return;
    if (!selectedOrder?.id) {
      toast.error("Selectează comanda pentru alocare");
      return;
    }
    if (!selectedDriver) {
      toast.error("Selectează un livrator");
      return;
    }
    setIsAssigning(true);
    try {
      await axios.put(`${API_URL}/api/orders/${selectedOrder.id}/assign`, { driver_id: selectedDriver });
      toast.success("Comandă alocată cu succes!");
      setIsAssignDialogOpen(false);
      setIsOrderSelectionLocked(false);
      await fetchData({ silent: true });
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Eroare la alocare"));
    } finally {
      setIsAssigning(false);
    }
  };

  const createOrder = async () => {
    if (isCreatingOrder) return;
    if (!newOrder.restaurant_id || !newOrder.customer_name || !newOrder.customer_phone || !newOrder.customer_latitude || !newOrder.customer_longitude) {
      toast.error("Completează câmpurile obligatorii");
      return;
    }
    if (!newOrder.delivery_zone_id) {
      toast.error("Selectează o locație validă dintr-o zonă de livrare");
      return;
    }
    setIsCreatingOrder(true);
    try {
      await axios.post(`${API_URL}/api/orders`, newOrder);
      toast.success("Comandă creată!");
      setIsNewOrderDialogOpen(false);
      setNewOrder({
        restaurant_id: "",
        customer_name: "",
        customer_phone: "",
        customer_address: "",
        customer_latitude: null,
        customer_longitude: null,
        items: [{ name: "", quantity: 1, price: 0 }],
        subtotal_amount: 0,
        delivery_fee: 0,
        total_amount: 0,
        delivery_zone_id: null,
        delivery_zone_name: "",
        delivery_sector: "",
        delivery_zone_level: null,
        payment_type: "CASH",
        notes: "",
        source: "S"
      });
      await fetchData({ silent: true });
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Eroare la creare comandă"));
    } finally {
      setIsCreatingOrder(false);
    }
  };

  const detectOrderZone = useCallback(async (lat, lng) => {
    if (!newOrder.restaurant_id) {
      toast.error("Selectează restaurantul înainte de verificarea zonei");
      return;
    }
    const requestId = detectZoneRequestRef.current + 1;
    detectZoneRequestRef.current = requestId;
    setIsDetectingOrderZone(true);
    try {
      const response = await axios.post(`${API_URL}/api/zones/detect`, {
        restaurant_id: newOrder.restaurant_id,
        lat,
        lng,
      });
      if (requestId !== detectZoneRequestRef.current) return;
      const zone = normalizeObject(response.data);
      setNewOrder((prev) => {
        const deliveryFee = zone.fee || 0;
        const subtotal = Number(prev.subtotal_amount || 0);
        return {
          ...prev,
          delivery_zone_id: zone.zone_id,
          delivery_zone_name: zone.zone_name || "",
          delivery_sector: zone.sector || "",
          delivery_zone_level: zone.zone_level,
          delivery_fee: deliveryFee,
          total_amount: Number((subtotal + deliveryFee).toFixed(2)),
        };
      });
      if (zone.zone_id) {
        toast.success(`Zonă detectată: ${zone.zone_name} · ${zone.fee} lei`);
      } else {
        toast.error("Adresa este în afara zonelor acestui restaurant");
      }
    } catch (error) {
      if (requestId === detectZoneRequestRef.current) {
        toast.error(getApiErrorMessage(error, "Nu am putut detecta zona"));
      }
    } finally {
      if (requestId === detectZoneRequestRef.current) {
        setIsDetectingOrderZone(false);
      }
    }
  }, [newOrder.restaurant_id, setNewOrder]);

  const updateOrderLocation = useCallback((location) => {
    setNewOrder((prev) => ({
      ...prev,
      ...location,
      delivery_zone_id: null,
      delivery_zone_name: "",
      delivery_sector: "",
      delivery_zone_level: null,
      delivery_fee: 0,
      total_amount: Number(prev.subtotal_amount || 0),
    }));
    if (location.customer_latitude && location.customer_longitude) {
      detectOrderZone(location.customer_latitude, location.customer_longitude);
    }
  }, [detectOrderZone]);

  const createDriver = async () => {
    if (isCreatingDriver) return;
    if (!newDriver.name || !newDriver.phone || !newDriver.email) {
      toast.error("Completează toate câmpurile");
      return;
    }
    setIsCreatingDriver(true);
    try {
      const res = await axios.post(`${API_URL}/api/drivers`, newDriver);
      if (res.data.email_delivery?.status === "sent") {
        toast.success(`Livrator creat. Codul de verificare a fost trimis pe email. Parolă: ${res.data.password}`);
      } else if (res.data.email_delivery?.status === "test_domain_restricted") {
        setDriverVerificationFallback({
          email: newDriver.email,
          code: res.data.email_delivery.verification_code,
          expiresAt: res.data.email_delivery.expires_at,
          password: res.data.password,
        });
        toast.warning("Resend blochează domeniul de test; am generat codul local pentru verificare.");
      } else {
        toast.warning(`Livrator creat, dar emailul nu a fost trimis. Verifică senderul Resend. Parolă: ${res.data.password}`);
      }
      setIsNewDriverDialogOpen(false);
      setNewDriver({ name: "", phone: "", email: "", vehicle_type: "scooter" });
      await fetchData({ silent: true });
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Eroare la creare livrator"));
    } finally {
      setIsCreatingDriver(false);
    }
  };

  const openDriverManagement = (driver) => {
    setDriverManagement(driver);
  };

  const createRestaurant = async () => {
    if (isCreatingRestaurant) return;
    if (!newRestaurant.name || !newRestaurant.address || !newRestaurant.phone || !newRestaurant.latitude || !newRestaurant.longitude) {
      toast.error("Completează toate câmpurile");
      return;
    }
    setIsCreatingRestaurant(true);
    try {
      const res = await axios.post(`${API_URL}/api/restaurants`, newRestaurant);
      toast.success(`Restaurant creat! Login: ${res.data.login_email} / ${res.data.password}`);
      setIsNewRestaurantDialogOpen(false);
      setNewRestaurant({
        name: "",
        address: "",
        phone: "",
        contact_name: "",
        email: "",
        latitude: 46.567,
        longitude: 26.913,
        location_source: "manual",
      });
      setSelectedRestaurantId(res.data.restaurant_id);
      await fetchData({ silent: true });
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Eroare la creare restaurant"));
    } finally {
      setIsCreatingRestaurant(false);
    }
  };

  // ============ DEMO SIMULATION ============
  const SIM_STEPS_TEMPLATE = [
    { key: "create", label: "Comandă nouă creată", icon: "Package", status: "pending" },
    { key: "preparing", label: "Restaurant setează timp pregătire (10 min)", icon: "Clock", status: "pending" },
    { key: "ready", label: "Restaurant marchează GATA", icon: "ChefHat", status: "pending" },
    { key: "assign", label: "Admin alocă livrator", icon: "Truck", status: "pending" },
    { key: "accept", label: "Livrator ACCEPTĂ comanda", icon: "CheckCircle", status: "pending" },
    { key: "pickup", label: "Livrator RIDICĂ comanda", icon: "Package", status: "pending" },
    { key: "deliver", label: "Livrator LIVREAZĂ cu succes", icon: "CheckCircle", status: "pending" },
  ];

  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  const updateStep = (stepIndex, status) => {
    setSimSteps((prev) => prev.map((s, i) => (i === stepIndex ? { ...s, status } : s)));
  };

  const runSimulation = async () => {
    simAbort.current = false;
    setSimSteps(SIM_STEPS_TEMPLATE.map((s) => ({ ...s })));
    setIsSimRunning(true);
    setIsSimDialogOpen(true);

    const randomNames = ["Alexandru Marin", "Elena Radu", "Bogdan Stoica", "Ana Gheorghe", "Mihai Florea"];
    const randomPhones = ["0722334455", "0733445566", "0744556677", "0755667788", "0766778899"];
    const randomAddresses = [
      "Calea Mărășești 45, Ap. 12, Bacău",
      "Str. Republicii 78, Ap. 3, Bacău",
      "Str. 9 Mai 22, Bacău",
      "Bd. Unirii 101, Ap. 8, Bacău",
      "Str. Mihai Eminescu 33, Bacău",
    ];

    const pick = (arr) => arr[Math.floor(Math.random() * arr.length)];

    try {
      // Step 1: Create order — apare la Restaurant
      updateStep(0, "active");
      await wait(1500);
      const rest = restaurants.length > 0 ? restaurants[Math.floor(Math.random() * restaurants.length)] : null;
      if (!rest) throw new Error("No restaurants");
      const orderRes = await axios.post(`${API_URL}/api/orders`, {
        restaurant_id: rest.id,
        customer_name: pick(randomNames),
        customer_phone: pick(randomPhones),
        customer_address: pick(randomAddresses),
        items: [{ name: "Pizza Margherita", quantity: 2, price: 35 }, { name: "Cola 500ml", quantity: 1, price: 8 }],
        total_amount: 78,
        payment_type: "CASH",
        notes: "Simulare demo - comandă test",
        source: "S",
      });
      const orderId = orderRes.data.id;
      updateStep(0, "done");
      if (simAbort.current) return;
      void fetchData({ silent: true });

      // Step 2: Restaurant setează pregătire
      updateStep(1, "active");
      await wait(5000);
      await axios.put(`${API_URL}/api/orders/${orderId}/preparing`, { preparation_time: 10 });
      updateStep(1, "done");
      if (simAbort.current) return;
      void fetchData({ silent: true });

      // Step 3: Restaurant marchează GATA
      updateStep(2, "active");
      await wait(5000);
      await axios.put(`${API_URL}/api/orders/${orderId}/ready`);
      updateStep(2, "done");
      if (simAbort.current) return;
      void fetchData({ silent: true });

      // Step 4: Admin alocă livrator — apare la Driver
      updateStep(3, "active");
      await wait(5000);
      const avail = drivers.filter((d) => d.is_active && !d.current_order_id);
      const driver = avail.length > 0 ? avail[0] : drivers.find((d) => d.is_active) || drivers[0];
      await axios.put(`${API_URL}/api/orders/${orderId}/assign`, { driver_id: driver.id });
      updateStep(3, "done");
      if (simAbort.current) return;
      void fetchData({ silent: true });

      // Step 5: Livrator acceptă
      updateStep(4, "active");
      await wait(5000);
      await axios.put(`${API_URL}/api/orders/${orderId}/status`, { status: "ACCEPTED" });
      updateStep(4, "done");
      if (simAbort.current) return;
      void fetchData({ silent: true });

      // Step 6: Livrator ridică
      updateStep(5, "active");
      await wait(5000);
      await axios.put(`${API_URL}/api/orders/${orderId}/status`, { status: "PICKED_UP" });
      updateStep(5, "done");
      if (simAbort.current) return;
      void fetchData({ silent: true });

      // Step 7: Livrator livrează
      updateStep(6, "active");
      await wait(5000);
      await axios.put(`${API_URL}/api/orders/${orderId}/status`, { status: "DELIVERED" });
      updateStep(6, "done");
      void fetchData({ silent: true });

      toast.success("Simulare completă! Comanda a parcurs tot fluxul.");
    } catch (err) {
      toast.error("Eroare în simulare: " + getApiErrorMessage(err, err.message || "necunoscută"));
    } finally {
      setIsSimRunning(false);
    }
  };

  const activeOrders = orders.filter((o) => o.status !== "DELIVERED");
  const activeDrivers = drivers.filter((d) => ["active", "delivery", "break"].includes(d.operational_status) || d.is_active);
  const canAssignDriver = (driver) => (driver.operational_status === "active" || (driver.is_active && !driver.operational_status)) && !driver.current_order_id;
  const driverAvailabilityLabel = (driver) => {
    if (canAssignDriver(driver)) return "Disponibil";
    if (driver.current_order_id || driver.operational_status === "delivery") return "În livrare";
    if (driver.operational_status === "break") return "În pauză";
    return "Offline";
  };
  const assignableOrders = activeOrders.filter((order) => ["NEW", "PREPARING", "READY"].includes(order.status));
  const filteredDriverCandidates = drivers
    .filter((driver) => {
      if (!debouncedAssignDriverSearch) return true;
      const haystack = `${driver.name || ""} ${driver.phone || ""} ${driver.vehicle_type || ""}`.toLowerCase();
      return haystack.includes(debouncedAssignDriverSearch);
    })
    .sort((a, b) => {
      const availabilitySort = Number(canAssignDriver(b)) - Number(canAssignDriver(a));
      if (availabilitySort !== 0) return availabilitySort;
      const term = debouncedAssignDriverSearch;
      const aStarts = term && a.name?.toLowerCase().startsWith(term) ? 1 : 0;
      const bStarts = term && b.name?.toLowerCase().startsWith(term) ? 1 : 0;
      if (aStarts !== bStarts) return bStarts - aStarts;
      return (b.ranking_score || 0) - (a.ranking_score || 0) || (a.name || "").localeCompare(b.name || "");
    });
  const filteredAssignableOrders = assignableOrders.filter((order) => {
    const term = assignOrderSearch.trim().toLowerCase();
    if (!term) return true;
    return `${order.order_number || ""} ${order.restaurant_name || ""} ${order.customer_name || ""} ${order.customer_address || ""}`.toLowerCase().includes(term);
  });
  const selectedRestaurant = restaurants.find((restaurant) => restaurant.id === selectedRestaurantId) || restaurants[0] || null;

  if (isLoading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-background">
        <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-primary"></div>
      </div>
    );
  }

  return (
    <div className="min-h-screen overflow-x-hidden bg-muted/30" data-testid="admin-dashboard">
      {/* Header */}
      <header className="sticky top-0 z-50 border-b bg-card/95 backdrop-blur-xl">
        <div className="mx-auto flex max-w-[1600px] flex-wrap items-center justify-between gap-3 px-3 py-3 sm:px-4 lg:px-6">
          <div className="flex min-w-0 items-center gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg" style={{ background: 'hsl(215 75% 22%)' }}>
              <Truck className="w-6 h-6 text-white" />
            </div>
            <div className="min-w-0">
              <h1 className="truncate text-lg font-bold tracking-tight sm:text-xl" style={{ fontFamily: 'var(--font-heading)' }}>
                PRODELIVERY <span style={{ color: 'hsl(24 95% 53%)', fontSize: '0.7em' }}>BACAU</span>
              </h1>
              <p className="text-xs text-muted-foreground">Dashboard Admin</p>
            </div>
          </div>

          <div className="flex shrink-0 items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              onClick={toggleTheme}
              className="border-border/80 bg-card/85 backdrop-blur"
              data-testid="admin-theme-toggle"
            >
              {isDark ? <Sun className="h-4 w-4" /> : <Moon className="h-4 w-4" />}
              <span className="hidden sm:inline">{isDark ? "Light" : "Dark"}</span>
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={() => fetchData({ manual: true })}
              disabled={isRefreshingData || !isOnline}
              data-testid="refresh-button"
            >
              <RefreshCw className={`h-4 w-4 sm:mr-2 ${isRefreshingData ? "animate-spin" : ""}`} />
              <span className="hidden sm:inline">Actualizează</span>
            </Button>
            <div className="text-sm text-right hidden sm:block">
              <p className="font-medium">{user?.name}</p>
              <p className="text-muted-foreground text-xs">{user?.email}</p>
            </div>
            <Button variant="ghost" size="icon" onClick={logout} data-testid="logout-button">
              <LogOut className="w-5 h-5" />
            </Button>
          </div>
        </div>
      </header>

      <main className="mx-auto w-full max-w-[1600px] px-3 py-4 sm:px-4 sm:py-5 lg:px-6 lg:py-6">
        <AdminCommandCenter
          stats={stats}
          activeDriversCount={activeDrivers.length}
          restaurantsCount={restaurants.length}
          isSimRunning={isSimRunning}
          actionsDisabled={!isOnline || isCreatingOrder}
          onRunSimulation={runSimulation}
          onNewOrder={() => setIsNewOrderDialogOpen(true)}
        />

        {/* Tabs */}
        <Tabs value={activeAdminTab} onValueChange={setActiveAdminTab} className="space-y-4">
          <TabsList className="admin-tabs-scroll flex h-auto w-full justify-start gap-1 overflow-x-auto rounded-xl border bg-card/90 p-1.5">
            <TabsTrigger className="shrink-0 whitespace-nowrap px-3 py-2" value="orders" data-testid="tab-orders">Comenzi ({activeOrders.length})</TabsTrigger>
            <TabsTrigger className="shrink-0 whitespace-nowrap px-3 py-2" value="analytics" data-testid="tab-analytics">Analize</TabsTrigger>
            <TabsTrigger className="shrink-0 whitespace-nowrap px-3 py-2" value="map" data-testid="tab-map">Hartă</TabsTrigger>
            <TabsTrigger className="shrink-0 whitespace-nowrap px-3 py-2" value="drivers" data-testid="tab-drivers">Livratori ({drivers.length})</TabsTrigger>
            <TabsTrigger className="shrink-0 whitespace-nowrap px-3 py-2" value="program" data-testid="tab-program">Program</TabsTrigger>
            <TabsTrigger className="shrink-0 whitespace-nowrap px-3 py-2" value="restaurants" data-testid="tab-restaurants">Restaurante ({restaurants.length})</TabsTrigger>
            <TabsTrigger className="shrink-0 whitespace-nowrap px-3 py-2" value="settings" data-testid="tab-settings">Setări</TabsTrigger>
          </TabsList>

          {/* Orders Tab */}
          <TabsContent value="orders">
            <OrdersTab activeOrders={activeOrders} onAssignOrder={handleAssignOrder} />
          </TabsContent>

          {/* Analytics Tab */}
          <TabsContent value="analytics" data-testid="analytics-tab">
            <div className="grid gap-4 lg:grid-cols-2 lg:gap-6">
              {/* Hourly Orders Chart */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <BarChart3 className="w-5 h-5 text-primary" />
                    Comenzi pe Oră
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">Distribuția comenzilor pe parcursul zilei</p>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={hourlyData.hourly_orders}>
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(220 15% 88%)" />
                      <XAxis dataKey="hour" tick={{ fontSize: 11 }} />
                      <YAxis tick={{ fontSize: 11 }} />
                      <Tooltip
                        contentStyle={{ borderRadius: '8px', border: '1px solid hsl(220 15% 88%)', fontSize: '13px' }}
                        labelStyle={{ fontWeight: 'bold' }}
                      />
                      <Bar dataKey="orders" name="Comenzi" fill="hsl(215 75% 22%)" radius={[4, 4, 0, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>

              {/* Orders by Restaurant Chart */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2">
                    <TrendingUp className="w-5 h-5" style={{ color: 'hsl(24 95% 53%)' }} />
                    Comenzi per Restaurant
                  </CardTitle>
                  <p className="text-sm text-muted-foreground">Distribuția comenzilor pe restaurante</p>
                </CardHeader>
                <CardContent>
                  <ResponsiveContainer width="100%" height={300}>
                    <BarChart data={analyticsData?.orders_by_restaurant || []} layout="vertical">
                      <CartesianGrid strokeDasharray="3 3" stroke="hsl(220 15% 88%)" />
                      <XAxis type="number" tick={{ fontSize: 11 }} />
                      <YAxis type="category" dataKey="name" tick={{ fontSize: 10 }} width={120} />
                      <Tooltip contentStyle={{ borderRadius: '8px', fontSize: '13px' }} />
                      <Bar dataKey="count" name="Comenzi" fill="hsl(24 95% 53%)" radius={[0, 4, 4, 0]} />
                    </BarChart>
                  </ResponsiveContainer>
                </CardContent>
              </Card>

              {/* Summary stats for today */}
              <Card className="md:col-span-2">
                <CardHeader>
                  <CardTitle>Sumar Zi Curentă</CardTitle>
                </CardHeader>
                <CardContent>
                  <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    <div className="p-4 rounded-lg bg-primary/5 border border-primary/20 text-center">
                      <p className="text-3xl font-bold text-primary">{stats.total_orders || 0}</p>
                      <p className="text-sm text-muted-foreground mt-1">Total Comenzi</p>
                    </div>
                    <div className="p-4 rounded-lg bg-green-50 border border-green-200 text-center dark:bg-green-950/30 dark:border-green-900">
                      <p className="text-3xl font-bold text-green-600">{stats.delivered_orders || 0}</p>
                      <p className="text-sm text-muted-foreground mt-1">Livrate</p>
                    </div>
                    <div className="p-4 rounded-lg bg-yellow-50 border border-yellow-200 text-center dark:bg-yellow-950/30 dark:border-yellow-900">
                      <p className="text-3xl font-bold text-yellow-600">{stats.active_orders || 0}</p>
                      <p className="text-sm text-muted-foreground mt-1">Active</p>
                    </div>
                    <div className="p-4 rounded-lg bg-red-50 border border-red-200 text-center dark:bg-red-950/30 dark:border-red-900">
                      <p className="text-3xl font-bold text-red-600">{stats.cancelled_orders || 0}</p>
                      <p className="text-sm text-muted-foreground mt-1">Anulate</p>
                    </div>
                  </div>
                </CardContent>
              </Card>

              {/* Orders by Driver */}
              {analyticsData?.orders_by_driver?.length > 0 && (
                <Card>
                  <CardHeader>
                    <CardTitle className="text-base">Comenzi per Livrator</CardTitle>
                  </CardHeader>
                  <CardContent>
                    <div className="space-y-3">
                      {analyticsData.orders_by_driver.map((d) => (
                        <div key={d.name} className="flex items-center justify-between p-2 rounded-lg bg-muted/50">
                          <span className="font-medium text-sm">{d.name}</span>
                          <Badge variant="outline">{d.count} comenzi</Badge>
                        </div>
                      ))}
                    </div>
                  </CardContent>
                </Card>
              )}

              {/* Cancelled Orders */}
              <Card>
                <CardHeader>
                  <CardTitle className="flex items-center gap-2 text-base text-red-600">
                    <XCircle className="w-5 h-5" />
                    Comenzi Anulate ({analyticsData?.cancelled_count || 0})
                  </CardTitle>
                </CardHeader>
                <CardContent>
                  {(analyticsData?.cancelled_orders?.length || 0) === 0 ? (
                    <p className="text-sm text-muted-foreground text-center py-4">Nicio comandă anulată</p>
                  ) : (
                    <div className="space-y-3 max-h-[300px] overflow-y-auto">
                      {analyticsData.cancelled_orders.map((o) => (
                        <div key={`${o.order_number}-${o.cancelled_by || "unknown"}`} className="p-3 bg-red-50 border border-red-200 rounded-lg dark:bg-red-950/30 dark:border-red-900">
                          <div className="flex justify-between text-sm">
                            <span className="font-mono font-bold">{o.order_number}</span>
                            <Badge variant="outline" className="text-xs">{o.cancelled_by || "?"}</Badge>
                          </div>
                          <p className="text-sm text-muted-foreground">{o.restaurant_name}</p>
                          <p className="text-sm text-red-700 mt-1 font-medium dark:text-red-100">Motiv: {o.cancellation_reason}</p>
                        </div>
                      ))}
                    </div>
                  )}
                </CardContent>
              </Card>
            </div>
          </TabsContent>

          {/* Map Tab */}
          <TabsContent value="map">
            <LiveMapPanel drivers={drivers} restaurants={restaurants} driverPositions={driverPositions} orders={activeOrders} onAssignDriver={handleAssignDriverFromMap} />
          </TabsContent>

          {/* Drivers Tab */}
          <TabsContent value="drivers">
            <Card>
              <CardHeader className="border-b bg-slate-50/70 dark:bg-slate-900/50">
                <div className="flex flex-wrap items-center justify-between gap-3">
                  <div>
                    <CardTitle className="flex items-center gap-2 text-lg">
                      <Truck className="h-5 w-5 text-indigo-600" />
                      Livratori
                    </CardTitle>
                    <p className="mt-1 text-sm text-muted-foreground">Flotă, vehicule, email verificat și scor operațional.</p>
                  </div>
                  <Button type="button" onClick={() => setIsNewDriverDialogOpen(true)} data-testid="drivers-add-driver-button">
                    <Users className="mr-2 h-4 w-4" />
                    Adaugă livrator
                  </Button>
                </div>
              </CardHeader>
              <CardContent className="p-4">
                <div className="grid gap-3 sm:grid-cols-2 xl:grid-cols-3 2xl:grid-cols-4">
                  {drivers.map((driver) => (
                    <div
                      key={driver.id}
                      role="button"
                      tabIndex={0}
                      onClick={() => openDriverManagement(driver)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") openDriverManagement(driver);
                      }}
                      className={`p-4 rounded-lg border transition-colors hover:border-indigo-300 hover:bg-indigo-50/40 dark:hover:bg-indigo-950/20 ${driver.is_active ? 'bg-green-50 border-green-200 dark:bg-green-950/20 dark:border-green-900' : 'bg-muted/50'}`}
                      data-testid={`driver-management-card-${driver.id}`}
                    >
                      <div className="flex items-center gap-3 mb-3">
                        <DriverAvatar driver={driver} size="md" testId={`driver-card-avatar-${driver.id}`} />
                        <div>
                          <p className="font-bold">{driver.name}</p>
                          <p className="text-sm text-muted-foreground font-mono">{driver.phone}</p>
                        </div>
                      </div>
                      <div className="flex justify-between text-sm">
                        <span>Livrări: {driver.total_deliveries || 0}</span>
                        <button
                          type="button"
                          className="font-semibold text-indigo-700 underline-offset-2 hover:underline dark:text-indigo-200"
                          onClick={(event) => {
                            event.stopPropagation();
                            setScoreDialogDriver(driver);
                          }}
                          data-testid={`driver-score-button-${driver.id}`}
                        >
                          Scor: {driver.ranking_score || 0}
                        </button>
                      </div>
                      <div className="flex flex-wrap gap-2 mt-2">
                        <Badge className={`mt-2 ${getDriverStatusMeta(driver).className}`} data-testid={`driver-operational-status-${driver.id}`}>
                          {getDriverStatusMeta(driver).label}
                        </Badge>
                        {driver.ranking_tier && (
                          <Badge variant="outline" data-testid={`driver-tier-${driver.id}`}>
                            {driver.ranking_tier}
                          </Badge>
                        )}
                        <Badge variant="outline" data-testid={`driver-vehicle-${driver.id}`}>
                          {driver.vehicle_type === "car" ? "Mașină" : "Scuter"}
                        </Badge>
                        <Badge className={driver.email_verified ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100" : "bg-amber-100 text-amber-800 dark:bg-amber-950/40 dark:text-amber-100"} data-testid={`driver-email-status-${driver.id}`}>
                          {driver.email_verified ? "Email verificat" : "Email neverificat"}
                        </Badge>
                      </div>
                      {driver.schedule_access?.opens_at && (
                        <p className="text-xs text-muted-foreground mt-2">
                          Acces calendar: {driver.schedule_access.opens_at_label || driver.schedule_access.opens_at}
                        </p>
                      )}
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="mt-3 w-full justify-center"
                        onClick={(event) => {
                          event.stopPropagation();
                          openDriverManagement(driver);
                        }}
                        data-testid={`driver-open-management-button-${driver.id}`}
                      >
                        <SlidersHorizontal className="mr-2 h-4 w-4" />
                        Gestionează livrator
                      </Button>
                    </div>
                  ))}
                </div>
              </CardContent>
            </Card>
          </TabsContent>

          {/* Restaurants Tab */}
          <TabsContent value="restaurants">
            <RestaurantsTab
              restaurants={restaurants}
              selectedRestaurant={selectedRestaurant}
              activeOrders={activeOrders}
              orders={orders}
              onSelectRestaurant={setSelectedRestaurantId}
              restaurantAnalytics={restaurantAnalytics}
              restaurantAnalyticsLoading={restaurantAnalyticsLoading}
              onNewRestaurant={() => setIsNewRestaurantDialogOpen(true)}
            />
          </TabsContent>

          {/* Program Tab */}
          <TabsContent value="program">
            <AdminScheduleView />
          </TabsContent>

          {/* Settings Tab */}
          <TabsContent value="settings">
            <SettingsTab settings={settings} onSettingsChange={setSettings} />
          </TabsContent>
        </Tabs>
      </main>

      {/* Assign Dialog */}
      <Dialog open={isAssignDialogOpen} onOpenChange={(open) => { setIsAssignDialogOpen(open); if (!open) setIsOrderSelectionLocked(false); }}>
        <DialogContent className="z-[1250] max-w-3xl" data-testid="assign-order-dialog">
          <DialogHeader>
            <DialogTitle>Alocă Comandă</DialogTitle>
            <DialogDescription>
              Alege comanda și livratorul disponibil. Căutarea filtrează instant pentru flotă mare.
            </DialogDescription>
          </DialogHeader>
          <div className="grid gap-4 lg:grid-cols-[1fr_1.1fr]">
            <div className="space-y-3">
              <Label>Comandă</Label>
              {isOrderSelectionLocked && selectedOrder ? (
                <div className="rounded-lg border border-indigo-300 bg-indigo-50 p-3 dark:bg-indigo-950/30" data-testid="assign-locked-order-summary">
                  <div className="flex items-center justify-between gap-3"><span className="font-mono text-xs font-black">{selectedOrder.order_number}</span><Badge variant="outline">{selectedOrder.total_amount} RON</Badge></div>
                  <p className="mt-1 font-semibold">{selectedOrder.restaurant_name}</p>
                  <p className="truncate text-xs text-muted-foreground">{selectedOrder.customer_name} · {selectedOrder.customer_address}</p>
                  <p className="mt-2 text-xs font-medium text-indigo-700 dark:text-indigo-100">Comanda selectată inițial este păstrată automat.</p>
                </div>
              ) : (
                <>
                  <div className="relative">
                    <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input value={assignOrderSearch} onChange={(event) => setAssignOrderSearch(event.target.value)} className="pl-9" placeholder="Caută după număr, client, restaurant" data-testid="assign-order-search-input" />
                  </div>
                  <div className="max-h-72 space-y-2 overflow-y-auto rounded-lg border bg-muted/20 p-2" data-testid="assign-order-options">
                    {filteredAssignableOrders.map((order) => (
                      <button key={order.id} type="button" className={`w-full rounded-md border p-3 text-left transition-colors ${selectedOrder?.id === order.id ? "border-indigo-400 bg-indigo-50 dark:bg-indigo-950/30" : "bg-card hover:bg-muted/60"}`} onClick={() => setSelectedOrder(order)} data-testid={`assign-order-option-${order.id}`}>
                        <div className="flex items-center justify-between gap-2"><span className="font-mono text-xs font-bold">{order.order_number}</span><Badge variant="outline" className="text-xs">{order.total_amount} RON</Badge></div>
                        <p className="mt-1 text-sm font-semibold">{order.restaurant_name}</p><p className="truncate text-xs text-muted-foreground">{order.customer_name} · {order.customer_address}</p>
                      </button>
                    ))}
                    {filteredAssignableOrders.length === 0 && <p className="p-3 text-sm text-muted-foreground" data-testid="assign-order-empty-state">Nicio comandă disponibilă.</p>}
                  </div>
                </>
              )}
            </div>
            <div className="space-y-3">
              <Label>Livrator</Label>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={assignDriverSearch}
                  onChange={(event) => setAssignDriverSearch(event.target.value)}
                  autoFocus
                  className="pl-9"
                  placeholder="Caută livrator după nume, telefon sau vehicul"
                  data-testid="assign-driver-search-input"
                />
              </div>
              <div className="max-h-72 space-y-2 overflow-y-auto rounded-lg border bg-muted/20 p-2" data-testid="assign-driver-options">
                {filteredDriverCandidates.map((driver) => {
                  const isAssignable = canAssignDriver(driver);
                  const availabilityLabel = driverAvailabilityLabel(driver);
                  return (
                  <button
                    key={driver.id}
                    type="button"
                    disabled={!isAssignable}
                    className={`w-full rounded-md border p-3 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-55 ${getAssignDriverRowClass({ selected: selectedDriver === driver.id, assignable: isAssignable })}`}
                    onClick={() => {
                      if (!isAssignable) return;
                      setSelectedDriver(driver.id);
                      setAssignDriverSearch(driver.name || "");
                    }}
                    data-testid={`assign-driver-option-${driver.id}`}
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="font-semibold">{driver.name}</span>
                      <div className="flex shrink-0 gap-1">
                        <Badge variant="outline" className="text-xs">Scor {driver.ranking_score || 0}</Badge>
                        <Badge className={`border-0 text-xs ${isAssignable ? "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100" : "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-100"}`} data-testid={`assign-driver-status-${driver.id}`}>{availabilityLabel}</Badge>
                      </div>
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">{driver.phone} · {driver.vehicle_type === "car" ? "Mașină" : "Scuter"}</p>
                  </button>
                );})}
                {filteredDriverCandidates.length === 0 && (
                  <p className="p-3 text-sm text-muted-foreground" data-testid="assign-driver-empty-state">Niciun livrator găsit pentru filtrul curent.</p>
                )}
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsAssignDialogOpen(false)} disabled={isAssigning} data-testid="assign-cancel-button">Anulează</Button>
            <Button onClick={confirmAssign} disabled={isAssigning || !selectedOrder?.id || !selectedDriver || !isOnline} data-testid="assign-confirm-button">
              {isAssigning ? "Se alocă..." : "Alocă"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* New Order Dialog */}
      <Dialog open={isNewOrderDialogOpen} onOpenChange={setIsNewOrderDialogOpen}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Comandă Nouă</DialogTitle>
            <DialogDescription>
              Completează comanda și selectează restaurantul pentru detectarea zonei corecte.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 max-h-[60vh] overflow-y-auto">
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Restaurant *</Label>
                <Button
                  type="button"
                  variant="outline"
                  className="w-full justify-between"
                  onClick={() => setIsRestaurantPickerOpen((open) => !open)}
                  data-testid="new-order-restaurant-select"
                >
                  <span className="truncate">
                    {restaurants.find((restaurant) => restaurant.id === newOrder.restaurant_id)?.name || "Selectează"}
                  </span>
                  <Store className="h-4 w-4 text-muted-foreground" />
                </Button>
                {isRestaurantPickerOpen && (
                  <div className="mt-2 max-h-52 space-y-2 overflow-y-auto rounded-lg border bg-card p-2 shadow-sm" data-testid="new-order-restaurant-options">
                    {restaurants.map((restaurant) => (
                      <button
                        key={restaurant.id}
                        type="button"
                        className={`w-full rounded-md border px-3 py-2 text-left text-sm transition-colors ${newOrder.restaurant_id === restaurant.id ? "border-orange-300 bg-orange-50 dark:bg-orange-950/20" : "hover:bg-muted/60"}`}
                        onClick={() => {
                          setNewOrder({
                            ...newOrder,
                            restaurant_id: restaurant.id,
                            delivery_zone_id: null,
                            delivery_zone_name: "",
                            delivery_sector: "",
                            delivery_zone_level: null,
                            delivery_fee: 0,
                            total_amount: Number(newOrder.subtotal_amount || 0),
                          });
                          setIsRestaurantPickerOpen(false);
                        }}
                        data-testid={`new-order-restaurant-option-${restaurant.id}`}
                      >
                        <span className="block font-medium">{restaurant.name}</span>
                        <span className="block truncate text-xs text-muted-foreground">{restaurant.address}</span>
                      </button>
                    ))}
                  </div>
                )}
              </div>
              <div>
                <Label>Sursă</Label>
                <Select value={newOrder.source} onValueChange={(v) => setNewOrder({...newOrder, source: v})}>
                  <SelectTrigger data-testid="new-order-source-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="S">Site/Telefon</SelectItem>
                    <SelectItem value="G">Glovo</SelectItem>
                    <SelectItem value="W">Wolt</SelectItem>
                    <SelectItem value="B">Bolt Food</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div>
              <Label>Nume Client *</Label>
              <Input value={newOrder.customer_name} onChange={(e) => setNewOrder({...newOrder, customer_name: e.target.value})} data-testid="new-order-customer-name-input" />
            </div>
            <div>
              <Label>Telefon Client *</Label>
              <Input value={newOrder.customer_phone} onChange={(e) => setNewOrder({...newOrder, customer_phone: e.target.value})} data-testid="new-order-customer-phone-input" />
            </div>
            <div>
              <Label>Adresă Livrare *</Label>
              <Input value={newOrder.customer_address} onChange={(e) => setNewOrder({...newOrder, customer_address: e.target.value})} data-testid="new-order-address-input" />
            </div>
            <div>
              <Label>Locație livrare pe hartă *</Label>
              <OrderLocationPicker value={newOrder} onChange={updateOrderLocation} />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Latitudine</Label>
                <Input value={newOrder.customer_latitude ?? ""} readOnly data-testid="new-order-latitude" />
              </div>
              <div>
                <Label>Longitudine</Label>
                <Input value={newOrder.customer_longitude ?? ""} readOnly data-testid="new-order-longitude" />
              </div>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Subtotal produse (RON) *</Label>
                <Input type="number" value={newOrder.subtotal_amount} onChange={(e) => {
                  const subtotal = parseFloat(e.target.value) || 0;
                  setNewOrder({
                    ...newOrder,
                    subtotal_amount: subtotal,
                    total_amount: Number((subtotal + (newOrder.delivery_fee || 0)).toFixed(2)),
                  });
                }} data-testid="new-order-subtotal-input" />
              </div>
              <div>
                <Label>Plată</Label>
                <Select value={newOrder.payment_type} onValueChange={(v) => setNewOrder({...newOrder, payment_type: v})}>
                  <SelectTrigger data-testid="new-order-payment-select">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="CASH">Cash</SelectItem>
                    <SelectItem value="CARD">Card</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div>
                <Label>Taxă livrare</Label>
                <Input value={newOrder.delivery_fee} readOnly data-testid="new-order-delivery-fee" />
              </div>
              <div>
                <Label>Zonă detectată</Label>
                <Input value={newOrder.delivery_zone_name || ""} readOnly data-testid="new-order-detected-zone" />
              </div>
              <div>
                <Label>Total final</Label>
                <Input value={newOrder.total_amount} readOnly data-testid="new-order-total-amount" />
              </div>
            </div>
            {newOrder.delivery_zone_name && (
              <div className="rounded-lg border bg-muted/40 p-3 text-sm" data-testid="new-order-zone-summary">
                <p><strong>Restaurant:</strong> {restaurants.find((rest) => rest.id === newOrder.restaurant_id)?.name || "-"}</p>
                <p><strong>Zonă:</strong> {newOrder.delivery_zone_name || "-"}</p>
                <p><strong>Taxă aplicată:</strong> {newOrder.delivery_fee} lei</p>
              </div>
            )}
            <div>
              <Label>Observații</Label>
              <Textarea value={newOrder.notes} onChange={(e) => setNewOrder({...newOrder, notes: e.target.value})} data-testid="new-order-notes-input" />
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsNewOrderDialogOpen(false)} disabled={isCreatingOrder} data-testid="new-order-cancel-button">Anulează</Button>
            <Button onClick={createOrder} disabled={isCreatingOrder || isDetectingOrderZone || !isOnline} data-testid="new-order-submit-button">
              {isCreatingOrder ? "Se creează..." : isDetectingOrderZone ? "Verific zona..." : "Creează Comandă"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* New Driver Dialog */}
      <Dialog open={isNewDriverDialogOpen} onOpenChange={setIsNewDriverDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Livrator Nou</DialogTitle>
            <DialogDescription>
              Adaugă un livrator nou în platformă și generează contul lui de acces.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Nume *</Label>
              <Input value={newDriver.name} onChange={(e) => setNewDriver({...newDriver, name: e.target.value})} data-testid="new-driver-name-input" />
            </div>
            <div>
              <Label>Telefon *</Label>
              <Input value={newDriver.phone} onChange={(e) => setNewDriver({...newDriver, phone: e.target.value})} data-testid="new-driver-phone-input" />
            </div>
            <div>
              <Label>Email *</Label>
              <Input type="email" value={newDriver.email} onChange={(e) => setNewDriver({...newDriver, email: e.target.value})} data-testid="new-driver-email-input" />
            </div>
            <div>
              <Label>Vehicul *</Label>
              <Select value={newDriver.vehicle_type} onValueChange={(value) => setNewDriver({...newDriver, vehicle_type: value})}>
                <SelectTrigger data-testid="new-driver-vehicle-select">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="scooter">Scuter</SelectItem>
                  <SelectItem value="car">Mașină</SelectItem>
                </SelectContent>
              </Select>
            </div>
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
              Se trimite cod de verificare pe email. Parola inițială se generează automat și se afișează după creare.
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsNewDriverDialogOpen(false)} disabled={isCreatingDriver} data-testid="new-driver-cancel-button">Anulează</Button>
            <Button onClick={createDriver} disabled={isCreatingDriver || !isOnline} data-testid="new-driver-submit-button">
              {isCreatingDriver ? "Se creează..." : "Creează Livrator"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!driverVerificationFallback} onOpenChange={(open) => !open && setDriverVerificationFallback(null)}>
        <DialogContent className="max-w-md" data-testid="driver-verification-fallback-dialog">
          <DialogHeader>
            <DialogTitle>Cod verificare generat local</DialogTitle>
            <DialogDescription>
              Resend blochează `onboarding@resend.dev` pentru destinatari externi. Folosește codul de mai jos în preview, apoi verifică domeniul Resend pentru email real.
            </DialogDescription>
          </DialogHeader>
          {driverVerificationFallback && (
            <div className="space-y-4">
              <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
                Email: <strong>{driverVerificationFallback.email}</strong><br />
                Parolă inițială: <strong>{driverVerificationFallback.password}</strong>
              </div>
              <div className="rounded-lg bg-slate-950 p-5 text-center text-white">
                <p className="text-xs uppercase tracking-[0.18em] text-slate-400">Cod verificare</p>
                <p className="mt-2 text-4xl font-black tracking-[0.2em]" data-testid="driver-verification-fallback-code">
                  {driverVerificationFallback.code}
                </p>
              </div>
              <Button
                type="button"
                className="w-full"
                onClick={() => {
                  navigator.clipboard?.writeText(driverVerificationFallback.code);
                  toast.success("Cod copiat");
                }}
                data-testid="driver-verification-copy-code-button"
              >
                Copiază codul
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <DriverManagementDialog
        driver={driverManagement}
        open={!!driverManagement}
        onOpenChange={(open) => !open && setDriverManagement(null)}
        onChanged={fetchData}
      />

      {/* Driver Score Dialog */}
      <Dialog open={!!scoreDialogDriver} onOpenChange={(open) => !open && setScoreDialogDriver(null)}>
        <DialogContent className="max-w-lg" data-testid="driver-score-dialog">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Info className="h-5 w-5 text-indigo-600" />
              Scor livrator · {scoreDialogDriver?.name}
            </DialogTitle>
            <DialogDescription>
              Scorul stabilește prioritatea la calendar și ajută dispeceratul la alocări.
            </DialogDescription>
          </DialogHeader>
          {scoreDialogDriver && (
            <div className="space-y-4">
              <div className="grid grid-cols-2 gap-3">
                <div className="rounded-lg border bg-muted/40 p-3">
                  <p className="text-xs text-muted-foreground">Scor total</p>
                  <p className="text-2xl font-bold">{scoreDialogDriver.ranking_score || 0}</p>
                </div>
                <div className="rounded-lg border bg-muted/40 p-3">
                  <p className="text-xs text-muted-foreground">Rank</p>
                  <p className="text-2xl font-bold">{scoreDialogDriver.ranking_tier || "Start"}</p>
                </div>
              </div>
              <div className="space-y-2">
                {Object.entries(scoreDialogDriver.ranking_breakdown || {}).map(([key, value]) => {
                  const labels = { deliveries: "Livrări", cancellations: "Anulări", punctuality: "Punctualitate", seniority: "Vechime", manual: "Ajustare manuală" };
                  return (
                    <div key={key} className="flex items-center justify-between rounded-md border p-2 text-sm">
                      <span>{labels[key] || key}</span>
                      <strong>{value} pct</strong>
                    </div>
                  );
                })}
              </div>
              <div className="rounded-lg border border-indigo-200 bg-indigo-50 p-3 text-sm text-indigo-900 dark:border-indigo-900 dark:bg-indigo-950/30 dark:text-indigo-100">
                <p><strong>Ore azi:</strong> {scoreDialogDriver.schedule_today_hours || 0}</p>
                <p><strong>Livrări totale:</strong> {scoreDialogDriver.ranking_metrics?.total_deliveries || scoreDialogDriver.total_deliveries || 0}</p>
                <p><strong>Punctualitate:</strong> {Math.round((scoreDialogDriver.ranking_metrics?.punctuality_rate || 0) * 100)}%</p>
                {scoreDialogDriver.next_tier ? (
                  <p><strong>Pentru următorul rank:</strong> încă {scoreDialogDriver.points_to_next_tier} puncte până la {scoreDialogDriver.next_tier.label}</p>
                ) : (
                  <p><strong>Rank maxim:</strong> livratorul este deja în top.</p>
                )}
              </div>
            </div>
          )}
        </DialogContent>
      </Dialog>

      {/* New Restaurant Dialog */}
      <Dialog open={isNewRestaurantDialogOpen} onOpenChange={setIsNewRestaurantDialogOpen}>
        <DialogContent className="max-w-2xl">
          <DialogHeader>
            <DialogTitle>Restaurant Nou</DialogTitle>
            <DialogDescription>
              Alege locația restaurantului, apoi vei putea desena zonele de livrare dedicate.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4 max-h-[70vh] overflow-y-auto pr-1">
            <div>
              <Label>Nume Restaurant *</Label>
              <Input
                value={newRestaurant.name}
                onChange={(e) => setNewRestaurant({...newRestaurant, name: e.target.value})}
                data-testid="new-restaurant-name-input"
              />
            </div>
            <div>
              <Label>Adresă / locație *</Label>
              <LocationAutocomplete
                value={newRestaurant.address}
                onChange={(address) => setNewRestaurant({...newRestaurant, address})}
                onSelect={(location) => {
                  setNewRestaurant((prev) => ({
                    ...prev,
                    address: location.label,
                    latitude: location.lat,
                    longitude: location.lng,
                    location_source: "nominatim",
                  }));
                }}
                placeholder="Caută restaurantul sau adresa în Bacău"
                testIdPrefix="new-restaurant-location"
              />
            </div>
            <RestaurantLocationPreview
              restaurant={newRestaurant}
              onLocationChange={(location) => setNewRestaurant((prev) => ({ ...prev, ...location }))}
            />
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Latitudine</Label>
                <Input value={newRestaurant.latitude || ""} readOnly data-testid="new-restaurant-latitude-input" />
              </div>
              <div>
                <Label>Longitudine</Label>
                <Input value={newRestaurant.longitude || ""} readOnly data-testid="new-restaurant-longitude-input" />
              </div>
            </div>
            <div>
              <Label>Telefon *</Label>
              <Input
                value={newRestaurant.phone}
                onChange={(e) => setNewRestaurant({...newRestaurant, phone: e.target.value})}
                data-testid="new-restaurant-phone-input"
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div>
                <Label>Persoană contact</Label>
                <Input
                  value={newRestaurant.contact_name}
                  onChange={(e) => setNewRestaurant({...newRestaurant, contact_name: e.target.value})}
                  data-testid="new-restaurant-contact-name-input"
                />
              </div>
              <div>
                <Label>Email</Label>
                <Input
                  value={newRestaurant.email}
                  onChange={(e) => setNewRestaurant({...newRestaurant, email: e.target.value})}
                  data-testid="new-restaurant-email-input"
                />
              </div>
            </div>
            <p className="text-sm text-muted-foreground">Se va crea automat un cont pentru restaurant, iar parola inițială se generează automat și se afișează după creare.</p>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setIsNewRestaurantDialogOpen(false)} disabled={isCreatingRestaurant} data-testid="new-restaurant-cancel-button">Anulează</Button>
            <Button onClick={createRestaurant} disabled={isCreatingRestaurant || !isOnline} data-testid="new-restaurant-submit-button">
              {isCreatingRestaurant ? "Se creează..." : "Creează Restaurant"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* Simulation Dialog */}
      <Dialog open={isSimDialogOpen} onOpenChange={(open) => { if (!isSimRunning) setIsSimDialogOpen(open); else { simAbort.current = true; setIsSimRunning(false); setIsSimDialogOpen(false); } }}>
        <DialogContent className="sm:max-w-md">
          <DialogHeader>
            <DialogTitle className="flex items-center gap-2">
              <Play className="w-5 h-5" style={{ color: 'hsl(24 95% 53%)' }} />
              Simulare Flux Comandă
            </DialogTitle>
            <DialogDescription>
              Urmărește pașii unei comenzi demo de la creare până la livrare.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3 py-2" data-testid="simulation-steps">
            {simSteps.map((step) => (
              <div key={step.key} className={`flex items-center gap-3 p-3 rounded-lg transition-all duration-500 ${
                step.status === "active" ? "bg-blue-50 border border-blue-200 scale-[1.02] dark:bg-blue-950/30 dark:border-blue-900" :
                step.status === "done" ? "bg-green-50 border border-green-200 dark:bg-green-950/30 dark:border-green-900" :
                "bg-muted/30 border border-transparent"
              }`}>
                <div className="shrink-0">
                  {step.status === "done" && <CheckCircle2 className="w-5 h-5 text-green-600" />}
                  {step.status === "active" && <Loader2 className="w-5 h-5 text-blue-600 animate-spin" />}
                  {step.status === "pending" && <Circle className="w-5 h-5 text-muted-foreground/30" />}
                </div>
                <div className="flex-1 min-w-0">
                  <p className={`text-sm font-medium ${
                    step.status === "done" ? "text-green-700 dark:text-green-100" :
                    step.status === "active" ? "text-blue-700 dark:text-blue-100" :
                    "text-muted-foreground"
                  }`}>
                    {step.label}
                  </p>
                </div>
                <span className="text-xs shrink-0">
                  {step.status === "done" && <Badge className="bg-green-100 text-green-700 border-0 dark:bg-green-950/40 dark:text-green-100">OK</Badge>}
                  {step.status === "active" && <Badge className="bg-blue-100 text-blue-700 border-0 animate-pulse dark:bg-blue-950/40 dark:text-blue-100">...</Badge>}
                </span>
              </div>
            ))}
          </div>
          {!isSimRunning && simSteps.some(s => s.status === "done") && (
            <DialogFooter>
              <Button variant="outline" onClick={() => setIsSimDialogOpen(false)}>Închide</Button>
              <Button onClick={runSimulation} className="gap-2" style={{ background: 'hsl(24 95% 53%)', color: 'white' }}>
                <Play className="w-4 h-4" /> Rulează din nou
              </Button>
            </DialogFooter>
          )}
        </DialogContent>
      </Dialog>
    </div>
  );
};

export default AdminDashboard;
