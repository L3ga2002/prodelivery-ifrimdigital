# ProDelivery — L5A refacere atomică versionată, 13 octombrie 2026

Închis local în scopul API și citire: o comandă originală versionată DELIVERED poate avea un singur copil creat prin noul protocol, fără ștergerea sau recreditarea originalului. Legătura părinte/copil, incrementarea versiunii, numărul comenzii, copilul NEW, două audituri și receiptul se comit în aceeași tranzacție. Orice write eșuat revine fără copil parțial; aceeași intenție se reia. Două intenții concurente creează un singur copil.

Restaurantul propriu sau administratorul declară explicit noul bon și modul de încasare. L5A cere suma articolelor egală cu valoarea bonului; produsele nominale pozitive nu pot fi mascate de un bon0. Produse0 explicit este acceptat numai cu articole0, în timp ce transportul și remunerația se iau din grila aprobată fixată la admitere. Nu se inventează gratuitate, CARD sau dovadă de plată a bonului original. Celelalte compensații/retururi cer protocol distinct și rămân deschise.

Markerul order-remake-v1 este implicit oprit. Headerul actorului este obligatoriu; autorizarea este verificată la admitere și recuperare. Rutele generice nu pot lega un copil de un părinte versionat/financiar ocolind protocolul nou. Părinții pur legacy își păstrează fluxul istoric, iar cursa legacy din /problem nu este declarată reparată de acest lot. Modificarea formatului financiar sau dezactivarea markerului după admitere nu rescrie operația în recuperare.

Citirile păstrează relația și marchează legăturile corupte. Administratorul poate deschide originalul din copil și invers; fiecare navigare citește din nou cu contul curent. Schimbarea contului închide selecția. Formularul restaurantului pentru trimiterea/recuperarea noului protocol nu este activat; migrarea controlată a UI rămâne pas separat după configurarea tarifelor și regulilor lipsă.

Dovezi distincte:53/53 teste L5 owner;53/53 regresie financiarăL3;19/19 QA independent (11Mongo+8contract);reviewbackend independent fără constatări deschise;frontend213/213;build0erori/0warnings;browser9/9 pe desktop1440 și mobil390. Regresia backend țintită1161PASS/4FAIL are toate4FAIL reproduse identic pe baselineL3; nu este prezentată ca integral verde. Primul QA independent17/19 avea două erori ale harnessului, corectate fără schimbarea produsului; ambele runde păstrate.

Browser fixture a parcurs prin serviciile reale pregătire→alocare→confirmare→READY→ridicare→livrare→refacere→replay. Browserul a verificat citirile autentificate, noul copil0RON cu transport23RON/remunerație14,37RON și originalul52,50RON. Toate cifrele sunt sintetice, fără tarif/aprobare comercială reală. Nu sunt probe de telefon, publicare sau activare live.

L4 numerar insuficient, L5B retur/custodie/rambursare, migrarea UI și L6 acceptarea completă rămân deschise. Etapele comerciale1/2 rămân DESCHISE. Următoarea implementare concretă este L4, cu ledger de evenimente separat de snapshotul financiar imuabil.
