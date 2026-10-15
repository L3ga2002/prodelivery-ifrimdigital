# ProDelivery — pachet Etapa 1 / D0

Data: 2026-10-11. Obiectiv: inventarul sursei actuale și reconcilierea PD-DISPATCH-01 v0.3, păstrând toate funcționalitățile și ordinea comercială 1 → 2 → 3.

Routing: echipa internă Codex, conform directivei proiectului. Owner backend, owner/reviewer frontend și QA independent; coordonatorul păstrează exclusiv controlul ADB. OpenClaw/Claude nu sunt invocate. Checkout-ul local `main` și modificările existente sunt păstrate, fără scrieri Git.

Scope autorizat: citire statică a surselor backend/frontend, hashuri, ancore de funcții/linii, teste nominale și prototipuri istorice. Pregătirea A8, feed-ul livratorului, ledgerul, recovery-ul, disponibilitatea, incidentele, harta și scrierile maintenance sunt inventariate. Nicio implementare D1, activare multi, migrare, DB, secret, build, preview, API sau ADB în D0.

Ieșiri: backend v3 + manifest, frontend v3 + manifest, reconciliere v2, review/QA independente, integritate mobile42/protected140 și documente noi în `.ifrim`. Publicarea locală acceptă numai inputuri fixate prin SHA256 și destinații noi; nu suprascrie sau șterge date ori documente existente.

Criteriu de închidere D0: dovezi statice și copiere byte-exact verificate; testele nominale rămân NOT_RUN. Acesta închide numai inventarul, nu o etapă comercială sau proba de baterie. Orice implementare viitoare cere pachet separat și verificare graduală pentru 1/2/5/10 comenzi.

Prioritatea telefonului rămâne în NEXT_SESSION și raportul bateriei; proba lungă f432 era PENDING în checkpoint-ul din 20:12 UTC, cu restaurare HONOR obligatorie. D0 nu schimbă starea sau setările telefonului. iOS și clientul rămân la urmă.
