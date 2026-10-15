import { act } from "react";
import { createRoot } from "react-dom/client";
import { OrderReadBrowser } from "./admin/OrderReadBrowser";
import { RestaurantHistoryDetailDialog } from "./restaurant/RestaurantDialogs";
import { CustodyRecoveryPanel } from "./OrderCustody";
import { useOrderReadDetail, useOrderReads } from "../hooks/useOrderReads";
import { custodyOrder, IDS, waitCommand } from "../lib/orderCustody.fixtures";
jest.mock("../hooks/useOrderReads", () => ({ useOrderReadDetail: jest.fn(), useOrderReads: jest.fn() }));
jest.mock("./OperationalIncidentReporter", () => ({ OperationalIncidentReporter: () => null, IncidentSummary: () => null }));
jest.mock("./ui/dialog", () => {
  const Part = ({ children, ...props }) => <div data-testid={props["data-testid"]}>{children}</div>;
  return { Dialog: ({ open, children }) => open ? <div role="dialog">{children}</div> : null, DialogContent: Part, DialogDescription: Part, DialogHeader: Part, DialogTitle: Part, DialogFooter: Part };
});
let root, container, recovery, applied, refresh, item;
const render = (element) => act(async () => root.render(element));
const ack = () => [...container.querySelectorAll("button")].find((button) => button.textContent === "Am văzut rezultatul și reîncarc comanda");
const deferred = () => { let resolve; const promise = new Promise((yes) => { resolve = yes; }); return { promise, resolve }; };
beforeEach(() => {
  globalThis.IS_REACT_ACT_ENVIRONMENT = true; item = custodyOrder("waiting"); applied = jest.fn(); refresh = jest.fn();
  const read = { phase: "ready", warnings: [], page: 1, canNext: false, canPrevious: false, refresh, items: [item], data: { order: item, history: [] } };
  useOrderReadDetail.mockReturnValue(read); useOrderReads.mockReturnValue(read);
  recovery = { available: true, durableAvailable: true, captureLease: () => "lease", isCurrentLease: () => true, acknowledge: jest.fn(async () => item),
    record: { order_id: "order", command: waitCommand(), receipt: { state: "applied", client_operation_id: IDS[0] } } };
  container = document.createElement("div"); document.body.append(container); root = createRoot(container);
});
afterEach(async () => { await act(async () => root.unmount()); container.remove(); });
test("admin detail contains existing custody recovery controller and acknowledgment safely closes detail", async () => {
  await render(<OrderReadBrowser context={{ actorId: "admin", role: "admin", apiUrl: "https://qa.invalid", isOnline: true, custodyRecovery: recovery, onCustodyAcknowledged: applied }} />);
  await act(async () => container.querySelector('[data-testid="order-read-eye-order"]').click());
  expect(container.querySelector('[data-testid="order-read-detail"] [data-testid="custody-recovery-panel"]')).not.toBeNull();
  await act(async () => ack().click()); expect(recovery.acknowledge).toHaveBeenCalledTimes(1); expect(applied).toHaveBeenCalledWith(item); expect(container.querySelector('[data-testid="order-read-detail"]')).toBeNull();
});
test("restaurant history exposes same saved receipt inside open dialog", async () => {
  await render(<RestaurantHistoryDetailDialog open historyDetailOrder={item} custodyRecovery={recovery} isOnline onCustodyAcknowledged={applied} setHistoryDetailOrder={jest.fn()} />);
  expect(container.querySelector('[role="dialog"] [data-testid="custody-recovery-panel"]')).not.toBeNull(); await act(async () => ack().click()); expect(applied).toHaveBeenCalledWith(item);
});
test("unmount while acknowledgement is pending suppresses old modal callback", async () => {
  const late = deferred(); recovery.acknowledge.mockReturnValue(late.promise);
  await render(<CustodyRecoveryPanel recovery={recovery} isOnline scopeKey="order" onAcknowledged={applied} />); await act(async () => ack().click()); await render(<p>Dialog închis</p>);
  await act(async () => late.resolve(item)); expect(applied).not.toHaveBeenCalled();
});
test("same actor opening another order fences old acknowledgment scope", async () => {
  const late = deferred(); recovery.acknowledge.mockReturnValue(late.promise);
  await render(<CustodyRecoveryPanel recovery={recovery} isOnline scopeKey="order" onAcknowledged={applied} />); await act(async () => ack().click());
  await render(<CustodyRecoveryPanel recovery={recovery} isOnline scopeKey="other-order" onAcknowledged={applied} />); await act(async () => late.resolve(item)); expect(applied).not.toHaveBeenCalled();
});
