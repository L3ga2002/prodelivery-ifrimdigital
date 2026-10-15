import { Button } from "../ui/button";
import { preparationApplied, preparationFailureMessage, preparationTerminal } from "../../lib/orderPreparationRecovery";

export const PreparationRecoveryPanel = ({ recovery, isOnline, onAcknowledged }) => {
  const { record, busy, error, storageInvalid, sessionSuspended, checkingSession } = recovery;
  if (!record && !error && !busy && !sessionSuspended) return null;
  const receipt = record?.receipt;
  const disabled = busy || sessionSuspended || storageInvalid || !recovery.durableAvailable;
  return <section className="my-3 space-y-2 break-words rounded-xl border border-orange-500/30 bg-orange-500/5 p-3 text-sm" data-testid="preparation-recovery-panel">
    <h2 className="font-bold">{record?.action === "ready" ? "Confirmarea comenzii gata" : "Confirmarea pregătirii"}</h2>
    {error && <p role="alert" data-testid="preparation-recovery-error">{error}</p>}
    {busy && <p role="status">Se verifică încercarea curentă…</p>}
    {sessionSuspended && <p role="status">{checkingSession ? "Se verifică sesiunea…" : "Reverifică sesiunea pentru a continua. Încercarea este păstrată."}</p>}
    {record && <div role="status" data-testid="preparation-recovery-state">
      <p>Comanda {record.order_id}{record.action === "preparing" ? ` · ${record.preparation_time} minute` : " · Gata"}</p>
      <p>{preparationApplied(receipt) ? "Încercarea este confirmată de server." : receipt?.state === "rejected" ? preparationFailureMessage(receipt.error_code) :
        recovery.notAdmitted ? "Serverul nu a găsit încă această încercare. O poți retrimite explicit, cu aceleași date." : "Rezultat neconfirmat. Încercarea inițială rămâne păstrată."}</p>
    </div>}
    {record && !recovery.durableAvailable && <p role="alert">Acest browser nu poate proteja recuperarea între taburi. Încercarea rămâne păstrată.</p>}
    <div className="flex flex-wrap gap-2">
      {sessionSuspended && <Button variant="outline" onClick={recovery.revalidateSession} disabled={!isOnline || checkingSession || !recovery.available} data-testid="preparation-session-button">Reverifică sesiunea</Button>}
      {record && !preparationTerminal(receipt) && <Button variant="outline" className="h-auto min-h-9 whitespace-normal" onClick={recovery.recover} disabled={disabled || !isOnline} data-testid="preparation-verify-button">Verifică aceeași încercare</Button>}
      {record && recovery.notAdmitted && !receipt && <Button variant="outline" className="h-auto min-h-9 whitespace-normal" onClick={recovery.resend} disabled={disabled || !isOnline} data-testid="preparation-resend-button">Retrimite aceeași încercare</Button>}
      {receipt?.state === "pending" && <Button variant="outline" onClick={recovery.resume} disabled={disabled || !isOnline} data-testid="preparation-resume-button">Continuă încercarea</Button>}
      {preparationTerminal(receipt) && <Button className="h-auto min-h-9 whitespace-normal" onClick={async () => {
        const lease = recovery.captureLease();
        const fresh = await recovery.acknowledge();
        if (fresh && recovery.isCurrentLease(lease)) onAcknowledged?.(fresh);
      }} disabled={disabled || !isOnline} data-testid="preparation-acknowledge-button">Am văzut rezultatul</Button>}
      {!record && error && !sessionSuspended && <Button variant="outline" onClick={recovery.chooseProtocol} disabled={busy || storageInvalid || !isOnline || !recovery.available} data-testid="preparation-capability-button">Verifică disponibilitatea</Button>}
    </div>
  </section>;
};
