import { useState, useEffect, useCallback, useMemo } from "react";
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
  DialogHeader,
  DialogTitle,
  DialogFooter,
} from "./ui/dialog";
import {
  MapContainer,
  TileLayer,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "leaflet-draw/dist/leaflet.draw.css";
import { DrawControl, ZoneMapClickResolver, ZonePolygons } from "./delivery-zones/DeliveryZoneMapParts";
import {
  MapPinned,
  Plus,
  Pencil,
  Trash2,
  Save,
  X,
  EyeOff,
  Layers,
  MousePointerClick,
} from "lucide-react";

const API_URL = process.env.REACT_APP_BACKEND_URL;
const FIXED_ZONE_FEES = { 1: 14, 2: 22, 3: 33 };
const ZONE_LEVEL_COLORS = { 1: "#2563eb", 2: "#f59e0b", 3: "#dc2626" };

const ZONE_COLORS = [
  "#22c55e",
  "#3b82f6",
  "#f59e0b",
  "#ef4444",
  "#8b5cf6",
  "#06b6d4",
  "#ec4899",
  "#14b8a6",
];

export function DeliveryZonesManager() {
  const [zones, setZones] = useState([]);
  const [isLoading, setIsLoading] = useState(true);
  const [isDrawing, setIsDrawing] = useState(false);
  const [selectedZone, setSelectedZone] = useState(null);
  const [sectorFilter, setSectorFilter] = useState("all");
  const [redrawMode, setRedrawMode] = useState(false);
  const [editDialog, setEditDialog] = useState(false);
  const [editForm, setEditForm] = useState({
    sector: "Centru",
    zone_level: 1,
    name: "",
    color: ZONE_LEVEL_COLORS[1],
    fee: FIXED_ZONE_FEES[1],
    is_active: true,
  });
  const [newPolygon, setNewPolygon] = useState(null);

  const sectorOptions = useMemo(
    () => Array.from(new Set(zones.map((zone) => zone.sector).filter(Boolean))),
    [zones],
  );
  const visibleZones = useMemo(
    () => (sectorFilter === "all" ? zones : zones.filter((zone) => zone.sector === sectorFilter)),
    [sectorFilter, zones],
  );
  const mapZones = useMemo(
    () => (sectorFilter === "all"
      ? zones.filter((zone) => zone.zone_level === 3 || zone.id === selectedZone?.id)
      : visibleZones),
    [sectorFilter, selectedZone?.id, visibleZones, zones],
  );
  const groupedZones = useMemo(
    () => visibleZones.reduce((acc, zone) => {
      const key = zone.sector || "General";
      if (!acc[key]) acc[key] = [];
      acc[key].push(zone);
      return acc;
    }, {}),
    [visibleZones],
  );

  const fetchZones = useCallback(async () => {
    try {
      const res = await axios.get(`${API_URL}/api/zones`);
      setZones(res.data);
    } catch {
      toast.error("Eroare la încărcarea zonelor");
    } finally {
      setIsLoading(false);
    }
  }, [setIsLoading, setZones]);

  useEffect(() => {
    fetchZones();
  }, [fetchZones]);

  const handlePolygonCreated = useCallback((coords) => {
    setNewPolygon(coords);
    if (redrawMode && selectedZone) {
      setEditDialog(true);
      setRedrawMode(false);
      return;
    }
    const nextSector = sectorFilter !== "all" ? sectorFilter : sectorOptions[0] || "Centru";
    setEditForm({
      sector: nextSector,
      zone_level: 1,
      name: `${nextSector} - Zona 1`,
      color: ZONE_LEVEL_COLORS[1],
      fee: FIXED_ZONE_FEES[1],
      is_active: true,
    });
    setSelectedZone(null);
    setEditDialog(true);
  }, [redrawMode, sectorFilter, sectorOptions, selectedZone]);

  const updateZoneLevel = (zoneLevel) => {
    setEditForm((prev) => ({
      ...prev,
      zone_level: zoneLevel,
      color: ZONE_LEVEL_COLORS[zoneLevel],
      fee: FIXED_ZONE_FEES[zoneLevel],
      name: prev.sector ? `${prev.sector} - Zona ${zoneLevel}` : prev.name,
    }));
  };

  const handleSaveZone = async () => {
    if (!editForm.name.trim()) {
      toast.error("Numele zonei este obligatoriu");
      return;
    }

    try {
      if (selectedZone) {
        await axios.put(`${API_URL}/api/zones/${selectedZone.id}`, {
          sector: editForm.sector,
          zone_level: editForm.zone_level,
          name: editForm.name,
          color: editForm.color,
          fee: editForm.fee,
          is_active: editForm.is_active,
          polygon: newPolygon || selectedZone.polygon,
        });
        toast.success("Zona a fost actualizată");
      } else {
        if (!newPolygon || newPolygon.length < 3) {
          toast.error("Desenează o zonă pe hartă mai întâi");
          return;
        }
        await axios.post(`${API_URL}/api/zones`, {
          sector: editForm.sector,
          zone_level: editForm.zone_level,
          name: editForm.name,
          color: editForm.color,
          fee: editForm.fee,
          polygon: newPolygon,
          is_active: editForm.is_active,
          sort_order: zones.length + 1,
        });
        toast.success("Zona a fost creată");
      }
      setEditDialog(false);
      setNewPolygon(null);
      setSelectedZone(null);
      setRedrawMode(false);
      fetchZones();
    } catch {
      toast.error("Eroare la salvarea zonei");
    }
  };

  const handleEditZone = (zone) => {
    setSelectedZone(zone);
    setEditForm({
      sector: zone.sector || "General",
      zone_level: zone.zone_level || 1,
      name: zone.name,
      color: zone.color,
      fee: zone.fee,
      is_active: zone.is_active,
    });
    setNewPolygon(null);
    setEditDialog(true);
  };

  const handleDeleteZone = async (zoneId) => {
    try {
      await axios.delete(`${API_URL}/api/zones/${zoneId}`);
      toast.success("Zona a fost ștearsă");
      if (selectedZone?.id === zoneId) setSelectedZone(null);
      fetchZones();
    } catch {
      toast.error("Eroare la ștergerea zonei");
    }
  };

  const handleZoneClick = (zone) => {
    setSelectedZone(zone);
    if (sectorFilter === "all" && zone.sector) {
      setSectorFilter(zone.sector);
    }
  };

  const startRedraw = () => {
    if (!selectedZone && !editDialog) {
      toast.error("Selectează mai întâi o zonă");
      return;
    }
    setEditDialog(false);
    setRedrawMode(!!selectedZone);
    setIsDrawing(true);
    toast.info("Desenează conturul pe hartă și fă dublu-click pentru finalizare");
  };

  if (isLoading) {
    return (
      <div className="flex justify-center py-12">
        <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary" />
      </div>
    );
  }

  return (
    <div className="space-y-4" data-testid="delivery-zones-manager">
      <Card>
        <CardHeader className="pb-3">
          <div className="flex items-center justify-between">
            <CardTitle className="flex items-center gap-2 text-lg">
              <MapPinned className="w-5 h-5" />
              Zone de Livrare - Bacău
            </CardTitle>
            <div className="flex gap-2">
              {isDrawing ? (
                <>
                  <Badge
                    variant="outline"
                    className="animate-pulse border-blue-400 text-blue-600 px-3 py-1 dark:border-blue-700 dark:text-blue-100"
                  >
                    <MousePointerClick className="w-3 h-3 mr-1" />
                    Click pe hartă pentru puncte, dublu-click pentru finalizare
                  </Badge>
                  <Button
                    variant="outline"
                    size="sm"
                    onClick={() => {
                      setIsDrawing(false);
                      setRedrawMode(false);
                    }}
                    data-testid="cancel-draw-btn"
                  >
                    <X className="w-4 h-4 mr-1" />
                    Anulează
                  </Button>
                </>
              ) : (
                <>
                  <Button
                    size="sm"
                    variant="outline"
                    onClick={startRedraw}
                    className="gap-1"
                    data-testid="redraw-zone-btn"
                  >
                    <Pencil className="w-4 h-4" />
                    Modifică Contur
                  </Button>
                  <Button
                    size="sm"
                    onClick={() => setIsDrawing(true)}
                    className="gap-1"
                    data-testid="draw-zone-btn"
                  >
                    <Plus className="w-4 h-4" />
                    Zonă Nouă
                  </Button>
                </>
              )}
            </div>
          </div>
          <p className="text-sm text-muted-foreground mt-1">
            4 sectoare × 3 zone fixe. Zona 1 = 14 lei, Zona 2 = 22 lei, Zona 3 = 33 lei.
          </p>
          <p className="text-xs text-muted-foreground mt-2">
            În modul „Toate” afișăm doar conturul exterior al fiecărui sector pentru o hartă mai clară. Când alegi un sector, vezi toate cele 3 zone ale lui.
          </p>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-4 mb-4">
            <Card className="border-blue-200 bg-blue-50 dark:border-blue-900 dark:bg-blue-950/20">
              <CardContent className="p-4">
                <p className="text-xs uppercase tracking-wide text-blue-700 dark:text-blue-100">Zona 1</p>
                <p className="text-2xl font-bold text-blue-800 dark:text-blue-50">14 lei</p>
              </CardContent>
            </Card>
            <Card className="border-amber-200 bg-amber-50 dark:border-amber-900 dark:bg-amber-950/20">
              <CardContent className="p-4">
                <p className="text-xs uppercase tracking-wide text-amber-700 dark:text-amber-100">Zona 2</p>
                <p className="text-2xl font-bold text-amber-800 dark:text-amber-50">22 lei</p>
              </CardContent>
            </Card>
            <Card className="border-red-200 bg-red-50 dark:border-red-900 dark:bg-red-950/20">
              <CardContent className="p-4">
                <p className="text-xs uppercase tracking-wide text-red-700 dark:text-red-100">Zona 3</p>
                <p className="text-2xl font-bold text-red-800 dark:text-red-50">33 lei</p>
              </CardContent>
            </Card>
            <Card>
              <CardContent className="p-4">
                <p className="text-xs uppercase tracking-wide text-muted-foreground">Filtru sector</p>
                <div className="flex flex-wrap gap-2 mt-2" data-testid="sector-filters">
                  <Button
                    size="sm"
                    variant={sectorFilter === "all" ? "default" : "outline"}
                    onClick={() => setSectorFilter("all")}
                    data-testid="sector-filter-all"
                  >
                    Toate
                  </Button>
                  {sectorOptions.map((sector) => (
                    <Button
                      key={sector}
                      size="sm"
                      variant={sectorFilter === sector ? "default" : "outline"}
                      onClick={() => setSectorFilter(sector)}
                      data-testid={`sector-filter-${sector.toLowerCase().replace(/\s+/g, "-")}`}
                    >
                      {sector}
                    </Button>
                  ))}
                </div>
                {selectedZone && (
                  <div className="mt-3 rounded-lg border bg-muted/40 p-3 text-sm" data-testid="selected-zone-summary">
                    <p className="font-semibold">{selectedZone.name}</p>
                    <p className="text-muted-foreground">{selectedZone.sector} · Zona {selectedZone.zone_level}</p>
                    <p className="mt-1">Taxă: <strong>{selectedZone.fee} lei</strong></p>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="grid lg:grid-cols-3 gap-4">
            {/* Map */}
            <div className="lg:col-span-2">
              <div
                className="h-[500px] rounded-lg overflow-hidden border"
                data-testid="zones-map"
              >
                <MapContainer
                  center={[46.567, 26.913]}
                  zoom={14}
                  className="h-full w-full"
                  doubleClickZoom={false}
                >
                  <TileLayer
                    attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>'
                    url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
                  />
                  <ZonePolygons
                    zones={mapZones}
                    selectedZoneId={selectedZone?.id}
                    onZoneClick={handleZoneClick}
                  />
                  <ZoneMapClickResolver zones={mapZones} onZoneClick={handleZoneClick} />
                  <DrawControl
                    onPolygonCreated={handlePolygonCreated}
                    isDrawing={isDrawing}
                    setIsDrawing={setIsDrawing}
                  />
                </MapContainer>
              </div>
            </div>

            {/* Zone List */}
            <div className="space-y-3" data-testid="zones-list">
              <div className="flex items-center gap-2 mb-2">
                <Layers className="w-4 h-4 text-muted-foreground" />
                <span className="text-sm font-semibold text-muted-foreground uppercase tracking-wider">
                  Zone ({zones.length})
                </span>
              </div>

              {visibleZones.length === 0 ? (
                <div className="text-center py-8 text-muted-foreground text-sm">
                  <MapPinned className="w-10 h-10 mx-auto mb-2 opacity-30" />
                  <p>Nicio zonă definită</p>
                  <p className="text-xs mt-1">
                    Apasă &quot;Zonă Nouă&quot; și desenează pe hartă
                  </p>
                </div>
              ) : (
                Object.entries(groupedZones).map(([sector, sectorZones]) => (
                  <div key={sector} className="space-y-2">
                    <div className="flex items-center justify-between pt-2">
                      <span className="text-xs uppercase tracking-[0.2em] text-muted-foreground">{sector}</span>
                      <Badge variant="secondary">{sectorZones.length} zone</Badge>
                    </div>
                    {sectorZones
                      .slice()
                      .sort((a, b) => (a.zone_level || 0) - (b.zone_level || 0))
                      .map((zone) => (
                        <div
                          key={zone.id}
                          className={`p-3 rounded-lg border cursor-pointer transition-all ${
                            selectedZone?.id === zone.id
                              ? "ring-2 ring-primary bg-primary/5"
                              : "hover:bg-muted/50"
                          } ${!zone.is_active ? "opacity-50" : ""}`}
                          onClick={() => handleZoneClick(zone)}
                          data-testid={`zone-card-${zone.id}`}
                        >
                          <div className="flex items-center gap-2 mb-2">
                            <div
                              className="w-4 h-4 rounded-full shrink-0 border"
                              style={{ backgroundColor: zone.color }}
                            />
                            <span className="font-semibold text-sm flex-1 truncate">
                              {zone.name}
                            </span>
                            {!zone.is_active && (
                              <EyeOff className="w-3 h-3 text-muted-foreground" />
                            )}
                          </div>
                          <div className="flex items-center justify-between gap-2 flex-wrap">
                            <div className="flex items-center gap-2">
                              <Badge
                                variant="outline"
                                className="text-xs font-mono"
                                style={{
                                  borderColor: zone.color,
                                  color: zone.color,
                                }}
                              >
                                {zone.fee} RON
                              </Badge>
                              <Badge variant="secondary">Zona {zone.zone_level || 1}</Badge>
                            </div>
                            <div className="flex gap-1">
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleEditZone(zone);
                                }}
                                data-testid={`edit-zone-${zone.id}`}
                              >
                                <Pencil className="w-3 h-3" />
                              </Button>
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-7 w-7 text-red-500 hover:text-red-700"
                                onClick={(e) => {
                                  e.stopPropagation();
                                  handleDeleteZone(zone.id);
                                }}
                                data-testid={`delete-zone-${zone.id}`}
                              >
                                <Trash2 className="w-3 h-3" />
                              </Button>
                            </div>
                          </div>
                        </div>
                      ))}
                  </div>
                ))
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* Edit/Create Zone Dialog */}
      <Dialog open={editDialog} onOpenChange={setEditDialog}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>
              {selectedZone ? "Editează Zona" : "Zonă Nouă"}
            </DialogTitle>
            <DialogDescription>
              Configurează sectorul, nivelul și conturul zonei de livrare.
            </DialogDescription>
          </DialogHeader>
          <div className="space-y-4">
            <div>
              <Label>Sector *</Label>
              <Input
                value={editForm.sector}
                onChange={(e) =>
                  setEditForm({
                    ...editForm,
                    sector: e.target.value,
                    name: `${e.target.value || "Sector"} - Zona ${editForm.zone_level}`,
                  })
                }
                placeholder="ex: Nord / Centru / Sud"
                data-testid="zone-sector-input"
              />
            </div>
            <div>
              <Label>Nume Zonă *</Label>
              <Input
                value={editForm.name}
                onChange={(e) =>
                  setEditForm({ ...editForm, name: e.target.value })
                }
                placeholder="ex: Zona 1 - Centru"
                data-testid="zone-name-input"
              />
            </div>
            <div>
              <Label>Nivel Zonă *</Label>
              <div className="grid grid-cols-3 gap-2 mt-2" data-testid="zone-level-grid">
                {[1, 2, 3].map((level) => (
                  <Button
                    key={level}
                    type="button"
                    variant={editForm.zone_level === level ? "default" : "outline"}
                    className="justify-between"
                    onClick={() => updateZoneLevel(level)}
                    data-testid={`zone-level-${level}`}
                  >
                    <span>Zona {level}</span>
                    <span>{FIXED_ZONE_FEES[level]} lei</span>
                  </Button>
                ))}
              </div>
            </div>
            <div>
              <Label>Taxă Livrare (fixă)</Label>
              <Input type="number" value={editForm.fee} readOnly data-testid="zone-fee-input" />
              <p className="text-xs text-muted-foreground mt-1">
                Tariful se aplică automat după nivel: 14 / 22 / 33 lei.
              </p>
            </div>
            <div>
              <Label>Culoare</Label>
              <div className="flex gap-2 mt-1 flex-wrap">
                {ZONE_COLORS.map((c) => (
                  <button
                    key={c}
                    className={`w-8 h-8 rounded-full border-2 transition-transform ${
                      editForm.color === c
                        ? "border-foreground scale-110"
                        : "border-transparent"
                    }`}
                    style={{ backgroundColor: c }}
                    onClick={() => setEditForm({ ...editForm, color: c })}
                    data-testid={`color-${c}`}
                  />
                ))}
              </div>
            </div>
            <div className="rounded-lg border border-dashed p-3 bg-muted/30">
              <p className="text-sm font-medium mb-1">Contur zonă</p>
              <p className="text-xs text-muted-foreground mb-3">
                {newPolygon
                  ? `Contur nou pregătit cu ${newPolygon.length} puncte.`
                  : selectedZone
                    ? `Folosești conturul curent al zonei ${selectedZone.name}.`
                    : "Desenează zona pe hartă, apoi completează datele."}
              </p>
              <Button type="button" variant="outline" onClick={startRedraw} data-testid="dialog-redraw-zone-btn">
                <Pencil className="w-4 h-4 mr-2" />
                {selectedZone ? "Redesenează conturul" : "Desenează conturul"}
              </Button>
            </div>
            <div className="flex items-center justify-between">
              <Label>Zonă Activă</Label>
              <Switch
                checked={editForm.is_active}
                onCheckedChange={(v) =>
                  setEditForm({ ...editForm, is_active: v })
                }
                data-testid="zone-active-switch"
              />
            </div>
          </div>
          <DialogFooter>
            <Button
              variant="outline"
              onClick={() => {
                setEditDialog(false);
                setNewPolygon(null);
                setRedrawMode(false);
              }}
            >
              Anulează
            </Button>
            <Button onClick={handleSaveZone} data-testid="save-zone-btn">
              <Save className="w-4 h-4 mr-1" />
              {selectedZone ? "Salvează" : "Creează Zona"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}

export { ZonePolygons };
