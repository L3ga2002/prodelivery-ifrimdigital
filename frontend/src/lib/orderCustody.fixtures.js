export const IDS = ["f29deeb5-e7a7-4b3e-9f13-f2408365858a", "af4373a2-4f78-4a1b-9889-ea59627d644f", "a1111111-1111-5111-8111-111111111111", "b1111111-1111-5111-8111-111111111111", "c1111111-1111-5111-8111-111111111111", "d1111111-1111-5111-8111-111111111111"];
export const driver = { id: "user", role: "driver", driver_id: "driver" };
export const restaurant = { id: "restaurant-user", role: "restaurant", restaurant_id: "restaurant" };
export const admin = { id: "admin-user", role: "admin" };
export const waitCommand = () => ({ event_type: "delivery_wait_started", incident_id: IDS[1], reason: "absent" });
export const custodyOrder = (status = null, overrides = {}) => {
  const reviewed = status && status !== "waiting", decided = ["return_requested", "keep_authorized", "returned", "kept"].includes(status), resolved = ["returned", "kept"].includes(status);
  return { id: "order", restaurant_id: "restaurant", driver_id: "driver", status: resolved ? "CANCELLED" : "PICKED_UP", order_version: 3,
    picked_up_at: "2026-10-14T08:00:00Z", delivered_at: null, cancelled_at: resolved ? "2026-10-14T08:20:00Z" : null,
    cancelled_by: resolved ? "actor" : null, cancellation_reason: resolved ? `custody_${status}` : null,
    ...(status ? { custody_contract_version: 1, custody_activity: { contract_version: 1, status, driver_id: "driver", incident_id: IDS[1], reason: "absent", arrival_evidence: "declared",
      wait_event_id: IDS[2], wait_started_at: "2026-10-14T08:01:00Z", wait_eligible_at: "2026-10-14T08:11:00Z", review_id: reviewed ? IDS[3] : null, reviewed_at: reviewed ? "2026-10-14T08:11:00Z" : null,
      customer_contact_attempted: reviewed ? true : null, restaurant_contacted: reviewed ? true : null, coordination_confirmed: reviewed ? true : null,
      decision_id: decided ? IDS[4] : null, decision: decided ? ["returned", "return_requested"].includes(status) ? "return" : "keep" : null, decided_at: decided ? "2026-10-14T08:12:00Z" : null,
      resolution_id: resolved ? IDS[5] : null, resolved_at: resolved ? "2026-10-14T08:20:00Z" : null, pricing_status: "pending" } } : {}), ...overrides };
};
