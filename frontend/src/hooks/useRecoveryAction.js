import { useCallback } from "react";

// One action per controller. Each caller retains its own lifecycle, capability
// and storage policy; a retired generation can never publish a late result.
export const useRecoveryAction = ({ controller, valid, suspended, flight, epoch, update, read }) =>
  useCallback(async (action, value) => {
    if (!controller || !valid() || suspended.current?.owner === controller || flight.current?.owner === controller) return null;
    const generation = epoch.current;
    let settle;
    const job = { owner: controller, settled: new Promise((resolve) => { settle = resolve; }) }; flight.current = job;
    update({ busy: true, error: "", errorCode: "" });
    try { const result = await controller[action](value); return valid() && generation === epoch.current ? (result === undefined ? true : result) : null; }
    catch (e) { if (generation === epoch.current) update({ error: e.message, errorCode: e.code }); return null; }
    finally { if (flight.current === job) { flight.current = null; update({ busy: false }); read(); } settle(); }
  }, [controller, valid, suspended, flight, epoch, update, read]);
