import { useEffect, useRef, useState } from 'react';
import { Alert, AppState, PermissionsAndroid, Platform, Pressable, StyleSheet, Text, View } from 'react-native';
import { randomUUID } from 'expo-crypto';
import type { RecorderController } from './controller';
import { batteryNative } from './batteryNative';
import { batteryObservationsComplete, type BatteryReport } from './batteryReport';
import { closeBatteryGpsWindow, markBatteryGpsWindow } from './batteryGpsBoundary';
import { awaitBatteryForeground, batteryActionDiagnostic } from './batteryStartBoundary';
import { batteryBudgetBlocksGpsStart, batteryBudgetMessage, batteryBudgetWarning } from './batteryBudget';

const labels = {
  none: 'Nicio proba', waiting_unplug: 'Asteapta scoaterea cablului', idle: 'Repaus, fara GPS',
  awaiting_gps: 'Repaus terminat: porneste GPS Fundal', gps: 'Masurare cu GPS in fundal',
  awaiting_stop: 'Interval terminat: oprire GPS necesara', completed: 'Observatii inregistrate', incomplete: 'Proba incompleta',
};
export function BatteryPanel({ getController, getBatteryStartRunId, onGateChange, onFullStart, onModeLockChange }: {
  getController: () => RecorderController | null; onGateChange: (blocked: boolean) => void; onFullStart: () => void;
  getBatteryStartRunId: () => string | null;
  onModeLockChange: (locked: boolean) => void;
}) {
  const [report, setReport] = useState<BatteryReport | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const owner = useRef({ mounted: false, epoch: 0, job: false, poll: false });
  const props = useRef({ getController, getBatteryStartRunId, onGateChange, onFullStart, onModeLockChange });
  props.current = { getController, getBatteryStartRunId, onGateChange, onFullStart, onModeLockChange };
  const current = useRef<BatteryReport | null>(null);
  function publish(next: BatteryReport, epoch: number, clearError = false) {
    if (!owner.current.mounted || epoch !== owner.current.epoch) return;
    current.current = next; setReport(next); if (clearError) setError(null);
    props.current.onGateChange(['waiting_unplug', 'idle', 'gps', 'awaiting_stop'].includes(next.phase) || next.starting || batteryBudgetBlocksGpsStart(next));
    props.current.onModeLockChange(next.kind === 'full' && !['completed', 'incomplete'].includes(next.phase));
  }
  async function action(work: () => Promise<BatteryReport>) {
    if (owner.current.job) return;
    owner.current.job = true; const epoch = ++owner.current.epoch;
    if (owner.current.mounted) setBusy(true);
    try { publish(await work(), epoch, true); }
    catch (failure) { if (owner.current.mounted && epoch === owner.current.epoch) setError(`Operatia probei nu este confirmata: ${batteryActionDiagnostic(failure)}. Starea jurnalului este afisata separat; poti incerca din nou.`); }
    finally { owner.current.job = false; if (owner.current.mounted && epoch === owner.current.epoch) setBusy(false); }
  }
  async function stopAndClose(runId: string, complete: boolean) {
    const controller = props.current.getController();
    let live: BatteryReport;
    try { live = batteryNative.peek(); }
    catch {
      try { return await batteryNative.stop(runId, 'cancelled'); }
      finally { if (controller) await controller.stop(); }
    }
    if (live.runId !== runId) throw new Error('battery_identity_changed');
    return closeBatteryGpsWindow(controller, complete ? live : { ...live, phase: 'incomplete' }, batteryNative.stop);
  }
  useEffect(() => {
    owner.current.mounted = true;
    async function poll() {
      if (!batteryNative.available || owner.current.poll || owner.current.job) return;
      owner.current.poll = true; const epoch = owner.current.epoch;
      try {
        const next = await batteryNative.status();
        if (!owner.current.mounted || epoch !== owner.current.epoch || owner.current.job) return;
        publish(next, epoch);
        const controller = props.current.getController();
        if (!next.runId || !controller) return;
        if (next.phase === 'awaiting_gps' && controller.state.phase === 'recording' && controller.state.mode === 'background' && controller.state.sessionId) {
          await action(() => markBatteryGpsWindow(controller, next, batteryNative.markGps, batteryNative.stop));
        } else if (next.phase === 'awaiting_gps' && ['starting', 'recording'].includes(controller.state.phase) && controller.state.mode !== 'background') {
          await action(() => stopAndClose(next.runId!, false));
        } else if (next.phase === 'awaiting_stop') {
          await action(() => stopAndClose(next.runId!, true));
        } else if (['waiting_unplug', 'idle'].includes(next.phase) && ['starting', 'recording'].includes(controller.state.phase)) {
          await action(() => stopAndClose(next.runId!, false));
        } else if (next.phase === 'incomplete' &&
          (props.current.getBatteryStartRunId() === next.runId || (next.gpsSessionId && next.gpsSessionId === controller.state.sessionId)) &&
          ['starting', 'recording'].includes(controller.state.phase)) {
          await action(() => stopAndClose(next.runId!, false));
        } else if (next.phase === 'gps' && (controller.state.phase !== 'recording' || controller.state.sessionId !== next.gpsSessionId)) {
          await action(() => stopAndClose(next.runId!, false));
        }
      } catch {
        if (owner.current.mounted && epoch === owner.current.epoch) {
          props.current.onGateChange(true);
          setError('Citirea bateriei nu este confirmata. Start este blocat pana la o citire valida. Datele lipsa nu reprezinta succes.');
        }
      } finally { owner.current.poll = false; }
    }
    void poll(); const timer = setInterval(() => { void poll(); }, 2000);
    const listener = AppState.addEventListener('change', state => { if (state === 'active') void poll(); });
    return () => { owner.current.mounted = false; owner.current.epoch++; clearInterval(timer); listener.remove(); };
  }, []);
  const active = !!report && (report.observerActive || report.starting || report.phase === 'awaiting_stop');
  function begin(kind: 'pilot' | 'full') {
    const controller = props.current.getController();
    if (owner.current.job || active || AppState.currentState !== 'active' || !controller || controller.state.phase !== 'idle' || controller.state.watchdog) return;
    const dialogEpoch = owner.current.epoch;
    Alert.alert('Proba locala de baterie', kind === 'pilot'
      ? 'Nu porneste GPS. Dupa scoaterea USB sunt necesare 20 secunde fara alimentare, apoi 30 secunde de observatii. Reconecteaza numai dupa rezultatul afisat.'
      : 'Limita totala de 45 minute incepe la armare, inclusiv asteptarea scoaterii USB si trecerea dintre intervale. Dupa scoaterea USB: 20 secunde de verificare, apoi 15 minute repaus. La mesajul de final al repausului selecteaza Fundal si foloseste Start → Continua cu consimtamantul GPS. Start necesita timp pentru 15 minute GPS si marja de observare. Dupa 15 minute revino si foloseste Stop. Pastreaza aceleasi conditii de ecran si retea; jurnalul se salveaza pe telefon.', [
      { text: 'Renunta', style: 'cancel' },
      { text: 'Incepe proba', onPress: () => {
        const live = props.current.getController();
        if (!owner.current.mounted || dialogEpoch !== owner.current.epoch || current.current?.observerActive || current.current?.starting || active || owner.current.job || AppState.currentState !== 'active' || live?.state.phase !== 'idle' || live.state.watchdog) return;
        if (kind === 'full') props.current.onFullStart();
        void action(async () => {
          props.current.onGateChange(true);
          if (Platform.OS === 'android' && Number(Platform.Version) >= 33 &&
            !await PermissionsAndroid.check(PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS)) {
            const permission = await PermissionsAndroid.request(PermissionsAndroid.PERMISSIONS.POST_NOTIFICATIONS);
            if (permission !== PermissionsAndroid.RESULTS.GRANTED) throw new Error('battery_notification_permission_required');
          }
          await awaitBatteryForeground(() => AppState.currentState === 'active' && batteryNative.foregroundReady(),
            () => owner.current.mounted && AppState.currentState !== 'background',
            ms => new Promise(resolve => setTimeout(resolve, ms)));
          if (!owner.current.mounted || AppState.currentState !== 'active') throw new Error('foreground_start_required');
          const runId = `pd-battery-${randomUUID()}`;
          const result = await batteryNative.start(runId, kind);
          if (result.runId !== runId) throw new Error('battery_identity_changed');
          return result;
        });
      } },
    ]);
  }
  const proved = report ? batteryObservationsComplete(report) : false;
  const budgetWarning = batteryBudgetWarning(report);
  return <View style={s.section}>
    <Text style={s.title}>Proba baterie fara incarcator</Text>
    <Text style={s.text}>Jurnal local, fara coordonate. Acelasi observator ruleaza in ambele intervale. Pornirea GPS necesita Start si acordul existent.</Text>
    {!batteryNative.available && <Text style={s.warning}>Masurarea necesita versiunea Android cu modulul nativ de baterie.</Text>}
    {error && <Text accessibilityRole="alert" style={s.warning}>{error}</Text>}
    <Text style={s.label}>{report ? labels[report.phase] : 'Citire in curs'}</Text>
    {report?.runId && report.kind === 'full' && <Text style={s.text}>{batteryBudgetMessage(report)}</Text>}
    {budgetWarning && <Text accessibilityRole="alert" style={s.warning}>{budgetWarning}</Text>}
    {report?.runId && <Text selectable style={s.code}>{report.runId}</Text>}
    <Text style={s.text}>Baterie: {report?.lastSnapshot?.levelPercent ?? '?'}% / alimentare: {report?.lastSnapshot?.plugMask === 0 && report.lastSnapshot.charging === false ? 'absenta la ultima citire' : 'prezenta sau necunoscuta'}</Text>
    <Text style={s.text}>Observatii: {report?.snapshots.length ?? 0}; intreruperi/erori: {report?.failures.length ?? 0}</Text>
    {report?.windows.map((w, i) => <Text key={i} style={s.text}>{w.phase === 'idle' ? 'Repaus' : 'GPS'}: {Math.floor(w.elapsedMs / 1000)} s, {w.start.levelPercent ?? '?'}% → {w.end.levelPercent ?? '?'}%, {w.valid ? 'interval observat' : 'incomplet'}</Text>)}
    {report?.phase === 'awaiting_gps' && !budgetWarning && <Text accessibilityRole="alert" style={s.warning}>Repaus terminat. Selecteaza Fundal, bifeaza consimtamantul si apasa Start → Continua, apoi Home. Nu reconecta USB. Timpul este verificat din nou dupa permisiuni si la pornirea intervalului GPS.</Text>}
    {report?.phase === 'awaiting_stop' && <Text accessibilityRole="alert" style={s.warning}>Revino in aplicatie si apasa Stop. Incheierea observatorului de baterie nu confirma oprirea GPS.</Text>}
    {proved && <Text style={s.text}>Observatiile cerute sunt pastrate. Procentul neschimbat nu inseamna consum zero; aceasta proba nu certifica autonomia unei ture.</Text>}
    {report?.phase === 'completed' && !proved && <Text accessibilityRole="alert" style={s.warning}>Inchiderea jurnalului nu este suficienta pentru un rezultat valid.</Text>}
    <View style={s.row}>
      <Pressable accessibilityRole="button" disabled={!batteryNative.available || busy || active} onPress={() => begin('pilot')} style={[s.button, (!batteryNative.available || busy || active) && s.disabled]}><Text style={s.buttonText}>Proba scurta fara GPS</Text></Pressable>
      <Pressable accessibilityRole="button" disabled={!batteryNative.available || busy || active} onPress={() => begin('full')} style={[s.button, (!batteryNative.available || busy || active) && s.disabled]}><Text style={s.buttonText}>Proba 15 + 15 minute</Text></Pressable>
    </View>
    <Pressable accessibilityRole="button" disabled={busy || !active || !report?.runId} onPress={() => { const id = current.current?.runId; if (id) void action(() => stopAndClose(id, current.current?.phase === 'awaiting_stop')); }} style={[s.button, (busy || !active) && s.disabled]}><Text style={s.buttonText}>{busy ? 'Verificare in curs' : 'Opreste proba si GPS'}</Text></Pressable>
    <Text style={s.text}>Procentele sunt rotunjite de sistem. Ecranul stins, pierderea procesului, alimentarea sau golurile de inregistrare pot lasa proba incompleta. Observatorul nu reia GPS dupa relansare.</Text>
    <Text style={s.text}>Limita totala: 45 minute de la armare, inclusiv asteptarea scoaterii USB si trecerea dintre intervale. Bugetul afisat este de la ultima observatie nativa; verificarea proaspata dupa permisiuni si la marker decide pornirea. O revenire tarzie dupa suspendare lasa proba incompleta. Daca GPS este activ, revino pentru Stop; observatorul nu opreste senzorul.</Text>
  </View>;
}
const s = StyleSheet.create({
  section: { borderTopWidth: 1, borderTopColor: '#d6dce1', paddingTop: 16, gap: 10 },
  title: { fontSize: 17, fontWeight: '600', color: '#20242b' }, text: { fontSize: 13, lineHeight: 19, color: '#58606e' },
  label: { fontSize: 15, fontWeight: '600', color: '#20242b' }, code: { fontSize: 12, color: '#434b55' },
  warning: { fontSize: 14, lineHeight: 20, color: '#775608' }, row: { gap: 8 },
  button: { minHeight: 48, padding: 12, borderRadius: 6, backgroundColor: '#303940', justifyContent: 'center' },
  buttonText: { fontSize: 14, color: '#fff', textAlign: 'center' }, disabled: { opacity: 0.4 },
});
