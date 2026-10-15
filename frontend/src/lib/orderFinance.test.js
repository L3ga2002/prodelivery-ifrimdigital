import { clientCollectionText, formatBani, readOrderFinance } from "./orderFinance";

export const financialOrder = (payment_type = "CASH") => ({
  id: "qa-finance-order", restaurant_id: "qa-restaurant", payment_type, total_amount: 65, financial_contract_version: 1,
  financial: { contract_version: 1, currency: "RON", collection_mode: payment_type === "CASH" ? "cash" : "prepaid", products_bani: 6500,
    client_collection_bani: payment_type === "CASH" ? 6500 : 0, restaurant_transport_bani: 1600,
    courier_remuneration_bani: 900, advance_required_bani: payment_type === "CASH" ? 6500 : 0,
    advance_paid_bani: null, refund_due_bani: null, refund_paid_bani: null, tariff_version: "qa-v1",
    restaurant_id: "qa-restaurant", basis: "zone", snapshot_digest: "a".repeat(64), snapshot_at: "2026-10-13T08:00:00Z" },
});

test("restaurant transport never becomes the client collection or driver remuneration", () => {
  const order = financialOrder();
  expect(clientCollectionText(order)).toBe("65,00 RON");
  expect(readOrderFinance(order).value.courier_remuneration_bani).toBe(900);
  expect(clientCollectionText(financialOrder("CARD"))).toBe("0,00 RON");
});
test("unknown payment evidence remains distinct from explicit zero", () => {
  expect(formatBani(null)).toBe("Neconsemnat");
  expect(formatBani(0)).toBe("0,00 RON");
  expect(formatBani(1530)).toBe("15,30 RON");
  expect(readOrderFinance(financialOrder()).value.advance_paid_bani).toBeNull();
});
test.each([NaN, Infinity, -1, 2.5, true, "900", undefined, 100000001])("invalid amount %p cannot fall back to an old total", (amount) => {
  const order = financialOrder(); order.financial.courier_remuneration_bani = amount;
  expect(readOrderFinance(order).state).toBe("invalid");
  expect(clientCollectionText(order)).toBe("Sumă indisponibilă");
});
test("tenant mismatch, unsupported contract and missing evidence fail closed", () => {
  for (const changes of [{restaurant_id:"foreign"}, {contract_version:2}, {advance_paid_bani:undefined}, {snapshot_digest:"bad"}, {client_collection_bani:8100}]) {
    const order = financialOrder(); Object.assign(order.financial, changes);
    expect(readOrderFinance(order).state).toBe("invalid");
  }
});
test("legacy orders stay recognizable and provenance is not copied into display", () => {
  expect(readOrderFinance({total_amount:4}).state).toBe("legacy");
  expect(clientCollectionText({total_amount:4})).toBe("4 RON");
  const order=financialOrder(); order.financial.distance_evidence_ref="private-reference";
  expect(readOrderFinance(order).value.distance_evidence_ref).toBeUndefined();
});
test.each([{ financial_contract_version: 1 }, {financial_contract_version: null}, {read_financial_invalid:true}])("marked or flagged missing snapshot %p never falls back to legacy", (extra) => {
  expect(clientCollectionText({ total_amount:99,...extra })).toBe("Sumă indisponibilă");
});
