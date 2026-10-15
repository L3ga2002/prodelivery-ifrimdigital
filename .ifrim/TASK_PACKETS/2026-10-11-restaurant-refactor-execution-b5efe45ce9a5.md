# PD-REFACTOR-2026-10-11 — execuție autorizată

Proiect: ProDelivery. Clasificare: engineering_support și etapa_1_3_core.
Autorizare: utilizatorul a spus «incepe» și cere păstrarea tuturor funcționalităților clientului, peste tot în aplicație.
Plan de referință: TASK_PACKETS/2026-10-11-astra-refactor-restaurant-dispatch-plan.md.

Ordine: A0 baseline/snapshot, A1 inventar de paritate, A2 adaptor HTTP recovery comun, A3 parser pregătire comun; apoi recuperare explicită pregătire/READY după contract și extragerea componentelor/citirilor RestaurantApp. Fiecare lot se verifică înaintea următorului.
Owner frontend/integrare: ROOT. Owner backend A3: refactor_backend. Reviewer independent: refactor_review. QA separat: refactor_qa. Numai Codex intern, fără Hub/OpenClaw/Claude.

Backup surse și teste: `.ifrim/BACKUPS/2026-10-11-restaurant-refactor-b5efe45ce9a5`; manifest: `QA_RUNS/2026-10-11-restaurant-refactor-b5efe45ce9a5/baseline.json`.
Lock logic: ROOT deține frontend; backend owner lucrează numai la parser, în staging. Integrarea este serială. Reviewer și QA nu editează sursele aplicației.
Preview: mediu nou loopback cu date sintetice, stabilit împreună cu QA; fără pornirea dev-start pe baza reală. Testele protejate, configurările de auth/tranzacții, istoricul dovezilor, datele clientului și telefonul sunt păstrate.

Acceptare: toate opțiunile și fluxurile existente rămân accesibile; aceleași validări/refuzuri; sesiuni vechi și clickuri duplicate nu produc efecte noi; baseline before/after, review independent și QA comportamentală pe sursa finală. Pentru READY/pregătire, reconcilierea nu trimite automat altă intenție, iar rezultatele incerte sunt explicite. Nu se inventează reguli financiare.
Risc mediu pentru cod comun/sesiuni; verificăm creare, editare, asignare, status, pregătire, gata, pauză, close-day, incidente, istoric, anulare, loading/offline și revenire. Browser desktop/mobil pentru paginile afectate.
Sursa refactorizată primește hashuri noi; manifestele istorice 294/140 rămân dovezi ale versiunii anterioare. Nu se modifică testele protejate pentru a ascunde regresii. Eșecurile istorice nominale sunt raportate separat.
iOS, bateria fără USB și răspunsurile financiare ale clientului rămân în gate-urile deja documentate. Fără commit/push/deploy, migrare/date live sau etapele dispatch/OCR în acest lot.
