import { useEffect, useRef, useState } from 'react';
import { Alert, AppState, Linking, Pressable, ScrollView, StyleSheet, Switch, Text, View } from 'react-native';
import { SafeAreaProvider, SafeAreaView } from 'react-native-safe-area-context';
import { Feather } from '@expo/vector-icons';
import { StatusBar } from 'expo-status-bar';
import { randomUUID } from 'expo-crypto';
import { NATIVE_WATCHDOG_MS, RecorderController } from './src/controller';
import { getStore, makeNativePort } from './src/native';
import { FRESH_MS, type Mode } from './src/sample';
import { BatteryPanel } from './src/BatteryPanel';
import { batteryNative } from './src/batteryNative';
import { batteryStartRunForReport, closeBatteryGpsWindow, withBatteryGpsStartGuard } from './src/batteryGpsBoundary';

const phaseLabels = { boot: 'Initializare', idle: 'Sesiune inchisa', starting: 'Pornire', recording: 'Inregistrare', stopping: 'Oprire', error: 'Atentie necesara' };
const shutdownLabels = { not_checked: 'Neverificata', not_attempted: 'Start curent: fara incercare nativa', pending: 'In curs', api_acknowledged: 'API confirmat / hardware neverificat', unconfirmed: 'Oprire nativa neconfirmata', failed: 'Eroare / neconfirmata' };

function RecorderScreen() {
  const controller = useRef<RecorderController | null>(null);
  const batteryStartRun = useRef<string | null>(null);
  const native = useRef(withBatteryGpsStartGuard(makeNativePort(), () => batteryStartRun.current, batteryNative.checkGpsStart));
  const visible = useRef(false);
  const fallbackPending = useRef(false);
  const fallbackUnconfirmed = useRef(false);
  const [, render] = useState(0);
  const [fatal, setFatal] = useState<string | null>(null);
  const [mode, setMode] = useState<Mode>('foreground');
  const [consent, setConsent] = useState(false);
  const consentNow = useRef(consent); consentNow.current = consent;
  const [batteryGate, setBatteryGate] = useState(false);
  const [batteryModeLock, setBatteryModeLock] = useState(false);
  const stopWithoutStore = () => {
    if (fallbackPending.current) return;
    fallbackPending.current = true;
    const timer = setTimeout(() => {
      fallbackUnconfirmed.current = true;
      if (visible.current) setFatal('sqlite_unavailable_native_shutdown_unconfirmed');
    }, NATIVE_WATCHDOG_MS);
    void native.current.stop().then(() => {
      if (visible.current && !fallbackUnconfirmed.current) setFatal('sqlite_unavailable_stop_api_returned_hardware_unverified');
    }, () => {
      fallbackUnconfirmed.current = true;
      if (visible.current) setFatal('sqlite_unavailable_native_shutdown_unconfirmed');
    }).finally(() => { clearTimeout(timer); fallbackPending.current = false; });
  };
  useEffect(() => {
    let mounted = true;
    visible.current = true;
    let instance: RecorderController | null = null;
    const refresh = () => { if (mounted) render(n => n + 1); };
    try {
      instance = new RecorderController(getStore(), native.current, Date.now, randomUUID, refresh);
      controller.current = instance;
      void instance.initialize().catch(() => { if (mounted) setFatal('initialization_failed'); });
    } catch {
      setFatal('sqlite_unavailable');
      stopWithoutStore();
    }
    const listener = AppState.addEventListener('change', state => {
      if (state === 'active' || state === 'inactive' || state === 'background') void controller.current?.lifecycle(state);
    });
    const timer = setInterval(() => { void controller.current?.check(); refresh(); }, 2000);
    return () => {
      mounted = false; visible.current = false; listener.remove(); clearInterval(timer);
      try { batteryNative.cancelCurrentSync(); } catch { /* Preserve native durability faults; GPS Stop still runs. */ }
      void instance?.stop('ui_unmounted');
    };
  }, []);
  const state = controller.current?.state;
  let snapshot;
  try { snapshot = controller.current ? getStore().snapshot() : null; } catch { snapshot = null; }
  const busy = !state || ['boot', 'starting', 'stopping', 'recording'].includes(state.phase);
  const blocked = busy || batteryGate || !!state?.watchdog || state?.nativeShutdown === 'unconfirmed' || !!snapshot?.shutdownUnconfirmed || !!snapshot?.nativeCleanupPending;
  const latest = snapshot?.currentSample;
  const age = latest?.captured_at ? Math.max(0, Date.now() - latest.captured_at) : null;
  const start = () => {
    if (!consent || blocked || (batteryModeLock && mode !== 'background')) return;
    let trial: string | null;
    try { trial = batteryStartRunForReport(batteryNative.available ? batteryNative.peek() : null, mode); }
    catch { return; }
    const continueStart = () => {
      const owner = controller.current;
      if (!visible.current || AppState.currentState !== 'active' || !consentNow.current || !owner || !['idle', 'error'].includes(owner.state.phase) || owner.state.watchdog) return;
      try {
        if (batteryStartRunForReport(batteryNative.available ? batteryNative.peek() : null, mode) !== trial) return;
      } catch { return; }
      batteryStartRun.current = trial;
      void owner.start(mode);
    };
    if (mode === 'background') {
      Alert.alert('Acord pentru GPS in fundal', 'Pozitiile raman in SQLite pe acest dispozitiv. Sistemul poate deschide Settings pentru acces permanent. Colectarea cu ecranul blocat depinde de sistem si ramane neverificata.', [
        { text: 'Renunta', style: 'cancel' },
        { text: 'Continua', onPress: continueStart },
      ]);
    } else continueStart();
  };
  const stop = () => {
    try {
      if (batteryNative.available) {
        const report = batteryNative.peek();
        if (report.runId && report.kind === 'full' && !['completed', 'incomplete'].includes(report.phase)) {
          void closeBatteryGpsWindow(controller.current, report, batteryNative.stop).catch(() => {
            if (visible.current) setFatal('battery_stop_unconfirmed');
          });
          return;
        }
      }
    } catch { if (visible.current) setFatal('battery_stop_unconfirmed'); }
    if (controller.current) void controller.current.stop(); else stopWithoutStore();
  };
  return <SafeAreaView style={s.safe}>
    <StatusBar style="dark" />
    <ScrollView contentContainerStyle={s.body}>
      <View style={s.heading}><Feather name="map-pin" size={25} color="#16734b" /><View style={s.grow}><Text style={s.title}>ProDelivery GPS</Text><Text style={s.muted}>Recorder local / proba tehnica</Text></View></View>
      <View style={s.status}><View style={[s.dot, { backgroundColor: state?.phase === 'recording' ? '#16734b' : '#777' }]} /><Text style={s.statusText}>{state ? phaseLabels[state.phase] : 'Initializare'}</Text><Text style={s.muted}>Hardware neverificat</Text></View>
      {(fatal || state?.error || snapshot?.fault) && <Text accessibilityRole="alert" style={s.error}>{fatal ?? state?.error ?? snapshot?.fault}</Text>}
      {state?.notice && <Text accessibilityRole="alert" style={s.warning}>{state.notice}</Text>}
      {state?.watchdog === 'cancellation_pending' && <Text accessibilityRole="alert" style={s.warning}>Anularea Start asteapta raspunsul verificarii sau permisiunii OS. Start curent nu a incercat pornirea senzorului. Rezolvati promptul OS sau verificati setarile aplicatiei. Start ramane blocat pana la terminarea cozii; acordarea tardiva a permisiunii nu porneste inregistrarea.</Text>}
      {(state?.watchdog === 'start' || state?.watchdog === 'stop') && <Text accessibilityRole="alert" style={s.error}>{state.watchdog === 'start' ? 'Pornirea' : 'Oprirea'} a depasit intervalul diagnostic de {NATIVE_WATCHDOG_MS / 1000} secunde. Expirarea nu anuleaza operatia nativa. Curatarea ramane serializata, inclusiv la un raspuns tardiv.</Text>}
      {(state?.nativeShutdown === 'unconfirmed' || fallbackUnconfirmed.current || (snapshot?.shutdownUnconfirmed && !['recording', 'starting'].includes(state?.phase ?? ''))) && <Text accessibilityRole="alert" style={s.error}>{snapshot && !snapshot.active_session ? 'Sesiunea locala este inchisa.' : 'Inchiderea sesiunii locale nu este confirmata.'} Oprirea GPS nativ nu este confirmata. Start blocat. Este necesara oprirea aplicatiei din sistem si verificarea indicatorilor si permisiunilor de locatie de catre proprietar. Pastrati dovezile diagnostice; relansarea si un raspuns API tardiv nu confirma recuperarea.</Text>}
      <View accessibilityRole="radiogroup" style={s.segment}>
        {(['foreground', 'background'] as const).map(value => <Pressable key={value} accessibilityRole="radio" accessibilityState={{ checked: mode === value, disabled: busy || batteryModeLock }} disabled={busy || batteryModeLock} onPress={() => setMode(value)} style={[s.mode, mode === value && s.selected]}><Feather name={value === 'foreground' ? 'sun' : 'moon'} size={18} color={mode === value ? '#fff' : '#222'} /><Text style={mode === value ? s.white : s.normal}>{value === 'foreground' ? 'Prim-plan' : 'Fundal'}</Text></Pressable>)}
      </View>
      <View style={s.row}><Text style={[s.normal, s.grow]}>Consimt la stocarea GPS pe acest dispozitiv</Text><Switch accessibilityLabel="Consimtamant stocare GPS locala" value={consent} disabled={busy} onValueChange={setConsent} trackColor={{ true: '#16734b' }} /></View>
      <View style={s.actions}>
        <Pressable accessibilityRole="button" disabled={blocked || !consent || !!fatal} accessibilityState={{ disabled: blocked || !consent || !!fatal }} onPress={start} style={[s.button, s.start, (blocked || !consent || !!fatal) && s.disabled]}><Feather name="play" color="#fff" size={20} /><Text style={s.white}>Start</Text></Pressable>
        <Pressable accessibilityRole="button" disabled={state?.phase === 'stopping'} accessibilityState={{ disabled: state?.phase === 'stopping' }} onPress={stop} style={[s.button, s.stop, state?.phase === 'stopping' && s.disabled]}><Feather name="square" color="#fff" size={18} /><Text style={s.white}>Stop</Text></Pressable>
      </View>
      <View style={s.section}>
        <Text style={s.sectionTitle}>Sesiune</Text>
        <Text selectable style={s.code}>{state?.sessionId ?? 'Nicio sesiune activa'}</Text>
        <Metric label="Oprire nativa" value={state ? shutdownLabels[state.nativeShutdown] : 'Neverificata'} />
        <Metric label="Sesiune SQLite" value={snapshot ? snapshot.active_session ? 'Activa' : 'Inchisa' : 'Stare necunoscuta'} />
        <Metric label="Permisiune prim-plan" value={state?.permissions?.foreground ? 'Acordata' : 'Neacordata'} />
        <Metric label="Permisiune fundal" value={state?.permissions?.background ? 'Acordata' : 'Neacordata'} />
        <Metric label="Servicii locatie" value={state?.permissions?.services ? 'Pornite' : 'Oprite / necunoscute'} />
        <Metric label="Precizie permisa" value={state?.permissions?.precision ?? 'Necunoscuta'} />
        <Pressable accessibilityRole="button" accessibilityLabel="Deschide setarile aplicatiei" onPress={() => { void Linking.openSettings().catch(() => setFatal('settings_unavailable')); }} style={s.settings}><Feather name="settings" size={18} color="#333" /><Text style={s.normal}>Setari aplicatie</Text></Pressable>
      </View>
      <View style={s.section}>
        <Text style={s.sectionTitle}>SQLite local</Text>
        <Metric label="Evenimente / limita" value={`${snapshot?.count ?? 0} / ${snapshot?.limit ?? 1000}`} />
        <Metric label="Sesiuni / limita" value={`${snapshot?.sessionCount ?? 0} / 100`} />
        <Metric label="Duplicate / respinse / tardive" value={`${snapshot?.duplicates ?? 0} / ${snapshot?.rejected ?? 0} / ${snapshot?.late ?? 0}`} />
        <Metric label="Varsta ultimei observatii" value={age === null ? 'Nicio observatie' : `${Math.floor(age / 1000)} s${age > FRESH_MS ? ' / stale' : ''}`} />
        <Metric label="Eligibilitate acum" value={state?.phase === 'recording' && state.permissions?.precision === 'precise' && state.permissions.foreground && latest?.eligible && age !== null && age <= FRESH_MS ? 'Criterii locale indeplinite' : 'Neeligibil / neverificat'} />
      </View>
      <View style={s.section}>
        <Text style={s.sectionTitle}>Ultimele evenimente</Text>
        {snapshot?.latest.length ? snapshot.latest.map((event, i) => <View style={s.event} key={i}><Text style={s.normal}>#{event.sequence} / {event.source} / {event.kind}</Text><Text style={s.muted}>{event.flags}</Text><Text style={s.muted}>{new Date(event.received_at).toLocaleTimeString()} / precizie {event.accuracy === null ? '?' : `${event.accuracy} m`}</Text></View>) : <Text style={s.muted}>Fara evenimente</Text>}
      </View>
      <BatteryPanel getController={() => controller.current} getBatteryStartRunId={() => batteryStartRun.current} onGateChange={setBatteryGate} onModeLockChange={setBatteryModeLock} onFullStart={() => { batteryStartRun.current = null; setMode('background'); setBatteryModeLock(true); }} />
    </ScrollView>
  </SafeAreaView>;
}
function Metric({ label, value }: { label: string; value: string }) {
  return <View style={s.metric}><Text style={[s.muted, s.grow]}>{label}</Text><Text style={s.value}>{value}</Text></View>;
}
export default function App() { return <SafeAreaProvider><RecorderScreen /></SafeAreaProvider>; }
const s = StyleSheet.create({
  safe: { flex: 1, backgroundColor: '#f7f8fa' }, body: { padding: 20, gap: 18, width: '100%', maxWidth: 640, alignSelf: 'center' },
  heading: { flexDirection: 'row', gap: 12, alignItems: 'center' }, grow: { flex: 1, minWidth: 0 },
  title: { fontSize: 23, fontWeight: '700', color: '#16181d' }, muted: { fontSize: 13, color: '#58606e', lineHeight: 19 }, normal: { fontSize: 15, color: '#20242b' },
  status: { flexDirection: 'row', alignItems: 'center', gap: 8, flexWrap: 'wrap' }, dot: { width: 8, height: 8, borderRadius: 4 }, statusText: { fontSize: 15, fontWeight: '600', marginRight: 8 },
  row: { flexDirection: 'row', gap: 10, alignItems: 'center' }, segment: { flexDirection: 'row', backgroundColor: '#e6e9ec', borderRadius: 6, padding: 3 },
  mode: { flex: 1, minHeight: 46, padding: 8, flexDirection: 'row', gap: 8, alignItems: 'center', justifyContent: 'center', borderRadius: 4 }, selected: { backgroundColor: '#303940' },
  actions: { flexDirection: 'row', gap: 12 }, button: { flex: 1, minHeight: 48, borderRadius: 6, flexDirection: 'row', alignItems: 'center', justifyContent: 'center', gap: 10 },
  start: { backgroundColor: '#16734b' }, stop: { backgroundColor: '#a3313b' }, disabled: { opacity: 0.4 }, white: { color: '#fff', fontSize: 15, fontWeight: '600' },
  section: { borderTopColor: '#d6dce1', borderTopWidth: 1, paddingTop: 16, gap: 10 }, sectionTitle: { fontSize: 17, fontWeight: '600' },
  metric: { flexDirection: 'row', gap: 12, alignItems: 'flex-start' }, value: { maxWidth: '50%', fontSize: 13, color: '#242a32', textAlign: 'right', lineHeight: 19 },
  code: { fontSize: 12, color: '#434b55' }, error: { fontSize: 14, color: '#a3313b', backgroundColor: '#fcecef', padding: 12, borderRadius: 4 },
  warning: { fontSize: 14, color: '#775608' }, settings: { flexDirection: 'row', alignItems: 'center', gap: 10, minHeight: 44 },
  event: { gap: 2, paddingVertical: 6 },
});
