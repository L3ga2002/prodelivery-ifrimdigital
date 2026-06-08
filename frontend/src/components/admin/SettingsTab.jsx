import { toast } from "sonner";
import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Input } from "../ui/input";
import { Switch } from "../ui/switch";
import { MapPin, Settings, Timer } from "lucide-react";

export const SettingsTab = ({ settings, onSettingsChange }) => (
  <Card>
    <CardHeader>
      <CardTitle className="flex items-center gap-2">
        <Settings className="h-5 w-5" />
        Setări Sistem
      </CardTitle>
    </CardHeader>
    <CardContent className="space-y-6">
      <div className="flex items-center justify-between rounded-lg border p-4">
        <div>
          <h4 className="font-bold">Alocare Automată</h4>
          <p className="text-sm text-muted-foreground">Sistemul alocă automat comenzile către cel mai apropiat livrator</p>
        </div>
        <div className="flex items-center gap-3">
          <span className={settings.autoAssign ? "text-green-600" : "text-muted-foreground"}>{settings.autoAssign ? "ACTIV" : "INACTIV"}</span>
          <Switch checked={settings.autoAssign} onCheckedChange={(checked) => onSettingsChange({ ...settings, autoAssign: checked })} data-testid="settings-auto-assign-switch" />
        </div>
      </div>

      <div className="rounded-lg border p-4">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h4 className="flex items-center gap-2 font-bold"><Timer className="h-4 w-4" />Timeout Acceptare</h4>
            <p className="text-sm text-muted-foreground">Timp de așteptare până la reatribuire automată</p>
          </div>
          <Badge variant="outline" className="text-lg">{settings.timeout} secunde</Badge>
        </div>
        <div className="flex items-center gap-2">
          <Input type="number" value={settings.timeout} onChange={(event) => onSettingsChange({ ...settings, timeout: parseInt(event.target.value, 10) || 60 })} className="w-24" disabled={!settings.autoAssign} data-testid="settings-timeout-input" />
          <span className="text-muted-foreground">secunde</span>
          {!settings.autoAssign && <span className="ml-4 text-sm text-orange-600">(Activează alocarea automată pentru a folosi timeout)</span>}
        </div>
      </div>

      <div className="rounded-lg border p-4">
        <div className="mb-3 flex items-center justify-between">
          <div>
            <h4 className="flex items-center gap-2 font-bold"><MapPin className="h-4 w-4" />Rază Maximă Alocare</h4>
            <p className="text-sm text-muted-foreground">Distanța maximă între livrator și restaurant</p>
          </div>
          <Badge variant="outline" className="text-lg">{settings.maxRadius} km</Badge>
        </div>
        <div className="flex items-center gap-2">
          <Input type="number" value={settings.maxRadius} onChange={(event) => onSettingsChange({ ...settings, maxRadius: parseFloat(event.target.value) || 5 })} className="w-24" data-testid="settings-max-radius-input" />
          <span className="text-muted-foreground">kilometri</span>
        </div>
      </div>

      <Button className="w-full" onClick={() => toast.success("Setări salvate (demo)")} data-testid="settings-save-button">Salvează Setările</Button>
      <div className="rounded-lg border border-yellow-200 bg-yellow-50 p-4 dark:border-yellow-900 dark:bg-yellow-950/30">
        <p className="text-sm text-yellow-800 dark:text-yellow-100"><strong>⚠️ Mod Demo:</strong> Setările sunt afișate pentru demonstrație. Funcționalitatea completă va fi activată în fazele următoare.</p>
      </div>
    </CardContent>
  </Card>
);
