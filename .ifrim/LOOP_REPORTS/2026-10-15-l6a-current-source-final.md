# L6A — acceptare delimitată pe sursa curentă, 15 octombrie 2026

Reconcilierea A și lotul B sunt încheiate ca verificări delimitate. E1, E2 și acceptarea generală L6 rămân deschise. Nu s-a modificat codul produsului sau vreun test protejat. Sursa verificată este commitul `2fc239d4bec3b25fa7ea1f566d068bf9b1dfb000`, cu 322 fișiere identice în checkout și copia izolată.

Arhiva locală: `.ifrim/QA_RUNS/2026-10-15-l6a-campaign/closed-ab-r2`. Copia de lucru și dovezile originale: `C:\Users\mihai\OneDrive\Documente\Mutare Proiecte de pe Emergent\pd-l6a-20261015-campaign`. Manifestul arhivei fixează hashurile; datele Mongo sintetice sunt păstrate separat. Arhiva brută, baza de date, dependințele și buildul nu se publică în Git.

## Rezultate și limite

- L6A HTTP R1: **11 PASS / 1 FAIL**, 609,178 secunde, fără timeout. S10 a eșuat din cauza așteptării greșite a harnessului (403 în locul răspunsului de confidențialitate 404 `ORDER_NOT_FOUND`). Rularea originală rămâne FAIL. Suplimentul S10 separat verifică șase refuzuri exacte, toate PASS, cu starea pozitivă neschimbată. Acoperirea scenariilor este acceptată cumulativ; nu declarăm R1 „12 PASS”.
- Lifecycle real prin TCP, autentificare cookie reală, routere actuale și Mongo izolat: 8 comenzi pozitive, contor 100→108, 2 livrate și 6 anulate. Citirea incidentelor driverului propriu are 200 cu listă goală după alocare coerentă; avertismentul istoric provenit din fixture manual nu se reproduce în acest pozitiv.
- Custodia așteaptă 600,276764 secunde reale înainte de review. Cele patru evenimente și eliberarea claimului nu creează livrare sau remunerație fictivă. Ramura `return_received` nu a fost exercitată.
- L4A păstrează exact trei evenimente a câte 4325 bani, snapshotul inițial imuabil și valorile efectiv plătit/rambursat necunoscute. Refacerea are un singur copil și legături bidirecționale; replay și close-day produc câte un efect. Livratorul pozitiv are două livrări și 20,74 RON remunerație calculată.
- Cele șase comenzi negative HTTP din cinci grafuri și cele două comenzi Brave sunt etichetate `NEGATIVE_ONLY`, cu actori/tenant separat. Nu se amestecă cu cele opt comenzi pozitive. 403 pentru driver dezactivat precede routerul și nu are `Cache-Control`; această limită este păstrată explicit, fără a extinde afirmația despre cele opt GET canonice.
- Buildul sursei actuale: 0 erori / 0 warnings, 5 fișiere rezultate, hashuri înainte și după. Regresia statusRecovery: **144 teste = 135 PASS / 9 FAIL**; cele 89 istorice au rezultate nominal identice, iar cele 55 noi trec. Cele 140 înregistrări protejate / 76 căi unice rămân intacte în checkout; 69 există în stage, iar cele 7 teste mobile rămân numai în checkout. Nu este suită integral verde.
- Brave real, executabil explicit verificat: administrator desktop/mobil, restaurant desktop/mobil în timpul custodiei, driver cu remunerația proprie. Două probe reale de reload pentru driver→CANCELLED și restaurant→ACCEPTED arată eroarea de autorizare, GET404/no-store, zero POST/PUT, intenția păstrată în ambele roluri și draftul de anulare păstrat la driver, fără ACK inventat sau schimbare DB/counter. Capturile sunt verificate vizual. Nu este dovadă BFCache, PWA sau telefon fizic.
- Consolele păstrează blocările intenționate CSP ale fonturilor/Posthog, 401 inițiale înainte de login și 404 așteptate în recuperare. Nu se declară zero erori de consolă.

Scenariile au owner separat; infrastructura QA a fost reviewată separat, iar rezultatele HTTP și hashurile au audit independent. Root a executat/verificat Brave. Rapoartele independente sunt `qa/L6A-HTTP-final.*`, `qa/CHECKPOINT-A-B-PROTECTED-*`, addendumul Brave și `review/protected-certification-r2.json`. Probe brute: `evidence/l6a-http-r1-raw`, `evidence/l6a-s10-supplement-r1-raw`, `evidence/brave-*-role-guard.*`.

## Restante păstrate

Reconcilierea E1 separă cele 18 răspunsuri primite și Q7 clarificat de noile întrebări 13/14 despre autoritatea încasării/refundului efectiv. Q3D și Q17D rămân incomplete. L4B nu se activează fără autoritate; L5C2 așteaptă proveniența traseului, zona 1 unică per restaurant/versiune, tariful distinct și rotunjirea jumătății de ban. E4 cere furnizor/API și confirmare umană. Probele fizice Android/iOS/GPS/baterie sunt amânate.

Nu s-a demonstrat un defect nou de produs în acest lot; nu se introduce refactor fără justificare. Următorul lot D adaugă concurență observabilă și restart real într-un namespace nou, păstrând separat probele HTTP și două taburi Brave. Nicio etapă comercială întreagă nu este declarată închisă din acest lot.

Arhiva închisă conține 97 artefacte; SHA256 ARCHIVE-MANIFEST.json: 080e47bc5f57840bfc6af77244df84305bf51682c341ae6acd1384c60f20a372. Prima tentativă de copiere a întâlnit limita Windows pentru căi de cache lungi; directorul parțial closed-ab este păstrat, fără statut de arhivă finală. Copia finală exclude cache-ul și este verificată fișier cu fișier.
