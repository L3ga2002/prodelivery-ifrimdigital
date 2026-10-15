import { parseOrderDetail } from "./orderReads";

const readChanges = (changes) => parseOrderDetail({
  order: { id: "synthetic-finance-audit", status: "NEW", created_at: "2026-10-13T08:00:00Z" },
  history: [{ action: "order.delivered", created_at: "2026-10-13T08:00:00Z", changes }],
  history_has_more: false, next_history_before: null, data_warnings: [],
}, "synthetic-finance-audit");

test("finance audit keeps exact remuneration and calculation identity after read", () => {
  const changes = { courier_remuneration_bani: 905, financial_snapshot_digest: "b".repeat(64) };
  const result = readChanges(changes);
  expect(result.history[0].changes).toEqual(changes);
  expect(result.data_warnings).toEqual([]);
});

test.each([null, true, -1, 0.5, 100000001, "905"])("invalid remuneration %p does not become audit evidence", (value) => {
  const result = readChanges({courier_remuneration_bani: value});
  expect(result.history[0].changes).toEqual({});
  expect(result.data_warnings).toContain("HISTORY_CHANGE_UNAVAILABLE");
});

test("invalid financial audit identity and raw private content stay excluded", () => {
  const result = readChanges({ financial_snapshot_digest: "bad", financial_snapshot: {private: true} });
  expect(result.history[0].changes).toEqual({});
  expect(result.data_warnings).toContain("HISTORY_CHANGE_UNAVAILABLE");
});
