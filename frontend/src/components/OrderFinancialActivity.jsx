import { Button } from "./ui/button";
import { formatBani } from "../lib/orderFinance";
import { financialEventEligibility, readFinancialActivity } from "../lib/orderFinancialActivity";
import { financialEventApplied, financialEventTerminal, financialEventFailureMessage } from "../lib/orderFinancialEventRecovery";

export const OrderFinancialActivitySummary = ({ order }) => {
  const activity = readFinancialActivity(order);
  if (activity.state === "none") return null;
  if (activity.state === "invalid") return <p role="alert" data-testid="financial-activity-invalid">Evidența numerarului necesită verificare. Ridicarea este blocată până la reîncărcare.</p>;
  const value = activity.value;
  return <section className="mt-3 min-w-0 space-y-2 rounded-lg border border-amber-500/30 p-3 text-sm" aria-label="Numerar insuficient" data-testid="financial-activity-summary">
    <p className="font-bold">{value.status === "declared" ? "Lipsă numerar declarată — așteaptă aprobarea restaurantului" :
      value.status === "approved" ? "Restaurantul a aprobat ridicarea fără plată" : "Restanță după ridicarea fără plată"}</p>
    <p>Avans neachitat declarat: <strong>{formatBani(value.declared_unpaid_bani)}</strong></p>
    {value.status === "outstanding" && <><p>Restanță: <strong>{formatBani(value.outstanding_bani)}</strong></p>
      <p>Se achită la următoarea ridicare de la același restaurant; dacă nu există, la finalul programului.</p></>}
    <p className="text-xs opacity-75">Declarația și aprobarea nu confirmă primirea banilor.</p>
  </section>;
};

export const FinancialEventControls = ({ order, actor, recovery, isOnline, disabled = false }) => {
  const command = financialEventEligibility(order, actor);
  if (!command || !recovery?.available || !recovery.capability?.enabled) return null;
  return <div className="mt-3 min-w-0 space-y-2">
    <p className="text-xs">{actor.role === "driver" ? `Declari că nu ai achitat nimic din avansul de ${formatBani(command.amount_bani)} din lipsă de fonduri. O plată parțială trebuie verificată separat.` :
      `Aprobi plecarea cu produsele fără plata avansului de ${formatBani(command.amount_bani)}. Aceasta nu confirmă o plată.`}</p>
    <Button variant="outline" className="h-auto min-h-11 w-full whitespace-normal" disabled={disabled || !isOnline || recovery.blocked || !recovery.durableAvailable}
      onClick={() => recovery.submit({ order })} data-testid={`financial-event-${actor.role}-${order.id}`}>
      {actor.role === "driver" ? "Nu am achitat — numerar insuficient" : "Aprob ridicarea fără plată"}
    </Button>
  </div>;
};

export const FinancialEventRecoveryPanel = ({ recovery, isOnline, onAcknowledged }) => {
  const { record, busy, error, storageInvalid, sessionSuspended, checkingSession } = recovery;
  if (!record && !error && !sessionSuspended) return null;
  const receipt = record?.receipt, blocked = busy || sessionSuspended || storageInvalid || !recovery.durableAvailable || !isOnline;
  return <section className="my-3 min-w-0 space-y-2 break-words rounded-xl border border-amber-500/30 p-3 text-sm" data-testid="financial-event-recovery-panel">
    <h2 className="font-bold">Confirmarea operației de numerar</h2>
    {!isOnline && <p role="status">Fără internet. Încercarea inițială rămâne păstrată.</p>}
    {error && <p role="alert">{error}</p>}
    {busy && <p role="status">Se verifică încercarea curentă…</p>}
    {sessionSuspended && <p role="status">{checkingSession ? "Se verifică sesiunea…" : "Reverifică sesiunea pentru aceeași încercare."}</p>}
    {record && <div role="status"><p>Comanda {record.order_id} · {formatBani(record.amount_bani)}</p>
      <p>{financialEventApplied(receipt) ? "Operația este confirmată de server. Reîncarcă starea comenzii." : receipt?.state === "rejected" ? financialEventFailureMessage(receipt.error_code) :
        recovery.notAdmitted ? "Încercarea nu este încă găsită pe server. Retrimiterea păstrează aceeași identitate." : "Rezultat neconfirmat. Încercarea inițială rămâne păstrată."}</p></div>}
    {record && !recovery.durableAvailable && <p role="alert">Browserul nu poate proteja această operație între taburi. Încercarea este păstrată.</p>}
    <div className="flex flex-wrap gap-2">
      {sessionSuspended && <Button variant="outline" onClick={recovery.revalidateSession} disabled={!isOnline || checkingSession || !recovery.available}>Reverifică sesiunea</Button>}
      {record && !financialEventTerminal(receipt) && <Button variant="outline" className="h-auto min-h-9 whitespace-normal" onClick={recovery.recover} disabled={blocked}>Verifică aceeași încercare</Button>}
      {record && recovery.notAdmitted && !receipt && <Button variant="outline" className="h-auto min-h-9 whitespace-normal" onClick={recovery.resend} disabled={blocked}>Retrimite aceeași încercare</Button>}
      {receipt?.state === "pending" && <Button variant="outline" onClick={recovery.resume} disabled={blocked}>Continuă încercarea</Button>}
      {financialEventTerminal(receipt) && <Button className="h-auto min-h-9 whitespace-normal" disabled={blocked} onClick={async () => {
        const lease = recovery.captureLease(), fresh = await recovery.acknowledge();
        if (fresh && recovery.isCurrentLease(lease)) onAcknowledged?.(fresh);
      }}>Am văzut rezultatul și reîncarc comanda</Button>}
      {!record && error && !sessionSuspended && <Button variant="outline" onClick={recovery.chooseProtocol} disabled={busy || storageInvalid || !isOnline || !recovery.available}>Verifică disponibilitatea numerarului</Button>}
    </div>
  </section>;
};
