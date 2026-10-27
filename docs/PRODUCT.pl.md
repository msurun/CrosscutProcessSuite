# Crosscut Process Suite — definicja produktu

Polski odpowiednik `docs/PRODUCT.md`; przy rozbieżności rozstrzyga wersja angielska.

Niniejszy dokument jest jedyną definicją produktu Crosscut Process Suite. Zastępuje `docs/PROJECT_DESIGN.md`, który pozostaje wyłącznie jako zapis historyczny. Tam, gdzie ADR w `docs/adr/` są sprzeczne z tym dokumentem, pierwszeństwo mają ADR. Data: 2026-10-27.

## 1. Definicja produktu

Crosscut to serwer on-prem z konsolą w przeglądarce, w której inżynier procesu konfiguruje system **bez programowania** (zasada *no-code*): podłącza historian lub DCS dowolnego dostawcy, analizuje i modeluje proces (pętle regulacji, wirtualne sensory, anomalie, reguły, MPC, optymalizacja), uruchamia modele online i zmienia nastawy w systemie sterowania przez jeden bezpieczny **Write Gateway**, w trybach `advisory` → `confirm` → `supervised`.

| Użytkownik | Rola |
|---|---|
| Inżynier procesu | Podłącza źródła, buduje katalog projektu, projektuje i wdraża modele. Odpowiada za konfigurację no-code. |
| Operator | Pracuje w konsoli, akceptuje lub odrzuca proponowane zapisy w trybie `confirm`. |
| Inżynier automatyki | Odpowiada za politykę zapisu, konfigurację gateway i ustawienia bezpieczeństwa. Nadzoruje wszystko, co dotyka regulatora. |

Zasady, które się nie zmieniają: dane z zakładu służą do walidacji cech i nigdy ich nie definiują. Żadna nazwa tagu, jednostka, kod braku danych, okno ani próg jednego zakładu nie może być stałą w `*/src`. Każda funkcja działa na dowolnym tagu, wyniku laboratoryjnym, analizatorze i pętli, które skonfiguruje użytkownik. Rzeczywiste dane z zakładu pozostają poza repozytorium.

## 2. Decyzje właściciela z 2026-10-27

1. Zapisy do systemu sterowania są cechą produktu, realizowaną przez jeden Write Gateway. Tryby `confirm` i `supervised` są w zakresie wersji v1.
2. Pierwszy kompletny produkt: monitoring pętli regulacji plus strojenie PID, od pozyskania danych po pracę online z zapisami.
3. Kolejność konektorów: OPC UA → PI → SQL/ODBC → pozostałe.
4. Wdrożenie: serwer on-prem plus przeglądarka. Bez chmury.
5. Symulator DCS naśladujący ABB 800xA to osobny projekt (Faza 1a).

Wcześniejsze dokumenty zapisywały stanowisko „żadnych zapisów do zakładu” (PROJECT_DESIGN §1, ADR 010, preambuła ADR 011). To stanowisko zostaje zastąpione przez ADR 012. Reguły bezpieczeństwa z ADR 011 pozostają w mocy.

## 3. Warstwy architektury

| Warstwa | Odpowiedzialność | Istnieje dziś | Luka |
|---|---|---|---|
| **Connect** | Odczyt historii i wartości bieżących, przeglądanie metadanych; zapis wyłącznie przez gateway | Import CSV wide/long, połączenie SQLite i dowolne DB-API/ODBC (pyodbc nie jest zależnością), odpytywanie i subskrypcja OPC UA, kolektor Parquet | Jeden interfejs konektora. Brak PI Web API, IP.21, PHD, AVEVA, OPC DA/HDA |
| **Katalog projektu** | Źródła, tagi, jednostki, zakresy, kody braków danych, strefa czasowa, pętle regulacji (PV/SP/OUT/tryb/parametry PID w postaci dostawcy), definicje labów; edycja w GUI | Nie istnieje. Ustawienia importu (kody braków danych, wartownik −9999) żyją w `loops/.../plant_import.py` jako ustawienia na poziomie kodu | Cała warstwa. Domyślna stała −9999 musi zostać usunięta (issue #42) |
| **Silniki** | Tryb projektowania offline i tryb pracy online dla każdego modułu | Pętle regulacji, fuzzy, supervisor, anomalie, wirtualny sensor: offline, na żądanie, po zapisanym oknie | Tryb pracy online. Generyczny edytor konfiguracji napędzany schematem |
| **Runtime** | Usługa on-prem (usługa Windows lub systemd) uruchamia wdrożone zadania cyklicznie: KPI pętli, skan anomalii, estymacja wirtualnego sensora, porada fuzzy. Status, dziennik błędów, start/stop z GUI | Nie istnieje | Cała warstwa |
| **Write Gateway** | Osobny proces. Zapisuje wyłącznie propozycje. Polityka jako dane, odczyt zwrotny, watchdog, priorytet operatora, kill switch, audyt | `gateway/` zawiera interfejsy i 12 scenariuszy strict-xfail. Kod zapisu istnieje tylko przeciwko symulatorowi | Pełna implementacja (Faza 2) |
| **Konsola web** | Interfejs w przeglądarce: Trends, Loops, Fuzzy, Advisor, Anomalies, Soft sensor, Import, Steps | Frontend React + TypeScript, zestaw e2e zielony. Niektóre konfiguracje są tylko do odczytu w GUI | Edycja konfiguracji supervisor, anomalii i wirtualnego sensora; kolejka propozycji; logowanie i role |

## 4. Moduły

### 4.1 Monitoring pętli regulacji i strojenie PID — pierwsze wydanie

**Cel.** Triage pętli: które są zdrowe, które wymagają uwagi i co zrobić dalej.

**Dostarcza dziś.** Lista robocza z ustaleniami (manual, nasycenie, flatline, oscylacja), test oscylacji ACF, kontrole zaworów i prowadzony test skoku, raport strojenia (SIMC/AMIGO, FOPDT; pętle integrujące eksperymentalnie), szacowanie korzyści, widok Steps.

**Luka do produktu.** Strojenie na poziomie modułu musi zostać domknięte jako pętla produktowa: detekcja → test → strojenie → zapis po potwierdzeniu → kontrola KPI → rollback jednym kliknięciem. Przegląd listy roboczej „na ślepo” i rzeczywisty test skoku zaworu pozostają zadaniami właściciela.

**Faza.** 3.

### 4.2 Wirtualne sensory

**Cel.** Estymacja zmiennej jakościowej z opóźnionych tagów procesowych, gdy wynik laboratoryjny jest spóźniony i rzadki albo analizator jest opóźniony.

**Dostarcza dziś.** Silnik (`softsensor/`) jest generyczny względem tagów, ale:

- obsługuje tylko PLS i działa wyłącznie offline;
- GUI potrafi jedynie odczytać konfigurację; nową konfigurację można dodać tylko przyciskiem „Load example”;
- w kodzie nie ma `reference input`. Analizator online może być jedynie zwykłym tagiem wejściowym. PROJECT_DESIGN §4.4 twierdził, że wejście referencyjne istnieje; niniejszy dokument to koryguje;
- korekcja błędu (bias) jest zawsze włączona; jej parametry są stałymi w `softsensor/.../bias.py`.

**Przypadek walidacyjny.** Praca nad analizatorem zakładu 1 (exp31, `tools/analyzer_vs_lab.py`, `tools/lab_extract.py`) jest przypadkiem walidacyjnym dla generycznego silnika, a nie osobną funkcją. Zostaje wchłonięta w Fazie 4.

**Luka do produktu (Faza 4).** Typ celu: lab, analizator lub oba, jako konfiguracja użytkownika: znaczenie znacznika czasu (początek, koniec albo środek plus przesunięcie), okno próbki złożonej, opóźnienie analizatora, kody braków danych i zakresy ważności. Wyszukiwanie opóźnienia (lag search). Jawne `reference input`. Korekcja błędu przełączalna, parametry w schemacie. Biblioteka modeli: PLS, ridge/linear, jeden model nieliniowy (gradient boosting), zawsze zablokowana walidacja krzyżowa, tabela porównania względem „ostatniej wartości laboratoryjnej”. Kreator w GUI: cel → proponowane wejścia → uczenie i porównanie → wdrożenie do runtime → opcjonalnie zapis estymaty do tagu DCS przez gateway.

**Faza.** 4.

### 4.3 Detekcja anomalii (część monitoringu)

**Cel.** Wskazywanie dryfu, zamrożenia i zdarzeń poza modelem oraz nazywanie tagów, które się do nich przyczyniają.

**Dostarcza dziś.** PCA z T2 i SPE, kolumny z opóźnieniami, reguła zablokowanego czujnika, ostrzeżenie o możliwym rampie. Runda 3 exp29 spełniła swoje kryteria.

**Luka do produktu.** Staje się zadaniem monitoringu w runtime. Limity detektora wymagają rzeczywistych danych spokojnych (≥ 2 tygodnie plus oznaczone zdarzenia, zadanie właściciela). Konfiguracja edytowalna w GUI (konfiguracje supervisor i anomalii są dziś tylko do odczytu).

**Faza.** 1 (zadanie online) i 3 (widok produktowy).

### 4.4 Fuzzy / supervisor ekspercki

**Cel.** Porada na poziomie procesu (pierwszy przypadek walidacyjny: natężenie zasilania), bramkowana stanem pętli, wyjaśniona, zalogowana, potwierdzona przez operatora.

**Dostarcza dziś.** Fuzzy Studio (pełna edycja zmiennych i reguł, wersje, odtwarzanie, backtest); supervisor doradczy bramkowany stanem pętli z modułu 1, wyjaśniany przez swoje dominujące reguły; dziennik audytu z łańcuchem haszy i potwierdzaniem przez operatora; tryby `off` i `advisory`. exp27 spełnił swoje zamrożone kryteria w symulacji.

**Luka do produktu.** Konfiguracja supervisor edytowalna w GUI (generyczny edytor w Fazie 1). Porada staje się propozycją zapisu do gateway: najpierw `confirm`, później `supervised`.

**Faza.** 1 (edytor konfiguracji) i 6 (pętla zamknięta).

### 4.5 MPC

**Cel.** Sterowanie wielowymiarowe z ograniczeniami ponad warstwą bazową PID.

**Dostarcza dziś.** Nic. Istnieje plan oraz test dymny w C++20 z testem zgodności w Pythonie.

**Luka do produktu.** Identyfikacja z testów skoku (widok Steps plus ogólne narzędzie odpowiedzi na wymuszenie), edytowalna macierz modelu w GUI, liniowy MPC z ograniczeniami (QP), runtime w C++ zgodnie z ADR 001, zapisy nastaw przez gateway w trybie `supervised`.

**Faza.** 7.

### 4.6 ML i optymalizacja

**Cel.** Rekomendacja zakresu pracy i warstwa ekonomiczna (RTO) ponad MPC i fuzzy.

**Dostarcza dziś.** Nic. Jedynym „ML” w repozytorium są PLS i PCA.

**Luka do produktu.** Rzeczywiste dane z historian, sprawdzalna analiza zmiennych zakłócających (confounding), cel ekonomiczny i ograniczenia (decyzja właściciela, niepodjęta). Plan pracy do zaproponowania przez asystenta i zatwierdzenia przez właściciela.

**Faza.** 8.

## 5. Zapis do systemu sterowania

ADR 012 („Writes are a product capability”, `docs/adr/012-writes-are-a-product-capability.md`) zastępuje stanowisko „bez zapisów” z ADR 010 i ADR 011. Powstaje równolegle z tym dokumentem. Reguły bezpieczeństwa z ADR 011 zachowują moc.

- Zapisuje wyłącznie Write Gateway. Jest to osobny proces. Pakiety analityczne nigdy nie importują kodu zapisu i nigdy nie przechowują poświadczeń. Testy strażnicze w CI oznaczają teraz „tylko gateway zapisuje”, a nie „nic nie zapisuje”.
- Polityka zapisu to dane (schemat `write-policy`). Limity, maksymalny krok, maksymalne tempo, minimalny odstęp, dozwolone tryby pętli, czas hold-off, okres watchdoga, tolerancja odczytu zwrotnego. Bez flagi wymuszenia.
- Weryfikacja odczytem zwrotnym każdego zapisu. Watchdog, który system sterowania może monitorować. Priorytet operatora: dowolna zmiana ręczna wyłącza zapis do tego celu na czas hold-off. Kill switch respektowany w jednym cyklu gateway, nie do obejścia przez konfigurację. Audyt z łańcuchem haszy każdej propozycji, decyzji i zapisu.
- Dozwolone cele: nastawy pętli w trybie kaskady lub zdalnej nastawy; parametry strojenia PID (tylko `confirm`); tagi wyjściowe wirtualnych sensorów. Nigdy wyjście regulatora ani tryb. Asystent testu skoku zapisujący OUT w trybie manual to otwarta decyzja właściciela (sekcja 10).
- Tryby na cel, domyślnie `off`: `off`, `advisory`, `dry_run`, `confirm`, `supervised`. Wersja 1 implementuje wszystkie pięć. Parametry strojenia PID są zapisywane tylko w `confirm`; `supervised` jest dozwolony dla nastaw pętli i tagów wirtualnych sensorów w granicach polityki. Kto może włączyć `supervised`, to decyzja właściciela (sekcja 10).
- Uwierzytelnianie, role (inżynier, operator) i logowanie są wymagane przed `confirm`. Tylko użytkownicy lokalni.
- Symulator z Fazy 1a zastępuje „soft PLC” z wcześniejszych planów. 12 scenariuszy gateway staje się rzeczywistymi testami przeciwko niemu w Fazie 2.

## 6. Symulator DCS (osobne repozytorium, Faza 1a)

Osobny projekt, który Crosscut widzi wyłącznie jako czarną skrzynkę przez OPC UA i eksport z historian. Wartość odniesienia (ground truth) jest udostępniana osobnym kanałem. Stanowi bazę dla przyszłego uproszczonego narzędzia do modelowania schematów technologicznych dla metalurgów.

Repozytorium to RougherSim (github.com/msurun/RougherSim, prywatne, licencja jeszcze nieustalona); jego plan znajduje się w `docs/IMPLEMENTATION_PLAN.md` w tamtym repozytorium, kamienie milowe M0–M7.

- **Model procesu jako dane.** Plik JSON schematu technologicznego plus biblioteka jednostek: podajnik i przenośnik z opóźnieniem transportu, młyn kulowy, zbiornik z pompą, hydrocyklon, bateria flotacji 3–4 ogniw z poziomem i powietrzem (model kinetyczny), prosty cleaner, zagęszczacz koncentratu. Zawory z martwą strefą i tarcie statyczne (stiction). Przetworniki z szumem, kwantyzacją i kompresją historian. Osobny bilans masy dla ciał stałych, wody i minerałów. Realistyczne sprzężenia: poziomy integrujące, interakcja między ogniwami, twardość rudy i zakłócenia zasilania. Około 20–30 pętli PID, w tym kaskady. Punktem wyjścia jest istniejący model mielenia w `sim/`.
- **Profil dostawcy jako wymienna warstwa.** Najpierw ABB 800xA / AC 800M: przestrzeń adresowa OPC UA i nazewnictwo w stylu 800xA; semantyka bloku PID (Man/Auto/Cascade/Remote SP, tracking, bumpless, nazwy i jednostki Gain/Ti/Td); alarmy i zdarzenia; format eksportu z historian. Nie imitujemy Operator Workplace ani Aspect Objects. Drugi profil: Siemens (PCS 7 / S7 PID).
- **Tryby pracy.** Czas rzeczywisty i przyspieszony. Skryptowe akcje operatora. Wstrzykiwanie awarii. Nagrywanie scenariuszy.
- **Ograniczenie do jawnego stwierdzenia.** Imitacja dowodzi naszego rozumienia 800xA, a nie zgodności z rzeczywistym 800xA. Kontrole na rzeczywistym stosie: Siemens PLCSIM Advanced (wersja próbna; tani test profilu Siemens); ABB SoftController tylko z legalną licencją ABB, w legalnym środowisku, wykonane przez właściciela. Żadnych nieoficjalnych pobrań.

Symulator DCS zastępuje „soft PLC” dla scenariuszy gateway w Fazie 2 oraz dla cyklu strojenia w Fazie 3.

Testy Crosscut względem RougherSim są elementem produktu, a nie dodatkiem na koniec: każde wyjście z fazy, które wskazuje symulator, odpowiada wierszowi macierzy akceptacyjnej L5 w `docs/TESTING_STRATEGY.md` (scenariusz, ziarno, kryterium zaliczenia), uruchamianemu przez harness `tests/integration_roughersim/` względem przypiętej wersji RougherSim. Wartość odniesienia (ground truth) czytają wyłącznie testy.

## 7. Fazy

Każda faza ma krótki szczegółowy plan przed rozpoczęciem oraz własne bramki: `ruff`, `pytest` dla całego repozytorium, `vitest`, `tsc`, `build`, `e2e:all`.

| Faza | Cel | Kryteria wyjścia |
|---|---|---|
| **Faza 0** — Sprzątanie, bez nowych funkcji | Ten dokument zastępuje PROJECT_DESIGN. ADR 012 zastępuje stanowisko „bez zapisów”. Testy strażnicze zmieniają znaczenie. `docs/archive/` dla jednorazowych planów i dokumentów. `tools/` oznaczone do wchłonięcia. Reguła anty-dryf w `CLAUDE.md`. Kamienie milowe GitHub 0–8. Zamknięte linie eksperymentów (stiction, ACF, idle) **nie** są przenoszone; `experiments/README.md` indeksuje ich status | Wszystkie bramki zielone po przeniesieniach. Brak martwych linków w dokumentacji. `git mv` zachowuje historię |
| **Faza 1** — Fundament online | Jeden interfejs konektora (przeglądanie, metadane, historia, wartości bieżące, zapis wyłącznie przez gateway). Katalog projektu plus edytor w GUI. Runtime jako usługa on-prem. Generyczny edytor konfiguracji generowany z `schemas/*.schema.json` | Symulowany serwer OPC UA → katalog zbudowany w GUI → runtime liczy KPI pętli na żywo i pokazuje je w konsoli. Żaden plik nie jest edytowany ręcznie (test e2e) |
| **Faza 1a** — Symulator DCS | Patrz sekcja 6 | Symulator działa jako serwer OPC UA w profilu ABB. Crosscut z Fazy 1 łączy się, buduje katalog, liczy KPI na żywo. Bilans masy się domyka (test). Odpowiedzi skokowe pętli zgadzają się z wartością odniesienia |
| **Faza 2** — Write Gateway v1 | Implementacja zgodnie z ADR 012: `off`, `advisory`, `dry_run`, `confirm`, potem `supervised`. Pierwszy protokół zapisu: OPC UA. Schemat polityki zapisu i edytor w GUI. Kolejka propozycji w konsoli. Role i logowanie | Wszystkie 12 scenariuszy gateway przechodzą przeciwko symulatorowi DCS z Fazy 1a. e2e pokazuje propozycję → potwierdzenie → zapis → odczyt zwrotny → wpis w audycie; kill switch zatrzymuje w jednym cyklu. Gateway, polityka i uprawnienia przechodzą przegląd |
| **Faza 3** — Moduł 1 jako kompletny produkt (pierwsze wydanie) | Monitoring online wszystkich pętli z katalogu. Ścieżka strojenia od detekcji do zapisu po potwierdzeniu, kontrola KPI, rollback jednym kliknięciem. Opcjonalny asystent testu skoku | Pełny cykl na symulatorze DCS: słaba pętla wykryta → test → strojenie → zapis po potwierdzeniu → poprawa KPI → rollback działa. Następnie pilotaż w zakładzie właściciela w trybie `confirm` |
| **Faza 4** — Uniwersalny silnik wirtualnych sensorów | Patrz sekcja 4.2 | Konfiguracja lab-plus-analizator zbudowana w całości w GUI odtwarza liczby z exp31. exp30 (syntetyczny) nadal spełnia swoje kryteria. Test ślepy na następnej dostawie danych |
| **Faza 5** — Konektory | PI (PI Web API, opcjonalnie AF SDK); profile SQL/ODBC (IP.21, PHD, AVEVA/Wonderware Historian, WinCC); OPC DA/HDA przez wrapper lub proxy UA; Excel i Parquet | Każdy konektor pokrywa historię, odczyt bieżący i metadane. Każdy ma test na nagranym fixture. Testy na rzeczywistych źródłach pozostają zadaniami właściciela. Zapisy pozostają wyłącznie przez gateway |
| **Faza 6** — Fuzzy w pętli zamkniętej | Porada supervisor staje się propozycją zapisu nastawy przez gateway: najpierw `confirm`, potem `supervised` | Propozycje zapisu przechodzą przez gateway; praca w `confirm`, następnie `supervised` przetestowana przeciwko symulatorowi DCS |
| **Faza 7** — MPC | Identyfikacja z testów skoku i edytowalna macierz modelu w GUI. Liniowy MPC z ograniczeniami (QP) sprawdzony na `sim/`. Runtime w C++ zgodnie z ADR 001 | MPC zapisuje nastawy przez gateway w trybie `supervised` przeciwko symulatorowi DCS |
| **Faza 8** — ML i optymalizacja | Rekomendacja zakresu pracy i warstwa ekonomiczna (RTO) ponad MPC i fuzzy | Plan zatwierdzony przez właściciela. Cel ekonomiczny i ograniczenia dostarczone przez właściciela |

## 8. Dyscyplina dowodowa i granice twierdzeń

- Zamrożone protokoły: eksperyment zamraża i commituje protokół przed jakimkolwiek uruchomieniem. Ziarna testowe uruchamia się raz. Porażki trafiają do wyników jawnie; progów się nie przesuwa.
- Eksperymenty służą funkcjom produktu z tego dokumentu. Nie są osobną linią pracy.
- Sukces w symulatorze nie jest twierdzeniem o zakładzie. Wnioski mówią „w naszym symulatorze, z naszym modelem operatora”.
- Rzeczywiste dane z zakładu pozostają poza repozytorium.

Patrz `docs/TESTING_STRATEGY.md` (drabinka L0–L7), `docs/ASSUMPTIONS.md` (niesprawdzone założenia i plany ich wycofania), `experiments/README.md` (indeks i status eksperymentów).

## 9. Reguła anty-dryf

Egzekwowana przy każdym zadaniu i zapisana do repozytoryjnego `CLAUDE.md` w Fazie 0:

1. Każde zadanie wskazuje moduł i fazę w tym dokumencie.
2. Praca na danych zakładu daje generyczną funkcję silnika plus przykładową konfigurację albo nic.
3. Nowy element najwyższego poziomu (pakiet, linia eksperymentów, narzędzie) wymaga zatwierdzenia przez właściciela.

## 10. Otwarte decyzje właściciela

| # | Decyzja | Co blokuje |
|---|---|---|
| 1 | Pierwszy DCS pilotażowy (ABB lub Siemens) dla zapisów parametrów PID i konwencji CAS | Pilotaż w Fazie 3 |
| 2 | Czy asystent testu skoku może proponować zapisy OUT w trybie manual (`confirm`) | Kryteria wyjścia Fazy 3 |
| 3 | Licencja osobnego projektu symulatora DCS RougherSim (nazwa ustalona); czy Siemens PLCSIM Advanced (wersja próbna) jest drugą kontrolą | Faza 1a |
| 4 | Czy istnieje legalny dostęp do ABB SoftController (Compact Control Builder) do sprawdzenia profilu ABB na rzeczywistym stosie | Weryfikacja ABB w Fazie 1a |
| 5 | Przegląd licencji ADR 008 (AGPL-3.0-only) | Warunki wydania |
| 6 | Przegląd listy roboczej „na ślepo” (≈20 pętli) | Dowody dla modułu 1 |
| 7 | Jeden rzeczywisty test skoku zaworu | Dowody dla modułu 1 |
| 8 | Cel optymalizacji (wartość ekonomiczna na jednostkę PV, ograniczenia pracy) | Faza 8 |
| 9 | Model uprawnień zapisu: kto może włączyć `confirm`/`supervised`, kto może zmienić politykę, co operator może zawsze zrobić | `supervised` w Fazie 2 |

Nadal istotne z PROJECT_DESIGN §8: rzeczywisty test skoku poziomu (pętla integrująca), rzeczywiste dane anomalii (≥ 2 tygodnie spokoju plus oznaczone zdarzenia), rzeczywiste dane wirtualnego sensora (znaczniki czasu labu, opóźnienie, tagi), znaczenie znacznika czasu labu i kodu braku danych, opóźnienie analizatora, kontrola w UaExpert i jeden eksport TI/TD bloku `PidCC` z ABB, precyzja ostrzeżenia o rampie na rzeczywistych lukach w archiwum, następna dostawa danych zachowana nietknięta do ślepego testu exp31.

## 11. Mapa dokumentów

| Dokument | Zastosowanie |
|---|---|
| `README.md` | Status, granice twierdzeń dla modułów, szybki start |
| `docs/PRODUCT.md` | Ten dokument: jedyna definicja produktu |
| `docs/PRODUCT.pl.md` | Polski odpowiednik tego dokumentu |
| `docs/HANDOFF.md` | Stan pracy, notatki o danych rzeczywistych, zasady pracy |
| `docs/IMPLEMENTATION_LOG.md` | Szczegóły implementacji krok po kroku |
| `docs/TESTING_STRATEGY.md` | Drabinka L0–L7, katalog wstrzykiwania awarii, backlog |
| `docs/ASSUMPTIONS.md` | Niesprawdzone założenia i plany ich wycofania |
| `docs/PROVENANCE.md` | Źródła publiczne i zbiory danych firm trzecich |
| `docs/OWNER_TASKS.md` | Co może zrobić tylko właściciel; co przynieść z powrotem |
| `docs/adr/001` | Runtime w C++, narzędzia offline w Pythonie (zaakceptowany) |
| `docs/adr/008` | Licencja AGPL-3.0-only |
| `docs/adr/009` | Konfiguracja jest danymi (proponowany) |
| `docs/adr/010` | Supervisor doradczy, bez zapisów (proponowany; stanowisko o zapisach zastąpione przez ADR 012) |
| `docs/adr/011` | Projekt ścieżki zapisu; reguły bezpieczeństwa nadal w mocy |
| `docs/adr/012` | Zapisy są cechą produktu |
| `experiments/README.md` | Indeks i status eksperymentów (zamknięte linie pozostają na miejscu) |
| `docs/archive/` | Jednorazowe plany i dokument| `docs/PROJECT_DESIGN.md` | Wyłącznie zapis historyczny; nieutrzymywany |