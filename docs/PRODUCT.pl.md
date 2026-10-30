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

### 3.1 Katalog projektu

**Cel.** Jedyny opis zakładu, który czytają wszystkie moduły. Presety (4.2), szablony urządzeń (4.3), strategie (4.4) i szablony pętli (4.1) wiążą się z rolami, a katalog jest miejscem, gdzie role spotykają rzeczywiste tagi. Nic specyficznego dla zakładu nie żyje w `*/src`; żyje tutaj, jako dane walidowane przez `schemas/`.

**Zawartość.**

| Element | Co przechowuje |
|---|---|
| **Źródła** | Typ i adres konektora, ustawienia odpytywania i historii, strefa czasowa, przesunięcie zegara. Poświadczenia są w magazynie sekretów systemu operacyjnego, nigdy w pliku katalogu |
| **Tagi** | Adres w źródle, opis, jednostka inżynierska, zakres fizyczny i limity inżynierskie, typ danych, próbkowanie i kompresja w historian, kody braków danych, odwzorowanie jakości ze źródła na good / uncertain / bad |
| **Hierarchia urządzeń** | Zakład → obszar → węzeł → urządzenie (poziomy ISA-95), każdy tag przypisany do swojego urządzenia. Dla urządzenia: krytyczność (skutek awarii) i przypisany szablon urządzenia (4.3) |
| **Pętle** | Tagi PV, SP, OUT i trybu; typ pętli (4.1); kierunek działania; limity wyjścia; powiązania kaskady, stosunku i feedforward; parametry PID w postaci dostawcy i profil dostawcy, który je przelicza |
| **Laby i analizatory** | Punkt poboru, mierzona zmienna, znaczenie znacznika czasu (początek, koniec albo środek plus przesunięcie), okno próbki złożonej, opóźnienie analizatora, kody braków danych, zakres ważności |
| **Tryby pracy** | Nazwane tryby zdefiniowane jako warunki na tagach (postój, rozruch, praca normalna, wysoka wydajność, zmiana rudy, mycie), na obszar lub urządzenie. Wspólne dla KPI pętli (4.1), wirtualnych sensorów (4.2), limitów anomalii (4.3) i stanów strategii (4.4) |
| **Jednostki** | Jednostka każdego tagu i przeliczenia między jednostkami używane przez presety i szablony |

**Profile dostawców.** Konwencje PID różnią się między dostawcami: wzmocnienie albo zakres proporcjonalności, czas całkowania w sekundach, minutach albo powtórzeniach na minutę, algorytm idealny, równoległy albo szeregowy, filtr różniczkowania. Profil dostawcy (dane, jeden plik na dostawcę: najpierw ABB, potem Siemens, potem pozostali) przelicza między postacią dostawcy a jedną wewnętrzną postacią kanoniczną. Każdy wynik strojenia i każdy zapis PID przechodzi przez to przeliczenie i pokazuje inżynierowi obie postacie.

**Budowa w GUI.**

1. Przeglądanie źródła i wybór tagów; metadane udostępniane przez źródło (jednostki i zakresy inżynierskie OPC UA, opisy, atrybuty punktów PI) są importowane automatycznie.
2. Silnik proponuje, a inżynier akceptuje lub edytuje: grupy PV/SP/OUT/tryb wykryte według wzorców nazewnictwa z profilu dostawcy, kody braków danych znalezione w danych, grupowanie urządzeń z nazw tagów, warunki trybów pracy z historii.
3. Raport gotowości (istniejące kontrole gotowości eksportu z historian) wymienia, co blokuje każdy moduł: brak zakresu, nieznana jednostka, nieodwzorowana jakość, za krótka historia.
4. Edycja masowa przez eksport i import CSV, walidowana przy imporcie, bo inżynierowie utrzymują duże listy tagów w arkuszach.
5. Każda zmiana to wersja z diffem. Konfiguracja modułu, która odwołuje się do usuniętego lub zmienionego tagu, widocznie nie przechodzi walidacji; nigdy nie działa na złym tagu.

**Dostarcza dziś.** `schemas/project.schema.json` i `schemas/tags.schema.json` (pętle, zmienne, tagi) oraz import CSV/SQL z ustawieniami braków danych trzymanymi na poziomie kodu w `loops/.../plant_import.py`. Brak edytora w GUI, powiązania ze źródłem, hierarchii urządzeń, trybów pracy, labów i profili dostawców. Domyślna stała −9999 musi zostać usunięta (issue #42).

**Faza.** 1.

## 4. Moduły

### 4.1 Monitoring pętli regulacji i strojenie PID — pierwsze wydanie

**Cel.** Powiedzieć inżynierowi, które pętle są zdrowe, które wymagają uwagi, dlaczego i co zrobić dalej, a potem bezpiecznie doprowadzić poprawkę do regulatora: detekcja → diagnoza → test → strojenie → zapis po potwierdzeniu → kontrola KPI → rollback jednym kliknięciem.

**Szablony pętli.** Każda pętla w katalogu ma typ, a każdy typ ma szablon (dane w `loops/templates/`, walidowane schematem, w pełni edytowalne): oczekiwany zakres dynamiki, progi KPI, obowiązujące reguły diagnozy, preferowana reguła strojenia i cel w pętli zamkniętej, dozwolone rodzaje testów i bezpieczny domyślny rozmiar skoku.

| Typ pętli | Typowy cel strojenia | Uwagi |
|---|---|---|
| Przepływ | Szybko i ciasno; stała czasowa pętli zamkniętej bliska opóźnieniu | Zaszumiona PV; problemy z zaworem widać tu najpierw |
| Ciśnienie (ciecz lub gaz) | Szybko (ciecz) lub umiarkowanie (gaz) | Ciśnienie gazu bywa integrujące |
| Poziom, ciasny | Trzymać poziom blisko nastawy | Proces integrujący |
| Poziom, uśredniający | Wykorzystać zbiornik do tłumienia zmian przepływu; strojenie z dopuszczalnego wahania poziomu | Integrujący; ciasne strojenie jest tu błędem, nie zaletą |
| Temperatura | Odpornie, wolno; człon D tam, gdzie uzasadniony | Długie inercje, często pętla nadrzędna kaskady |
| Gęstość i konsystencja | Umiarkowanie | Szum pomiaru i efekty pulpy |
| Skład lub analizator | Wolno, odpornie; respektowany czas próbkowania i opóźnienie analizatora | Często zasilana przez wirtualny sensor (4.2) |
| Prędkość i napęd | Szybko | Zwykle pętla podrzędna kaskady |
| Kaskada podrzędna / nadrzędna, stosunek, feedforward | Najpierw podrzędna, nadrzędna na zidentyfikowanej zamkniętej pętli podrzędnej | Szablony przechowują powiązanie i kolejność strojenia |

**KPI monitoringu** (liczone online na pętlę i na tryb pracy; wyłączone, gdy urządzenie stoi):

- współczynnik pracy: udział czasu w zamierzonym trybie (auto, kaskada);
- udział nasycenia wyjścia i czas na limitach;
- uchyb regulacji: odchylenie standardowe i całka z modułu uchybu znormalizowane zakresem;
- wskaźnik oscylacji (test ACF) i klastry oscylacji w zakładzie (pętle oscylujące ze wspólnym okresem);
- skok zaworu na godzinę, zmiany kierunku, podejrzenie stiction, kwantyzacja;
- poziom szumu PV;
- odpowiedź na zmianę nastawy, jeśli takie zmiany występują (przeregulowanie, czas ustalania);
- później: wskaźnik jakości oparty na wariancji minimalnej, gdy jego założenia zostaną sprawdzone na rzeczywistych danych.

**Lista robocza i diagnoza.** Jedno ustalenie na pętlę i problem, szeregowane według ciężkości × krytyczności urządzenia × szacowanej korzyści. Każde ustalenie wskazuje prawdopodobną klasę przyczyny i następne działanie. Kolejność diagnozy jest stała, bo strojenie „wokół” innej usterki pogarsza sytuację:

1. **Przyrząd:** zamrożona, zaszumiona lub dryfująca PV (wspólne z 4.3).
2. **Zawór:** stiction, martwa strefa, nasycenie, zły dobór → test zaworu, utrzymanie ruchu, nie strojenie.
3. **Przyczyna zewnętrzna:** pętla oscyluje z tym samym okresem co inne → znaleźć pętlę źródłową w klastrze, nie przestrajać tej.
4. **Projekt lub tryb:** pętla trzymana w manualu, zły kierunek działania, brak kaskady lub feedforward.
5. **Strojenie:** dopiero gdy 1–4 są wykluczone.

Każde ustalenie dostaje od użytkownika wynik (naprawione, to nie problem, odłożone, zgłoszone do utrzymania ruchu), jak w 4.3, więc lista robocza uczy się, które ustalenia są użyteczne.

**Ścieżka strojenia.**

1. **Model.** Z historii (identyfikacja w pętli zamkniętej, FOPDT lub integrujący) albo z testu skoku zaplanowanego przez asystenta. Bramka jakości modelu odmawia strojenia, gdy danych jest za mało (skoki tylko SP, obcinanie, za małe ruchy wyjścia, nieznane jednostki) i mówi, jakich danych potrzeba. Odmowa jest prawidłowym wynikiem.
2. **Reguła i cel.** Reguła z szablonu (SIMC, AMIGO, lambda); inżynier wybiera kompromis szybkość/odporność suwakiem, z pokazanym zapasem odporności.
3. **Podgląd.** Przewidywana odpowiedź z obecnymi i proponowanymi parametrami obok siebie, na zidentyfikowanym modelu; parametry w postaci kanonicznej i postaci dostawcy (profil dostawcy z katalogu).
4. **Zapis.** Propozycja do Write Gateway, dla parametrów PID wyłącznie `confirm` (sekcja 5). Operator i inżynier widzą uzasadnienie, stare i nowe wartości oraz punkt rollbacku.
5. **Kontrola.** Po okresie ustalania KPI są porównywane przed i po, na tryb pracy, w oknie ustalonym w szablonie.
6. **Rollback.** Poprzednie parametry przywracane jednym kliknięciem i proponowane automatycznie, jeśli KPI się pogorszą.

**Zawory.** Prowadzony test skoku zaworu (zapis OUT w manualu to otwarta decyzja właściciela nr 2), kwantyfikacja stiction, trend zdrowia zaworu wspólny z szablonem urządzenia „zawór” (4.3).

**Korzyść i raporty.** Szacowanie korzyści: redukcja wariancji → możliwe przesunięcie nastawy w stronę limitu → wartość roczna, z wartością na jednostkę PV wpisaną przez użytkownika (warstwa ekonomiczna to otwarta decyzja właściciela nr 8). Raport zmianowy i tygodniowy pętli: co się zmieniło, co naprawiono, co nadal czeka.

**Dostarcza dziś.** Lista robocza z ustaleniami (manual, nasycenie, flatline, oscylacja); test oscylacji ACF i klastry oscylacji; KPI zdrowia zaworów, podejrzenie stiction i prowadzony test skoku; identyfikacja w pętli zamkniętej i ze skoków (FOPDT, integrujące eksperymentalnie) z bramką jakości; raport strojenia (SIMC/AMIGO, planowanie kaskady); szacowanie korzyści; widok Steps. Wszystko offline i na żądanie. Brak szablonów pętli, KPI na tryb pracy, kolejności przyczyn na liście roboczej, wyników ustaleń, zapisu, kontroli KPI i rollbacku.

**Walidacja.** Wiersze L5 względem RougherSim: źle nastrojona pętla zostaje wykryta i poprawiona; zawór ze stiction jest zdiagnozowany jako problem zaworu, a nie strojenia; pętla pobudzana zewnętrzną oscylacją nie jest przestrajana; poziom uśredniający nie jest strojony ciasno; rollback dokładnie przywraca poprzednie parametry. Dowody z zakładu: przegląd listy roboczej „na ślepo” i jeden rzeczywisty test skoku zaworu (zadania właściciela), potem pilotaż Fazy 3 w `confirm`.

**Luka do produktu.**

1. Zadanie KPI online w runtime, na tryb pracy (Faza 1).
2. Szablony pętli i profile dostawców przez katalog (Fazy 1 i 3).
3. Szeregowanie listy roboczej według krytyczności i korzyści, stała kolejność diagnozy, wyniki ustaleń (Faza 3).
4. Ścieżka strojenia z podglądem, zapisem w `confirm`, kontrolą KPI i rollbackiem (Faza 3, wymaga gateway z Fazy 2).
5. Opcjonalny asystent testu skoku (Faza 3, decyzja właściciela nr 2).

**Faza.** 1 (KPI online) i 3 (pętla produktowa).

### 4.2 Wirtualne sensory

**Cel.** Estymacja dowolnej zmiennej procesowej z innych tagów, gdy nie jest mierzona, jest mierzona rzadko i z opóźnieniem albo mierzy ją przyrząd, który może ulec awarii lub dryfować. Moduł ma cztery zastosowania, obsługiwane przez jeden silnik:

| Zastosowanie | Przykład | Co daje estymata |
|---|---|---|
| **Wnioskowanie o jakości** | Zawartość, P80, wilgotność z tagów procesowych między wynikami laboratoryjnymi albo przy opóźnionym analizatorze | Wypełnia lukę między wolnymi pomiarami |
| **Pomiar zapasowy** (redundancja analityczna) | Zapasowa waga taśmowa z mocy napędu i prędkości taśmy przenośnika; zapasowy przepływomierz z obrotów, mocy, ciśnień pompy i gęstości | Zastępuje przyrząd uszkodzony lub wyłączony do serwisu |
| **Walidacja przyrządu** | Residuum między fizyczną wagą taśmową a jej wirtualnym odpowiednikiem | Wykrywa dryf, błąd kalibracji lub zamrożony przetwornik; zasila detekcję anomalii (4.3) i monitoring pętli (4.1) |
| **Stan niemierzony** | Zapas w zasobniku lub rząpiu z bilansu masy; energia jednostkowa (kWh/t) | Dostarcza zmienną, której nikt nie mierzy |

**Struktury modeli.** Silnik nie jest wyłącznie oparty na danych. Każdy wirtualny sensor używa jednej z trzech struktur:

- **Oparta na danych:** PLS, ridge/liniowy, jeden model nieliniowy (gradient boosting). Wejścia i opóźnienia są proponowane z danych.
- **Szablon fizyczny z dopasowanymi parametrami:** równanie z pierwszych zasad o stałej strukturze, którego parametry są dopasowywane na danych z zakładu albo wpisywane z karty katalogowej. Przykłady: moc netto napędu proporcjonalna do obciążenia taśmy; prawa podobieństwa pomp plus charakterystyki wysokości podnoszenia i mocy; przepływ przez zawór z Cv(położenie), ΔP i gęstości; poziom hydrostatyczny; bilans masy węzła.
- **Hybrydowa:** szablon fizyczny plus oparta na danych korekcja jego residuum.

**Presety.** Dla każdego typowego zastosowania przemysłowego produkt dostarcza preset: gotową konfigurację, którą użytkownik mapuje na katalog i może zmienić w każdym polu. Preset to dane, nie kod: jeden plik w `softsensor/presets/`, walidowany schematem `schemas/softsensor-preset.schema.json`. Preset definiuje:

- zmienną docelową, jednostkę i zakres fizyczny;
- **role wejść**, a nie nazwy tagów (na przykład `drive_power`, `belt_speed`; role wymagane i opcjonalne, oczekiwana jednostka i zakres); użytkownik przypisuje każdej roli tag z katalogu, z kontrolą jednostek;
- strukturę modelu, równanie i parametry z wartościami domyślnymi, granicami oraz wskazaniem, które są dopasowywane;
- domyślne przetwarzanie wstępne: opóźnienia, filtry, zakresy ważności, obsługę braków danych;
- **warunki ważności:** kiedy estymata ma sens (pompa pracuje, taśma obciążona, otwarcie zaworu w zaufanym zakresie Cv, wnętrze obszaru kalibracji); poza nimi estymata jest oznaczana jako nieważna;
- procedurę kalibracji: względem fizycznego przyrządu, gdy jest sprawny, względem labu lub analizatora, albo wyłącznie z wartości katalogowych;
- metryki jakości i naiwny punkt odniesienia, który musi pokonać (ostatnia wartość laboratoryjna, ostatnia dobra wartość przyrządu, stała).

Wartości domyślne w presecie pochodzą ze źródeł publicznych z wierszem w `docs/PROVENANCE.md`, nigdy z zakładu. Dostosowany preset zapisuje się jako wersjonowaną konfigurację projektu; dostarczony preset pozostaje bez zmian. Opcja „Custom” (oparta na danych, bez presetu) jest zawsze dostępna.

**Katalog presetów.** Proponowany zestaw pierwszego wydania oznaczono **v1**; reszta to plan rozwoju. Ostateczny zestaw v1 to decyzja właściciela (sekcja 10).

| Preset | Estymuje | Typowe wejścia | Struktura | v1 |
|---|---|---|---|---|
| Zapasowa waga taśmowa | Masowe natężenie przepływu ciał stałych, t/h; tonaż sumaryczny | Moc lub prąd napędu, prędkość taśmy, krzywa mocy pustej taśmy, (nachylenie, długość) | Fizyczna: moc netto ∝ obciążenie × prędkość; kalibracja względem wagi | **v1** |
| Zapasowy przepływomierz z pompy | Przepływ objętościowy | Obroty pompy, moc silnika, ciśnienie tłoczenia i ssania, gęstość | Fizyczna: prawa podobieństwa + charakterystyki H/P; korekcja hybrydowa na zużycie | **v1** |
| Przepływomierz z zaworu | Przepływ przez zawór regulacyjny | Położenie zaworu, ciśnienie przed i za zaworem, gęstość, krzywa Cv | Fizyczna: równanie zaworu (postać IEC 60534) | **v1** |
| Przepływ ciał stałych i gęstość pulpy | Sucha masa t/h, % części stałych | Przepływ objętościowy, gęstość pulpy, gęstość właściwa ciał stałych | Fizyczna: bilans masy i objętości; zapasowa gęstość z mocy pompy i przepływu (hybrydowa) | **v1** |
| Uziarnienie przelewu hydrocyklonu | P80 lub % przejścia przez sito | Ciśnienie na cyklonie, gęstość nadawy, przepływ nadawy, liczba otwartych cyklonów | Hybrydowa: empiryczny model klasyfikacji + korekcja z danych; kalibracja na labie | **v1** |
| Wnioskowanie o jakości z labu / analizatora | Zawartość, uzysk, wilgotność, dowolna zmienna laboratoryjna | Opóźnione tagi procesowe, opcjonalnie analizator jako wejście referencyjne | Oparta na danych (istniejący silnik) | **v1** |
| Zapas z bilansu masy | Zapas w zasobniku, rząpiu lub zbiorniku; strumień niemierzony | Mierzone strumienie wejściowe i wyjściowe, poziom, jeśli jest | Fizyczna: bilans masy węzła z korekcją dryfu | **v1** |
| Poziom z ciśnienia | Poziom | Ciśnienie przy dnie, gęstość, (ciśnienie nad cieczą) | Fizyczna: hydrostatyka | później |
| Wypełnienie i wydajność młyna | Wypełnienie młyna, estymata świeżej nadawy | Moc młyna, ciśnienie łożysk, dźwięk, dodatek wody | Hybrydowa | później |
| Wydajność podajnika | t/h z podajnika | Prędkość podajnika, zmiana poziomu w zasobniku | Fizyczna + kalibracja | później |
| Moc cieplna i zanieczyszczenie wymiennika | Moc cieplna, temperatura wylotowa, trend UA | Przepływy, temperatury wlotowe i wylotowe | Fizyczna: bilans energii | później |
| Przepływ pary lub gazu | Przepływ masowy | Położenie zaworu, ciśnienia, temperatura | Fizyczna: równanie zaworu lub kryzy dla płynu ściśliwego | później |
| Energia jednostkowa | kWh/t | Tagi mocy i wydajności | Obliczenie | później |
| Uzgadnianie danych węzła (data reconciliation) | Uzgodnione przepływy, flagi błędów grubych | Wszystkie redundantne strumienie węzła | Ważona metoda najmniejszych kwadratów | później |

**Tryby pracy wdrożonego wirtualnego sensora.**

- `shadow`: liczony i porównywany z fizycznym przyrządem; residuum jest logowane i monitorowane. Domyślny dla presetów zapasowych i walidacyjnych.
- `backup`: publikowany jako wartość zastępcza, gdy fizyczny przyrząd zostanie uznany za niesprawny (zły status jakości, flatline, residuum ponad limit albo ręczne przełączenie przez operatora).
- `primary`: jedyne źródło zmiennej (wnioskowanie o jakości, stan niemierzony).

Każda estymata ma status jakości (good, uncertain, bad, odwzorowane na kody statusu OPC UA) oraz pasmo niepewności z residuów kalibracji. Rekalibracja jest proponowana, a nie stosowana po cichu, gdy residuum względem sprawnego przyrządu dryfuje; korekcja błędu (bias) jest przełączalna, a jej parametry żyją w schemacie.

**Granica z systemem sterowania.** Crosscut zapisuje wyłącznie tag wyjściowy wirtualnego sensora, przez Write Gateway (sekcja 5). O tym, czy pętla użyje wartości zapasowej jako PV, decyduje logika DCS, która czyta tag wyjściowy i jego status jakości; Crosscut nigdy nie przełącza źródła PV ani trybu regulatora.

**Dostarcza dziś.** Silnik (`softsensor/`) jest generyczny względem tagów, ale:

- obsługuje tylko PLS i działa wyłącznie offline;
- GUI potrafi jedynie odczytać konfigurację; nową konfigurację można dodać tylko przyciskiem „Load example”;
- w kodzie nie ma `reference input`. Analizator online może być jedynie zwykłym tagiem wejściowym. PROJECT_DESIGN §4.4 twierdził, że wejście referencyjne istnieje; niniejszy dokument to koryguje;
- korekcja błędu (bias) jest zawsze włączona; jej parametry są stałymi w `softsensor/.../bias.py`;
- nie ma szablonów fizycznych, presetów, warunków ważności, trybów pracy ani statusu jakości.

**Przypadki walidacyjne.** Praca nad analizatorem zakładu 1 (exp31, `tools/analyzer_vs_lab.py`, `tools/lab_extract.py`) jest przypadkiem walidacyjnym dla wnioskowania o jakości, a nie osobną funkcją; zostaje wchłonięta w Fazie 4a. Każdy preset v1 dostaje wiersz L5 względem RougherSim: wartość odniesienia z symulatora oraz scenariusz wstrzykiwania awarii, który psuje fizyczny przyrząd i sprawdza przełączenie oraz dokładność. RougherSim musi udostępniać sygnały potrzebne presetom (moc napędu i prędkość taśmy, obroty, moc i ciśnienia pompy, położenie zaworu, ciśnienie na cyklonie); tam, gdzie jeszcze tego nie robi, jest to pozycja kamienia milowego RougherSim, a nie kod Crosscut. Wyniki z symulatora nie są twierdzeniami o zakładzie.

**Luka do produktu (Faza 4a).**

1. Schemat presetu, loader presetów i presety v1, każdy z wierszem PROVENANCE przed implementacją.
2. Struktury szablonu fizycznego i hybrydowa obok biblioteki opartej na danych (PLS, ridge/liniowy, gradient boosting); zawsze zablokowana walidacja krzyżowa; tabela porównania względem naiwnego punktu odniesienia presetu.
3. Typ celu: lab, analizator, fizyczny przyrząd albo brak, jako konfiguracja użytkownika: znaczenie znacznika czasu (początek, koniec albo środek plus przesunięcie), okno próbki złożonej, opóźnienie analizatora, kody braków danych i zakresy ważności. Wyszukiwanie opóźnienia (lag search). Jawne `reference input`.
4. Warunki ważności, status jakości, pasmo niepewności oraz tryby `shadow` / `backup` / `primary` z regułami przełączania w runtime. Residua publikowane do detekcji anomalii.
5. Kreator w GUI: wybór presetu lub Custom → przypisanie ról do tagów z katalogu → akceptacja lub edycja parametrów (punkty charakterystyki pompy, tabela Cv, dane taśmy albo dopasowanie z danych) → kalibracja na oknie → raport walidacyjny → wybór trybu → wdrożenie do runtime → opcjonalnie zapis estymaty do tagu DCS przez gateway.

**Faza.** 4a.

### 4.3 Detekcja anomalii i predykcyjne utrzymanie ruchu (część monitoringu)

**Cel.** Wcześnie powiedzieć inżynierowi, że coś idzie źle, gdzie i ile czasu zostało na reakcję. Trzy poziomy korzystają z jednego silnika:

| Poziom | Pytanie | Typowe sygnały |
|---|---|---|
| **Anomalia procesu** | Czy zakład zachowuje się inaczej niż w normalnej pracy w tym trybie? | Wiele tagów procesowych naraz (wielowymiarowo) |
| **Zdrowie przyrządu** | Czy ten przetwornik jest zamrożony, dryfuje, szumi albo stracił kalibrację? | Sam tag, jego redundantny lub wirtualny odpowiednik (4.2), zachowanie pętli (4.1) |
| **Zdrowie urządzenia** (predykcyjne utrzymanie ruchu) | Czy ta pompa, przenośnik, młyn, silnik lub zawór się degraduje i jak szybko? | Tagi z DCS i historian: moc i prąd, temperatury łożysk i uzwojeń, ciśnienia, przepływ względem obrotów, ogólne wartości drgań importowane jako tagi |

Analiza widmowa drgań, analiza oleju i termowizja są poza zakresem: ich wyniki trafiają do Crosscut jako tagi z systemów, które je wytwarzają.

**Łańcuch przetwarzania.** Moduł stosuje strukturę warstw ISO 13374 (przetwarzanie danych monitorowania stanu): pozyskanie danych → obróbka danych (czyszczenie, kody braków, przepróbkowanie, cechy) → wykrycie stanu (czy jest nienormalnie?) → ocena zdrowia (co się degraduje i jak bardzo?) → prognoza (ile czasu do limitu?) → porada (co zrobić i dla kogo). Każda warstwa ma własny wynik w konsoli i w dzienniku audytu, więc inżynier widzi, skąd wziął się wniosek.

**Reguły projektowe** (z publicznej praktyki monitorowania procesów, zarządzania alarmami i utrzymania ruchu według stanu; każde źródło dostaje wiersz w `docs/PROVENANCE.md` przed implementacją):

1. **Najpierw kontekst pracy.** Model zna tryb pracy. Użytkownik definiuje tryby jako warunki na tagach z katalogu (postój, rozruch, praca normalna, wysoka wydajność, zmiana rudy, mycie); silnik może proponować tryby przez klasteryzację historii, a użytkownik je akceptuje. Każdy detektor ma limity na tryb. W stanach nieprocesowych (urządzenie zatrzymane, rozruch, odstawienie) detektory są wyciszone, a nie alarmują. Jeden model dla zakładu wielotrybowego to najczęstsza przyczyna fałszywych alarmów.
2. **Dane normalne wybiera człowiek i są one zapisane.** Okno uczące wybiera się w GUI, znane zdarzenia są wykluczane, a wykluczenia zapisuje się razem z modelem. Minimalna ilość spokojnych danych na tryb jest parametrem schematu (wartość dla zakładu pozostaje zadaniem właściciela: ≥ 2 tygodnie plus oznaczone zdarzenia).
3. **Wartość oczekiwana i residuum dla urządzeń.** Wskaźnik zdrowia urządzenia to różnica między tym, co urządzenie robi, a tym, co powinno robić w tych samych warunkach: temperatura łożyska względem obciążenia, obrotów i temperatury otoczenia; moc i wysokość podnoszenia pompy względem przepływu, obrotów i gęstości (szablon charakterystyki pompy z 4.2); moc napędu względem obciążenia taśmy; skok zaworu względem sygnału sterującego (kontrole zaworów z 4.1). Residuum usuwa wpływ punktu pracy, więc stały górny limit nie przeoczy awarii przy niskim obciążeniu.
4. **Adaptacja jest bramkowana i widoczna.** Limity i modele mogą podążać za powolną normalną zmianą, ale aktualizacje odbywają się wyłącznie w ustalonej, zdrowej pracy i nigdy nie wchłaniają otwartego zdarzenia. Aktualizacja jest proponowana, wersjonowana i akceptowana przez inżyniera, nigdy cicha.
5. **Niewiele, ale znaczących powiadomień.** Zdarzenia Crosscut to powiadomienia doradcze w konsoli, a nie alarmy DCS, ale stosują praktykę zarządzania alarmami (ANSI/ISA-18.2, EEMUA 191): opóźnienie załączenia i wyłączenia (trwałość), histereza, priorytet z konsekwencji i czasu na reakcję, odkładanie (shelving) z powodem i terminem wygaśnięcia, wyciszanie zależne od stanu pracy oraz grupowanie skorelowanych wykryć w jedno zdarzenie z jednym kandydatem na przyczynę. Budżet powiadomień na rolę użytkownika jest konfigurowany i śledzony; jego przekroczenie samo jest pokazywane jako problem zdrowia monitoringu.
6. **Diagnoza, nie tylko detekcja.** Każde zdarzenie wskazuje tagi, które się do niego przyczyniają, ich kolejność w czasie (co ruszyło się pierwsze) oraz kontekst z katalogu: pętla w manualu, zawór w nasyceniu, nieodświeżany przetwornik, residuum wirtualnego sensora, niedawna zmiana nastawy. Jeśli dla urządzenia istnieje tabela trybów awarii, zdarzenie wymienia prawdopodobne tryby awarii.
7. **Informacja zwrotna zamyka pętlę.** Każde zdarzenie dostaje od użytkownika wynik: potwierdzona usterka, problem z przyrządem, zmiana procesu, fałszywy alarm, nieznane; opcjonalnie numer zlecenia pracy. Wyniki budują zbiór oznaczony, dają precyzję każdego detektora i pokazują dryf: detektor, którego precyzja spada, jest oznaczany do przeglądu.
8. **Wartością jest czas wyprzedzenia.** Dla urządzeń użytecznym wynikiem jest ostrzeżenie przed utratą funkcji (przedział P-F). Prognoza jest pokazywana jako **czas do limitu**: trend wskaźnika zdrowia ekstrapolowany do limitu użytkownika, z pasmem niepewności. Nie twierdzimy nic o pozostałym czasie życia (RUL), dopóki nie istnieją rzeczywiste historie awarii dla danego typu urządzenia.
9. **Najpierw krytyczność.** Użytkownik szereguje urządzenia według skutków awarii; GUI zaczyna od tych kilku, które zatrzymują linię. Celem nie jest monitorowanie wszystkich tagów naraz.
10. **Uczciwa ewaluacja.** Detektory ocenia się per zdarzenie: wykryte zdarzenia, czas wyprzedzenia przed znanym zdarzeniem, fałszywe zdarzenia na tydzień na tryb, czas do wykrycia. Nie używa się F1 z korektą punktową (point adjustment), bo zawyża wyniki (Kim i in., AAAI 2022). Protokoły są zamrażane przed uruchomieniem (sekcja 8).

**Szablony urządzeń.** Podobnie jak presety wirtualnych sensorów, każdy typowy rodzaj urządzenia ma szablon: dane w `anomaly/templates/`, walidowane schematem `schemas/asset-template.schema.json`, w pełni edytowalne, wartości domyślne ze źródeł publicznych. Szablon definiuje role wejść, wskaźniki zdrowia (modele wartości oczekiwanej i residua), tryby awarii ze wskaźnikami, które je ujawniają (w duchu ISO 17359), warunki trybów pracy, reguły powiadomień i domyślny priorytet.

| Szablon | Wskaźniki (przykłady) | Pokazywane tryby awarii | v1 |
|---|---|---|---|
| Pompa wirowa do pulpy | Moc i wysokość podnoszenia względem przepływu, obrotów, gęstości; residuum temperatury łożyska; zapas ciśnienia ssania | Zużycie wirnika i wykładzin, ryzyko kawitacji, degradacja łożysk, zatkanie | **v1** |
| Przenośnik taśmowy | Moc napędu względem obciążenia taśmy; równowaga prądów silników; waga taśmowa względem wirtualnego odpowiednika (4.2); wyłączniki zbiegu i poślizgu | Wzrost oporów, awaria krążnika lub bębna, poślizg, dryf wagi | **v1** |
| Silnik i przekładnia | Residuum temperatury uzwojeń i łożysk względem obciążenia i otoczenia; asymetria prądów; trend ogólnego tagu drgań | Zużycie łożysk, utrata chłodzenia, przeciążenie, niewspółosiowość | **v1** |
| Zawór regulacyjny | Odchyłka skoku, wskaźniki tarcia statycznego i martwej strefy (4.1), nasycenie wyjścia, ciśnienie w siłowniku | Stiction, usterka siłownika lub ustawnika, zły dobór | **v1** |
| Przetwornik | Zamrożona wartość, zmiana szumu, dryf względem redundantnego lub wirtualnego odpowiednika | Przyrząd zamrożony, dryfujący lub uszkodzony | **v1** |
| Młyn | Moc względem wypełnienia i nadawy, ciśnienie łożysk, trend zużycia wykładzin względem tonażu | Przeciążenie, zużycie wykładzin, problem ze smarowaniem | później |
| Bateria hydrocyklonów | Ciśnienie względem przepływu i gęstości, gęstość przelewu | Roping, zatkany wylew, zużyty cyklon | później |
| Komora flotacyjna | Moc mieszadła, przepływ powietrza względem zaworu, jakość regulacji poziomu | Zużycie mieszadła, zatkanie linii powietrza | później |
| Zagęszczacz | Trend momentu zgarniacza, gęstość wylewu względem obrotów pompy | Ryzyko zablokowania zgarniacza, zatkanie linii wylewu | później |
| Sprężarka lub dmuchawa | Spręż względem przepływu i mocy, temperatura tłoczenia | Zanieczyszczenie, spadek sprawności, problemy z zaworami | później |

**Granica z systemem sterowania.** Moduł nigdy nie zapisuje nastawy ani parametru regulatora. Może opublikować indeks zdrowia urządzenia albo flagę zdarzenia do tagu DCS przez Write Gateway, tą samą ścieżką co wyjścia wirtualnych sensorów (sekcja 5). Zlecenie pracy do systemu utrzymania ruchu (CMMS) to późniejszy eksport, a nie zapis do zakładu.

**Dostarcza dziś.** PCA z T2 i SPE, kolumny z opóźnieniami, reguła zablokowanego czujnika, ostrzeżenie o możliwej rampie. Runda 3 exp29 spełniła swoje kryteria. Brak trybów pracy, szablonów urządzeń, modeli wartości oczekiwanej, zarządzania powiadomieniami, wyników zdarzeń i prognozy.

**Walidacja.** RougherSim wstrzykuje degradacje z wartością odniesienia (zużycie pompy, rosnąca temperatura łożyska, opory przenośnika, stiction zaworu, dryf i zamrożenie przetwornika) oraz zmiany trybu pracy, które **nie** mogą wywołać zdarzeń. Każdy szablon v1 dostaje wiersz L5: wykrycie, czas wyprzedzenia i fałszywe zdarzenia na tryb według zamrożonego protokołu. Wstrzykiwanie degradacji, tam gdzie jeszcze nie istnieje, jest pozycją kamienia milowego RougherSim. Rzeczywiste dowody wymagają danych właściciela: spokojnych okresów na tryb i oznaczonych zdarzeń, najlepiej z historią utrzymania ruchu.

**Luka do produktu.**

1. Zadanie monitoringu online w runtime z trybami pracy i limitami na tryb (Faza 1).
2. Konfiguracja edytowalna w GUI (konfiguracje supervisor i anomalii są dziś tylko do odczytu): wybór okna normalnego z wykluczeniami, definicje trybów, ustawienia detektorów (Faza 1).
3. Zarządzanie zdarzeniami: trwałość, histereza, priorytet, odkładanie, wyciszanie zależne od stanu, grupowanie, budżet, wyniki i precyzja detektorów (Faza 3).
4. Widok zdrowia przyrządów powiązany z monitoringiem pętli i residuami wirtualnych sensorów (Faza 3).
5. Szablony urządzeń, modele wartości oczekiwanej, indeks zdrowia, czas do limitu oraz widok urządzeń w GUI uszeregowany według krytyczności (Faza 4b, wspólna maszyneria presetów z 4.2).

**Faza.** 1 (zadanie online), 3 (widok produktowy, zarządzanie zdarzeniami, zdrowie przyrządów) i 4b (szablony urządzeń i predykcyjne utrzymanie ruchu).

### 4.4 Fuzzy / supervisor ekspercki

**Cel.** Uchwycić wiedzę doświadczonych operatorów i technologów w postaci czytelnych reguł i zamienić ją w poradę na poziomie procesu (pierwszy przypadek walidacyjny: natężenie zasilania), bramkowaną stanem pętli, wyjaśnioną, zalogowaną i potwierdzoną przez operatora.

**Edycja graficzna: Kanwa strategii.** Strategię ekspercką się rysuje, a nie pisze. Inżynier nigdy nie edytuje pliku ani nie wpisuje kodu; każdy element poniżej to edytor graficzny nad tą samą konfiguracją walidowaną schematem (ADR 009).

- **Kanwa z blokami i połączeniami.** Sygnały płyną od lewej do prawej przez bloki, które inżynier umieszcza i łączy: *wejścia* (tagi z katalogu, estymaty wirtualnych sensorów, wskaźniki zdrowia z 4.3, stany pętli z 4.1) → *kondycjonowanie* (filtr, szybkość zmian, średnia krocząca, opóźnienie, kontrola jakości i zakresu) → *bloki reguł* (bazy reguł fuzzy) → *łączenie* (priorytet, minimum lub maksimum, suma ważona, nadpisanie) → *wyjścia* (tekst porady, propozycja zmiany nastawy z limitami, przekazywana do Write Gateway). Strategia z wieloma wejściami staje się łańcuchem małych bloków reguł zamiast jednej nieczytelnej bazy reguł.
- **Stany procesu jako diagram stanów.** Stany takie jak rozruch, praca normalna, przeciążenie, niskie zasilanie czy zmiana rudy to bąbelki; przejścia to warunki rysowane jako strzałki. Każdy stan włącza lub wyłącza własne bloki reguł, czyli dokładnie tak, jak myślą operatorzy („gdy młyn jest przeciążony, liczą się tylko te reguły”).
- **Edytor funkcji przynależności.** Każdy termin lingwistyczny („niski”, „normalny”, „wysoki”, „rośnie”) to krzywa na rzeczywistym zakresie inżynierskim zmiennej, z histogramem wartości historycznych w tle. Inżynier przeciąga uchwyty; wartości przyciągają się do sensownych kroków; ruchomy znacznik pokazuje bieżącą wartość i to, jak mocno aktywny jest każdy termin. Kolory terminów są takie same w całej kanwie.
- **Macierz reguł i reguły zdaniowe.** Reguły dwuwejściowe to kolorowa siatka: klik w komórkę i wybór terminu wyjściowego. Te same reguły czyta się jako zdania („JEŻELI obciążenie młyna JEST wysokie I moc ROŚNIE TO zmiana zasilania JEST duże zmniejszenie”). Każda reguła ma wagę i przełącznik włącz/wyłącz. Po odtworzeniu historii siatka cieniuje każdą komórkę według tego, jak często była aktywna, co pokazuje martwe reguły i obszary pracy, których nie pokrywa żadna reguła.
- **Animacja na żywo.** W runtime i przy odtwarzaniu połączenia pokazują bieżące wartości, bloki pokazują aktywne terminy i siłę zadziałania reguł, a aktywny stan procesu jest podświetlony. Kliknięcie wyjścia prowadzi jego wyjaśnienie wstecz przez kanwę do dominujących reguł; to samo jednozdaniowe uzasadnienie trafia na ekran operatora i do dziennika audytu.
- **Najpierw próba, potem działanie.** Suwaki what-if na dowolnym wejściu, odtwarzanie okresu historycznego, backtest wyjścia strategii względem tego, co faktycznie robili operatorzy, oraz dwie wersje obok siebie na tym samym okresie.
- **Wersje i wizualny diff.** Każda zmiana to wersja; diff pokazuje przesunięte krzywe, zmienione komórki i przepięte bloki. Import i eksport jako JSON walidowany schematem.
- **Szablony strategii.** Strategie startowe dla typowych zastosowań (supervisor zasilania młyna, supervisor poziomu i powietrza flotacji, supervisor wylewu zagęszczacza), dostosowywane przez inżyniera tak jak presety z 4.2.

Szczegóły UX i otwarte pytania są w `docs/design/fuzzy-studio.md`.

**Dostarcza dziś.** Fuzzy Studio (pełna edycja zmiennych i reguł, wersje, odtwarzanie, backtest); supervisor doradczy bramkowany stanem pętli z modułu 1, wyjaśniany przez swoje dominujące reguły; dziennik audytu z łańcuchem haszy i potwierdzaniem przez operatora; tryby `off` i `advisory`. exp27 spełnił swoje zamrożone kryteria w symulacji. Nie ma kanwy bloków, diagramu stanów, cieniowania aktywnych reguł ani szablonów strategii; konfiguracja supervisor jest w GUI tylko do odczytu.

**Luka do produktu.** Konfiguracja supervisor edytowalna w GUI (generyczny edytor w Fazie 1). Kanwa strategii z blokami, połączeniami, diagramem stanów, animacją na żywo, cieniowaniem aktywnych reguł i szablonami. Porada staje się propozycją zapisu do gateway: najpierw `confirm`, później `supervised`.

**Faza.** 1 (edytor konfiguracji) i 6 (Kanwa strategii i pętla zamknięta).

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
| **Faza 0** — Sprzątanie, bez nowych funkcji | Ten dokument zastępuje PROJECT_DESIGN. ADR 012 zastępuje stanowisko „bez zapisów”. Testy strażnicze zmieniają znaczenie. `docs/archive/` dla jednorazowych planów i dokumentów. `tools/` oznaczone do wchłonięcia. Reguła anty-dryf w `CLAUDE.md`. Kamienie milowe GitHub 0–8, z Fazą 4 podzieloną na 4a i 4b. Zamknięte linie eksperymentów (stiction, ACF, idle) **nie** są przenoszone; `experiments/README.md` indeksuje ich status | Wszystkie bramki zielone po przeniesieniach. Brak martwych linków w dokumentacji. `git mv` zachowuje historię |
| **Faza 1** — Fundament online | Jeden interfejs konektora (przeglądanie, metadane, historia, wartości bieżące, zapis wyłącznie przez gateway). Katalog projektu plus edytor w GUI. Runtime jako usługa on-prem. Generyczny edytor konfiguracji generowany z `schemas/*.schema.json` | Symulowany serwer OPC UA → katalog zbudowany w GUI → runtime liczy KPI pętli na żywo i pokazuje je w konsoli. Żaden plik nie jest edytowany ręcznie (test e2e) |
| **Faza 1a** — Symulator DCS | Patrz sekcja 6 | Symulator działa jako serwer OPC UA w profilu ABB. Crosscut z Fazy 1 łączy się, buduje katalog, liczy KPI na żywo. Bilans masy się domyka (test). Odpowiedzi skokowe pętli zgadzają się z wartością odniesienia |
| **Faza 2** — Write Gateway v1 | Implementacja zgodnie z ADR 012: `off`, `advisory`, `dry_run`, `confirm`, potem `supervised`. Pierwszy protokół zapisu: OPC UA. Schemat polityki zapisu i edytor w GUI. Kolejka propozycji w konsoli. Role i logowanie | Wszystkie 12 scenariuszy gateway przechodzą przeciwko symulatorowi DCS z Fazy 1a. e2e pokazuje propozycję → potwierdzenie → zapis → odczyt zwrotny → wpis w audycie; kill switch zatrzymuje w jednym cyklu. Gateway, polityka i uprawnienia przechodzą przegląd |
| **Faza 3** — Moduł 1 jako kompletny produkt (pierwsze wydanie) | Monitoring online wszystkich pętli z katalogu. Ścieżka strojenia od detekcji do zapisu po potwierdzeniu, kontrola KPI, rollback jednym kliknięciem. Opcjonalny asystent testu skoku | Pełny cykl na symulatorze DCS: słaba pętla wykryta → test → strojenie → zapis po potwierdzeniu → poprawa KPI → rollback działa. Następnie pilotaż w zakładzie właściciela w trybie `confirm` |
| **Faza 4a** — Uniwersalny silnik wirtualnych sensorów z presetami | Patrz sekcja 4.2 | Konfiguracja lab-plus-analizator zbudowana w całości w GUI odtwarza liczby z exp31. exp30 (syntetyczny) nadal spełnia swoje kryteria. Test ślepy na następnej dostawie danych. Każdy preset v1, skonfigurowany wyłącznie w GUI, przechodzi swój wiersz L5 względem RougherSim, w tym scenariusz awarii przyrządu (kryteria przełączenia i dokładności zamrożone w protokole przed uruchomieniem) |
| **Faza 4b** — Szablony urządzeń i predykcyjne utrzymanie ruchu | Patrz sekcja 4.3 (szablony urządzeń, modele wartości oczekiwanej, indeks zdrowia, czas do limitu). Korzysta z maszynerii presetów z Fazy 4a i zarządzania zdarzeniami z Fazy 3 | Każdy szablon urządzenia v1 wykrywa wstrzykniętą w RougherSim degradację z czasem wyprzedzenia i częstością fałszywych zdarzeń ustalonymi w zamrożonym protokole i nie zgłasza zdarzeń przy zmianach trybu pracy. Widok urządzeń w GUI uszeregowany według krytyczności |
| **Faza 5** — Konektory | PI (PI Web API, opcjonalnie AF SDK); profile SQL/ODBC (IP.21, PHD, AVEVA/Wonderware Historian, WinCC); OPC DA/HDA przez wrapper lub proxy UA; Excel i Parquet | Każdy konektor pokrywa historię, odczyt bieżący i metadane. Każdy ma test na nagranym fixture. Testy na rzeczywistych źródłach pozostają zadaniami właściciela. Zapisy pozostają wyłącznie przez gateway |
| **Faza 6** — Fuzzy w pętli zamkniętej | Kanwa strategii (sekcja 4.4). Porada supervisor staje się propozycją zapisu nastawy przez gateway: najpierw `confirm`, potem `supervised` | Propozycje zapisu przechodzą przez gateway; praca w `confirm`, następnie `supervised` przetestowana przeciwko symulatorowi DCS |
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
| 10 | Zestaw presetów wirtualnych sensorów v1 (sekcja 4.2) i czy tryb `backup` wchodzi do v1; które przyrządy w zakładzie (waga taśmowa, pompa, zawór) mogą dostarczyć dane walidacyjne | Zakres Fazy 4a |
| 11 | Lista urządzeń krytycznych i szablony urządzeń v1 (sekcja 4.3); czy można udostępnić historię utrzymania ruchu (zlecenia pracy, rejestry awarii) jako oznaczone zdarzenia | Dowody dla Fazy 4b |

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
| `docs/archive/` | Jednorazowe plany i dokumenty |
| `docs/PROJECT_DESIGN.md` | Wyłącznie zapis historyczny; nieutrzymywany |