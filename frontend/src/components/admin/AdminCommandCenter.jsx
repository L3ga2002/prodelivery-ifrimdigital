import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent } from "../ui/card";
import { Clock, Loader2, Package, Play, Plus, Store, UserCheck, XCircle } from "lucide-react";

const AdminStatCard = ({ icon: Icon, label, value, tone = "slate", testId }) => {
  const toneClasses = {
    slate: "border-slate-200 bg-white text-slate-900 dark:border-slate-800 dark:bg-slate-950",
    blue: "border-blue-200 bg-blue-50/80 text-blue-900 dark:border-blue-900 dark:bg-blue-950/20 dark:text-blue-100",
    green: "border-emerald-200 bg-emerald-50/80 text-emerald-900 dark:border-emerald-900 dark:bg-emerald-950/20 dark:text-emerald-100",
    amber: "border-amber-200 bg-amber-50/80 text-amber-900 dark:border-amber-900 dark:bg-amber-950/20 dark:text-amber-100",
    orange: "border-orange-200 bg-orange-50/80 text-orange-900 dark:border-orange-900 dark:bg-orange-950/20 dark:text-orange-100",
    red: "border-red-200 bg-red-50/80 text-red-900 dark:border-red-900 dark:bg-red-950/20 dark:text-red-100",
  };

  return (
    <Card className={`overflow-hidden transition-transform hover:-translate-y-0.5 hover:shadow-md ${toneClasses[tone]}`} data-testid={testId}>
      <CardContent className="p-4">
        <div className="flex items-center justify-between gap-3">
          <div>
            <p className="text-xs font-semibold uppercase tracking-wide opacity-70">{label}</p>
            <p className="mt-1 text-3xl font-bold tracking-tight">{value}</p>
          </div>
          <div className="rounded-lg bg-white/70 p-2 shadow-sm dark:bg-slate-900/70">
            <Icon className="h-6 w-6 opacity-80" />
          </div>
        </div>
      </CardContent>
    </Card>
  );
};

export const AdminCommandCenter = ({
  stats,
  activeDriversCount,
  restaurantsCount,
  isSimRunning,
  actionsDisabled = false,
  onRunSimulation,
  onNewOrder,
}) => (
  <>
    <section className="mb-5 overflow-hidden rounded-xl border border-slate-200 bg-slate-950 text-white shadow-sm lg:mb-6" data-testid="admin-command-center-hero">
      <div className="grid gap-4 p-4 sm:p-5 lg:grid-cols-[1.5fr_1fr] lg:p-6">
        <div>
          <Badge className="mb-3 border-white/20 bg-white/10 text-white hover:bg-white/10">Control Room · Bacău</Badge>
          <h2 className="text-2xl font-bold tracking-tight sm:text-3xl">Operațiuni live, restaurante și program într-un singur panou.</h2>
          <p className="mt-2 max-w-2xl text-sm text-slate-300">
            Fluxul este construit pentru dispecerat: comenzi active, timp de preparare, zone per restaurant și sloturi normale generate rapid.
          </p>
        </div>
        <div className="grid grid-cols-3 gap-2 text-center sm:gap-3">
          <div className="rounded-lg border border-white/10 bg-white/10 p-3" data-testid="hero-active-orders">
            <p className="text-2xl font-bold">{stats.active_orders || 0}</p>
            <p className="text-xs text-slate-300">active</p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/10 p-3" data-testid="hero-active-drivers">
            <p className="text-2xl font-bold">{activeDriversCount}</p>
            <p className="text-xs text-slate-300">livratori</p>
          </div>
          <div className="rounded-lg border border-white/10 bg-white/10 p-3" data-testid="hero-restaurants">
            <p className="text-2xl font-bold">{restaurantsCount}</p>
            <p className="text-xs text-slate-300">restaurante</p>
          </div>
        </div>
      </div>
    </section>

    <div className="mb-5 grid grid-cols-2 gap-3 md:grid-cols-3 lg:gap-4 xl:grid-cols-6">
      <AdminStatCard icon={Package} label="Active" value={stats.active_orders || 0} tone="amber" testId="admin-stat-active-orders" />
      <AdminStatCard icon={Clock} label="Total" value={stats.total_orders || 0} tone="blue" testId="admin-stat-total-orders" />
      <AdminStatCard icon={UserCheck} label="Livratori" value={stats.active_drivers || 0} tone="green" testId="admin-stat-active-drivers" />
      <AdminStatCard icon={Store} label="Restaurante" value={stats.total_restaurants || 0} tone="orange" testId="admin-stat-restaurants" />
      <AdminStatCard icon={Package} label="Livrate" value={stats.delivered_orders || 0} tone="green" testId="admin-stat-delivered" />
      <AdminStatCard icon={XCircle} label="Anulate" value={stats.cancelled_orders || 0} tone="red" testId="admin-stat-cancelled" />
    </div>

    <div className="mb-5 flex flex-wrap gap-2">
      <Button
        onClick={onRunSimulation}
        disabled={isSimRunning || actionsDisabled}
        className="gap-2 shadow-lg"
        style={{ background: "linear-gradient(135deg, hsl(24 95% 53%), hsl(24 95% 45%))", color: "white" }}
        data-testid="simulate-demo-btn"
      >
        {isSimRunning ? <Loader2 className="w-4 h-4 animate-spin" /> : <Play className="w-4 h-4" />}
        {isSimRunning ? "Simulare în curs..." : "Simulare Demo"}
      </Button>
      <Button onClick={onNewOrder} disabled={actionsDisabled} data-testid="new-order-btn">
        <Plus className="w-4 h-4 mr-2" />
        Comandă Nouă
      </Button>
    </div>
  </>
);
