# Decizie - Scalare progresiva, fara schimbare de etape

Data2026-10-08. Catalin a aprobat recomandarea de pregatire progresiva pentru
scalare. Aceasta decizie nu autorizeaza deployment, costuri, topologie, Kafka,
Kubernetes, schimbari de baze reale sau migrare live.

- Pachetul de10etape si scope-ul de10.000EUR raman referinta; nu adaugam
  o etapa commerciala paralela si nu promovam automat etapa curenta.
- Pastram backend modular si contracte explicite. API poate fi replicat numai
  cu invariantii/idempotenta in stocare durabila partajata, nu locks in-memory
  considerate globale. Lucrarile de transaction/recovery existente se pastreaza.
- Citiri paginate server-side si limite/deadline se pregatesc in Etapa2.
  Rezultate incomplete si schimbari concurente sunt semnalate, nu mascate.
- Lucrarile OCR/alocare/notificari pot primi workeri separati la etapele lor,
  pe contracte recuperabile; outbox/event transport cand exista cerinta reala.
- Packaging/health/observability/backup/restore si benchmark apartin Etapei9.
  Se pregateste compatibilitate Kubernetes, nu un cluster obligatoriu acum.
- Kafka este optiune CONDITIONATA de volum si nevoi demonstrate. Nu este
  conditie pentru prima lansare si nu promitem migrare ulterioara fara munca.
- 50restaurante/100livratori este profil de testare planificat, nu limita
  maxima hardcoded si nu capacitate deja verificata. Minimum10comenzi fezabile
  simultane/livrator ramane cerinta Etapei7, nu single-slot-ul curent.
- Finantele, incidentele si probele fiziceGPS asteapta confirmarile specifice;
  intre timp avanseaza lucrarile independente aprobate, fara inventarea regulilor.
