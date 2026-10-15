import { getCurrentStepLabel } from "./DriverApp";
import { custodyOrder } from "../lib/orderCustody.fixtures";
jest.mock("../context/AuthContext", () => ({ useAuth: jest.fn() }));
jest.mock("../components/DriverSchedule", () => ({ DriverSchedule: () => null }));
jest.mock("../components/AvatarUploadCropper", () => ({ AvatarUploadCropper: () => null }));
jest.mock("../components/DriverAvatar", () => ({ DriverAvatar: () => null }));

test("driver task follows the validated restaurant return or keep instruction", () => {
  expect(getCurrentStepLabel(custodyOrder("return_requested"))).toBe("Returnează produsele restaurantului");
  expect(getCurrentStepLabel(custodyOrder("keep_authorized"))).toBe("Confirmă instrucțiunea de păstrare");
  expect(getCurrentStepLabel(custodyOrder("waiting"))).toBe("Livrează clientului");
  expect(getCurrentStepLabel(custodyOrder())).toBe("Livrează clientului");
});

test("malformed custody projection cannot present a return, keep or delivery instruction", () => {
  for (const status of ["return_requested", "keep_authorized"]) {
    const order = custodyOrder(status);
    expect(getCurrentStepLabel({ ...order, custody_activity: { ...order.custody_activity, decision_id: null } })).toBe("Verifică evidența produselor");
    expect(getCurrentStepLabel({ ...order, read_custody_invalid: true })).toBe("Verifică evidența produselor");
  }
});
