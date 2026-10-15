# Observator local Android pentru proba bateriei

Modul Expo local autolinkat din `modules/prodelivery-battery`; nu schimbă identitatea aplicației. Nu colectează poziții, nu citește/scrie baza GPS, nu pornește/oprește GPS și nu folosește rețea, ADB, wake lock, optimizări globale sau pornire după reboot. Datele sunt private aplicației, în `files/prodelivery-battery-v1/<runId>.jsonl`; backup-ul aplicației rămâne dezactivat. Jurnalele nu sunt șterse sau înlocuite.

## API

Numele native este `ProDeliveryBattery`. Cele cinci operații de măsurare întorc JSON serializat; verificarea de disponibilitate `foregroundReady` întoarce un boolean. Erorile de precondiție se aruncă:

- `foregroundReady()` — verificare sincronă, fără efecte secundare: activitatea există, nu se închide, nu este distrusă și are focusul ferestrei. UI poate aștepta limitat revenirea focusului după dialogul de permisiuni. Nu pornește măsurarea, nu scrie jurnalul și nu înlocuiește guard-ul identic din `start`.
- `start(runId, kind)` — `kind` este `pilot` sau `full`; pornire numai cu activitatea vizibilă și notificări permise. Același ID este idempotent; alt ID nu poate înlocui un observator activ.
- `status()` — recuperează ultimul jurnal. Un proces relansat marchează o sesiune neîncheiată `incomplete/process_interrupted`; nu reia măsurarea sau GPS.
- `checkGpsStart(runId)` — guard sincron, imediat după permisiunile controllerului și înainte de apelul lui GPS Start. Salvează un snapshot real și cere aceeași probă full activă, `awaiting_gps`, nealimentată, fără întreruperi/deadline depășit și cu serviciul GPS încă oprit. Nu schimbă faza sau sesiunea și nu pornește GPS. Dacă permisiunile au ținut UI blocat până după expirare, refuză pornirea.
- `markPhase(runId, sessionId)` — numai după ce controllerul existent confirmă efectiv Start GPS în fundal. ID-ul sesiunii este corelare cu controllerul, nu dovadă că senzorul GPS a produs poziții.
- `stop(runId, reason)` — `gps_stopped` numai după Stop GPS confirmat, sau `cancelled`. Oprirea acestui modul nu oprește controllerul GPS.

`runId`: `pd-battery-[a-z0-9][a-z0-9-]{7,80}`. `sessionId`: `[A-Za-z0-9_-]{1,100}`. Apelurile sunt protejate în jurnal cu același ID; UI trebuie să protejeze și răspunsurile întârziate.

## Succesiunea măsurării

`waiting_unplug` cere 20 secunde consecutive confirmate fără alimentare (mască plug zero și BatteryManager.isCharging false). Conectarea în această perioadă resetează gate-ul. Necunoscute, revenirea ceasului monoton sau pauze mai mari de 25 secunde fac proba incompletă.

După gate, pilotul măsoară 30 secunde de repaus și salvează `completed`; proba scurtă fără USB durează aproximativ 50 secunde. Aceasta verifică observatorul, nu acceptarea probei lungi.

Proba completă înregistrează 900 secunde `idle`, apoi `awaiting_gps`; UI cere Start GPS prin controllerul existent. `markPhase` folosește un nou snapshot real drept baseline, apoi înregistrează 900 secunde `gps`. Rezultatul durabil trece în `awaiting_stop`: notificarea cere revenirea și Stop GPS. Numai după Stop confirmat, `stop(..., 'gps_stopped')` produce `completed`.

Între cele două ferestre se înregistrează și timpul de predare, dar el nu intră în durata niciunei ferestre. Orice alimentare în `idle`, `awaiting_gps` sau `gps` face proba incompletă. După închiderea durabilă a ferestrei GPS, reconectarea USB nu invalidează retroactiv ferestrele salvate. Există patru endpoint-uri reale, nu un singur B presupus comun.

## Validitate și limite

Observatorul citește bateria la 10 secunde, plus evenimente de baterie/încărcare/ecran. Duratele folosesc `SystemClock.elapsedRealtime`, care include somnul; ora calendaristică se păstrează separat. Nu există recuperare inventată a intervalelor lipsă. Deadline-ul observatorului este 45 minute și se verifică la observațiile reale; nu reprezintă un deadline pentru GPS. Dacă JS este suspendat, utilizatorul trebuie să revină în aplicație pentru Stop; controllerul și notificarea GPS rămân independente.

Procentul bateriei este grosier. Charge counter este opțional și necunoscut când proprietatea nu este suportată. Niciun rezultat nu reprezintă o estimare precisă a energiei sau acceptare comercială GPS. Ecranul este observat, nu forțat; starea lui trebuie inclusă în interpretarea probei.

Fiecare snapshot include `ownGpsServiceStarted: boolean | null`: observare Android `ActivityManager.getRunningServices` pentru clasa exactă `expo.modules.location.services.LocationTaskService` a propriului UID/package și flagul `started`. Un serviciu doar legat, fără `started`, se consideră oprit. `waiting_unplug` și `idle` cer false; `gps` cere true la fiecare citire; necunoscut înseamnă probă incompletă. `markPhase` cere confirmarea controllerului plus această observare fresh; Stop final cere serviciul oprit. Aceasta confirmă numai prezența serviciului propriu la observațiile reale, nu faptul că GPS a produs continuu poziții. Identificatorii serviciilor nu sunt salvați. Clasa a fost verificată în sursa instalată Expo Location 57.0.20 și manifestul acesteia.

Notificarea specialUse este vizibilă. Serviciul este `START_NOT_STICKY`, fără auto-restart. Jurnalul este append-only, sincronizat pe disc pentru fiecare eveniment. Limite: 1 MiB/jurnal, 4096 snapshot-uri și 64 probe păstrate; atingerea limitei cere o decizie explicită despre arhivare, nu șterge date. Observatorul și fsync-ul produc propriul consum, prezent în ambele faze. Doze sau oprirea procesului pot cauza probe incomplete; nu se maschează prin wake lock. Deadline-ul de 45 minute este verificat la observațiile reale; un callback întârziat de somnul dispozitivului nu garantează terminarea serviciului exact la minutul 45.

API-uri documentate: [BatteryManager](https://developer.android.com/reference/android/os/BatteryManager), [Foreground service specialUse](https://developer.android.com/about/versions/14/changes/fgs-types-required#special-use), [observarea serviciilor proprii](https://developer.android.com/reference/android/app/ActivityManager#getRunningServices(int)), [ceasurile Android](https://developer.android.com/reference/android/os/SystemClock), [Module Expo locale](https://docs.expo.dev/modules/get-started/). Declarația specialUse este pentru acest instrument local și nu reprezintă aprobare Google Play.

## Metadate opționale de diagnostic vc6

Această copie separată adaugă numai obiectul opțional `diagnostic` la evenimentele `sample` din jurnalul brut. Cele opt câmpuri ale snapshot-ului, API-ul bridge, protocolul, fazele, pragurile și controlul GPS rămân identice. Nu se adaugă thread, alarmă, wake lock, excepție de optimizare sau sursă nouă de observații. Metadatele nu intră în status, ferestre sau calculul verdictului; recuperarea jurnalului folosește aceleași snapshot-uri și ignoră obiectul `diagnostic`.

Obiectul are exact cinci câmpuri scalare: `trigger`, `elapsedBeforeMs`, `uptimeBeforeMs`, `uptimeAfterMs`, `elapsedAfterMs`. Trigger-ul este numai `heartbeat`, `battery_changed`, `screen_on`, `screen_off`, `charging` sau `discharging`, provenit din callback-ul existent. Cele patru ceasuri sunt numere întregi sigure JSON între 0 și 9007199254740991. Ambele perechi înainte/după sunt monotone, iar `snapshot.elapsedMs` trebuie să fie în intervalul `elapsedBeforeMs..elapsedAfterMs`. Câmpuri suplimentare, valori lipsă, tipuri nepermise, numere fracționare/negative/nesigure sau ordini invalide duc la omiterea metadatelor; observația originală este salvată și evaluată identic. Absența ori omiterea înseamnă **UNKNOWN**, nu zero și nu o dovadă de continuitate. Obiectul valid este copiat înainte de serializare.

Ordinea reală este `elapsedRealtime` înainte → `uptimeMillis` înainte → colectarea existentă a snapshot-ului → `uptimeMillis` după → `elapsedRealtime` după. Duratele din aceeași pereche descriu numai colectarea snapshot-ului. Nu includ așteptarea în coada main looper înainte de callback, așteptarea lock-ului jurnalului sau append/fsync. Citirile adiacente au granularitate de milisecundă și nu sunt simultane; diferențele între ceasuri trebuie interpretate cu toleranță, fără egalitate exactă.

Între două observații, elapsed care avansează mult mai mult decât uptime este compatibil cu suspendarea procesorului; avansul asemănător al ambelor ceasuri în timp ce lipsesc callback-uri indică o întârziere în timp activ. Aceste date singure nu identifică Doze, o politică OEM, blocarea main thread sau cauza exactă. Observer-ul folosește în continuare același Handler pe main looper și poate eșua cu `heartbeat_gap`; instrumentarea nu repară și nu ascunde pauzele. Metadatele adaugă puțin lucru și spațiu jurnalului, cu aceeași limită de 1 MiB păstrată. Nu se salvează poziții, identificatori de dispozitiv/proces/serviciu sau alte date în acest obiect.

Vezi [Handler.postDelayed](https://developer.android.com/reference/android/os/Handler#postDelayed(java.lang.Runnable,long)) și [SystemClock](https://developer.android.com/reference/android/os/SystemClock) pentru diferența dintre uptime și elapsedRealtime.


## GPS admission budget — vc7

- New start journals retain schemaVersion 1 and include `gpsAdmissionPolicy: "full_window_reserve_v1"`. Missing historical policy keeps prior replay semantics. Explicit unsupported/malformed policy fails closed as journal corruption; the capture is not rewritten.
- Full trials require strictly more than 925000 ms (900000 ms GPS window + existing 25000 ms maximum sample gap) from the native monotonic lifetime at both fresh `checkGpsStart` and fresh `markPhase`. Existing timing constants and sample limits are unchanged.
- Pre-start refusal first durably records the actual sample and an existing interrupted event with `gps_budget_insufficient`. A late marker first durably records its attempted GPS marker, then terminalizes before assigning the diagnostic GPS session and throws the same reason, allowing the parent controller to stop only its owned live session.
- Module errors stop only this diagnostic observer for a terminal or durability-failed matching run. Cleanup failures are attached to the original error rather than masking it. They do not directly stop location services or another app. Parent GPS cleanup continues through the existing owned controller boundary.
- `gpsAdmissionPolicy`, `remainingRunMs`, `gpsAdmissionRequiredMs` are optional/null for historical reports. The remaining native budget is as of `lastSnapshot.elapsedMs`; it is presentation information, not a JavaScript or wall-clock countdown. Full newpolicy reports require exact 925000 ms, and unsafe/rollback monotonic observations yield unknown remaining budget. Pilot has no GPS budget.
- Historical f432 is still INCOMPLETE / observer_deadline; its raw capture and replay semantics are preserved. Passing host tests does not certify battery autonomy, actual Android cleanup, or the full physical test.
