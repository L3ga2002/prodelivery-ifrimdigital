import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "../ui/table";
import { Package } from "lucide-react";

const getStatusBadge = (status) => {
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

const getSourceBadge = (source) => {
  const config = {
    S: { label: "Site", className: "bg-orange-100 text-orange-800 dark:bg-orange-950/40 dark:text-orange-100" },
    B: { label: "Bolt", className: "bg-blue-100 text-blue-800 dark:bg-blue-950/40 dark:text-blue-100" },
    W: { label: "Wolt", className: "bg-cyan-100 text-cyan-800 dark:bg-cyan-950/40 dark:text-cyan-100" },
    G: { label: "Glovo", className: "bg-emerald-100 text-emerald-800 dark:bg-emerald-950/40 dark:text-emerald-100" },
  };
  const item = config[source] || { label: source || "Necunoscut", className: "bg-slate-100 text-slate-700 dark:bg-slate-800 dark:text-slate-100" };
  return <Badge className={`${item.className} border-0`} data-testid={`order-source-badge-${source || "unknown"}`}>{item.label}</Badge>;
};

export const OrdersTab = ({ activeOrders, onAssignOrder }) => (
  <Card className="control-surface overflow-hidden" data-testid="admin-orders-control-surface">
    <CardHeader className="border-b bg-slate-50/70 pb-4 dark:bg-slate-900/50">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <CardTitle className="flex items-center gap-2 text-lg">
            <Package className="h-5 w-5 text-indigo-600 dark:text-indigo-300" />
            Comenzi active în dispecerat
          </CardTitle>
          <p className="mt-1 text-sm text-muted-foreground">Prioritizare rapidă pentru pregătire, alocare și urmărire.</p>
        </div>
        <Badge variant="outline" className="border-indigo-200 bg-indigo-50 text-indigo-700 dark:border-indigo-900 dark:bg-indigo-950/30 dark:text-indigo-100" data-testid="admin-orders-active-count">
          {activeOrders.length} active
        </Badge>
      </div>
    </CardHeader>
    <CardContent className="p-0">
      <div className="grid gap-3 p-3 md:hidden" data-testid="admin-orders-mobile-list">
        {activeOrders.length === 0 ? (
          <div className="rounded-lg border border-dashed p-6 text-center text-sm text-muted-foreground" data-testid="admin-orders-mobile-empty">
            Nu există comenzi active
          </div>
        ) : activeOrders.map((order) => (
          <article key={order.id} className="rounded-xl border bg-card p-3 shadow-sm" data-testid={`admin-order-mobile-card-${order.id}`}>
            <div className="flex items-start justify-between gap-3">
              <div className="min-w-0">
                <p className="font-mono text-xs font-black text-slate-600 dark:text-slate-200">{order.order_number}</p>
                <h3 className="truncate text-base font-bold">{order.restaurant_name}</h3>
              </div>
              {getSourceBadge(order.source)}
            </div>
            <div className="mt-3 grid gap-2 text-sm">
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Client</span>
                <span className="truncate font-semibold">{order.customer_name}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Telefon</span>
                <span className="font-mono">{order.customer_phone}</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Sumă</span>
                <span className="font-black">{order.total_amount} RON</span>
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Status</span>
                {getStatusBadge(order.status)}
              </div>
              <div className="flex items-center justify-between gap-3">
                <span className="text-muted-foreground">Livrator</span>
                <span className="truncate font-medium">{order.driver_name || "-"}</span>
              </div>
            </div>
            {["NEW", "PREPARING", "READY"].includes(order.status) && (
              <Button size="sm" className="mt-3 w-full bg-indigo-700 hover:bg-indigo-600" onClick={() => onAssignOrder(order)} data-testid={`admin-order-mobile-assign-button-${order.id}`}>
                Alocă livrator
              </Button>
            )}
          </article>
        ))}
      </div>
      <div className="hidden overflow-x-auto md:block" data-testid="admin-orders-table-wrapper">
      <Table className="min-w-[920px]">
        <TableHeader>
          <TableRow className="bg-muted/40 hover:bg-muted/40">
            <TableHead className="w-[100px]">Nr.</TableHead>
            <TableHead>Sursă</TableHead>
            <TableHead>Restaurant</TableHead>
            <TableHead>Client</TableHead>
            <TableHead>Sumă</TableHead>
            <TableHead>Status</TableHead>
            <TableHead>Livrator</TableHead>
            <TableHead className="text-right">Acțiuni</TableHead>
          </TableRow>
        </TableHeader>
        <TableBody>
          {activeOrders.length === 0 ? (
            <TableRow>
              <TableCell colSpan={8} className="py-8 text-center text-muted-foreground">
                Nu există comenzi active
              </TableCell>
            </TableRow>
          ) : (
            activeOrders.map((order) => (
              <TableRow key={order.id} className="group border-l-4 border-l-transparent transition-colors hover:border-l-indigo-500 hover:bg-slate-50/80 dark:hover:bg-slate-900/60" data-testid={`admin-order-row-${order.id}`}>
                <TableCell className="font-mono text-xs font-semibold text-slate-700 dark:text-slate-100">{order.order_number}</TableCell>
                <TableCell>{getSourceBadge(order.source)}</TableCell>
                <TableCell className="font-medium">{order.restaurant_name}</TableCell>
                <TableCell>
                  <div>
                    <p className="text-sm font-medium">{order.customer_name}</p>
                    <p className="text-xs text-muted-foreground">{order.customer_phone}</p>
                  </div>
                </TableCell>
                <TableCell>
                  <span className="font-semibold">{order.total_amount} RON</span>
                  <Badge variant="outline" className="ml-2 text-xs">{order.payment_type}</Badge>
                </TableCell>
                <TableCell>{getStatusBadge(order.status)}</TableCell>
                <TableCell>{order.driver_name || "-"}</TableCell>
                <TableCell className="text-right">
                  {["NEW", "PREPARING", "READY"].includes(order.status) && (
                    <Button size="sm" className="bg-indigo-700 hover:bg-indigo-600" onClick={() => onAssignOrder(order)} data-testid={`admin-order-assign-button-${order.id}`}>
                      Alocă
                    </Button>
                  )}
                </TableCell>
              </TableRow>
            ))
          )}
        </TableBody>
      </Table>
      </div>
    </CardContent>
  </Card>
);
