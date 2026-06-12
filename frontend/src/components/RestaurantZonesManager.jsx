import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import axios from "axios";
import { toast } from "sonner";
import { Button } from "./ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "./ui/card";
import { Badge } from "./ui/badge";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import { Switch } from "./ui/switch";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "./ui/dialog";
import { MapContainer, Marker, Polygon, Popup, TileLayer, useMap, useMapEvents } from "react-leaflet";
import L from "leaflet";
import "leaflet/dist/leaflet.css";
import { CornerDownLeft, MapPinned, Pencil, Plus, RotateCcw, Save, Trash2, Undo2, X } from "lucide-react";
import { getApiErrorMessage, normalizeArray, retryApiCall } from "../lib/api";

const API_URL = process.env.REACT_APP_BACKEND_URL;

const ZONE_COLORS = ["#2563eb", "#059669", "#f59e0b", "#7c3aed", "#0891b2", "#e11d48"];

const restaurantIcon = new L.Icon({
  iconUrl: "https://raw.githubusercontent.com/pointhi/leaflet-color-markers/master/img/marker-icon-2x-orange.png",
  shadowUrl: "https://cdnjs.cloudflare.com/ajax/libs/leaflet/1.7.1/images/marker-shadow.png",
  iconSize: [25, 41],
  iconAnchor: [12, 41],
  popupAnchor: [1, -34],
  shadowSize: [41, 41],
});

function MapFocus({ restaurant }) {
  const map = useMap();
  const lastFocusedId = useRef(null);

  useEffect(() => {
    if (restaurant?.id && restaurant?.latitude && restaurant?.longitude && lastFocusedId.current !== restaurant.id) {
      map.setView([restaurant.latitude, restaurant.longitude], 14, { animate: true });
      lastFocusedId.current = restaurant.id;
    }
  }, [map, restaurant?.id, restaurant?.latitude, restaurant?.longitude]);

  return null;
}

function DrawControl({ isDrawing, undoTick, onPointCountChange, onPolygonCreated }) {
  const map = useMap();
  const pointsRef = useRef([]);
  const polylineRef = useRef(null);
  const markersRef = useRef([]);

  const clearLayers = useCallback(() => {
    if (polylineRef.current) {
      map.removeLayer(polylineRef.current);
      polylineRef.current = null;
    }
    markersRef.current.forEach((marker) => map.removeLayer(marker));
    markersRef.current = [];
  }, [map]);

  const resetDrawing = useCallback(() => {
    clearLayers();
    pointsRef.current = [];
    onPointCountChange(0);
  }, [clearLayers, onPointCountChange]);

  const redrawDraft = useCallback(() => {
    clearLayers();
    pointsRef.current.forEach(([lat, lng], index) => {
      const marker = L.circleMarker([lat, lng], {
        radius: index === 0 ? 8 : 5,
        color: index === 0 ? "#16a34a" : "#2563eb",
        fillColor: index === 0 ? "#16a34a" : "#2563eb",
        fillOpacity: 1,
      }).addTo(map);
      markersRef.current.push(marker);
    });
    if (pointsRef.current.length > 1) {
      polylineRef.current = L.polyline(pointsRef.current, {
        color: "#2563eb",
        weight: 3,
        dashArray: "6,8",
      }).addTo(map);
    }
    onPointCountChange(pointsRef.current.length);
  }, [clearLayers, map, onPointCountChange]);

  const undoLastPoint = useCallback(() => {
    if (!isDrawing || pointsRef.current.length === 0) return;
    pointsRef.current = pointsRef.current.slice(0, -1);
    redrawDraft();
  }, [isDrawing, redrawDraft]);

  const completePolygon = useCallback(() => {
    if (pointsRef.current.length < 3) {
      toast.error("Ai nevoie de minim 3 puncte pentru o zonă");
      return;
    }
    const coords = pointsRef.current.map(([lat, lng]) => ({ lat, lng }));
    resetDrawing();
    onPolygonCreated(coords);
  }, [onPolygonCreated, resetDrawing]);

  useEffect(() => {
    if (!isDrawing) resetDrawing();
  }, [isDrawing, resetDrawing]);

  useEffect(() => {
    undoLastPoint();
  }, [undoTick, undoLastPoint]);

  useEffect(() => {
    const handleKeyDown = (event) => {
      if (!isDrawing) return;
      if (event.key === "Control") {
        event.preventDefault();
        undoLastPoint();
      }
      if (event.key === "Enter") {
        event.preventDefault();
        completePolygon();
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [completePolygon, isDrawing, undoLastPoint]);

  useMapEvents({
    click(event) {
      if (!isDrawing) return;
      const clickedPoint = [event.latlng.lat, event.latlng.lng];
      const firstPoint = pointsRef.current[0];
      const closesPolygon = firstPoint
        && pointsRef.current.length >= 3
        && map.distance(event.latlng, L.latLng(firstPoint[0], firstPoint[1])) < 25;

      if (closesPolygon) {
        completePolygon();
        return;
      }

      pointsRef.current = [...pointsRef.current, clickedPoint];
      redrawDraft();
    },
  });

  return null;
}

function ZonePolygon({ zone }) {
  const positions = useMemo(() => zone.polygon.map((point) => [point.lat, point.lng]), [zone.polygon]);
  const pathOptions = useMemo(() => ({
    color: zone.color,
    fillColor: zone.color,
    fillOpacity: 0.16,
    opacity: 0.9,
    weight: 2,
  }), [zone.color]);

  return <Polygon positions={positions} pathOptions={pathOptions} />;
}

function ZonePolygons({ zones }) {
  return zones
    .filter((zone) => zone.is_active && (zone.polygon || []).length >= 3)
    .map((zone) => <ZonePolygon key={zone.id} zone={zone} />);
}

export function RestaurantZonesManager({ restaurant, onZonesChange }) {
  const [zones, setZones] = useState([]);
  const [loading, setLoading] = useState(false);
  const [isDrawing, setIsDrawing] = useState(false);
  const [pointCount, setPointCount] = useState(0);
  const [undoTick, setUndoTick] = useState(0);
  const [draftPolygon, setDraftPolygon] = useState(null);
  const [selectedZone, setSelectedZone] = useState(null);
  const [dialogOpen, setDialogOpen] = useState(false);
  const [isSavingZone, setIsSavingZone] = useState(false);
  const [deletingZoneId, setDeletingZoneId] = useState(null);
  const [protectedAction, setProtectedAction] = useState(null);
  const [protectionText, setProtectionText] = useState("");
  const [form, setForm] = useState({ name: "", fee: 10, color: ZONE_COLORS[0], is_active: true });

  const center = useMemo(() => [restaurant?.latitude || 46.567, restaurant?.longitude || 26.913], [restaurant]);

  const fetchZones = useCallback(async () => {
    if (!restaurant?.id) return;
    setLoading(true);
    try {
      const response = await retryApiCall(() => axios.get(`${API_URL}/api/zones`, { params: { restaurant_id: restaurant.id } }));
      const nextZones = normalizeArray(response.data);
      setZones(nextZones);
      onZonesChange?.(nextZones);
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Nu am putut încărca zonele restaurantului"));
    } finally {
      setLoading(false);
    }
  }, [onZonesChange, restaurant?.id]);

  useEffect(() => {
    fetchZones();
  }, [fetchZones]);

  const openCreateDialog = (polygon) => {
    setDraftPolygon(polygon);
    setSelectedZone(null);
    setForm({
      name: `Zona ${zones.length + 1}`,
      fee: 10,
      color: ZONE_COLORS[zones.length % ZONE_COLORS.length],
      is_active: true,
    });
    setDialogOpen(true);
    setIsDrawing(false);
  };

  const openEditDialog = (zone) => {
    setSelectedZone(zone);
    setDraftPolygon(null);
    setForm({
      name: zone.name || "",
      fee: zone.fee || 0,
      color: zone.color || ZONE_COLORS[0],
      is_active: zone.is_active !== false,
    });
    setDialogOpen(true);
  };

  const startDrawing = () => {
    setDialogOpen(false);
    setSelectedZone(null);
    setDraftPolygon(null);
    setIsDrawing(true);
    toast.info("Click pe hartă pentru puncte. Apasă pe primul punct ca să închizi zona.");
  };

  const startRedraw = (zoneOverride = null) => {
    const zoneToRedraw = zoneOverride || selectedZone;
    if (!zoneToRedraw) {
      toast.error("Alege o zonă înainte de redesenare");
      return;
    }
    setSelectedZone(zoneToRedraw);
    setDialogOpen(false);
    setDraftPolygon(null);
    setIsDrawing(true);
    toast.info("Redesenează conturul. Tasta Ctrl șterge ultimul punct.");
  };

  const saveZone = async (confirmed = false) => {
    if (isSavingZone) return;
    if (!form.name.trim()) {
      toast.error("Numele zonei este obligatoriu");
      return;
    }
    if (Number(form.fee) < 0) {
      toast.error("Prețul trebuie să fie pozitiv");
      return;
    }
    if (selectedZone && selectedZone.is_locked !== false && !confirmed) {
      setProtectedAction({ type: "save", zone: selectedZone });
      setProtectionText("");
      return;
    }
    setIsSavingZone(true);
    try {
      if (selectedZone) {
        await axios.put(`${API_URL}/api/zones/${selectedZone.id}`, {
          name: form.name.trim(),
          fee: Number(form.fee),
          color: form.color,
          is_active: form.is_active,
          polygon: draftPolygon || selectedZone.polygon,
          restaurant_id: restaurant.id,
          restaurant_name: restaurant.name,
          sector: restaurant.name,
          zone_level: 1,
          confirm_protected_action: confirmed,
        });
        toast.success("Zona a fost actualizată");
      } else {
        if (!draftPolygon || draftPolygon.length < 3) {
          toast.error("Desenează zona pe hartă înainte de salvare");
          return;
        }
        await axios.post(`${API_URL}/api/zones`, {
          restaurant_id: restaurant.id,
          restaurant_name: restaurant.name,
          sector: restaurant.name,
          zone_level: 1,
          name: form.name.trim(),
          fee: Number(form.fee),
          color: form.color,
          polygon: draftPolygon,
          is_active: form.is_active,
          sort_order: zones.length + 1,
        });
        toast.success("Zona a fost creată");
      }
      setDialogOpen(false);
      setDraftPolygon(null);
      setSelectedZone(null);
      await fetchZones();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Eroare la salvarea zonei"));
    } finally {
      setIsSavingZone(false);
    }
  };

  const deleteZone = async (zone, confirmed = false) => {
    if (deletingZoneId) return;
    if (zone.is_locked !== false && !confirmed) {
      setProtectedAction({ type: "delete", zone });
      setProtectionText("");
      return;
    }
    setDeletingZoneId(zone.id);
    try {
      await axios.delete(`${API_URL}/api/zones/${zone.id}`, { params: { confirm_protected_action: confirmed } });
      toast.success("Zona a fost ștearsă");
      if (selectedZone?.id === zone.id) setSelectedZone(null);
      await fetchZones();
    } catch (error) {
      toast.error(getApiErrorMessage(error, "Eroare la ștergerea zonei"));
    } finally {
      setDeletingZoneId(null);
    }
  };

  if (!restaurant) {
    return (
      <Card data-testid="restaurant-zones-empty-state">
        <CardContent className="p-6 text-sm text-muted-foreground">
          Selectează un restaurant pentru a-i desena ariile de livrare.
        </CardContent>
      </Card>
    );
  }

  return (
    <div className="space-y-4" data-testid="restaurant-zones-manager">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex flex-wrap items-center justify-between gap-3">
            <div>
              <CardTitle className="flex items-center gap-2 text-lg">
                <MapPinned className="h-5 w-5 text-orange-600" />
                Arii livrare · {restaurant.name}
              </CardTitle>
              <p className="mt-1 text-sm text-muted-foreground">
                Zonele se aplică doar acestui restaurant și sunt folosite la filtrarea comenzilor/adreselor.
              </p>
            </div>
            <div className="flex flex-wrap gap-2">
              {isDrawing ? (
                <>
                  <Badge variant="outline" className="gap-1 border-blue-300 text-blue-700" data-testid="drawing-status-badge">
                    <CornerDownLeft className="h-3 w-3" />
                    {pointCount} puncte · Ctrl șterge ultimul punct
                  </Badge>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setUndoTick((value) => value + 1)}
                    data-testid="zone-undo-point-button"
                  >
                    <Undo2 className="mr-1 h-4 w-4" />
                    Undo
                  </Button>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    onClick={() => setIsDrawing(false)}
                    data-testid="zone-cancel-drawing-button"
                  >
                    <X className="mr-1 h-4 w-4" />
                    Anulează
                  </Button>
                </>
              ) : (
                <Button type="button" size="sm" onClick={startDrawing} disabled={isSavingZone || deletingZoneId !== null} data-testid="restaurant-draw-zone-button">
                  <Plus className="mr-1 h-4 w-4" />
                  Zonă nouă
                </Button>
              )}
            </div>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
            <div className="h-[470px] overflow-hidden rounded-lg border" data-testid="restaurant-zones-map">
              <MapContainer center={center} zoom={14} className="h-full w-full" doubleClickZoom={false}>
                <TileLayer
                  attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                  url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                />
                <MapFocus restaurant={restaurant} />
                <Marker position={center} icon={restaurantIcon}>
                  <Popup>{restaurant.name}</Popup>
                </Marker>
                <ZonePolygons zones={zones} />
                <DrawControl
                  isDrawing={isDrawing}
                  undoTick={undoTick}
                  onPointCountChange={setPointCount}
                  onPolygonCreated={(polygon) => {
                    if (selectedZone) {
                      setDraftPolygon(polygon);
                      setDialogOpen(true);
                      setIsDrawing(false);
                    } else {
                      openCreateDialog(polygon);
                    }
                  }}
                />
              </MapContainer>
            </div>

            <aside className="space-y-3" data-testid="restaurant-zones-list">
              <div className="flex items-center justify-between">
                <p className="text-sm font-semibold text-muted-foreground">Zone definite</p>
                <Badge variant="secondary" data-testid="restaurant-zones-count">{zones.length}</Badge>
              </div>
              {loading ? (
                <div className="rounded-lg border p-4 text-sm text-muted-foreground">Se încarcă...</div>
              ) : zones.length === 0 ? (
                <div className="rounded-lg border border-dashed p-4 text-sm text-muted-foreground" data-testid="restaurant-no-zones-message">
                  Nu există încă zone pentru acest restaurant.
                </div>
              ) : (
                zones.map((zone) => (
                  <div
                    key={zone.id}
                    className="rounded-lg border bg-card p-3 transition-colors hover:bg-muted/40"
                    data-testid={`restaurant-zone-card-${zone.id}`}
                  >
                    <div className="flex items-start justify-between gap-2">
                      <div className="min-w-0">
                        <div className="flex items-center gap-2">
                          <span className="h-3 w-3 rounded-full" style={{ backgroundColor: zone.color }} />
                          <p className="truncate font-semibold">{zone.name}</p>
                        </div>
                        <p className="mt-1 text-sm text-muted-foreground">{zone.fee} RON · {(zone.polygon || []).length} puncte</p>
                      </div>
                      <Badge variant={zone.is_active ? "outline" : "secondary"}>
                        {zone.is_active ? "Activă" : "Inactivă"}
                      </Badge>
                      {zone.is_locked !== false && (
                        <Badge variant="outline" className="border-amber-300 text-amber-700 dark:border-amber-900 dark:text-amber-100">
                          Blocată
                        </Badge>
                      )}
                    </div>
                    <div className="mt-3 flex gap-2">
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={isSavingZone || deletingZoneId !== null}
                        onClick={() => openEditDialog(zone)}
                        data-testid={`restaurant-zone-edit-button-${zone.id}`}
                      >
                        <Pencil className="mr-1 h-3.5 w-3.5" />
                        Edit
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        disabled={isSavingZone || deletingZoneId !== null}
                        onClick={() => {
                          startRedraw(zone);
                        }}
                        data-testid={`restaurant-zone-redraw-button-${zone.id}`}
                      >
                        <RotateCcw className="mr-1 h-3.5 w-3.5" />
                        Contur
                      </Button>
                      <Button
                        type="button"
                        variant="outline"
                        size="sm"
                        className="text-slate-600 hover:text-red-700"
                        disabled={isSavingZone || deletingZoneId === zone.id}
                        onClick={() => deleteZone(zone)}
                        data-testid={`restaurant-zone-delete-button-${zone.id}`}
                      >
                        <Trash2 className="h-3.5 w-3.5" />
                      </Button>
                    </div>
                  </div>
                ))
              )}
            </aside>
          </div>
        </CardContent>
      </Card>

      <Dialog open={dialogOpen} onOpenChange={setDialogOpen}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>{selectedZone ? "Editează zona" : "Ce nume are zona?"}</DialogTitle>
            <DialogDescription>
              Completează numele, prețul și starea zonei pentru restaurantul selectat.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Nume zonă *</Label>
              <Input
                value={form.name}
                onChange={(event) => setForm((prev) => ({ ...prev, name: event.target.value }))}
                placeholder="ex: Centru / Letea / Șerbănești"
                data-testid="restaurant-zone-name-input"
              />
            </div>
            <div>
              <Label>Preț livrare (RON) *</Label>
              <Input
                type="number"
                min="0"
                step="0.5"
                value={form.fee}
                onChange={(event) => setForm((prev) => ({ ...prev, fee: event.target.value }))}
                data-testid="restaurant-zone-fee-input"
              />
            </div>
            <div>
              <Label>Culoare</Label>
              <div className="mt-2 flex flex-wrap gap-2">
                {ZONE_COLORS.map((color) => (
                  <button
                    key={color}
                    type="button"
                    className={`h-8 w-8 rounded-full border-2 transition-transform ${form.color === color ? "scale-110 border-foreground" : "border-transparent"}`}
                    style={{ backgroundColor: color }}
                    onClick={() => setForm((prev) => ({ ...prev, color }))}
                    data-testid={`restaurant-zone-color-${color.replace("#", "")}`}
                  />
                ))}
              </div>
            </div>
            <div className="flex items-center justify-between rounded-lg border p-3">
              <Label>Zonă activă</Label>
              <Switch
                checked={form.is_active}
                onCheckedChange={(value) => setForm((prev) => ({ ...prev, is_active: value }))}
                data-testid="restaurant-zone-active-switch"
              />
            </div>
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setDialogOpen(false)} disabled={isSavingZone} data-testid="restaurant-zone-dialog-cancel-button">
              Anulează
            </Button>
            {selectedZone && (
              <Button type="button" variant="outline" onClick={() => startRedraw()} disabled={isSavingZone} data-testid="restaurant-zone-dialog-redraw-button">
                <RotateCcw className="mr-1 h-4 w-4" />
                Redesenează
              </Button>
            )}
            <Button type="button" onClick={saveZone} disabled={isSavingZone} data-testid="restaurant-zone-save-button">
              <Save className="mr-1 h-4 w-4" />
              {isSavingZone ? "Se salvează..." : "Salvează"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      <Dialog open={!!protectedAction} onOpenChange={(open) => !open && setProtectedAction(null)}>
        <DialogContent className="max-w-md" data-testid="zone-protection-dialog">
          <DialogHeader>
            <DialogTitle>Confirmare zonă blocată</DialogTitle>
            <DialogDescription>
              Zona „{protectedAction?.zone?.name}” este protejată împotriva modificărilor accidentale.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-3">
            <div className="rounded-lg border border-amber-200 bg-amber-50 p-3 text-sm text-amber-900 dark:border-amber-900 dark:bg-amber-950/30 dark:text-amber-100">
              {protectedAction?.type === "delete"
                ? "Ștergerea poate afecta calculul taxelor și comenzile viitoare."
                : "Modificarea conturului/prețului poate schimba aria de acoperire a restaurantului."}
            </div>
            <Label>Scrie CONFIRM pentru continuare</Label>
            <Input
              value={protectionText}
              onChange={(event) => setProtectionText(event.target.value)}
              data-testid="zone-protection-confirm-input"
            />
          </div>
          <DialogFooter>
            <Button type="button" variant="outline" onClick={() => setProtectedAction(null)} data-testid="zone-protection-cancel-button">Înapoi</Button>
            <Button
              type="button"
              variant={protectedAction?.type === "delete" ? "destructive" : "default"}
              disabled={protectionText !== "CONFIRM" || isSavingZone || deletingZoneId !== null}
              onClick={() => {
                const action = protectedAction;
                setProtectedAction(null);
                if (action?.type === "delete") deleteZone(action.zone, true);
                if (action?.type === "save") saveZone(true);
              }}
              data-testid="zone-protection-confirm-button"
            >
              Confirmă
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
