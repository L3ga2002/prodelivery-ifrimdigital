// Wait only for the consent/permission window to dismiss; never weaken native Start checks.
export async function awaitBatteryForeground(ready: () => boolean, active: () => boolean, delay: (ms: number) => Promise<void>): Promise<void> {
  for (let attempt = 0; attempt <= 20; attempt++) {
    if (!active()) throw new Error('foreground_start_required');
    if (ready()) return;
    if (attempt === 20) throw new Error('foreground_window_unavailable');
    await delay(100);
  }
}
export function batteryActionDiagnostic(error: unknown): string {
  const message = error instanceof Error ? error.message : '';
  const known = ['foreground_start_required','foreground_window_unavailable','notification_permission_required',
    'battery_notification_permission_required','observer_not_started','observer_not_active','observer_incomplete',
    'journal_write_failed','journal_directory_failed','journal_storage_limit','run_id_already_exists','invalid_run_id',
    'battery_identity_changed','gps_start_unconfirmed','idle_window_required','battery_native_build_required', 'gps_budget_insufficient'];
  return known.find(code => message.includes(code)) ?? 'battery_operation_unconfirmed';
}
