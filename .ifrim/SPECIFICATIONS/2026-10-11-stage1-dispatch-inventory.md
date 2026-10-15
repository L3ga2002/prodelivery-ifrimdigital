# ProDelivery — inventar dispatch din Etapa 1

Data: 2026-10-11. Lot D0: inventar static și reconciliere a specificației. Aplicația și funcționalitățile existente sunt păstrate. Acest lot nu implementează asignarea multiplă și nu închide o etapă comercială.

Inventarul verificat acoperă 48 de consumatori backend, 43 de linii care folosesc exact `current_order_id` în 8 fișiere și 69 de apeluri directe către colecția drivers. Frontend-ul are 14 observații, inclusiv 7 utilizări directe în 4 fișiere. Manifestele fixează separat 66 de intrări backend și 44 frontend; numerele nu reprezintă fișiere unice cumulate sau teste executate.

Pregătirea independentă din A8, filtrarea comenzilor terminale din feed-ul livratorului și protecția citirilor multi incompatibile există deja în sursă. Addendumul corectează descrierile vechi din PD-DISPATCH-01 v0.3 fără a rescrie documentul original. Ledgerul `order_operations`, identitatea intenției și recuperarea după răspuns pierdut trebuie păstrate. Incidentele folosesc separat `operational_operations`; condiția unei singure comenzi active este aplicată driverului, cu scope distinct pentru admin și restaurant.

Sursele aplicației, testele și documentele existente au fost numai citite. Referințele la teste sunt nominale, NOT_RUN în D0. Nu au fost executate teste ale aplicației, build, preview, API, DB, ADB, migrare, deploy sau scrieri Git. Hashurile celor 42 de surse mobile și ale celor 140 de intrări protejate (76 de fișiere unice) au fost păstrate.

Versiunile canonice și dovezile independente sunt copiate byte-exact în directorul QA_RUNS al acestui lot și legate prin `publication-checkpoint.json`. Inventarele detaliate sunt backend v3 și frontend v3; reconcilierea este v2. Versiunile anterioare din launcher rămân păstrate.

Pașii comerciali rămân secvențiali: Etapa 1, apoi Etapa 2, apoi Etapa 3. Următoarea implementare de dispatch cere pachet separat și probe distincte pentru 1, 2, 5 și 10 comenzi pe același livrator; nu începe prin D0. Prototipurile istorice și testele nominale nu certifică multi-dispatch în aplicație.

D0 nu califică bateria telefonului. Checkpoint-ul `full-ready` din 20:12 UTC a consemnat proba lungă `pd-battery-f432a0db-bf13-40be-a242-8a2f723dc1ed` ca PENDING și restaurarea obligatorie a configurației temporare HONOR. Pentru starea ulterioară se citește prioritar `.ifrim/NEXT_SESSION.md` și raportul bateriei. D0 nu schimbă acel checkpoint și nu controlează telefonul. iOS fizic și răspunsurile clientului rămân la urmă.
