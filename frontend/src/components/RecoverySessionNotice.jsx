import { Button } from "./ui/button";
import { RefreshCw } from "lucide-react";

export const RecoverySessionNotice = ({ recovery, isOnline }) => recovery.sessionSuspended ?
  <div className="space-y-2 break-words text-sm" data-testid="recovery-session-notice">
    <p role="status">{recovery.checkingSession ? "Sesiunea se verifica. Intentia ramane pastrata." : "Reverifica sesiunea pentru a continua. Intentia ramane pastrata."}</p>
    <Button variant="outline" className="h-auto min-h-9 max-w-full whitespace-normal" onClick={recovery.revalidateSession} disabled={!isOnline || recovery.checkingSession} data-testid="recovery-session-button">
      <RefreshCw className="mr-2 h-4 w-4" />Reverifica sesiunea
    </Button>
  </div> : null;
