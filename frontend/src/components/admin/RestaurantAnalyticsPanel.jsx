import { Badge } from "../ui/badge";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
import { Bar, BarChart, CartesianGrid, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { BarChart3, CalendarCheck, Clock, Loader2, Package, Timer, TrendingUp, Truck } from "lucide-react";

const getOrderStatusBadge = (status) => {
  const config = {
    NEW: { label: "Nou", className: "bg-yellow-100 text-yellow-800 dark:bg-yellow-950/40 dark:text-yellow-100" },
    PREPARING: { label: "Preparare", className: "bg-blue-100 text-blue-800 dark:bg-blue-950/40 dark:text-blue-100" },
    READY: { label: "Gata", className: "bg-green-100 text-green-800 dark:bg-green-950/40 dark:text-green-100" },
    ASSIGNED: { label: "Alocat", className: "bg-purple-100 text-purple-800 dark:bg-purple-950/40 dark:text-purple-100" },
    ACCEPTED: { label: "Acceptat", className: "bg-indigo-100 text-indigo-800 dark:bg-indigo-950/40 dark:text-indigo-100" },
    PICKED_UP: { label: "Ridicat", className: "bg-orange-100 text-orange-800 dark:bg-orange-950/40 dark:text-orange-100" },
    DELIVERED: { label: "Livrat", className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100" },
    CANCELLED: { label: "Anulat", className: "bg-red-100 text-red-800 dark:bg-red-950/40 dark:text-red-100" },
  };
  const item = config[status] || { label: status, className: "bg-gray-100 text-gray-800 dark:bg-slate-800 dark:text-slate-100" };
  return <Badge className={`${item.className} border-0`}>{item.label}</Badge>;
};

const MetricTile = ({ label, value, icon: Icon, tone = "blue", testId }) => {
  const toneClasses = {
    blue: "border-blue-500/40 bg-blue-500/15 text-blue-100",
    green: "border-emerald-500/40 bg-emerald-500/15 text-emerald-100",
    amber: "border-orange-500/40 bg-orange-500/15 text-orange-100",
    slate: "border-slate-600 bg-slate-800 text-slate-100",
  };

  return (
    <div className={`rounded-lg border p-4 ${toneClasses[tone]}`} data-testid={testId}>
      <div className="flex items-center justify-between gap-3">
        <div>
          <p className="text-xs uppercase tracking-wide opacity-75">{label}</p>
          <p className="mt-1 text-2xl font-bold">{value}</p>
        </div>
        {Icon && <Icon className="h-6 w-6 opacity-80" />}
      </div>
    </div>
  );
};

const RestaurantChartCard = ({ title, icon: Icon, data, color = "hsl(215 75% 22%)", testId, interval }) => (
  <Card className="border-zinc-800 bg-zinc-950 text-zinc-50 shadow-sm transition-transform hover:-translate-y-0.5 hover:shadow-md" data-testid={testId}>
    <CardHeader className="pb-2">
      <CardTitle className="flex items-center gap-2 text-base">
        {Icon && <Icon className="h-5 w-5 text-orange-400" />}
        {title}
      </CardTitle>
    </CardHeader>
    <CardContent>
      <ResponsiveContainer width="100%" height={220}>
        <BarChart data={data || []}>
          <CartesianGrid strokeDasharray="3 3" stroke="rgba(255,255,255,.22)" />
          <XAxis dataKey="label" tick={{ fontSize: 10, fill: "#d4d4d8" }} interval={interval} />
          <YAxis tick={{ fontSize: 11, fill: "#d4d4d8" }} />
          <Tooltip contentStyle={{ borderRadius: "8px", fontSize: "13px", background: "#18181b", border: "1px solid #3f3f46", color: "#fafafa" }} />
          <Bar dataKey="count" name="Comenzi" fill={color} radius={[4, 4, 0, 0]} />
        </BarChart>
      </ResponsiveContainer>
    </CardContent>
  </Card>
);

export const RestaurantAnalyticsPanel = ({ analytics, isLoading }) => {
  if (isLoading && !analytics) {
    return (
      <Card className="min-h-[620px] border-slate-200 shadow-sm" data-testid="restaurant-analytics-loading">
        <CardContent className="grid min-h-[620px] place-items-center p-6">
          <div className="space-y-3 text-center text-sm text-muted-foreground">
            <Loader2 className="mx-auto h-6 w-6 animate-spin text-slate-600" />
            <p>Se încarcă analytics...</p>
          </div>
        </CardContent>
      </Card>
    );
  }
  if (!analytics) return null;

  const summary = analytics.summary || {};
  const charts = analytics.charts || {};
  const recentOrders = analytics.recent_orders || [];

  return (
    <div className="relative space-y-4 transition-opacity duration-200" data-testid="restaurant-analytics-panel">
      {isLoading && (
        <div className="pointer-events-none absolute right-3 top-3 z-10 rounded-full border border-slate-200 bg-white/95 px-3 py-1 text-xs font-medium text-slate-600 shadow-sm dark:border-slate-800 dark:bg-slate-950/95 dark:text-slate-200" data-testid="restaurant-analytics-refresh-indicator">
          Actualizez discret...
        </div>
      )}
      <div className="grid gap-3 md:grid-cols-4">
        <MetricTile label="Comenzi total" value={summary.total_orders || 0} icon={Package} tone="slate" testId="restaurant-analytics-total-orders" />
        <MetricTile label="Prep. mediu" value={`${summary.avg_preparation_actual_minutes || 0} min`} icon={Timer} tone="blue" testId="restaurant-analytics-average-prep" />
        <MetricTile label="Întârziere medie" value={`${summary.avg_preparation_delay_minutes || 0} min`} icon={Clock} tone="amber" testId="restaurant-analytics-average-delay" />
        <MetricTile label="Livrare medie" value={`${summary.avg_delivery_minutes || 0} min`} icon={Truck} tone="green" testId="restaurant-analytics-average-delivery" />
      </div>

      <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-3">
        <RestaurantChartCard title="Comenzi pe ore" icon={BarChart3} data={charts.by_hour || []} testId="restaurant-chart-hour" interval={2} />
        <RestaurantChartCard title="Comenzi pe zile" icon={CalendarCheck} data={charts.by_day || []} color="hsl(158 64% 36%)" testId="restaurant-chart-day" />
        <RestaurantChartCard title="Comenzi pe săptămâni" icon={TrendingUp} data={charts.by_week || []} color="hsl(217 33% 35%)" testId="restaurant-chart-week" />
        <RestaurantChartCard title="Comenzi pe luni" icon={TrendingUp} data={charts.by_month || []} color="hsl(24 90% 50%)" testId="restaurant-chart-month" />
        <RestaurantChartCard title="Comenzi pe ani" icon={BarChart3} data={charts.by_year || []} color="hsl(220 14% 46%)" testId="restaurant-chart-year" />
        <Card className="border-orange-500/30 bg-[radial-gradient(circle_at_top_left,rgba(249,115,22,.24),transparent_32%),#09090b] text-white shadow-sm" data-testid="restaurant-analytics-insight-card">
          <CardContent className="flex h-full min-h-[220px] flex-col justify-between p-5">
            <div>
              <p className="text-xs font-semibold uppercase tracking-wide text-slate-400">Insight operațional</p>
              <p className="mt-3 text-3xl font-bold">{summary.avg_preparation_delay_minutes || 0} min</p>
              <p className="mt-1 text-sm text-slate-300">întârziere medie restaurant</p>
            </div>
            <p className="text-sm text-slate-300">Datele se actualizează din comenzile reale și ajută la discuții clare cu restaurantul.</p>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader>
          <CardTitle className="text-base">Istoric comenzi restaurant</CardTitle>
          <p className="text-sm text-muted-foreground">Timp estimat, timp real și întârziere sunt calculate automat din fluxul comenzilor.</p>
        </CardHeader>
        <CardContent className="p-0">
          <Table>
            <TableHeader>
              <TableRow>
                <TableHead>Nr.</TableHead>
                <TableHead>Status</TableHead>
                <TableHead>Total</TableHead>
                <TableHead>Prep. estimat</TableHead>
                <TableHead>Prep. real</TableHead>
                <TableHead>Întârziere</TableHead>
                <TableHead>Livrare</TableHead>
              </TableRow>
            </TableHeader>
            <TableBody>
              {recentOrders.slice(0, 12).map((order) => (
                <TableRow key={order.id} data-testid={`restaurant-analytics-order-${order.id}`}>
                  <TableCell className="font-mono text-xs">{order.order_number}</TableCell>
                  <TableCell>{getOrderStatusBadge(order.status)}</TableCell>
                  <TableCell>{order.total_amount} RON</TableCell>
                  <TableCell>{order.preparation_time ? `${order.preparation_time} min` : "-"}</TableCell>
                  <TableCell>{order.preparation_actual_minutes != null ? `${order.preparation_actual_minutes} min` : "-"}</TableCell>
                  <TableCell>{order.preparation_delay_minutes != null ? `${order.preparation_delay_minutes} min` : "-"}</TableCell>
                  <TableCell>{order.delivery_minutes != null ? `${order.delivery_minutes} min` : "-"}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </CardContent>
      </Card>
    </div>
  );
};
