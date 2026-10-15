import { act } from "react";
import { createRoot } from "react-dom/client";
import axios from "axios";
import { useOrderCreationRecovery } from "../hooks/useOrderCreationRecovery";
import { useOrderEditingRecovery } from "../hooks/useOrderEditingRecovery";

jest.mock("axios", () => ({ create: jest.fn() }));
const ID = "123e4567-e89b-42d3-a456-426614174000";
let root, container, creation, editing, cookieActor, effects, transport;
const order = { id: "order", order_version: 4, status: "NEW", restaurant_id: "restaurant",
  customer_name: "Synthetic Customer", customer_phone: "0700000000", customer_address: "Synthetic Street",
  items: [{ name: "Synthetic product", quantity: 1, price: 20 }], total_amount: 20,
  payment_type: "CASH", source: "S", delivery_zone_id: "zone", notes: "" };
const creationOrder = { ...order }; delete creationOrder.id; delete creationOrder.order_version; delete creationOrder.status;
function Harness({ token = null }) {
  creation = useOrderCreationRecovery("admin-a", "https://qa.invalid", true, token);
  editing = useOrderEditingRecovery("admin-a", "https://qa.invalid", true, token);
  return null;
}
const render = (token = null) => act(async () => root.render(<Harness token={token} />));
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; localStorage.clear(); sessionStorage.clear(); jest.clearAllMocks();
  cookieActor = "admin-a"; effects = [];
  Object.defineProperty(navigator, "locks", { configurable: true, value: { request: async (_k, _o, fn) => fn({}) } });
  Object.defineProperty(window, "crypto", { configurable: true, value: { randomUUID: () => ID } });
  const guard = (options) => {
    const expected = options?.headers?.["X-Expected-Actor-ID"];
    if (expected !== undefined && expected !== cookieActor) throw { response: { status: 403, data: { detail: { code: "AUTH_CONTEXT_CHANGED" } } } };
  };
  transport = {
    get: jest.fn(async (path, options) => { guard(options); return { status: 200, data: path.includes("/edit/") ?
      { edit_recovery_enabled: true } : { create_recovery_enabled: true } }; }),
    post: jest.fn(async (path, body, options) => {
      guard(options); effects.push({ actor: cookieActor, path });
      return { status: path.endsWith("/create") ? 201 : 200, data: { client_operation_id: body?.client_operation_id || ID,
        state: "applied", order_id: "order", order_version: path.endsWith("/create") ? 0 : 5 } };
    }),
  };
  axios.create.mockReturnValue(transport);
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); await Promise.resolve(); container.remove(); });
test.each([null, "synthetic-bearer-a"])("create refuses a replaced shared cookie even with token %j", async (token) => {
  await render(token); cookieActor = "admin-b";
  await act(async () => creation.submit(creationOrder));
  expect(effects).toEqual([]);
  expect(creation.record?.receipt).toBeNull();
});
test.each([null, "synthetic-bearer-a"])("edit refuses a replaced shared cookie even with token %j", async (token) => {
  await render(token); cookieActor = "admin-b";
  await act(async () => editing.submit({ order, changes: { customer_address: "Synthetic corrected address" } }));
  expect(effects).toEqual([]);
  expect(localStorage.getItem("prodelivery:order-edit:v1:admin-a")).toBeNull();
});
test("legacy creation uses the same comparative actor guard", async () => {
  await render(); cookieActor = "admin-b";
  await act(async () => creation.submitLegacy(creationOrder));
  expect(effects).toEqual([]);
  expect(transport.post).toHaveBeenCalledTimes(1);
});
