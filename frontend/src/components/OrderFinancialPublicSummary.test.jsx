import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { OrderFinancialSummary } from "./OrderFinancialSummary";
import { parseOrderPage } from "../lib/orderReads";

const fixture = (visibility = "restaurant", payment = "CARD") => ({ id: "o", restaurant_id: "r", status: "READY", payment_type: payment,
  financial_contract_version: 1, financial_read_contract_version: 1, financial_read_visibility: visibility,
  financial: { contract_version: 1, currency: "RON", restaurant_id: "r", tariff_version: "v1", products_bani: 8000,
    collection_mode: payment === "CARD" ? "prepaid" : "cash", client_collection_bani: payment === "CARD" ? 0 : 8000,
    restaurant_transport_bani: 1600, advance_required_bani: payment === "CARD" ? 0 : 8000,
    advance_paid_bani: null, refund_due_bani: null, refund_paid_bani: null, basis: "zone", snapshot_at: "2026-10-15T00:00:00Z",
    ...(visibility === "assigned_driver" ? { courier_remuneration_bani: 917 } : {}) } });
let container, root;
beforeEach(() => { globalThis.IS_REACT_ACT_ENVIRONMENT = true; container = document.createElement("div"); document.body.append(container); root = createRoot(container); });
afterEach(() => { act(() => root.unmount()); container.remove(); });
const render = (order, role) => act(() => root.render(<OrderFinancialSummary order={order} role={role} />));
const field = (name) => container.querySelector(`[data-testid="order-finance-${name}"]`);

test.each(["restaurant", "driver", "admin"])("restaurant DTO never invents salary with UI role %s", (role) => {
  render(fixture(), role);
  expect(field("courier_remuneration_bani")).toBeNull();
  expect(field("client_collection_bani").textContent).toBe("0,00 RON");
  expect(field("restaurant_transport_bani").textContent).toBe("16,00 RON");
  for (const name of ["advance_paid_bani", "refund_due_bani", "refund_paid_bani"]) expect(field(name).textContent).toBe("Neconsemnat");
  expect(container.textContent).toContain("nu se încasează din nou");
});
test.each(["restaurant", "driver", "admin"])("assigned-driver DTO salary has role-aware rendering for %s", (role) => {
  render(fixture("assigned_driver", "CASH"), role);
  expect(field("client_collection_bani").textContent).toBe("80,00 RON");
  if (role === "restaurant") expect(field("courier_remuneration_bani")).toBeNull();
  else expect(field("courier_remuneration_bani").textContent).toBe("9,17 RON");
});
test("full admin remains full, public read normalization preserves display", () => {
  const order = fixture("assigned_driver"); delete order.financial_read_contract_version; delete order.financial_read_visibility;
  order.financial.snapshot_digest = "a".repeat(64);
  render(order, "admin"); expect(field("courier_remuneration_bani").textContent).toBe("9,17 RON");
  const parsed = parseOrderPage({ items: [fixture()], limit: 25, has_more: false, next_cursor: null, data_warnings: [] });
  render(parsed.items[0], "restaurant"); expect(field("client_collection_bani").textContent).toBe("0,00 RON");
});
test.each([null, {}, { salary: 0 }])("invalid public finance warns without fallback or invented zero %#", (financial) => {
  render({ ...fixture(), financial, total_amount: 99 }, "restaurant");
  expect(container.querySelector('[role="alert"]')).not.toBeNull();
  expect(field("client_collection_bani")).toBeNull(); expect(container.textContent).not.toContain("99");
});
test("legacy absence renders nothing, while own null requires verification", () => {
  const legacy = { id: "o", restaurant_id: "r", payment_type: "CASH", status: "NEW", total_amount: 20 };
  render(legacy, "restaurant"); expect(container.textContent).toBe("");
  render({ ...legacy, financial: null }, "restaurant"); expect(container.querySelector('[role="alert"]')).not.toBeNull();
});
