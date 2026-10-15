import React, { act } from "react";
import { createRoot } from "react-dom/client";
import { OrderFinancialSummary } from "./OrderFinancialSummary";
import { parseOrderDetail, parseOrderPage } from "../lib/orderReads";
import { readOrderFinance } from "../lib/orderFinance";

const order = { id: "qa-finance", restaurant_id: "qa-r", payment_type: "CARD", status: "READY", total_amount: 80, financial_contract_version: 1,
  financial: { contract_version: 1, currency: "RON", collection_mode: "prepaid", products_bani: 8000, client_collection_bani: 0,
    restaurant_transport_bani: 1600, courier_remuneration_bani: 750, advance_required_bani: 0,
    advance_paid_bani: null, refund_due_bani: null, refund_paid_bani: null, tariff_version: "qa-v1",
    restaurant_id: "qa-r", basis: "zone", snapshot_at: "2026-10-13T08:00:00Z", snapshot_digest: "a".repeat(64) },
};
let container, root;
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true;
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(() => { act(() => root.unmount()); container.remove(); });
const render = (element) => { act(() => root.render(element)); return { rerender: (next) => act(() => root.render(next)) }; };
const screen = {
  getByTestId: (id) => { const value=container.querySelector(`[data-testid="${id}"]`); expect(value).not.toBeNull(); return value; },
  queryByTestId: (id) => container.querySelector(`[data-testid="${id}"]`),
  getByRole: (role) => { const value=container.querySelector(`[role="${role}"]`); expect(value).not.toBeNull(); return value; },
  queryByRole: (role) => container.querySelector(`[role="${role}"]`),
  getByText: (pattern) => [...container.querySelectorAll("p")].find((el) => pattern.test(el.textContent)),
};
test("restaurant sees separate charge and prepaid collection, without courier pay", () => {
  render(<OrderFinancialSummary order={order} />);
  expect(screen.getByTestId("order-finance-client_collection_bani").textContent).toBe("0,00 RON");
  expect(screen.getByTestId("order-finance-restaurant_transport_bani").textContent).toBe("16,00 RON");
  expect(screen.getByTestId("order-finance-advance_paid_bani").textContent).toBe("Neconsemnat");
  expect(screen.queryByTestId("order-finance-courier_remuneration_bani")).toBeNull();
  expect(screen.getByText(/nu se încasează din nou/)).toBeTruthy();
});
test.each(["driver", "admin"])("%s sees explicit remuneration", (role) => {
  render(<OrderFinancialSummary order={order} role={role} />);
  expect(screen.getByTestId("order-finance-courier_remuneration_bani").textContent).toBe("7,50 RON");
});
test("invalid finance warns rather than showing invented zero; legacy renders no new assertion", () => {
  const { rerender } = render(<OrderFinancialSummary order={{...order, financial:{}}} />);
  expect(screen.getByRole("alert").textContent).toContain("necesită verificare");
  expect(screen.queryByTestId("order-finance-client_collection_bani")).toBeNull();
  const legacy = {...order}; delete legacy.financial_contract_version;
  rerender(<OrderFinancialSummary order={{...legacy, financial:null}} />);
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByTestId("order-finance-summary")).toBeNull();
});
test("page and detail preserve financial display contract across sanitization", () => {
  const page=parseOrderPage({items:[order],has_more:false,next_cursor:null,limit:25,data_warnings:[]});
  const detail=parseOrderDetail({order,history:[],next_history_before:null,history_has_more:false,data_warnings:[]},order.id);
  expect(readOrderFinance(page.items[0]).state).toBe("ready");
  expect(readOrderFinance(detail.order).value).toEqual(readOrderFinance(order).value);
});
test("invalid finance stays invalid after read projection and disables mutation actions", () => {
  const raw={...order, financial:{...order.financial,restaurant_transport_bani:"16"}};
  const page=parseOrderPage({items:[raw],has_more:false,next_cursor:null,limit:25,data_warnings:[]});
  expect(page.data_warnings).toContain("INVALID_ORDER_FINANCE");
  expect(page.items[0].read_data_invalid).toBe(true);
  expect(readOrderFinance(page.items[0]).state).toBe("invalid");
});
