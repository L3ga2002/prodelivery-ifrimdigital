import L from "leaflet";

export const DRIVER_SCOOTER_SVG = `
  <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
    <path d="M18 44c0 4.4-3.6 8-8 8s-8-3.6-8-8 3.6-8 8-8 8 3.6 8 8Z" fill="currentColor"/>
    <path d="M58 44c0 4.4-3.6 8-8 8s-8-3.6-8-8 3.6-8 8-8 8 3.6 8 8Z" fill="currentColor"/>
    <path d="M15 43h16c7 0 12-5 12-12h-8l-6 7H16" fill="none" stroke="currentColor" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M38 22h10l7 13" fill="none" stroke="currentColor" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M30 26h-8l-5-8h10l5 8Z" fill="currentColor"/>
    <path d="M40 17c0 3.2-2.5 5.7-5.7 5.7s-5.7-2.5-5.7-5.7 2.5-5.7 5.7-5.7S40 13.8 40 17Z" fill="currentColor"/>
    <path d="M10 44h40" stroke="white" stroke-width="1.8" stroke-linecap="round" opacity=".8"/>
  </svg>
`;

export const DRIVER_CAR_SVG = `
  <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
    <path d="M12 35 18 22c1-2 3-4 6-4h16c3 0 5 2 6 4l6 13" fill="none" stroke="currentColor" stroke-width="6" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M10 35h44v11H10V35Z" fill="currentColor"/>
    <path d="M20 46c0 3.5-2.8 6.3-6.3 6.3S7.4 49.5 7.4 46s2.8-6.3 6.3-6.3S20 42.5 20 46Z" fill="currentColor"/>
    <path d="M56.6 46c0 3.5-2.8 6.3-6.3 6.3S44 49.5 44 46s2.8-6.3 6.3-6.3 6.3 2.8 6.3 6.3Z" fill="currentColor"/>
    <path d="M23 23h18l4 9H19l4-9Z" fill="white" opacity=".82"/>
  </svg>
`;

export const DriverScooterIcon = () => (
  <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
    <path d="M18 44c0 4.4-3.6 8-8 8s-8-3.6-8-8 3.6-8 8-8 8 3.6 8 8Z" fill="rgba(255,255,255,.92)" />
    <path d="M58 44c0 4.4-3.6 8-8 8s-8-3.6-8-8 3.6-8 8-8 8 3.6 8 8Z" fill="rgba(255,255,255,.92)" />
    <path d="M15 43h16c7 0 12-5 12-12h-8l-6 7H16" fill="none" stroke="white" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M38 22h10l7 13" fill="none" stroke="white" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M30 26h-8l-5-8h10l5 8Z" fill="rgba(255,255,255,.82)" />
    <path d="M40 17c0 3.2-2.5 5.7-5.7 5.7s-5.7-2.5-5.7-5.7 2.5-5.7 5.7-5.7S40 13.8 40 17Z" fill="white" />
  </svg>
);

export const DriverCarIcon = () => (
  <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
    <path d="M12 35 18 22c1-2 3-4 6-4h16c3 0 5 2 6 4l6 13" fill="none" stroke="white" strokeWidth="5" strokeLinecap="round" strokeLinejoin="round" />
    <path d="M10 35h44v11H10V35Z" fill="rgba(255,255,255,.9)" />
    <path d="M20 46c0 3.5-2.8 6.3-6.3 6.3S7.4 49.5 7.4 46s2.8-6.3 6.3-6.3S20 42.5 20 46Z" fill="white" />
    <path d="M56.6 46c0 3.5-2.8 6.3-6.3 6.3S44 49.5 44 46s2.8-6.3 6.3-6.3 6.3 2.8 6.3 6.3Z" fill="white" />
    <path d="M23 23h18l4 9H19l4-9Z" fill="rgba(15,23,42,.18)" />
  </svg>
);

export const RESTAURANT_STOREFRONT_SVG = `
  <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
    <path d="M11 27h42v26H11V27Z" fill="currentColor"/>
    <path d="M16 31h32v18H16V31Z" fill="white" opacity=".82"/>
    <path d="M9 23 15 10h34l6 13H9Z" fill="currentColor"/>
    <path d="M13 23h10v8c0 2.8-2.2 5-5 5s-5-2.2-5-5v-8Zm10 0h9v8c0 2.8-2 5-4.5 5S23 33.8 23 31v-8Zm9 0h9v8c0 2.8-2 5-4.5 5S32 33.8 32 31v-8Zm9 0h10v8c0 2.8-2.2 5-5 5s-5-2.2-5-5v-8Z" fill="white" opacity=".5"/>
    <path d="M22 39h20M26 47h12" stroke="currentColor" stroke-width="4" stroke-linecap="round"/>
  </svg>
`;

export const RestaurantStorefrontIcon = () => (
  <svg viewBox="0 0 64 64" aria-hidden="true" focusable="false">
    <path d="M11 27h42v26H11V27Z" fill="rgba(255,255,255,.9)" />
    <path d="M16 31h32v18H16V31Z" fill="rgba(15,23,42,.18)" />
    <path d="M9 23 15 10h34l6 13H9Z" fill="white" />
    <path d="M13 23h10v8c0 2.8-2.2 5-5 5s-5-2.2-5-5v-8Zm10 0h9v8c0 2.8-2 5-4.5 5S23 33.8 23 31v-8Zm9 0h9v8c0 2.8-2 5-4.5 5S32 33.8 32 31v-8Zm9 0h10v8c0 2.8-2.2 5-5 5s-5-2.2-5-5v-8Z" fill="rgba(255,255,255,.74)" />
    <path d="M22 39h20M26 47h12" stroke="white" strokeWidth="4" strokeLinecap="round" />
  </svg>
);

const escapeHtmlAttribute = (value) => String(value).replace(/[&<>'"]/g, (char) => ({
  "&": "&amp;",
  "<": "&lt;",
  ">": "&gt;",
  "'": "&#39;",
  '"': "&quot;",
}[char]));

const safeMarkerId = (value) => String(value).replace(/[^a-zA-Z0-9_-]/g, "-");

delete L.Icon.Default.prototype._getIconUrl;
L.Icon.Default.mergeOptions({
  iconRetinaUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon-2x.png",
  iconUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-icon.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png",
});

export const getDriverMapStatus = (driver) => {
  if (driver.current_order_id) return "delivery";
  if (driver?.operational_status === "break") return "break";
  if (driver?.is_active) return "active";
  if (driver?.operational_status) return driver.operational_status;
  if (!driver?.is_active) return "offline";
  return "active";
};

export const createMapMarkerIcon = ({ kind, status = "active", id = "marker", vehicleType = "scooter" }) => {
  const isDriver = kind === "driver";
  const icon = isDriver && vehicleType === "car" ? DRIVER_CAR_SVG : isDriver ? DRIVER_SCOOTER_SVG : RESTAURANT_STOREFRONT_SVG;
  const statusLabel = {
    active: "Livrator activ",
    delivery: "Livrator în livrare",
    break: "Livrator în pauză",
    offline: "Livrator offline",
  }[status] || "Livrator";
  const restaurantStatus = status === "break" ? "paused" : "active";
  const label = isDriver ? statusLabel : status === "break" ? "Restaurant în pauză" : "Restaurant activ";
  const tone = isDriver ? `driver-${status}` : `restaurant-${restaurantStatus}`;
  const badge = isDriver ? `<span class="delivery-map-marker-status-dot delivery-map-marker-status-dot-${status}"></span>` : "";
  const testId = `map-${kind}-marker-${safeMarkerId(id)}`;

  return L.divIcon({
    className: "delivery-map-div-icon",
    html: `
      <div class="delivery-map-marker delivery-map-marker-${tone}" data-testid="${testId}" aria-label="${escapeHtmlAttribute(label)}">
        <span class="delivery-map-marker-icon">${icon}</span>
        ${badge}
      </div>
    `,
    iconSize: isDriver ? [36, 36] : [24, 24],
    iconAnchor: isDriver ? [18, 18] : [12, 12],
    popupAnchor: [0, isDriver ? -18 : -14],
  });
};

export const restaurantIcon = createMapMarkerIcon({ kind: "restaurant", id: "preview" });
