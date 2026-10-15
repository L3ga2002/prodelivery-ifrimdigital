# Decisions

<!-- S2-06-2026-10-08:begin -->
## 2026-10-08 - Scalare progresiva si S2-06

Catalin a aprobat pregatire incrementala pentru scalare in aceleasi10etape,
nu Kubernetes/Kafka obligatorii acum. Pastram modularbackend, shared durable
idempotency si API replicabil, workers OCR/allocation/notifications la etapele
lor. Packaging/health/observability/backup/restore/benchmark inEtapa9,
Kubernetes-compatible; Kafka numai dupa nevoie masurata. Spec separata:
SPECIFICATIONS/PD-SCALING-PROGRESSIVE-2026-10-08.md. Fara instalare/deploy/costuri
noi/DB/topology sau etape comerciale suplimentare.50restaurants/100drivers este
profil planificat, nu plafon hardcoded/capacitate deja certificata; minimum10
fezabile simultan/livrator ramane Etapa7, nu single-slot curent.

S2-06 intern aprobat: reads bounded/strict, paginare admin, freshdetail/embedded
history, fara rescriere app/writer/designed UI.11source/test files integrate
cu backup/hashguard si review/QA separate; gate live distinct. Marker-ele
create/edit/assign/status nu sunt activate si6livecredentialtests neexecutate.
Etapa2 ramane in_progress; nu incepeEtapa3+. S2-05B asteapta regulile clientului
pentru finante/incidente/refaceri; avansam numai lucrari independente aprobate.
Nu modifica scope/pretul planului10.000EUR/10etape din aceasta decizie tehnica.
<!-- S2-06-2026-10-08:end -->

## Actualizare prioritara 2026-09-26

Decizia noua inlocuieste ipotezele comerciale incompatibile de mai jos: 10.000 EUR suplimentari fata de platile anterioare; 26.000 EUR ramane reper istoric, nu promisiune de pret pentru rest. Minimum 10 comenzi active per livrator, plafon configurabil si respectarea constrangerilor. Integrare API initiala pentru un restaurant, furnizor si operatii de nominalizat. Fara POS. Restaurant PWA, admin web, livrator Android/iOS; garantie 90 zile. Tinta trei luni se valideaza cu noul scop, nu este dovada de livrare.

Sursa curenta: `EXECUTION_PLAN_2026-09-26.md` si planul client v1.2 din 26 septembrie 2026. Notele de mai jos raman istoric; nu prevaleaza asupra acestei decizii. Autorizarea curenta nu include commit/push/deploy, schimbari de secrete, baze de date sau lansarea agentilor externi. Cerintele noi sunt planificate, nu implementate prin actualizarea documentelor.

## Istoric pastrat

## 2026-07-10

- The client-facing roadmap is normalized to 10 commercial stages. The currently approved historical Phase 2 is treated commercially as Stage 1 because it is the first paid delivery stage.
- Stage 1 has an already agreed price of EUR 3,500 and is currently in progress/finalization.
- Catalin reported approximately RON 13,000 paid toward Stage 1. Do not invent a RON/EUR conversion; reconcile the payment using invoices/payment documents and the contractually agreed exchange-rate rule.
- The target fixed price for the complete 10-stage project is EUR 26,000, including the EUR 3,500 Stage 1 price and deducting documented payments already made.
- All development prices and future stage prices are stated in EUR. Third-party charges remain external costs billed by their providers.
- Do not use a fixed 40/60, advance/acceptance payment formula in the client proposal. Payments may be made in mutually agreed amounts, including payment for multiple stages or a larger portion of the project, and every documented payment is credited against the EUR 26,000 total.
- The client-facing proposal must explain both the business result and the technical work under clear subtitles for every stage; a short commercial summary is not sufficient.
- Marketplace scope: maximum 3 reusable marketplace platform connectors and initial onboarding/configuration for maximum 20 restaurants. The client supplies official API access, credentials, approvals, and venue identifiers.
- POS integrations are excluded. The product must remain technically scalable beyond the initial 20-restaurant onboarding batch.
- This commercial normalization is planning only. Phase 3+ implementation still requires Catalin's explicit approval.

## 2026-07-03

- Catalin re-provided the older Emergent roadmap and clarified the commercial phase rule.
- ProDelivery is paid by phases; Codex must not start Phase 3 or any later commercial phase until Catalin explicitly approves that transition.
- Catalin clarified again that the current approved commercial phase is Phase 2.
- Catalin corrected the official commercial phase list. The active commercial roadmap is:
  - Phase 2: Panou pentru restaurante - restaurantul vede comenzile si marcheaza cand sunt gata de ridicat.
  - Phase 3: GPS live pe harta.
  - Phase 4: Alocare automata.
  - Phase 5: Notificari cu sunet.
  - Phase 6: Rapoarte complete.
  - Phase 7: Aplicatie mobila nativa.
  - Phase 8: Lansare si suport.
- Earlier mapping that treated Phase 3 as code quality, Phase 4 as Admin Settings, and Phase 5 as live GPS/smarter dispatch was report-derived/internal and is superseded.
- Code quality, preview reliability, tests, and production-readiness hardening are engineering support tasks for safely closing the approved phase; they are not commercial phase transitions by themselves.
- Admin Settings real is not in the official commercial phase list. Treat it as an operational/change-request item requiring Catalin's scope approval before implementation.
- Marketplace/POS integrations are also not currently placed in the official commercial phase list. Historical memory mentions Glovo/Wolt/Bolt API, and current code has source labels, but no verified real connector module. Treat Glovo/Wolt/Bolt/restaurant POS integration as a separate future paid scope until Catalin assigns it to a phase.
- A detailed historical AI-agent report was provided on 2026-07-03. Treat it as product/client context and historical evidence only; do not treat its implementation claims as current truth until Codex audits the active codebase.
- A new local memory file records the commercial roadmap and gate:
  - `.ifrim/PHASE_ROADMAP.md`
- Important distinction:
  - Internal engineering stage labels are used for verification discipline.
  - The commercial phase roadmap controls paid scope and what Codex is allowed to start.
- Before implementation, Codex should audit what is already done vs remaining against `.ifrim/PHASE_ROADMAP.md`.

## 2026-07-02

- Catalin selected the ProDelivery next-stage direction:
  - 1B: optimize the next ProDelivery push for real production launch readiness, not only a client-review demo.
  - 2C: convert Admin Settings and live map into real production features now, instead of hiding/labeling them as demo.
  - 3A: focus the next stage on Admin/dispatcher operational reliability.
- Product implication: ProDelivery should not start client app, catalog, Android app, or advanced analytics until the Admin/dispatcher production path is reliable.
- Technical implication: the next scope should prioritize reliable local verification, real persisted Admin Settings, real driver location/live map behavior, admin dispatch reliability, and production security/release gates.
- Loop report and scope packet:
  - `.ifrim/LOOP_REPORTS/2026-07-02-0014-project-stage-loop.md`
  - `.ifrim/LOOP_REPORTS/2026-07-02-0020-production-readiness-scope.md`

## 2026-06-09

- Claude Code is added as an external IfrimDigital engineering specialist coordinated by Codex.
- Codex remains the main coordinator for memory, preview, Git/GitHub, final decisions, and verification.
- OpenClaw remains the local IfrimDigital agent team for routine specialist work.
- Claude Code is used for independent review, deeper security/architecture analysis, QA summaries, and selected implementation only when explicitly requested.
- Default Claude model is `sonnet`; use `opus` for architecture/security/deep debugging, `haiku` only for simple summaries, and `fable` only for the hardest long-running investigations.
- Review-oriented Claude agents are read-only and must not inspect env files, private memory, uploads, or test credential notes.

## 2026-06-08

- Codex remains the main coordinator/technical brain.
- OpenClaw agents are IfrimDigital specialist engineers used for focused review, implementation, QA, DevOps, design, migration, and integrations.
- Reviewer agents do not edit files. They report actionable findings with owner and fix recipe.
- Fixer agents receive reviewer findings and implement changes.
- QA verifies after fixes.
- For multiple projects, use one project folder, one `.ifrim/` memory folder, and preferably one Codex thread per project.
- ProDelivery gets durable project memory in `.ifrim/` plus a central registry in `..\PROJECTS.md`.
- Git should be initialized locally for history, but production secrets and local env files must stay ignored.
- Do not create the first baseline commit until demo credentials and local-only testing files are reviewed.
