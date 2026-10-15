# PD-STAGE1-20261002

Proiect: ProDelivery.
Cale: `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery`.
Clasificare: `etapa_1_3_core` si `engineering_support`.
Etapa: 1 din cele 10 etape ale pachetului operational de 10.000 EUR.

Cerere curenta: Catalin doreste inceperea lucrului astazi si evaluarea termenului de o luna pentru pachetul de 10.000 EUR. Incepem cu inventar focalizat, baseline sigur, preview si pachete tehnice verificabile. Nu presupunem autorizarea tuturor etapelor avansate din simpla intrebare despre termen.

Owner: Codex. Review: trecere separata Codex, fara audit independent pretins. QA: teste existente izolate si verificare preview. Nu invocam OpenClaw/Claude, conform restrictiei curente. Endpoint Agent Hub citit read-only; taskul vechi PD-HUB-001 si eticheta Phase 2 din raspuns nu inlocuiesc planul 2026-09-26. Catalin gestioneaza Hub.

Roluri afectate de analiza: admin, restaurant, livrator.
Zone: comenzi, asignari, frontend comun, mobil/GPS/OCR, launcher local.
Preview: `http://127.0.0.1:3000/login`, API `http://127.0.0.1:8000/api/`.
Lock: exista advisory restaurant-panel in Hub; nu editam acest flux prin inventar. Orice editare de launcher va avea backup punctual.
Backup: necesar pentru orice fisier existent editat; rapoartele noi nu inlocuiesc rapoarte anterioare.

Criterii:
- Confirmam dependentele reale de `current_order_id`, ce poate fi reutilizat si ce ramane de construit.
- Rulam testele de comenzi pure/fake-DB fara acces la baza existenta sau credentiale.
- Verificam pornirea locala si pagina de autentificare, daca infrastructura permite.
- Salvam rezultate exacte si un prim increment concret, fara a transforma planul in functionalitati declarate terminate.
- Estimarea de patru saptamani ramane conditionata de probele dispatch/mobil/OCR; API amanat pana la acces si documentatie.

Limite: fara seed/reset, scrieri in date client, schimbari de secrete, plati/API externe, commit/push/deploy sau modificarea Hub.
