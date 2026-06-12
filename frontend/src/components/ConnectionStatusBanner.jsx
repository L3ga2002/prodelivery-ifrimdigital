import { WifiOff } from "lucide-react";
import { useNetworkStatus } from "../hooks/useNetworkStatus";

export const ConnectionStatusBanner = () => {
  const { hasConnectionProblem, message } = useNetworkStatus();

  if (!hasConnectionProblem) return null;

  return (
    <div
      className="fixed inset-x-0 top-0 z-[1000] border-b border-amber-300 bg-amber-50 px-4 py-2 text-center text-sm font-semibold text-amber-950 shadow-sm dark:border-amber-800 dark:bg-amber-950 dark:text-amber-100"
      data-testid="connection-status-banner"
    >
      <span className="inline-flex items-center justify-center gap-2">
        <WifiOff className="h-4 w-4" />
        {message || "Conexiune instabilă. Verifică rețeaua și încearcă din nou."}
      </span>
    </div>
  );
};
