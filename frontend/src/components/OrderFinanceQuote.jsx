import { formatBani } from "../lib/orderFinance";

export const OrderFinanceQuote = ({ finance, disabled = false }) => (
  <section className="space-y-3 rounded-lg border p-3 text-sm" aria-label="Cotație financiară" data-testid="finance-quote-panel">
    <p className="font-semibold">Cotație financiară pentru această comandă</p>
    {finance.mode === "unknown" && <p>Verifică disponibilitatea financiară înainte de creare.</p>}
    {finance.error && <p role="alert">{finance.error}</p>}
    {finance.mode === "financial" && <>
      <label className="block">Grilă aprobată
        <select className="mt-1 w-full rounded border bg-background p-2" aria-label="Grilă aprobată" data-testid="finance-tariff-select"
          value={finance.tariffVersion} disabled={disabled || finance.loading} onChange={(event) => finance.setTariffVersion(event.target.value)}>
          <option value="">Alege explicit versiunea</option>
          {finance.tariffs.map((tariff) => <option key={tariff.version} value={tariff.version}>{tariff.version} · RON</option>)}
        </select>
      </label>
      {finance.discoveryState === "ready" && finance.tariffs.length === 0 && <p>Nu există grile aprobate disponibile.</p>}
      {finance.capability && !finance.capability.create_quote_enabled && <p>Crearea financiară nu este disponibilă acum.</p>}
      <button type="button" className="min-h-10 rounded border px-3 py-2" onClick={finance.requestQuote} disabled={disabled || finance.loading} data-testid="finance-request-quote">
        {finance.loading ? "Verific cotația..." : "Calculează cotația"}
      </button>
    </>}
    {finance.quote && <>
      <dl className="grid grid-cols-2 gap-2" data-testid="finance-quote-values">
        {[["Produse", "products_bani"], ["De încasat de la client", "client_collection_bani"], ["Transport datorat de restaurant", "restaurant_transport_bani"],
          ["Remunerație livrator", "courier_remuneration_bani"], ["Avans necesar", "advance_required_bani"], ["Avans achitat", "advance_paid_bani"],
          ["Rambursare datorată", "refund_due_bani"], ["Rambursare achitată", "refund_paid_bani"]].map(([label, key]) => <div key={key}>
          <dt className="text-muted-foreground">{label}</dt><dd className="font-semibold">{formatBani(finance.quote[key])}</dd>
        </div>)}
      </dl>
      <p>Cotație informativă pentru grila {finance.quote.tariff_version}. Plățile efective nu sunt consemnate.</p>
      <label className="flex items-start gap-2"><input type="checkbox" checked={finance.confirmed} disabled={disabled}
        onChange={(event) => finance.confirm(event.target.checked)} data-testid="finance-confirm-quote" />Confirm cotația afișată pentru datele curente.</label>
    </>}
    {(finance.mode === "unknown" || finance.error) && <button type="button" className="min-h-10 rounded border px-3 py-2" onClick={finance.refresh} disabled={disabled || finance.loading}>Reverifică disponibilitatea financiară</button>}
  </section>
);
