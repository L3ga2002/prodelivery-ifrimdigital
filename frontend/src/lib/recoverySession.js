// A bounded cookie read precedes reactivation; late reads cannot reactivate a retired epoch.
export const verifyRecoverySession = async ({ api, actorId, roles, timeout, isOnline, currentOwner, fail }) => {
  currentOwner();
  if (!isOnline()) fail("OFFLINE", "Fara internet. Sesiunea trebuie reverificata inainte de reluare.");
  let timer;
  try {
    const auth = await Promise.race([
      api.get("/api/auth/me", { timeout }),
      new Promise((_, reject) => { timer = setTimeout(() => reject(new Error("SESSION_TIMEOUT")), timeout); }),
    ]);
    currentOwner();
    if (auth?.status !== 200 || auth.data?.id !== actorId || !roles.includes(auth.data?.role) ||
      ["account_disabled", "is_disabled"].some((k) => Object.hasOwn(auth.data, k) && auth.data[k] !== false)) {
      fail("SESSION_CHANGED", "Actorul autentificat s-a schimbat. Intentia ramane pastrata pentru contul initial.");
    }
  } catch (error) {
    currentOwner();
    if (["SESSION_CHANGED", "OFFLINE", "AUTH_REQUIRED", "RECOVERY_UNAVAILABLE"].includes(error?.code)) throw error;
    fail(error?.response?.status === 401 ? "AUTH_REQUIRED" : error?.response?.status === 403 ? "SESSION_CHANGED" : "RECOVERY_UNAVAILABLE",
      "Sesiunea nu poate fi confirmata. Intentia ramane pastrata; reverifica sesiunea.");
  } finally { clearTimeout(timer); }
};
