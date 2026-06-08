import { useCallback, useEffect, useMemo, useRef } from "react";
import { Polygon, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import { toast } from "sonner";

function pointInPolygon(point, polygon) {
  const x = point.lng;
  const y = point.lat;
  let inside = false;
  for (let i = 0, j = polygon.length - 1; i < polygon.length; j = i++) {
    const xi = polygon[i].lng;
    const yi = polygon[i].lat;
    const xj = polygon[j].lng;
    const yj = polygon[j].lat;
    const intersect = ((yi > y) !== (yj > y)) &&
      (x < ((xj - xi) * (y - yi)) / ((yj - yi) || 1e-12) + xi);
    if (intersect) inside = !inside;
  }
  return inside;
}

function getPolygonArea(polygon) {
  let area = 0;
  for (let i = 0; i < polygon.length; i += 1) {
    const next = polygon[(i + 1) % polygon.length];
    area += polygon[i].lng * next.lat - next.lng * polygon[i].lat;
  }
  return Math.abs(area / 2);
}

function resolveClickedZone(latlng, zones) {
  return [...zones]
    .filter((zone) => zone.is_active && pointInPolygon(latlng, zone.polygon || []))
    .sort((a, b) => getPolygonArea(a.polygon || []) - getPolygonArea(b.polygon || []))[0] || null;
}

function getDisplayPositions(zone, sectorZones) {
  const outer = (zone.polygon || []).map((point) => [point.lat, point.lng]);
  if (!outer.length) return null;

  if ((zone.zone_level || 0) === 3) {
    const inner = sectorZones.find((item) => item.zone_level === 2);
    return inner ? [outer, inner.polygon.map((point) => [point.lat, point.lng])] : outer;
  }

  if ((zone.zone_level || 0) === 2) {
    const inner = sectorZones.find((item) => item.zone_level === 1);
    return inner ? [outer, inner.polygon.map((point) => [point.lat, point.lng])] : outer;
  }

  return outer;
}

export function ZoneMapClickResolver({ zones, onZoneClick }) {
  useMapEvents({
    click(event) {
      const bestZone = resolveClickedZone(event.latlng, zones);
      if (bestZone && onZoneClick) onZoneClick(bestZone);
    },
  });

  return null;
}

export function DrawControl({ onPolygonCreated, isDrawing, setIsDrawing }) {
  const map = useMap();
  const pointsRef = useRef([]);
  const polylineRef = useRef(null);
  const markersRef = useRef([]);

  const cleanup = useCallback(() => {
    if (polylineRef.current) {
      map.removeLayer(polylineRef.current);
      polylineRef.current = null;
    }
    markersRef.current.forEach((marker) => map.removeLayer(marker));
    markersRef.current = [];
    pointsRef.current = [];
  }, [map]);

  useEffect(() => {
    if (!isDrawing) cleanup();
  }, [cleanup, isDrawing]);

  useMapEvents({
    click(event) {
      if (!isDrawing) return;
      const { lat, lng } = event.latlng;
      pointsRef.current.push([lat, lng]);
      const marker = L.circleMarker([lat, lng], {
        radius: 6,
        color: "#3b82f6",
        fillColor: "#3b82f6",
        fillOpacity: 1,
      }).addTo(map);
      markersRef.current.push(marker);

      if (polylineRef.current) map.removeLayer(polylineRef.current);
      if (pointsRef.current.length > 1) {
        polylineRef.current = L.polyline(pointsRef.current, {
          color: "#3b82f6",
          weight: 2,
          dashArray: "5,10",
        }).addTo(map);
      }
    },
    dblclick(event) {
      if (!isDrawing) return;
      L.DomEvent.stopPropagation(event);
      L.DomEvent.preventDefault(event);

      if (pointsRef.current.length >= 3) {
        onPolygonCreated(pointsRef.current.map(([lat, lng]) => ({ lat, lng })));
      } else {
        toast.error("Minim 3 puncte pentru o zonă");
      }
      cleanup();
      setIsDrawing(false);
    },
  });

  return null;
}

function ZonePolygon({ zone, positions, isSelected }) {
  const pathOptions = useMemo(() => ({
    color: zone.color,
    fillColor: zone.color,
    fillOpacity: isSelected ? 0.28 : 0.08,
    opacity: isSelected ? 1 : 0.72,
    weight: isSelected ? 3 : 2,
  }), [isSelected, zone.color]);

  return <Polygon positions={positions} interactive={false} pathOptions={pathOptions} />;
}

export function ZonePolygons({ zones, selectedZoneId }) {
  const zonesBySector = useMemo(() => zones.reduce((acc, zone) => {
    const key = zone.sector || "General";
    if (!acc[key]) acc[key] = [];
    acc[key].push(zone);
    return acc;
  }, {}), [zones]);

  return (
    <>
      {[...zones]
        .filter((zone) => zone.is_active)
        .sort((a, b) => (b.zone_level || 0) - (a.zone_level || 0))
        .map((zone) => {
          const positions = getDisplayPositions(zone, zonesBySector[zone.sector || "General"] || []);
          if (!positions) return null;
          const hasEnoughPoints = Array.isArray(positions[0]) && Array.isArray(positions[0][0])
            ? positions[0].length >= 3
            : positions.length >= 3;
          if (!hasEnoughPoints) return null;
          return <ZonePolygon key={zone.id} zone={zone} positions={positions} isSelected={zone.id === selectedZoneId} />;
        })}
    </>
  );
}
