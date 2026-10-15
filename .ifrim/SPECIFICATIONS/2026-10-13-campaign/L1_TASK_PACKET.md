# ProDelivery — L1: contract actualizat și matrice de acceptare

ID: PD-CAMPAIGN-20261013-L1. Versiune documentară: 1.0-candidate. Data: 2026-10-13, Europe/Bucharest.

Stare: CANDIDAT PENTRU REVIEW. Lot exclusiv documentar; nu declară implementarea aplicației, executarea testelor funcționale, activarea sau închiderea unei etape comerciale.

## Identitate, autoritate și limite

Proiect activ: `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery`.

Directorul acestui lot: `C:\Users\mihai\OneDrive\Documente\Mutare Proiecte de pe Emergent\pd-campaign-20261013\l1`.

Catalin a aprobat implementarea planului extins L1–L8 și continuarea prin **loturi independente**: se epuizează lucrările disponibile în etapa curentă, apoi se continuă cele independente din etapa următoare. O etapă care depinde de client/dispozitiv rămâne explicit deschisă. Această instrucțiune curentă, transmisă de coordonator în campania din 13 octombrie, supersedează numai blocarea absolută a progresului din vechile instrucțiuni secvențiale 1 → 2 → 3. Nu renumerotează etapele, nu adoptă politici lipsă și nu transformă aprobarea implementării în aprobare live.

Rutare: Codex și agenți interni OpenAI; owner documentar `astra_stage_plan`; ROOT integrează după review/QA distincte. Fără OpenClaw, Claude Code, mutații Agent Hub, servicii externe, Git writes, pornire aplicație/DB, dispozitive, secrete sau date reale în L1. Ownerul scrie numai fișiere noi în directorul de mai sus. ROOT deține integrarea în proiect și `NEXT_SESSION.md`.

## Livrabile

1. `L1_REQUIREMENTS_DELTA_MATRIX.md`: cele 11 răspunsuri din al treilea set, cerințe precedente păstrate, ancore de cod/specificație, diferențe, acceptanțe și dependențe.
2. `L1_PROPOSED_SPEC_ADDITIONS.md`: blocuri aditive și ancore exacte pentru specificațiile existente, fără aplicarea lor aici. Include contractul sarcinii obligatorii și compatibilitatea cu operațiile existente.
3. `L1_SOURCE_AND_OUTPUT_MANIFEST.json`: lista finită de surse citite, hashuri la final și hashurile celor trei documente; nu este audit al întregului proiect.

## Registrul seturilor de întrebări

| Set | Dovadă | Stare și utilizare |
| --- | --- | --- |
| Client 2026-10-08, 15 întrebări | `LOOP_REPORTS/2026-10-08-client-operational-rules-intake.md` | Primit; se păstrează ce nu a fost supersedat explicit. |
| Client 2026-10-09, 11 întrebări | `LOOP_REPORTS/2026-10-09-client-operational-rules-followup.md` | Primit; numerotare distinctă de primul/al treilea set. |
| Client 2026-10-12, 11 întrebări | `LOOP_REPORTS/2026-10-12-client-operational-rules-third-set.md` | Primit și integrat documentar; Q7/Q8 retrase, Q10 obligatoriu. Aceste Q1–Q11 sunt cele din matricea L1. |
| Dezvoltator 2026-10-12, D1–D5 | `LOOP_REPORTS/2026-10-12-developer-answers-gradual-pilot.md` | Primit; D5 nu adoptă încă politica sau duratele datelor. |
| Client, grilă ulterioară de 18 întrebări | Instrucțiunea curentă a coordonatorului | Răspunsuri neprimite. Textul exact nu este disponibil în contextul compactat și nu a fost găsit prin căutarea focalizată în `TASK_PACKETS`, `SPECIFICATIONS`, `LOOP_REPORTS` după `18 întrebări`, `18 intrebari`, `Q18`, `Întrebarea 18`, `Intrebarea 18`, `grilă.*18`, `grila.*18`. Nu afirmăm că lipsește din orice arhivă; nu reconstruim și nu remapăm întrebările după presupuneri. |

Nu retrimitem automat chestionarele sau Q7/Q8. Dependențele numite în matrice provin din rapoartele disponibile, nu reprezintă transcrierea presupusă a grilei de 18.

## Baseline de păstrat

- A0–A8 sunt închise local. A7 este review/QA/handoff, nu Etapa 7 comercială. Transportul recovery, parserul, executorul, prezentarea/citirile restaurantului și A8 pregătire/READY nu se reconstruiesc. A8 are markerul de admitere implicit dezactivat; operațiile deja admise rămân recuperabile. Sursă: `LOOP_REPORTS/2026-10-11-restaurant-refactor-final.md:1–20`.
- D0 static este închis: inventarul consumatorilor/writerilor și diferențelor față de v0.3 există. Sursa aplicației rămâne singulară; inventarul nu închide D1 sau 1/2/5/10. Sursă: `LOOP_REPORTS/2026-10-11-stage1-d0-inventory.md:3–11`.
- Close-day operațional, incidentele factuale, auditul și recovery au închidere locală ulterioară BOOST03. Close-day păstrează `accepting_orders`/`pause_until`, nu blochează singur comenzi noi/active și nu introduce cutoff. Sursă: `LOOP_REPORTS/2026-10-10-stage12-independent-closure.md:3–19`; `backend/routers/restaurants.py:257–278,330`. Vechiul P1 PARTIAL/OPEN nu descrie acest baseline.
- BOOST și S2-01…06 rămân reutilizabile în limitele dovezilor lor. O execuție veche nu este rerulare curentă; FAIL/SKIP istorice și testele protejate nu se șterg sau reetichetează.
- Etapele comerciale 1 și 2 rămân deschise. Proba Android a8c este `INCOMPLETE/heartbeat_gap`; HONOR a fost restaurat, servicii proprii absente în dovada de recuperare. Bateria, exteriorul și offline complet au acceptanțe restante. Nu reînarmăm telefonul. Sursă: `NEXT_SESSION.md:1–19`.
- Lipsa unui Mac local nu este tratată ca imposibilitate absolută a pregătirii iOS: instrucțiunea curentă permite planificarea traseului cloud build. Conturile, costurile/accesul, buildul efectiv, testul fizic și publicarea sunt rezultate/gate-uri distincte; L1 nu pornește cloud build.

## Numerotarea comercială păstrată

Conform `EXECUTION_PLAN_2026-09-26.md:36–49`:

| Etapa | Rezultat |
| --- | --- |
| 1 | Inventar actual, reguli si specificatie inchisa |
| 2 | Comenzi si administrare |
| 3 | Panou restaurant |
| 4 | OCR si conector API initial |
| 5 | Aplicatie livrator |
| 6 | GPS si harta |
| 7 | Alocare si ordinea opririlor |
| 8 | Notificari, exceptii, rapoarte simple |
| 9 | Infrastructura si securitate |
| 10 | Pilot, publicare, instruire, predare |

L1–L8 sunt loturi de execuție, nu alte opt etape comerciale.

## Delimitarea deciziilor

Clientul/firma confirmă grilele monetare, cine suportă excepțiile, mecanismul achitării numerarului restant, cazul A/B/C și limitele operaționale. Restaurantul proprietar decide produsele/refacerea, returul/păstrarea și sumele de colectat. Dezvoltatorul proiectează validarea, identitățile, tranzacțiile, retry/recovery, versionarea și UI; acestea nu cer inventarea unei politici comerciale.

Pentru date, echipa propune scopuri tehnice, acces, retenție pe categorii, arhivare/ștergere, backup/restore și monitorizare. Firma validează nevoile/instrucțiunile; nu adoptăm durate sau atribuții juridice prin L1. Furnizorul și accesul API sunt în curs de obținere; fluxul importului și outbound statuses se decid după analiza sa. Costurile serviciilor se prezintă înaintea activării. Conturile Apple/Google sunt ale firmei clientului și trebuie pregătite. Pilotul planificat începe cu 2–3 restaurante fără reducerea capacității/funcțiilor contractate. Sursă: `LOOP_REPORTS/2026-10-12-developer-answers-gradual-pilot.md:7–18`.

## Contract comun pentru loturile următoare

Fiecare lot începe prin verificarea lacunei pe sursa curentă și reutilizează ceea ce este deja închis. Contractele financiare și de dispatch folosesc versiuni explicite, snapshoturi imuabile, identitatea semantică a operației și capabilități distincte de activare. Datele sintetice și valorile de test sunt marcate ca atare. O valoare neconfirmată nu primește fallback zero/10%; distanța absentă nu devine zero. Un zero explicit al restaurantului este diferit de o valoare lipsă.

Nu schimbăm semantica înregistrărilor vechi, fingerprintul unei intenții pending, ledgerul sau cheile sub aceeași versiune. Adaptarea între versiuni cere contract, lookup/replay și compatibilitate pentru toate rolurile; fără două protocoale care admit aceeași intenție. Oprirea admisiei noi păstrează recovery pentru operațiile deja admise. Migrarea/backfill, markerii, indexurile/topologia live, datele reale, deploy/publicarea și serviciile cu plată au gate-uri distincte.

## Acceptarea L1 și handoff

- `L1-A01`: toate cele 11 răspunsuri au rând propriu; setul de 18 este distinct și nu este reconstruit.
- `L1-A02`: fiecare rând are autoritate, ancoră de cod/specificație, comportament de păstrat/delta, acceptanță observabilă și dependențe.
- `L1-A03`: Q10 nu mai admite refuz comercial; ACK-ul tehnic, refuzul unei operații invalide și incidentul offline sunt separate. Timeoutul ACK nu poate elibera automat o sarcină obligatorie comisă.
- `L1-A04`: Q7/Q8 nu elimină decontarea/close-day; A0–A8, D0 și close-day local închis sunt recunoscute; etapele 1/2/7 nu sunt declarate închise.
- `L1-A05`: amendamentele sunt propuneri aditive cu ancore, fără editarea proiectului activ; baselineul și rezultatele istorice rămân intacte.
- `L1-A06`: valori sintetice, versiuni și gate-uri sunt explicite; responsabilitățile client/dezvoltator și dependențele iOS/API/costuri/date sunt delimitate.
- `L1-A07`: reviewerul și QA distincte verifică artefactele finale; ownerul nu își atribuie verdict independent. Manifestul identifică exact fișierele livrate și sursele finite.

ROOT decide integrarea după review/QA, cu backup/hashguard pentru documentele active. Închiderea L1 este documentară și nu închide Etapa 1 sau 2. L2–L8 avansează pe loturi independente în ordinea aprobată; dacă lipsesc numai decizii client/probe fizice, se păstrează explicit `open_external_dependency` pentru criteriul respectiv, fără blocarea muncii independente.

Regula de resurse a campaniei: peste 20% disponibil — loturi finite normale; 10–20% — loturi mici, QA și handoff; aproximativ 10% — checkpoint și oprire. ROOT citește usage după lot/dinamic; cota este comună contului, nu atribuie tot consumul acestei campanii și nu execută lucru artificial pentru atingerea pragului. L1 nu citește sau modifică usage și nu pornește o automatizare.
