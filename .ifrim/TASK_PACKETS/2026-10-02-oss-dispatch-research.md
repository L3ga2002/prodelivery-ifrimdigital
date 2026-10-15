# Task packet - PD-OSS-RESEARCH-20261002

## Cerere

Cercetare extinsa a surselor publice pentru componente reutilizabile ProDelivery, cu accent pe alocare/rutare multi-comanda si inspiratie din platforme de food delivery.

## Incadrare

- Proiect: ProDelivery.
- Root: `C:\Users\mihai\OneDrive\Desktop\Ifrim Digital Proiecte\ProDelivery`.
- Plan: pachet suplimentar 10.000 EUR, 10 etape; Etapa 1, pregatire tehnica.
- Routing: Codex only, cerere explicita a utilizatorului; fara OpenClaw/Claude.
- Owner: Codex, cercetare si redactare.
- Review: Codex, verificare separata a surselor primare/licentelor si distinctiei dintre dovezi si propuneri; nu este audit independent.
- QA: verificare documentara si inspectie statica. Niciun benchmark sau QA functional nou pretins.
- Lock/backup: nu este necesar pentru citire si doua documente noi, fara suprascriere.

## In scope

Surse oficiale, repository-uri, documentatie si lucrari ale autorilor; termeni de reutilizare; comparatie OR-Tools/VROOM; rutare; OCR; GPS mobil; implicatii pentru codul existent; limite si scenarii de benchmark.

## Out of scope

Implementare, instalare, clonare, schimbare arhitectura, modificare secrete/env/date/Hub, invocare agenti, test pe date reale, activare Etapa 4-10, commit/push/deploy.

## Rezultat

Raport: `.ifrim/LOOP_REPORTS/2026-10-02-oss-dispatch-research.md`.

OR-Tools este primul candidat de evaluat; VROOM este alternativa. Nu s-a ales definitiv si nu s-a integrat un motor. Nu a fost identificat un motor complet public verificabil Glovo/Foodpanda cu drepturi clare de reutilizare in cautarea efectuata.

## Criterii de inchidere

- Surse primare legate de fiecare afirmatie externa importanta.
- Licente si restrictii explicite, fara prezentarea codului public ca automat utilizabil comercial.
- Minimum 10 comenzi active/livrator pastrat ca cerinta, distinct de capacitate fizica si opriri.
- Limitele codului singular actual evidentiate.
- Fara garantie de performanta, cost sau termen bazata doar pe README-uri.
- Niciun fisier existent suprascris; verificarile si cele neefectuate delimitate.

## Evidenta locala

Git: `main...origin/main`, worktree deja modificat; modificarile existente au fost pastrate.
HTTP local: frontend `/login` 200, backend `/api/` 200. Nu echivaleaza cu smoke functional.
Persistenta: doua documente noi, copiate numai daca destinatiile nu exista; verificare SHA-256.

## Continuare

Documentarea criteriilor de acceptare pentru multi-comanda si un benchmark izolat, numai la aprobare. Integrarea API a restaurantului asteapta documentatia si accesul; cercetarea nu schimba aceasta dependenta.
