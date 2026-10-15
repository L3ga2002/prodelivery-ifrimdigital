# F3B — refaceri financiare în restaurant, închis local

15 octombrie 2026. Integrat și verificat independent în ProDelivery: 13 fișiere (8 produs, 5 teste noi), 3 copii exacte ale fișierelor înlocuite, 300 surse din afara lotului păstrate. Protecții: 140 intrări / 76 căi; F2B12 și F3A6 intacte. 172 dovezi arhivate, plus dovada independentă după integrare.

Restaurantul cere cotația pentru produsele noi, alege explicit CASH/CARD și grila aprobată, confirmă sumele și creează refacerea financiară legată atomic de original. Editarea produsului, cantității, prețului, plății sau grilei cere o nouă confirmare. Prețul zero este explicit. Ordinele financiare indisponibile/corupte nu folosesc fluxul legacy; ordinele legacy pure își păstrează funcția existentă.

Intenția durabilă păstrează numai metadate, iar datele private ale cererii rămân în sesiunea filei. Reload, offline, răspuns pierdut și două taburi păstrează aceeași încercare. Operația admisă pending necesită reluare explicită. Confirmarea rezultatului cere receipt proaspăt, readback valid când este aplicat și publicarea listei actualizate înaintea ștergerii intenției; o listă indisponibilă păstrează recuperarea.

## Verificare

- Owner: 163 teste noi PASS; suita combinată 797 PASS / 8 FAIL. Toate cele 642 rezultate istorice sunt identice cu baseline634 PASS / 8 FAIL. Eșecurile istorice din orderStatusRecovery rămân vizibile; nu este acceptarea L6 verde.
- Review independent: 70/70 PASS. QA independent: 131/131 PASS, zero skip. Sursa R2 exactă a fost înghețată pentru toate aceste probe.
- Build final: 0 erori / 0 avertismente, 125 surse și 5 artefacte verificate înainte și după.
- Brave real + TCP local + Mongo replica-set real, autentificare reală cu date sintetice și fără dependency overrides: 10 grupuri. CASH, CARD, zero explicit, răspuns pierdut, reload/offline/două taburi/fără draft privat, pending/close/resume, cotație schimbată/refuzată, fără downgrade, legacy, pregătire/READY/program/istoric și viewport1440/390/320.
- Cinci refaceri au exact un POST inițial și câte un copil. Snapshoturile părinte/child non-null sunt identice cu snapshoturile admise. Captura finală: 14 comenzi, counter112; toate fault flags restaurate, fără intenție rămasă. Datele se păstrează în namespace-ul QA propriu.
- Verificare independentă după integrare: exact13 surse,3 backupuri,300 non-scope,140/76 protecții, F2B/F3A,172 arhive și proof bytes. PASS fără findings.

## Limite și următorul pas

Brave a revenit din istoric printr-un document nou; BFCache real nu este demonstrat. Viewporturile mobile nu sunt telefoane fizice. Harnessul blochează fonturi/PostHog externe și service-workerul primește MIME neacceptat; nu se declară PWA/zero erori console. Încercările QA eșuate sunt păstrate, inclusiv corectarea câmpului financial și a codului409 pentru rejected; rezultatele finale au fost recalculate independent.

Browserul QA propriu și serverul58081 au fost închise. Mongo comun și previzualizarea veche57881 au fost păstrate; aceasta din urmă nu reprezintă sursa nouă. Nu s-au făcut Git, deploy, servicii plătite, date reale sau probe pe telefon.

Etapa1 OPEN: inventarul și lucrările software delimitate sunt salvate; probele fizice Android/iOS/GPS/offline/baterie și clarificările comerciale restante se evaluează separat. Etapa2 OPEN: P1 privacy pentru8GET, L4B autoritate pentru plăți/refunduri efective, L5C2 anulare/adresă durabilă cu dovezi verificate și acceptarea L6. Lotul F3B este închis; aceste două etape comerciale nu sunt declarate100%.

Următorul lot: P1,9 fișiere de produs și4 teste noi pe baseline313, păstrând sumele restaurantului, remunerația proprie a livratorului și snapshotul complet pentru administrator. Contractul și matricea sunt revizuite; implementarea pornește numai în noul stage după bootstrap verificat. Ultima cotă confirmată în sesiune era74% disponibil; citirile actuale au expirat, deci această valoare nu este cotă curentă.
