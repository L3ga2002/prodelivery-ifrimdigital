import { Badge } from "../ui/badge";
import { Button } from "../ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "../ui/card";
import { Plus, Store } from "lucide-react";
import { RestaurantZonesManager } from "../RestaurantZonesManager";
import { RestaurantAnalyticsPanel } from "./RestaurantAnalyticsPanel";

export const RestaurantsTab = ({
  restaurants,
  selectedRestaurant,
  activeOrders,
  orders,
  onSelectRestaurant,
  restaurantAnalytics,
  restaurantAnalyticsLoading,
  onNewRestaurant,
}) => (
  <div className="space-y-4">
    <Card className="control-surface overflow-hidden">
      <CardHeader className="border-b bg-slate-50/70 dark:bg-slate-900/50">
        <div className="flex flex-wrap items-center justify-between gap-3">
          <div>
            <CardTitle className="flex items-center gap-2 text-lg">
              <Store className="h-5 w-5 text-orange-600" />
              Restaurante operaționale
            </CardTitle>
            <p className="mt-1 text-sm text-muted-foreground">Alege restaurantul pentru performanță, zone și coordonate.</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Badge variant="outline" className="border-slate-300 bg-white dark:bg-slate-950" data-testid="restaurants-panel-count">
              {restaurants.length} restaurante
            </Badge>
            <Button type="button" size="sm" onClick={onNewRestaurant} data-testid="restaurants-add-restaurant-button">
              <Plus className="mr-1 h-4 w-4" />
              Adaugă restaurant
            </Button>
          </div>
        </div>
      </CardHeader>
      <CardContent className="p-4">
        <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
          {restaurants.map((restaurant) => {
            const isSelected = selectedRestaurant?.id === restaurant.id;
            const activeForRestaurant = activeOrders.filter((order) => order.restaurant_id === restaurant.id).length;
            const totalForRestaurant = orders.filter((order) => order.restaurant_id === restaurant.id).length;
            return (
              <button
                key={restaurant.id}
                type="button"
                onClick={() => onSelectRestaurant(restaurant.id)}
                className={`premium-card relative overflow-hidden rounded-lg border p-4 text-left ${isSelected ? "border-indigo-300 bg-indigo-50/60 ring-2 ring-indigo-100 dark:border-indigo-800 dark:bg-indigo-950/20 dark:ring-indigo-950" : "bg-card hover:border-slate-300 hover:bg-slate-50/70 dark:hover:bg-slate-900/60"}`}
                data-testid={`restaurant-card-${restaurant.id}`}
              >
                <div className="absolute right-3 top-3 rounded-full border bg-white/80 px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide text-slate-500 dark:bg-slate-950/80">
                  {isSelected ? "activ" : "profil"}
                </div>
                <div className="mb-3 flex items-center gap-3 pr-14">
                  <div className="rounded-lg bg-orange-50 p-2 text-orange-600 dark:bg-orange-950/30">
                    <Store className="h-6 w-6" />
                  </div>
                  <div className="min-w-0">
                    <p className="truncate font-bold">{restaurant.name}</p>
                    <p className="text-xs text-muted-foreground">{activeForRestaurant} active · {totalForRestaurant} total</p>
                  </div>
                </div>
                <p className="line-clamp-2 text-sm text-muted-foreground">{restaurant.address}</p>
                <p className="mt-2 text-sm font-medium font-mono">{restaurant.phone}</p>
                {restaurant.email && <p className="mt-1 text-xs text-muted-foreground">{restaurant.email}</p>}
                <Badge className={`mt-3 ${isSelected ? "bg-indigo-700 text-white" : ""}`} variant={isSelected ? "default" : "outline"}>
                  {isSelected ? "Selectat" : "Alege pentru zone"}
                </Badge>
              </button>
            );
          })}
        </div>
      </CardContent>
    </Card>

    <RestaurantAnalyticsPanel analytics={restaurantAnalytics} isLoading={restaurantAnalyticsLoading} />
    <RestaurantZonesManager restaurant={selectedRestaurant} />
  </div>
);
