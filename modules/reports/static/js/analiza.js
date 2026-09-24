/* modules/reports/static/js/analiza.js
   Dashboard Analizy sprzedazowej — wypelnianie szkieletu danymi.

   ZASADA: ten plik NICZEGO NIE LICZY. Udzialy, zmiany procentowe, cena za m3
   i wnioski przychodza policzone z /reports/api/analytics. Poprzednik liczyl
   TTL m3, koszt kuriera netto i statystyki wykonczenia w przegladarce — to
   jeden z dlugow wypisanych w specyfikacji.

   ZASADA DRUGA: wartosci wchodza przez textContent, nigdy przez innerHTML.
   Slowniki z BaseLinkera sa brudne (delivery_method miewa wpisy w rodzaju
   „680 zl za nasz transport jesli chce”), a to jest tekst od zewnetrznego
   systemu wstawiany na strone zalogowanego uzytkownika.
*/
(function () {
  'use strict';

  var korzen = document.getElementById('analiza');
  if (!korzen) { return; }

  // roundingMode: 'halfEven' — TA SAMA regula zaokraglania, co serwerowe
  // formatuj_liczbe (Python Decimal domyslnie zaokragla do parzystej, tzw.
  // bankers' rounding: f'{Decimal("2.5"):,.0f}' == '2', nie '3'). Bez tego
  // Intl.NumberFormat domyslnie zaokragla „od zera" (2,5 -> 3) i ta sama
  // liczba potrafi wyjsc inaczej w kafelku KPI (ten plik) niz we wniosku
  // ponizej niego (ten sam kafelek: np. _wniosek_srednie sklada zdanie z
  // dane.kpi.srednie_zamowienie i dane.kpi.zamowienia przez formatuj_liczbe —
  // znalezisko z przegladu, WAZNE 7). Przegladarka NIE dostaje od serwera
  // gotowego napisu dla samych kafelkow (tylko dla zdan wnioskow, ktore i tak
  // ida przez textContent bez przeliczania — patrz rysujWnioski), wiec
  // jedyny sposob, zeby ta sama liczba wygladala tak samo wszedzie, to
  // liczyc zaokraglenie DOKLADNIE tak samo jak serwer.
  //
  // useGrouping: 'always' — z tego samego powodu dla SPACJI TYSIECY. Polska
  // regula Intl grupuje dopiero od pieciu cyfr, wiec „2027,4" zostawalo bez
  // spacji („+2027,4% wobec surowego", porzadki koncowe, punkt 3h), a serwerowe
  // formatuj_liczbe pisze „2 027,4". Silnik bez Intl NumberFormat v3 (ten sam,
  // ktory nie zna roundingMode) traktuje napis jak `true` i wraca do reguly
  // polskiej — nic sie nie psuje.
  var fmt0 = new Intl.NumberFormat('pl-PL',
    { maximumFractionDigits: 0, roundingMode: 'halfEven', useGrouping: 'always' });
  var fmt1 = new Intl.NumberFormat('pl-PL',
    { minimumFractionDigits: 1, maximumFractionDigits: 1, roundingMode: 'halfEven',
      useGrouping: 'always' });
  var fmt2 = new Intl.NumberFormat('pl-PL',
    { minimumFractionDigits: 2, maximumFractionDigits: 2, roundingMode: 'halfEven',
      useGrouping: 'always' });

  // Kolory serii wprost z makiety. Kanaly maja kolory nazwane, bo czytelnik
  // rozpoznaje je miedzy kartami; pozostale wymiary dostaja kolor wg rangi.
  var KOLORY_KANALU = {
    shop: '#0F7D94', sklep: '#0F7D94',
    allegro: '#6B5B8A',
    personal: '#ED6B24', manual: '#ED6B24',
    olx: '#8A8278'
  };
  var KOLORY_RANGI = ['#ED6B24', '#ED6B24', '#F0A473', '#F0A473', '#C9C2B7', '#E7CDB7', '#A8420E'];
  var KOLORY_PIERSCIENIA = ['#C9C2B7', '#ED6B24', '#0F7D94', '#6B5B8A', '#E7CDB7'];

  // Kolor kawalka kola — JEDNA funkcja dla pierscienia i obu legend
  // (wykonczenia, kolo klientow). INDEKS koloru przychodzi z serwera
  // (`w.indeks_koloru`, analiza_service._przydziel_kolory) i idzie za
  // ENCJA: wartosc ma ten sam kolor przy kazdej kombinacji wykluczen.
  // Indeks 0 (#C9C2B7, `--neutral` z analiza.css) to kolor NEUTRALNY
  // (analiza_service.INDEKS_NEUTRALNY): nosi go „Pozostale (N)" i kazda
  // wartosc spoza czolowki karty bez wykluczen, zadna kategoria.
  // Ten plik tylko tlumaczy indeks na barwe. Kolory NIGDY nie ida cyklicznie
  // (indeks modulo dlugosc palety dawal ogonowi kolory widocznych kawalkow,
  // weryfikacja partii E, D5); `Math.min` pilnuje, zeby indeks spoza palety
  // nie zawinal sie na jej poczatek. Wiersze rozwinietego ogona to czesci
  // kawalka „Pozostale" i serwer daje im JEGO indeks.
  function kolorKawalka(indeks) {
    return KOLORY_PIERSCIENIA[Math.min(indeks, KOLORY_PIERSCIENIA.length - 1)];
  }

  /* ---------- przelacznik miary „zl / szt. / zl + szt." (24.09.2026) ---------- */

  // CO RYSUJE TRYB, mowi serwer: `dane.przelaczniki[klucz].opcje[].miary`
  // (analiza_service.MIARY_TRYBOW). PIERWSZA miara to slupki — dlugosc slupka
  // i pierwsza kolumna liczb na liscie, lewa os wykresu czasowego, kawalki
  // kola, kolor mapy, pole „Sprzedaz" w KPI. DRUGA (tylko tryb „zl + szt.")
  // to krzywa na prawej osi albo druga kolumna liczb. Ten plik nie zna nazw
  // trybow ani nie ma wlasnej listy miar — dostaje je z payloadu.
  //
  // Kafelek bez przelacznika (i kafelek, ktorego opisu payload nie niesie)
  // rysuje sie w zlotowkach, jak przed przelacznikiem.
  var MIARY_DOMYSLNE = ['netto'];

  // Klucze wiersza payloadu, ktore niosa DANA miare (kontrakt etapu SERWER):
  // udzial %, srodek kola i stopien kartogramu dla sztuk leza pod wlasnymi
  // kluczami obok zlotowkowych. To NAZWY kluczy, nie liczby — kazda liczba
  // przychodzi policzona z serwera. Tak samo dopisek pod kolem klientow
  // (`uwaga`): zdanie, ktore nazywa miare kawalka, ma wariant dla sztuk
  // gotowy z serwera — ten plik tekstu nie sklada.
  var POLA_MIARY = {
    netto: { udzial: 'udzial', najwiekszy: 'najwiekszy', poziom: 'poziom', uwaga: 'uwaga' },
    sztuki: { udzial: 'udzial_sztuk', najwiekszy: 'najwiekszy_sztuk', poziom: 'poziom_sztuk',
              uwaga: 'uwaga_sztuk' }
  };

  function polaMiary(miara) {
    return POLA_MIARY[miara] || POLA_MIARY[MIARY_DOMYSLNE[0]];
  }

  // KARTA W MIERZE TRYBU. Funkcje rysujace czytaja z wiersza zawsze `netto`
  // (dlugosc slupka, liczba obok, wielkosc kawalka kola, kwota w legendzie)
  // i `udzial`, a z karty `najwiekszy` — tak jak przed przelacznikiem. Dla
  // trybu z inna pierwsza miara PRZEPISUJEMY pola tej miary pod te nazwy
  // (sztuki pod `netto`, `udzial_sztuk` pod `udzial`, `najwiekszy_sztuk` pod
  // `najwiekszy`), a druga miare trybu „zl + szt." pod `druga`. To
  // PRZEPISANIE gotowych liczb z serwera, nie liczenie — ten sam zabieg, co
  // kartaKubelkowa. Dzieki niemu slupek i liczba obok czytaja w kazdym
  // trybie JEDNO pole i nie maja jak sie rozjechac.
  //
  // Tryb domyslny zwraca TE SAME obiekty, co w payloadzie — pulpit „zl"
  // rysuje sie dokladnie tak jak przed przelacznikiem.
  function kopiaObiektu(obiekt) {
    var kopia = {};
    Object.keys(obiekt).forEach(function (k) { kopia[k] = obiekt[k]; });
    return kopia;
  }

  function trybDomyslny(miary) {
    return miary.length === 1 && miary[0] === MIARY_DOMYSLNE[0];
  }

  function wierszWMierze(w, miary) {
    if (!w || trybDomyslny(miary)) { return w; }
    var pola = polaMiary(miary[0]);
    var nowy = kopiaObiektu(w);
    nowy.netto = w[miary[0]];
    if (Object.prototype.hasOwnProperty.call(w, pola.udzial)) { nowy.udzial = w[pola.udzial]; }
    if (miary[1]) { nowy.druga = w[miary[1]]; }
    return nowy;
  }

  function wierszeWMierze(lista, miary) {
    if (!lista || trybDomyslny(miary)) { return lista; }
    return lista.map(function (w) { return wierszWMierze(w, miary); });
  }

  function kartaWMierze(karta, miary) {
    if (!karta || trybDomyslny(miary)) { return karta; }
    var nowa = kopiaObiektu(karta);
    nowa.wiersze = wierszeWMierze(karta.wiersze || [], miary);
    nowa.ogon = wierszeWMierze(karta.ogon || [], miary);
    var pola = polaMiary(miary[0]);
    if (Object.prototype.hasOwnProperty.call(karta, pola.najwiekszy)) {
      nowa.najwiekszy = karta[pola.najwiekszy];
    }
    if (Object.prototype.hasOwnProperty.call(karta, pola.uwaga)) {
      nowa.uwaga = karta[pola.uwaga];
    }
    return nowa;
  }

  // Obszary kartogramu: stopien skali miary trybu pod `poziom` (serwer liczy
  // go dla kazdej miary osobno). Reszta pol obszaru zostaje — dymek pokazuje
  // prawdziwe zlotowki, objetosc i zamowienia takze w trybie „szt.".
  function obszaryWMierze(obszary, miara) {
    var pole = polaMiary(miara).poziom;
    if (pole === 'poziom') { return obszary; }
    return obszary.map(function (obszar) {
      var nowy = kopiaObiektu(obszar);
      nowy.poziom = obszar[pole];
      return nowy;
    });
  }

  // Os wykresu trendu w TYSIACACH (podzialka „440k", podpis „tys. …") ma
  // wylacznie miara zlotowkowa — tak jak dotad. Sztuk jest w miesiacu kilka
  // tysiecy, a „2k" mowiloby mniej niz „1 600".
  var MIARY_W_TYSIACACH = { netto: true };

  function opisPrzelacznika(wezel, dane) {
    var klucz = wezel.getAttribute('data-klucz');
    return (dane && dane.przelaczniki && dane.przelaczniki[klucz]) || null;
  }

  // Miary, ktore kafelek rysuje w SWOIM biezacym trybie. Tryb niesie atrybut
  // kafelka (`data-tryb-miary`, wypisany przez serwer jako domyslny); tryb,
  // ktorego lista opcji nie zna, rysuje sie jak domyslny.
  function miaryKafelka(wezel, dane) {
    var opis = opisPrzelacznika(wezel, dane);
    if (!opis || !opis.opcje) { return MIARY_DOMYSLNE; }
    var tryb = wezel.getAttribute('data-tryb-miary') || opis.domyslny;
    var opcja = opis.opcje.filter(function (o) { return o.tryb === tryb; })[0]
      || opis.opcje.filter(function (o) { return o.tryb === opis.domyslny; })[0];
    return (opcja && opcja.miary && opcja.miary.length) ? opcja.miary : MIARY_DOMYSLNE;
  }

  // PRZELACZENIE TRYBU. Obie miary przyszly juz w payloadzie kafelka
  // (`danePulpitu`, zapamietany przy ostatnim rysowaniu), wiec kafelek rysuje
  // sie od nowa TA SAMA funkcja, co przy ladowaniu strony — bez zadnego
  // zadania do serwera. Stan trybu to stan WIDOKU: nie idzie do adresu ani do
  // ukladu, a kafelek przyniesiony z serwera (podglad wymiaru, odswiezenie,
  // „Anuluj") zaczyna od trybu domyslnego.
  //
  // Grupa radiowa: zaznaczona opcja ma `aria-checked` i JEDYNY przystanek
  // Taba w grupie (tabIndex 0), reszta -1 — strzalki chodza po niej
  // (podepnijPrzelaczniki).
  function ustawTrybMiary(wezel, tryb, zFokusem) {
    var grupa = wezel.querySelector('[data-przelacznik]');
    if (!grupa || !tryb) { return; }
    var zmiana = wezel.getAttribute('data-tryb-miary') !== tryb;
    wezel.setAttribute('data-tryb-miary', tryb);
    Array.prototype.forEach.call(grupa.querySelectorAll('[data-opcja-miary]'), function (opcja) {
      var wybrana = opcja.getAttribute('data-opcja-miary') === tryb;
      opcja.setAttribute('aria-checked', wybrana ? 'true' : 'false');
      opcja.tabIndex = wybrana ? 0 : -1;
      if (wybrana && zFokusem) { opcja.focus(); }
    });
    if (!zmiana) { return; }
    // Dymek pokazywal liczby poprzedniej miary — nie moze zostac na ekranie.
    schowajDymekWykresu();
    if (wezel.querySelector('[data-mapa]')) { schowajDymek(); }
    // Kafelek bez danych (szkielet) narysuje sie w nowym trybie sam, gdy
    // przyjdzie payload — rysujKafelek czyta tryb z atrybutu.
    if (wezel.danePulpitu) { rysujKafelek(wezel, wezel.danePulpitu); }
  }

  // Tryb edycji zaczyna sie od kafelkow w trybie DOMYSLNYM: przelacznik jest
  // wtedy schowany (naglowek nalezy do narzedzi kafelka), a kafelek w trybie
  // „szt." bez widocznego przelacznika nie mowilby, dlaczego pokazuje sztuki.
  // Domyslny tryb wypisuje serwer na grupie (`data-domyslny`).
  function przywrocTrybyDomyslne() {
    kafelki().forEach(function (wezel) {
      var grupa = wezel.querySelector('[data-przelacznik]');
      if (grupa) { ustawTrybMiary(wezel, grupa.getAttribute('data-domyslny')); }
    });
  }

  // Klik i klawiatura — delegacja na korzeniu, bo kafelki przychodza
  // i odchodza (podglad, tryb edycji). Wzorzec radiogroup: strzalki
  // przechodza do sasiedniej opcji i od razu ja wybieraja (przelaczenie nic
  // nie pobiera, wiec wybor za fokusem jest tani), Home/End — do skrajnych.
  //
  // Kafelek w drodze z serwera (`aria-busy`: podglad wymiaru, dociaganie)
  // nie reaguje: ma jeszcze stare liczby i za chwile zostanie wymieniony na
  // nowy, w trybie domyslnym — przelaczenie przestawiloby tylko napisy.
  function podepnijPrzelaczniki() {
    function opcjaZdarzenia(zdarzenie) {
      var cel = zdarzenie.target;
      return (cel && cel.closest) ? cel.closest('[data-opcja-miary]') : null;
    }
    korzen.addEventListener('click', function (zdarzenie) {
      var opcja = opcjaZdarzenia(zdarzenie);
      var wezel = opcja ? opcja.closest('[data-kafelek]') : null;
      if (!wezel || trybEdycji() || wezel.getAttribute('aria-busy') === 'true') { return; }
      ustawTrybMiary(wezel, opcja.getAttribute('data-opcja-miary'));
    });
    korzen.addEventListener('keydown', function (zdarzenie) {
      var opcja = opcjaZdarzenia(zdarzenie);
      var wezel = opcja ? opcja.closest('[data-kafelek]') : null;
      if (!wezel || trybEdycji() || wezel.getAttribute('aria-busy') === 'true') { return; }
      var opcje = Array.prototype.slice.call(
        opcja.parentNode.querySelectorAll('[data-opcja-miary]'));
      var i = opcje.indexOf(opcja);
      var cel = null;
      switch (zdarzenie.key) {
        case 'ArrowRight': case 'ArrowDown': cel = opcje[(i + 1) % opcje.length]; break;
        case 'ArrowLeft': case 'ArrowUp': cel = opcje[(i - 1 + opcje.length) % opcje.length]; break;
        case 'Home': cel = opcje[0]; break;
        case 'End': cel = opcje[opcje.length - 1]; break;
        // Enter i spacja wybieraja opcje z fokusem; obsluzone jawnie z tego
        // samego powodu, co przy wierszu „Pozostale" (podepnijRozwijanie).
        case 'Enter': case ' ': case 'Spacebar': cel = opcja; break;
        default: return;
      }
      zdarzenie.preventDefault();
      ustawTrybMiary(wezel, cel.getAttribute('data-opcja-miary'), true);
    });
  }

  // Jednostki miar przychodza Z SERWERA (payload.jednostki, zrodlem jest
  // analiza_service.JEDNOSTKI_MIAR). Ten plik ich NIE zgaduje i nie trzyma
  // wlasnej listy — inaczej naglowek kolumny wypisany przez szablon i napis
  // doklejony przez JavaScript bylyby dwoma zrodlami prawdy o tym samym.
  var jednostki = {};
  // Nazwy miar („Netto", „Udzial") dla wspolnego dymka wykresow — z tego
  // samego powodu z serwera (payload.etykiety_miar, ETYKIETY_MIAR).
  var etykietyMiar = {};

  /* ---------- pomocnicze ---------- */

  function pole(sciezka) {
    return korzen.querySelector('[data-pole="' + sciezka + '"]');
  }

  function ustaw(sciezka, tekst, klasa) {
    var wezel = pole(sciezka);
    if (!wezel) { return; }
    wezel.textContent = tekst;
    if (klasa) { wezel.className = klasa; }
  }

  // Pole WEWNATRZ jednego kafelka. Od Planu D ten sam typ moze stac na
  // pulpicie kilka razy, a podglad wymiaru potrafi chwilowo dac dwa kafelki
  // o tym samym kluczu — szukanie po calej stronie trafialoby wtedy
  // w pierwszy z nich. Kafelek szuka wylacznie w sobie.
  function poleW(kafelek, sciezka) {
    return kafelek.querySelector('[data-pole="' + sciezka + '"]');
  }

  function ustawW(kafelek, sciezka, tekst, klasa) {
    var wezel = poleW(kafelek, sciezka);
    if (!wezel) { return; }
    wezel.textContent = tekst;
    if (klasa) { wezel.className = klasa; }
  }

  function czysc(wezel) {
    while (wezel.firstChild) { wezel.removeChild(wezel.firstChild); }
  }

  function el(znacznik, klasa, tekst) {
    var w = document.createElement(znacznik);
    if (klasa) { w.className = klasa; }
    if (tekst !== undefined && tekst !== null) { w.textContent = tekst; }
    return w;
  }

  // KAZDA CYFRA W IBM PLEX MONO (zasada projektu) — takze w zdaniach
  // skladanych z napisu: „najwyzej 20 kafelkow", „blad 502", „90 dni".
  // Tekst wchodzi kawalkami przez textContent, nigdy przez innerHTML.
  // `split` z grupa przechwytujaca oddaje ciagi cyfr na nieparzystych
  // indeksach.
  function tekstZCyframi(wezel, tekst) {
    czysc(wezel);
    String(tekst).split(/(\d+)/).forEach(function (kawalek, i) {
      if (!kawalek) { return; }
      wezel.appendChild(i % 2 ? el('span', 'an-mono', kawalek) : document.createTextNode(kawalek));
    });
    return wezel;
  }

  function kolorWiersza(wymiar, wartosc, indeks) {
    if (wymiar === 'order_source' && wartosc && KOLORY_KANALU[String(wartosc).toLowerCase()]) {
      return KOLORY_KANALU[String(wartosc).toLowerCase()];
    }
    return KOLORY_RANGI[Math.min(indeks, KOLORY_RANGI.length - 1)];
  }

  // Jednostka jest TEKSTEM, liczba cyframi — stad osobny <span> z krojem
  // tekstowym (IBM Plex Sans), a nie doklejenie do tresci wezla, ktory ma
  // krój monospace. Spacja przed jednostka jest NIEROZDZIELAJACA, wiec
  // „41 248" i „zl" nie rozjada sie na dwie linie na koncu wiersza.
  function jednostkaSpan(nazwa, przyrostek) {
    var tekst = jednostki[nazwa] || '';
    if (tekst && przyrostek) { tekst += ' ' + przyrostek; }
    return el('span', 'an-jednostka', ' ' + tekst);
  }

  // Liczba (monospace) plus jednostka (tekst) w jednym wezle data-pole
  // wewnatrz kafelka.
  function ustawZJednostka(kafelek, sciezka, tekst, nazwaJednostki, przyrostek) {
    var wezel = poleW(kafelek, sciezka);
    if (!wezel) { return; }
    czysc(wezel);
    wezel.appendChild(document.createTextNode(tekst));
    wezel.appendChild(jednostkaSpan(nazwaJednostki, przyrostek));
  }

  function zmianaNaTekst(wartosc) {
    if (wartosc === null || wartosc === undefined) { return '—'; }
    return (wartosc >= 0 ? '+' : '−') + fmt1.format(Math.abs(wartosc)) + '%';
  }

  function klasaZmiany(wartosc) {
    if (wartosc === null || wartosc === undefined) { return 'an-zmiana an-zmiana--brak'; }
    return 'an-zmiana ' + (wartosc >= 0 ? 'an-zmiana--wzrost' : 'an-zmiana--spadek');
  }

  // Podpis i jednostka kolumny liczb karty kubelkowej. Zmieniaja sie razem
  // z wymiarem („Klienci wedlug: liczba zamowien" ma w kolumnie zlotowki,
  // „Klienci wedlug: Opiekun" — sztuki), wiec przychodza z serwera przy kazdym
  // odswiezeniu. Ten plik ich nie sklada i nie ma wlasnej listy jednostek.
  function rysujNaglowekKolumny(kafelek, naglowek) {
    var blok = kafelek.querySelector('[data-naglowek]');
    if (!blok || !naglowek) { return; }
    var podpis = blok.querySelector('[data-naglowek-podpis]');
    var jednostka = blok.querySelector('[data-naglowek-jednostka]');
    if (podpis) { podpis.textContent = naglowek.podpis; }
    if (jednostka) { jednostka.textContent = naglowek.jednostka; }
  }

  // Wiersze karty kubelkowej w ksztalcie, ktorego oczekuje rysujWiersze.
  // To PRZEPISANIE jednej liczby pod inna nazwe, nie liczenie: `liczba`
  // przychodzi gotowa z serwera, a rysujWiersze czyta zawsze `netto`, zeby
  // slupek i wypisana liczba nie mialy jak sie rozjechac.
  function kartaKubelkowa(klucz, dane) {
    function naWiersz(w) {
      return { wartosc: w.wartosc, etykieta: w.etykieta, netto: w.liczba,
               objetosc: 0, cena_za_m3: null, zbiorczy: w.zbiorczy };
    }
    return { wymiar: klucz, wiersze: dane.wiersze.map(naWiersz),
             ogon: (dane.ogon || []).map(naWiersz) };
  }

  /* ---------- rozwijany wiersz „Pozostale (N)" ---------- */

  // Etykieta wiersza zbiorczego jako PRAWDZIWY <button>. Dzieki temu Enter
  // i spacja dzialaja natywnie, fokus jest widoczny, a czytnik ekranu dostaje
  // `aria-expanded` bez ani jednej linii wlasnej obslugi klawiatury.
  function etykietaRozwijana(tekst, klasa) {
    var przycisk = el('button', (klasa ? klasa + ' ' : '') + 'an-rozwin', tekst);
    przycisk.type = 'button';
    przycisk.title = tekst;
    przycisk.setAttribute('aria-expanded', 'false');
    return przycisk;
  }

  // Rozwiniety ogon: wszystko, co w ciele karty jest ogonem pokazanym (pojemnik
  // .an-ogon na kartach ze slupkami i w legendzie, kadr tabeli z ogonem).
  var ROZWINIETE_OGONY = '.an-ogon:not([hidden]), .an-kadr-listy--rozwiniety';

  // WYSOKOSC CIALA ZWINIETEGO karty — wymiar UKLADU, nie liczba danych. Zna
  // ja tylko silnik renderujacy, wiec czytamy ja w trybie pomiaru: klasa na
  // karcie (analiza.css: karta o wysokosci wlasnej tresci, ogony schowane,
  // regula rozwiniecia wylaczona), odczyt, zdjecie klasy. Wszystko w jednym
  // zadaniu, bez malowania pomiedzy — uzytkownik niczego nie widzi. Wynik idzie
  // do zmiennej CSS; to z niej arkusz bierze `min-height` rozwinietego ciala,
  // wiec rzad siatki po rozwinieciu ma dokladnie te wysokosc, co przedtem
  // (weryfikacja poprawek, znalezisko 3).
  function zmierzZwinieteCialo(cialo) {
    var kafelek = cialo ? cialo.closest('[data-kafelek]') : null;
    if (!kafelek) { return; }
    kafelek.classList.add('an-kafelek--pomiar');
    var wysokosc = cialo.getBoundingClientRect().height;
    kafelek.classList.remove('an-kafelek--pomiar');
    cialo.style.setProperty('--wys-zwinieta', wysokosc + 'px');
  }

  // Szerokosc strony sie zmienila (okno, zwiniety pasek boczny) — cialo
  // zwiniete ma teraz inna wysokosc, a rozwiniete karty trzymalyby stara.
  // Obserwujemy SZEROKOSC korzenia: jego wysokosc bywa wysokoscia tresci
  // i zmienia sie od samego pomiaru, wiec reagowanie na nia zapetliloby
  // obserwatora.
  function podepnijPomiarRozwinietych() {
    if (!window.ResizeObserver) { return; }
    var szerokosc = korzen.clientWidth;
    new window.ResizeObserver(function () {
      if (korzen.clientWidth === szerokosc) { return; }
      szerokosc = korzen.clientWidth;
      Array.prototype.forEach.call(korzen.querySelectorAll('.an-karta__cialo'), function (cialo) {
        if (cialo.querySelector(ROZWINIETE_OGONY)) { zmierzZwinieteCialo(cialo); }
      });
    }).observe(korzen);
  }

  // Bez wolnego miejsca w karcie ogon laduje POD dolna krawedzia ciala —
  // klikniecie „Pozostale" nie zmienialoby na ekranie nic poza paskiem
  // przewijania. Cialo przewija sie wiec tak, zeby wiersz „Pozostale" stanal
  // u gory (pod przyklejonym naglowkiem tabeli), a pod nim pierwsze wiersze
  // ogona. Przewija sie WYLACZNIE cialo karty (`scrollTop`) — strona stoi,
  // dlatego nie `scrollIntoView`, ktore przesuneloby takze ja.
  function odslonOgon(wiersz, element) {
    var cialo = wiersz.closest('.an-karta__cialo');
    if (!cialo || !element || cialo.scrollHeight <= cialo.clientHeight) { return; }
    var pierwszy = element.classList.contains('an-ogon') ? element.firstElementChild : element;
    if (!pierwszy) { return; }
    var gora = cialo.getBoundingClientRect().top;
    if (pierwszy.getBoundingClientRect().bottom <= gora + cialo.clientHeight) { return; }
    // Nad wierszem zostaje przyklejony naglowek tabeli (stoi przy samej
    // krawedzi ciala), a na kartach bez tabeli — gorny odstep ciala, ten sam
    // co nad pierwszym wierszem karty.
    var tabela = wiersz.closest('table');
    var naglowek = tabela ? tabela.querySelector('thead') : null;
    var zapas = naglowek ? naglowek.getBoundingClientRect().height
      : (parseFloat(window.getComputedStyle(cialo).paddingTop) || 0);
    cialo.scrollTop = cialo.scrollTop + wiersz.getBoundingClientRect().top - gora - zapas;
  }

  // Podpiecie rozwijania. Ogon PRZYSZEDL JUZ POLICZONY z serwera (patrz
  // analiza_service._wiersze_wymiaru) — ten kod wylacznie go pokazuje i chowa.
  // Zadna liczba tutaj nie powstaje.
  //
  // Nasluch siedzi na CALYM wierszu, bo 11-pikselowa etykieta to za maly cel
  // dla myszy. Klikniecie w przycisk wewnatrz bąbelkuje do wiersza, wiec
  // przelaczenie dzieje sie raz, nie dwa razy.
  function podepnijRozwijanie(wiersz, przycisk, elementy, kadr) {
    if (!elementy.length) { return; }
    wiersz.classList.add('an-rozwijalny');

    function przelacz() {
      var rozwiniete = przycisk.getAttribute('aria-expanded') !== 'true';
      // Wysokosc ciala ZWINIETEGO — PRZED pokazaniem ogona. To ona, a nie
      // tresc z ogonem, wchodzi do wysokosci rzedu siatki (patrz ROZWINIETY
      // OGON w analiza.css).
      if (rozwiniete) { zmierzZwinieteCialo(wiersz.closest('.an-karta__cialo')); }
      przycisk.setAttribute('aria-expanded', rozwiniete ? 'true' : 'false');
      elementy.forEach(function (element) { element.hidden = !rozwiniete; });
      // Klasa kadru: przyklejony naglowek tabeli w przewijanym ciele karty.
      if (kadr) {
        if (rozwiniete) { kadr.classList.add('an-kadr-listy--rozwiniety'); }
        else { kadr.classList.remove('an-kadr-listy--rozwiniety'); }
      }
      if (rozwiniete) { odslonOgon(wiersz, elementy[0]); }
    }

    wiersz.addEventListener('click', przelacz);
    // Enter i spacja OBSLUZONE JAWNIE, choc <button> robi to natywnie. Powod:
    // preventDefault() gasi natywna aktywacje, wiec przelaczenie dzieje sie
    // raz i tylko raz, niezaleznie od tego, czy przegladarka (albo warstwa
    // automatyzacji) zamienia klawisz na klikniecie. Bez tego zestawu nie da
    // sie tez sprawdzic, czy klawiatura dziala, bo syntetyczne zdarzenie
    // klawiatury nie wywoluje domyslnej akcji przycisku (sprawdzone 23.09.2026:
    // keydown dochodzi do przycisku, ale click juz sie nie rodzi).
    wiersz.addEventListener('keydown', function (zdarzenie) {
      var klawisz = zdarzenie.key;
      if (klawisz !== 'Enter' && klawisz !== ' ' && klawisz !== 'Spacebar') { return; }
      zdarzenie.preventDefault();
      przelacz();
    });
  }

  /* ---------- karty ze slupkami ---------- */

  // `gniazdo` to WEZEL ciala (albo pojemnik rozbicia kanalu), nie nazwa karty.
  // Do 23.09.2026 funkcja szukala go po stalym kluczu na calej stronie — przy
  // dwoch kafelkach tego samego typu rysowalaby oba zestawy slupkow w pierwszym.
  function rysujWiersze(gniazdo, karta, opcje) {
    if (!gniazdo) { return; }

    // Czyscimy WYLACZNIE bezposrednie dzieci. Karta kanalow ma w srodku drugi
    // pojemnik (kanal_rozbicie) i szerokie querySelectorAll zjadaloby jego
    // wiersze przy kazdym odswiezeniu karty nadrzednej.
    var dzieci = Array.prototype.slice.call(gniazdo.children);
    var przedPodsekcja = null;
    dzieci.forEach(function (dziecko) {
      // .an-ogon to pojemnik rozwinietego ogona — kasujemy go razem z wierszami,
      // inaczej przy kazdym odswiezeniu zostawalby na karcie kolejny.
      if (dziecko.classList.contains('an-wiersz')
          || dziecko.classList.contains('an-ogon')) { gniazdo.removeChild(dziecko); }
      else if (!przedPodsekcja && dziecko.classList.contains('an-podsekcja')) {
        przedPodsekcja = dziecko;
      }
    });

    // `opcje.porownanie`: wiersze segmentu, WYROWNANE CO DO INDEKSU do
    // karta.wiersze — wyrownanie robi serwer (Zadanie 10), bo tylko on wie,
    // co wpadlo do wiersza zbiorczego "Pozostale (N)".
    // `opcje.porownanieOgon`: to samo dla rozpisanego ogona, zeby rozwiniety
    // wiersz nie wygladal inaczej niz wiersze nad nim.
    var porownanie = opcje.porownanie || null;
    var ogon = karta.ogon || [];
    var porownanieOgona = opcje.porownanieOgon || null;

    // PRZELACZNIK „zl / szt. / zl + szt." (24.09.2026): karta przychodzi tu
    // juz W MIERZE TRYBU (kartaWMierze) — `netto` wiersza to pierwsza miara
    // trybu, wiec slupek, jego skala i pierwsza kolumna liczb dalej czytaja
    // TO SAMO pole. `opcje.drugaKolumna` (tylko tryb „zl + szt.") dokłada
    // druga kolumne liczb z `w.druga`; krzywej po kategoriach nie rysujemy,
    // bo sugerowalaby ciaglosc tam, gdzie jej nie ma.
    var maks = 0;
    karta.wiersze.forEach(function (w) { if (w.netto > maks) { maks = w.netto; } });
    ogon.forEach(function (w) { if (w.netto > maks) { maks = w.netto; } });
    if (porownanie) {
      porownanie.forEach(function (w) { if (w.netto > maks) { maks = w.netto; } });
    }

    function zbudujWiersz(w, i, drugiWiersz, rozwijalny) {
      var wiersz = el('div', 'an-wiersz');
      // Brak wiersza segmentu na tej pozycji znaczy zero, nie „nie rysuj" —
      // pasek o zerowej szerokosci mowi wprost, ze w segmencie tego nie ma.
      var drugi = drugiWiersz || { netto: 0 };

      var nazwa = rozwijalny
        ? etykietaRozwijana(w.etykieta, 'an-wiersz__nazwa')
        : el('span', 'an-wiersz__nazwa', w.etykieta);
      nazwa.style.width = (opcje.szerokoscNazwy || 82) + 'px';
      nazwa.title = w.etykieta;

      var tor = el('span', 'an-wiersz__tor'
        + (opcje.niskiTor ? ' an-wiersz__tor--niski' : '')
        + (porownanie ? ' an-wiersz__tor--pary' : ''));

      if (porownanie) {
        // Dwa wypelnienia, oba skalowane tym samym maksimum — inaczej pasek
        // segmentu i pasek bazy nie bylyby ze soba porownywalne wizualnie.
        var wypBaza = el('span', 'an-wiersz__wypelnienie an-wiersz__wypelnienie--baza');
        wypBaza.style.width = (maks ? (w.netto / maks) * 100 : 0) + '%';
        wypBaza.style.background = kolorWiersza(karta.wymiar, w.wartosc, i);
        tor.appendChild(wypBaza);

        var wypPorownanie = el('span', 'an-wiersz__wypelnienie an-wiersz__wypelnienie--porownanie');
        wypPorownanie.style.width = (maks ? (drugi.netto / maks) * 100 : 0) + '%';
        tor.appendChild(wypPorownanie);
      } else {
        var wyp = el('span', 'an-wiersz__wypelnienie');
        wyp.style.width = (maks ? (w.netto / maks) * 100 : 0) + '%';
        wyp.style.background = kolorWiersza(karta.wymiar, w.wartosc, i);
        tor.appendChild(wyp);
      }

      // Liczba w kolumnie to ZAWSZE to samo pole, po ktorym skalowany jest
      // slupek (w.netto) — inaczej slupek i liczba w jednym wierszu mowilyby
      // o dwoch roznych wielkosciach. Regresja buga: karty wojewodztwo
      // i dostawa mialy tu kiedys warunkowa opcje przelaczajaca liczbe na
      // objetosc, wiec slupek niosl netto, a liczba obok byla objetoscia.
      // Szerokosci kolumnie NIE nadajemy — ustala ja CSS (min-width: 10ch,
      // flex-basis: content). Dawna opcja szerokosci wartosci i tak z nim
      // przegrywala od ca9fb27 (partia E, punkt E7: martwy kod usuniety).
      var wartosc = el('span', 'an-wiersz__wartosc', fmt0.format(w.netto));
      // W trybie „zl + szt." pierwsza kolumna jest wezsza (--para, analiza.css).
      if (opcje.drugaKolumna) { wartosc.classList.add('an-wiersz__wartosc--para'); }

      wiersz.appendChild(nazwa);
      wiersz.appendChild(tor);
      wiersz.appendChild(wartosc);
      // Druga kolumna trybu „zl + szt." — druga miara TEGO SAMEGO wiersza,
      // z serwera (`druga`, kartaWMierze); naglowek nad nia podpisuje jej
      // jednostke.
      if (opcje.drugaKolumna) {
        wiersz.appendChild(el('span', 'an-wiersz__wartosc', fmt0.format(w.druga)));
      }
      wiersz.przycisk = rozwijalny ? nazwa : null;
      return wiersz;
    }

    function wstaw(element) {
      if (przedPodsekcja) { gniazdo.insertBefore(element, przedPodsekcja); }
      else { gniazdo.appendChild(element); }
    }

    karta.wiersze.forEach(function (w, i) {
      var rozwijalny = !!(w.zbiorczy && ogon.length);
      var wiersz = zbudujWiersz(w, i, porownanie ? porownanie[i] : null, rozwijalny);
      wstaw(wiersz);
      if (!rozwijalny) { return; }

      var pojemnik = el('div', 'an-ogon');
      pojemnik.hidden = true;
      ogon.forEach(function (o, j) {
        pojemnik.appendChild(zbudujWiersz(
          o, i + 1 + j, porownanieOgona ? porownanieOgona[j] : null, false));
      });
      wstaw(pojemnik);
      podepnijRozwijanie(wiersz, wiersz.przycisk, [pojemnik]);
    });
  }

  function rysujTabeleMiksu(kafelek, karta, porownanie, porownanieOgona) {
    var cialo = kafelek.querySelector('[data-lista="' + kafelek.getAttribute('data-klucz') + '"]');
    if (!cialo) { return; }
    czysc(cialo);
    var kadr = kafelek.querySelector('[data-kadr]');
    if (kadr) { kadr.classList.remove('an-kadr-listy--rozwiniety'); }
    var ogon = karta.ogon || [];

    function zbudujWiersz(w, drugi, rozwijalny) {
      var tr = el('tr');
      var komorka = el('td');
      if (rozwijalny) {
        tr.przycisk = etykietaRozwijana(w.etykieta);
        komorka.appendChild(tr.przycisk);
      } else {
        komorka.textContent = w.etykieta;
        komorka.title = w.etykieta;
      }
      tr.appendChild(komorka);
      var m3 = el('td', 'an-mono', fmt2.format(w.objetosc));
      m3.style.fontWeight = '700';
      // Druga wartosc m3 (segment porownawczy) WYROWNANA PO INDEKSIE do wiersza
      // bazy — wyrownanie robi serwer (_karta_porownania), tu tylko rysujemy.
      // Karta miksu bierze segment (KARTY_Z_SEGMENTEM), wiec bez tego wyglada
      // po wlaczeniu segmentu identycznie jak bez niego (znalezisko z przegladu).
      if (drugi) {
        m3.appendChild(el('span', 'an-mono an-wartosc--porownanie',
          ' / ' + fmt2.format(drugi.objetosc)));
      }
      tr.appendChild(m3);
      tr.appendChild(el('td', 'an-mono', w.cena_za_m3 === null ? '—' : fmt0.format(w.cena_za_m3)));
      return tr;
    }

    karta.wiersze.forEach(function (w, i) {
      var rozwijalny = !!(w.zbiorczy && ogon.length);
      var tr = zbudujWiersz(w, porownanie ? porownanie[i] : null, rozwijalny);
      cialo.appendChild(tr);
      if (!rozwijalny) { return; }
      // Wiersze ogona to <tr> i nie da sie ich opakowac we wspolny, przewijany
      // blok — chowamy je pojedynczo, a przewija sie cala tabela (kadr).
      var ukryte = ogon.map(function (o, j) {
        var wiersz = zbudujWiersz(o, porownanieOgona ? porownanieOgona[j] : null, false);
        wiersz.hidden = true;
        // Klasa dla trybu pomiaru ciala zwinietego (analiza.css).
        wiersz.classList.add('an-ogon-wiersz');
        cialo.appendChild(wiersz);
        return wiersz;
      });
      podepnijRozwijanie(tr, tr.przycisk, ukryte, kadr);
    });
  }

  // Karta przychodzi W MIERZE TRYBU przelacznika (kartaWMierze): kwota
  // w legendzie to ta sama miara, co kawalek obok niej.
  function rysujLegendeWykonczenia(kafelek, karta, porownanie, porownanieOgona) {
    var cialo = kafelek.querySelector('[data-lista="' + kafelek.getAttribute('data-klucz') + '"]');
    if (!cialo) { return; }
    czysc(cialo);
    var ogon = karta.ogon || [];

    function zbudujRzad(w, drugi, rozwijalny) {
      var rzad = el('div');
      rzad.style.cssText = 'display:flex;align-items:center;gap:7px;margin-bottom:9px';
      var probka = el('span', 'an-probka');
      probka.style.background = kolorKawalka(w.indeks_koloru);
      var nazwa = rozwijalny ? etykietaRozwijana(w.etykieta) : el('span', '', w.etykieta);
      // Nazwa ucieta wielokropkiem ma sie dac przeczytac w calosci (partia E,
      // punkt E7) — atrybut, nie innerHTML.
      nazwa.title = w.etykieta;
      nazwa.style.cssText = 'font-size:11.5px;color:#3A352E;flex-grow:1';
      var kwota = el('span', 'an-mono', fmt0.format(w.netto));
      kwota.style.cssText = 'font-size:11px;font-weight:600';
      rzad.appendChild(probka); rzad.appendChild(nazwa); rzad.appendChild(kwota);
      // Druga kwota (segment porownawczy), tym samym wyrownaniem po indeksie
      // co wiersze ze slupkami — karta wykonczenia tez bierze segment.
      if (drugi) {
        var drugaKwota = el('span', 'an-mono an-wartosc--porownanie', fmt0.format(drugi.netto));
        drugaKwota.style.cssText = 'font-size:11px;font-weight:600';
        rzad.appendChild(drugaKwota);
      }
      rzad.przycisk = rozwijalny ? nazwa : null;
      return rzad;
    }

    karta.wiersze.forEach(function (w, i) {
      var rozwijalny = !!(w.zbiorczy && ogon.length);
      var rzad = zbudujRzad(w, porownanie ? porownanie[i] : null, rozwijalny);
      cialo.appendChild(rzad);
      if (!rozwijalny) { return; }
      var pojemnik = el('div', 'an-ogon');
      pojemnik.hidden = true;
      // Wiersze ogona to czesci kawalka „Pozostale" — serwer daje im jego
      // indeks koloru.
      ogon.forEach(function (o, j) {
        pojemnik.appendChild(zbudujRzad(
          o, porownanieOgona ? porownanieOgona[j] : null, false));
      });
      cialo.appendChild(pojemnik);
      podepnijRozwijanie(rzad, rzad.przycisk, [pojemnik]);
    });
  }

  /* ---------- karta lejka ---------- */

  // Wybrany podzial lejka. `null` znaczy „uzytkownik jeszcze nie wybral" —
  // wtedy bierzemy domyslny Z PAYLOADU, zeby wartosc domyslna miala jedno
  // zrodlo (serwer), a nie dwa.
  var podzialLejka = null;

  // Ostatni payload z blokiem lejka. Przelaczenie podzialu NIE odpytuje
  // serwera: wszystkie warianty przyszly juz policzone (patrz
  // analiza_service.BEZ_PODZIALU), wiec rysujemy z tego, co juz mamy. Ten plik
  // niczego nie liczy. Zapamietuje go rysowanie kafelka lejka, nie wypelnij():
  // kafelek wstawiony w miejscu przychodzi z WLASNYM payloadem.
  var ostatnieDane = null;

  function wymiarLejka(dane) {
    return podzialLejka || dane.lejek.domyslny_wymiar;
  }

  // Lejek jest typem JEDNOKROTNYM (uklad.KATALOG), wiec na stronie stoi
  // najwyzej jeden taki kafelek — i tylko on ma selektor podzialu.
  function kafelekLejka() {
    return korzen.querySelector('[data-kafelek][data-typ="lejek"]');
  }

  // Widoczna etykieta selektora to OSOBNY <span> (przezroczysty <select> lezy
  // nad nim — patrz .an-sel-opak w analiza.css), wiec po zmianie wyboru trzeba
  // ja przepisac. Bez tego kontrolka pokazuje poprzedni wymiar, mimo ze karta
  // juz sie przeladowala.
  function ustawEtykieteSelektora(wybor) {
    var opakowanie = wybor.parentNode;
    var etykieta = opakowanie && opakowanie.querySelector('.an-sel-etykieta');
    var wybrana = wybor.options[wybor.selectedIndex];
    if (etykieta && wybrana) { etykieta.textContent = wybrana.textContent; }
  }

  // Opcje podzialu sklada SERWER (analiza_service.wymiary_lejka, lista
  // z rejestru pol). Szkielet w szablonie niesie sama opcje domyslna, zeby
  // kontrolka byla czytelna od pierwszej klatki.
  function rysujOpcjeLejka(dane, kafelek) {
    kafelek = kafelek || kafelekLejka();
    var wybor = kafelek ? kafelek.querySelector('[data-selektor-lejka]') : null;
    if (!wybor) { return; }
    var biezacy = wymiarLejka(dane);
    czysc(wybor);
    dane.lejek.wymiary.forEach(function (w) {
      var opcja = el('option', '', w.etykieta);
      opcja.value = w.nazwa;
      if (w.nazwa === biezacy) { opcja.selected = true; }
      wybor.appendChild(opcja);
    });
    ustawEtykieteSelektora(wybor);
  }

  function rysujLejek(dane, kafelek) {
    var klucz = kafelek.getAttribute('data-klucz');
    var gniazdo = kafelek.querySelector('[data-cialo="' + klucz + '"]');
    if (!gniazdo) { return; }

    // Wiersze stopni wstawiamy PRZED pierwsza podsekcja i kasujemy wylacznie
    // je — dokladnie tak samo jak rysujWiersze na kartach ze slupkami.
    var przedPodsekcja = null;
    Array.prototype.slice.call(gniazdo.children).forEach(function (dziecko) {
      if (dziecko.classList.contains('an-wiersz')) { gniazdo.removeChild(dziecko); }
      else if (!przedPodsekcja && dziecko.classList.contains('an-podsekcja')) {
        przedPodsekcja = dziecko;
      }
    });

    dane.lejek.stopnie.forEach(function (stopien, i) {
      var wiersz = el('div', 'an-wiersz');

      var nazwa = el('span', 'an-wiersz__nazwa', stopien.etykieta);
      nazwa.style.width = '96px';
      nazwa.title = stopien.etykieta;

      var tor = el('span', 'an-wiersz__tor an-wiersz__tor--niski');
      var wyp = el('span', 'an-wiersz__wypelnienie');
      // Slupek to UDZIAL stopnia w stopniu pierwszym — policzony na serwerze,
      // tutaj tylko przepisany na szerokosc. Liczba obok jest tym samym
      // stopniem w sztukach, wiec slupek i liczba nie maja jak sobie przeczyc.
      wyp.style.width = stopien.udzial + '%';
      wyp.style.background = kolorWiersza('lejek', stopien.klucz, i);
      tor.appendChild(wyp);

      var liczba = el('span', 'an-wiersz__wartosc', fmt0.format(stopien.liczba));
      var udzial = el('span', 'an-wiersz__wartosc an-wiersz__wartosc--slaba',
                      fmt1.format(stopien.udzial));
      udzial.style.width = '36px';

      wiersz.appendChild(nazwa);
      wiersz.appendChild(tor);
      wiersz.appendChild(liczba);
      wiersz.appendChild(udzial);

      if (przedPodsekcja) { gniazdo.insertBefore(wiersz, przedPodsekcja); }
      else { gniazdo.appendChild(wiersz); }
    });

    ustawW(kafelek, klucz + '.srednia_wycena', fmt0.format(dane.lejek.srednia_wycena));
    ustawW(kafelek, klucz + '.srednia_zamowiona', fmt0.format(dane.lejek.srednia_zamowiona));
    // Mediana bez ani jednej dowiazanej pary jest NIEOKRESLONA, a nie zerowa
    // — karta pokazuje wtedy kreske, tak samo jak przy zmianie z zerowej bazy.
    ustawW(kafelek, klucz + '.mediana_dni',
      (dane.lejek.mediana_dni === null || dane.lejek.mediana_dni === undefined)
        ? '—' : fmt1.format(dane.lejek.mediana_dni));
    ustawW(kafelek, klucz + '.uwaga', dane.lejek.uwaga);

    rysujPodzialLejka(dane, kafelek);
  }

  function rysujPodzialLejka(dane, kafelek) {
    kafelek = kafelek || kafelekLejka();
    if (!kafelek || !dane.lejek) { return; }
    var blok = kafelek.querySelector('[data-podzial]');
    var cialo = kafelek.querySelector('[data-lista="lejek-podzial"]');
    if (!blok || !cialo) { return; }

    var wymiar = wymiarLejka(dane);
    var podzial = dane.lejek.podzial[wymiar];
    // Brak podzialu = tabelki nie ma wcale. Karta zostaje wtedy tej samej
    // wysokosci co przed rozbudowa i nie rozpycha rzedu siatki.
    blok.hidden = !podzial;
    czysc(cialo);
    var kadr = blok.querySelector('[data-kadr="lejek-podzial"]');
    if (kadr) { kadr.classList.remove('an-kadr-listy--rozwiniety'); }
    if (!podzial) { return; }

    var naglowek = blok.querySelector('[data-naglowek-podzialu]');
    if (naglowek) {
      var opis = dane.lejek.wymiary.filter(
        function (w) { return w.nazwa === wymiar; })[0];
      naglowek.textContent = opis ? opis.etykieta : '';
    }

    var ogon = podzial.ogon || [];

    function zbudujWiersz(w, rozwijalny) {
      var tr = el('tr');
      var komorka = el('td');
      if (rozwijalny) {
        tr.przycisk = etykietaRozwijana(w.etykieta);
        komorka.appendChild(tr.przycisk);
      } else {
        komorka.textContent = w.etykieta;
        // Pelna nazwa w podpowiedzi: kolumna jest waska i tnie ja wielokropkiem.
        komorka.title = w.etykieta;
      }
      tr.appendChild(komorka);
      tr.appendChild(el('td', 'an-mono', fmt0.format(w.wycen)));
      tr.appendChild(el('td', 'an-mono', fmt0.format(w.zamowione)));
      var konwersja = el('td', 'an-mono', fmt1.format(w.konwersja));
      konwersja.style.fontWeight = '700';
      tr.appendChild(konwersja);
      return tr;
    }

    podzial.wiersze.forEach(function (w) {
      // Wiersz zbiorczy podzialu poznajemy po pustej wartosci — tak samo jak
      // na kartach ze slupkami, gdzie znacznik `zbiorczy` odroznia go od
      // prawdziwej wartosci pustej.
      var rozwijalny = !!(w.wartosc === null && ogon.length);
      var tr = zbudujWiersz(w, rozwijalny);
      cialo.appendChild(tr);
      if (!rozwijalny) { return; }
      var ukryte = ogon.map(function (o) {
        var wiersz = zbudujWiersz(o, false);
        wiersz.hidden = true;
        // Klasa dla trybu pomiaru ciala zwinietego (analiza.css).
        wiersz.classList.add('an-ogon-wiersz');
        cialo.appendChild(wiersz);
        return wiersz;
      });
      podepnijRozwijanie(tr, tr.przycisk, ukryte, kadr);
    });
  }

  /* ---------- mapa wojewodztw ---------- */

  // Indeks „identyfikator obszaru -> gotowe liczby z payloadu" trzyma KAZDY
  // blok mapy u siebie (wlasciwosc `obszaryMapy` wezla [data-mapa]). To NIE
  // jest liczenie: serwer przysyla komplet statystyk kazdego wojewodztwa,
  // a tutaj tylko zapamietujemy, do ktorego ksztaltu ktory wiersz nalezy.
  // Jeden wspolny indeks nie wystarcza od Planu D: drugi kafelek wojewodztw
  // (z innym wymiarem, bez mapy) czyscilby indeks pierwszego i dymek
  // przestawalby cokolwiek pokazywac.
  //
  // Wiersze dymka (nazwa miary, jej podpis, liczba miejsc dziesietnych) —
  // tez z serwera, razem z mapa. Przegladarka nie ma wlasnej listy miar.
  // Trzyma je KAZDY blok mapy u siebie (`miaryMapy`), obok indeksu obszarow:
  // w trybie „szt." przelacznika dymek ma dodatkowy wiersz sztuk, a tryb
  // nalezy do kafelka, nie do strony.
  var nazwaSegmentu = '';
  var dymekMapy = null;
  var dymekPrzypiety = false;

  var FORMATY = { 0: fmt0, 1: fmt1, 2: fmt2 };

  function formatujMiare(wartosc, miejsca) {
    return (FORMATY[miejsca] || fmt0).format(wartosc);
  }

  // Tekst dymka bez znacznikow — trafia do aria-label obszaru, zeby czytnik
  // ekranu przeczytal to samo, co widzi oko. Sam dymek jest wizualny
  // i ma aria-hidden, wiec bez tego obszar mowilby czytnikowi samą nazwę.
  function opisObszaru(obszar, porownanie, mapaMiary) {
    var czesci = [];
    mapaMiary.forEach(function (miara) {
      var tekst = miara.etykieta + ' '
        + formatujMiare(obszar[miara.nazwa], miara.miejsca)
        + ' ' + (jednostki[miara.nazwa] || '');
      // Segment porownawczy MUSI wejsc takze tutaj. Dymek pokazuje obie
      // liczby, wiec czytnik ekranu, ktory dostaje tylko pierwsza, czyta
      // co innego niz widzi oko.
      if (porownanie) {
        tekst += ', w segmencie ' + formatujMiare(porownanie[miara.nazwa], miara.miejsca);
      }
      czesci.push(tekst);
    });
    // Miary rozdziela SREDNIK, nie kropka: „szt." samo konczy sie kropka
    // i czytnik ekranu dostawal „599 szt.." z podwojna kropka.
    return obszar.nazwa + '. ' + czesci.join('; ');
  }

  function wypelnijDymek(obszar, porownanie, mapaMiary) {
    var tytul = dymekMapy.querySelector('[data-dymek="nazwa"]');
    var lista = dymekMapy.querySelector('[data-dymek="miary"]');
    if (!tytul || !lista) { return; }
    tytul.textContent = obszar.nazwa;
    czysc(lista);
    mapaMiary.forEach(function (miara) {
      lista.appendChild(el('dt', 'an-etykieta', miara.etykieta));
      var wartosc = el('dd', 'an-mapa__dymek-liczba',
        formatujMiare(obszar[miara.nazwa], miara.miejsca));
      wartosc.appendChild(jednostkaSpan(miara.nazwa));
      // Druga seria (segment porownawczy) — ten sam zapis co w tabeli miksu:
      // „/ liczba" wyszarzone obok wartosci bazowej. Bez niej karta po
      // wlaczeniu segmentu wygladalaby identycznie jak bez niego.
      if (porownanie) {
        wartosc.appendChild(el('span', 'an-mono an-wartosc--porownanie',
          ' / ' + formatujMiare(porownanie[miara.nazwa], miara.miejsca)));
      }
      lista.appendChild(wartosc);
    });
    var stopka = dymekMapy.querySelector('[data-dymek="segment"]');
    if (stopka) {
      stopka.textContent = porownanie ? nazwaSegmentu : '';
      stopka.hidden = !porownanie;
    }
  }

  // Dymek jest pozycjonowany fixed, wiec wspolrzedne sa wzgledem OKNA.
  // Przy krawedziach przerzucamy go na druga strone kursora, zeby nie
  // wystawal poza ekran i nie zmuszal do przewijania strony.
  function ustawPozycjeDymka(x, y) {
    var odstep = 14;
    dymekMapy.style.left = '0px';
    dymekMapy.style.top = '0px';
    var wymiar = dymekMapy.getBoundingClientRect();
    var lewo = x + odstep;
    if (lewo + wymiar.width > window.innerWidth - 8) { lewo = x - odstep - wymiar.width; }
    if (lewo < 8) { lewo = 8; }
    var gora = y + odstep;
    if (gora + wymiar.height > window.innerHeight - 8) { gora = y - odstep - wymiar.height; }
    if (gora < 8) { gora = 8; }
    dymekMapy.style.left = lewo + 'px';
    dymekMapy.style.top = gora + 'px';
  }

  function blokMapy(wezel) {
    return (wezel && wezel.closest) ? wezel.closest('[data-mapa]') : null;
  }

  // Obszar poznajemy po `data-obszar`, nie po `id`: `id` sciezki niesie
  // prefiks kafelka (dwa kafelki wojewodztw nie moga dzielic identyfikatorow),
  // a indeks bloku jest kluczowany identyfikatorem wojewodztwa z payloadu.
  function pokazDymek(ksztalt, x, y) {
    var blok = blokMapy(ksztalt);
    var obszary = blok ? blok.obszaryMapy : null;
    var wpis = obszary ? obszary[ksztalt.getAttribute('data-obszar')] : null;
    if (!dymekMapy || !wpis) { return; }
    wypelnijDymek(wpis.dane, wpis.porownanie, blok.miaryMapy || []);
    dymekMapy.hidden = false;
    ustawPozycjeDymka(x, y);
  }

  function schowajDymek() {
    if (!dymekMapy) { return; }
    dymekMapy.hidden = true;
    dymekPrzypiety = false;
  }

  function ksztaltZdarzenia(zdarzenie) {
    var cel = zdarzenie.target;
    return (cel && cel.classList && cel.classList.contains('voivodeship')) ? cel : null;
  }

  // Dymek WYLACZNIE na :hover wyklucza klawiature i tablet, wiec podpinamy
  // trzy drogi naraz: mysz, fokus i dotkniecie. Dotkniecie PRZYPINA dymek
  // (na tablecie nie ma „zjechania kursorem"), a odpina go ponowne
  // dotkniecie, Escape albo klikniecie gdziekolwiek poza mapa.
  //
  // Sluchacze siedza na KORZENIU strony (delegacja), nie na bloku mapy:
  // kafelek wojewodztw bywa wymieniany w miejscu (podglad wymiaru), a sluchacz
  // przypiety do starego bloku znikalby razem z nim. `mouseleave` nie babelkuje,
  // wiec jego odpowiednikiem jest `mouseout`, ktorego cel lezy POZA blokiem.
  function podepnijMape() {
    dymekMapy = document.getElementById('an-mapa-dymek');
    if (!dymekMapy) { return; }

    korzen.addEventListener('mousemove', function (zdarzenie) {
      var ksztalt = ksztaltZdarzenia(zdarzenie);
      if (!ksztalt || dymekPrzypiety) { return; }
      pokazDymek(ksztalt, zdarzenie.clientX, zdarzenie.clientY);
    });
    korzen.addEventListener('mouseout', function (zdarzenie) {
      var blok = blokMapy(zdarzenie.target);
      if (!blok || dymekPrzypiety) { return; }
      if (zdarzenie.relatedTarget && blok.contains(zdarzenie.relatedTarget)) { return; }
      schowajDymek();
    });
    korzen.addEventListener('click', function (zdarzenie) {
      var ksztalt = ksztaltZdarzenia(zdarzenie);
      if (!ksztalt) { return; }
      dymekPrzypiety = !dymekPrzypiety;
      if (dymekPrzypiety) {
        pokazDymek(ksztalt, zdarzenie.clientX, zdarzenie.clientY);
      } else {
        schowajDymek();
      }
    });
    korzen.addEventListener('focusin', function (zdarzenie) {
      var ksztalt = ksztaltZdarzenia(zdarzenie);
      if (!ksztalt) { return; }
      // Z klawiatury nie ma kursora — dymek staje przy samym ksztalcie.
      var ramka = ksztalt.getBoundingClientRect();
      pokazDymek(ksztalt, ramka.left + ramka.width / 2, ramka.bottom);
    });
    korzen.addEventListener('focusout', function (zdarzenie) {
      if (!blokMapy(zdarzenie.target)) { return; }
      if (!dymekPrzypiety) { schowajDymek(); }
    });
    document.addEventListener('keydown', function (zdarzenie) {
      if (zdarzenie.key === 'Escape') { schowajDymek(); }
    });
    document.addEventListener('click', function (zdarzenie) {
      if (dymekPrzypiety && !blokMapy(zdarzenie.target)) { schowajDymek(); }
    });
  }

  // Zwraca true, gdy kafelek wojewodztw pokazuje mape. Klucz `mapa` przychodzi
  // z serwera WYLACZNIE dla wymiaru opisujacego wojewodztwa — po przelaczeniu
  // selektora karty na „Opiekun" mapa Polski opisywalaby handlowcow, wiec
  // karta wraca wtedy do slupkow.
  //
  // `miara` — miara, ktora maluje kartogram w biezacym trybie przelacznika
  // („zl" albo „szt."; mapa pokazuje jedna naraz). Stopien skali dla kazdej
  // miary liczy SERWER (`poziom`, `poziom_sztuk` — POLA_MIARY). W trybie
  // „szt." dymek dostaje na poczatku wiersz sztuk (`mapa.dymek_sztuk`, opis
  // z serwera), a reszta wierszy zostaje ta sama, co w trybie „zl".
  function rysujMapeWojewodztw(kafelek, karta, porownanie, opisSegmentu, miara) {
    var blok = kafelek.querySelector('[data-mapa]');
    if (!blok) { return false; }

    var mapa = karta ? karta.mapa : null;
    blok.hidden = !mapa;
    if (!mapa) { blok.obszaryMapy = {}; blok.miaryMapy = []; return false; }

    miara = miara || MIARY_DOMYSLNE[0];
    var mapaMiary = (mapa.dymek_sztuk && mapa.dymek_sztuk.nazwa === miara)
      ? [mapa.dymek_sztuk].concat(mapa.miary) : mapa.miary;
    blok.miaryMapy = mapaMiary;
    nazwaSegmentu = opisSegmentu || '';
    var obszary = {};

    obszaryWMierze(mapa.obszary, miara).forEach(function (obszar, i) {
      var drugi = (porownanie && porownanie.obszary) ? porownanie.obszary[i] : null;
      obszary[obszar.id] = { dane: obszar, porownanie: drugi };

      var ksztalt = blok.querySelector('[data-obszar="' + obszar.id + '"]');
      if (!ksztalt) { return; }
      // Stopien skali policzyl SERWER — tutaj tylko przepisujemy go na
      // atrybut, po ktorym CSS dobiera odcien. „brak" to osobny stan:
      // wojewodztwo bez ani jednego zamowienia ma wygladac inaczej niz
      // takie z zamowieniami na zero zlotych.
      ksztalt.setAttribute('data-poziom',
        obszar.ma_dane ? String(obszar.poziom) : 'brak');
      ksztalt.setAttribute('aria-label', opisObszaru(obszar, drugi, mapaMiary));
    });
    blok.obszaryMapy = obszary;

    rysujPozaMapa(kafelek, mapa, porownanie, miara);
    return true;
  }

  // Pierwsza kolumna liczb to miara, ktora maluje mapa; zamowienia obok
  // zostaja w kazdym trybie (naglowki wariantow wypisuje serwer).
  function rysujPozaMapa(kafelek, mapa, porownanie, miara) {
    var tabela = kafelek.querySelector('[data-poza-mapa]');
    var cialo = tabela ? tabela.querySelector('tbody') : null;
    if (!tabela || !cialo) { return; }
    czysc(cialo);
    tabela.hidden = !mapa.poza_mapa.length;

    mapa.poza_mapa.forEach(function (wiersz, i) {
      var drugi = (porownanie && porownanie.poza_mapa) ? porownanie.poza_mapa[i] : null;
      var tr = el('tr');
      var nazwa = el('td', '', wiersz.etykieta);
      nazwa.title = wiersz.etykieta;
      tr.appendChild(nazwa);
      [[miara || MIARY_DOMYSLNE[0], 0], ['zamowienia', 0]].forEach(function (para) {
        var komorka = el('td', 'an-mono', formatujMiare(wiersz[para[0]], para[1]));
        if (drugi) {
          komorka.appendChild(el('span', 'an-mono an-wartosc--porownanie',
            ' / ' + formatujMiare(drugi[para[0]], para[1])));
        }
        tr.appendChild(komorka);
      });
      cialo.appendChild(tr);
    });
  }

  function rysujWnioski(kafelek, lista) {
    var cialo = cialoKafelka(kafelek);
    if (!cialo) { return; }
    // Czyscimy WYLACZNIE wnioski (.an-wniosek). Kontener niesie tez adnotacje
    // "segment nie dotyczy tej karty" (.an-bez-segmentu) — szerokie czysc(cialo)
    // kasowalo ja bezpowrotnie juz przy pierwszym wypelnieniu, wiec karta
    // "Statystyki" nigdy jej nie pokazywala (znalezisko z przegladu Zadania 10).
    var dzieci = Array.prototype.slice.call(cialo.children);
    var przedAdnotacja = null;
    dzieci.forEach(function (dziecko) {
      if (dziecko.classList.contains('an-wniosek')) { cialo.removeChild(dziecko); }
      else if (!przedAdnotacja && dziecko.classList.contains('an-bez-segmentu')) {
        przedAdnotacja = dziecko;
      }
    });
    lista.forEach(function (w) {
      var blok = el('div', 'an-wniosek an-wniosek--' + w.akcent);
      blok.appendChild(el('p', '', w.tekst));
      blok.appendChild(el('small', 'an-mono', w.kontekst));
      if (przedAdnotacja) { cialo.insertBefore(blok, przedAdnotacja); }
      else { cialo.appendChild(blok); }
    });
  }

  function rysujOstrzezenieSalda(kafelek, naleznosci) {
    var gniazdo = poleW(kafelek, kafelek.getAttribute('data-klucz') + '.ostrzezenie');
    if (!gniazdo) { return; }
    czysc(gniazdo);
    var ile = naleznosci.ostrzezenie.zamowienia;
    if (!ile) { return; }
    // Czerwien WYLACZNIE tutaj i przy bledach — saldo w tej bazie jest
    // niewiarygodne i widget musi to powiedziec, a nie tylko pokazac sume.
    var blok = el('div', 'an-ostrzezenie');
    blok.appendChild(el('p', '', ile + ' zamówień starszych niż 90 dni wisi w statusie '
      + '„W produkcji". Saldo wymaga weryfikacji przed użyciem jako wskaźnik.'));
    gniazdo.appendChild(blok);
  }

  function rysujNadplaty(kafelek, naleznosci) {
    var gniazdo = poleW(kafelek, kafelek.getAttribute('data-klucz') + '.nadplaty');
    if (!gniazdo) { return; }
    czysc(gniazdo);
    var n = naleznosci.nadplaty || { zamowienia: 0, saldo: 0 };
    // Bursztyn, NIE czerwien — nadplata nie jest bledem (rezerwacja czerwieni
    // patrz rysujOstrzezenieSalda). Zdanie pierwsze jest ZAWSZE widoczne:
    // kubelki obok licza wylacznie salda dodatnie i karta ma to mowic wprost,
    // niezaleznie od tego, czy akurat sa jakies nadplaty do pokazania.
    var blok = el('div', 'an-info');
    var akapit = document.createElement('p');
    akapit.appendChild(document.createTextNode(
      'Kubełki obok liczą wyłącznie zamówienia z saldem dodatnim.'));
    if (n.zamowienia) {
      akapit.appendChild(document.createTextNode(' Osobno: '));
      akapit.appendChild(el('b', 'an-mono', fmt0.format(n.zamowienia)));
      akapit.appendChild(document.createTextNode(' zamówień ma nadpłatę na łączną kwotę '));
      akapit.appendChild(el('b', 'an-mono', fmt0.format(n.saldo)));
      akapit.appendChild(jednostkaSpan('netto'));
      // Przypis dawniej obiecywal kafelek KPI "Saldo" ("... dają saldo z KPI
      // powyzej") — takiego kafelka na dashboardzie NIE MA (petla kafelkow
      // w dashboard.html renderuje tylko netto/objetosc/zamowienia/
      // srednie_zamowienie/cena_za_m3; kpi.saldo, choc serwer je liczy,
      // nigdy nie trafia na ekran). Przypis ma mowic prawde o tym, co
      // widac — czyli powiedziec WPROST, ze to wyliczenie nie ma tu
      // osobnego miejsca na ekranie (znalezisko z przegladu, WAZNE 3).
      akapit.appendChild(document.createTextNode(
        ' — należności minus nadpłaty dają rzeczywiste saldo zamówień, '
        + 'którego dashboard nie pokazuje osobnym kafelkiem.'));
    }
    blok.appendChild(akapit);
    gniazdo.appendChild(blok);
  }

  /* ---------- wykresy (tylko dwa rodzaje) ---------- */

  // Kanwa wykresu nalezy do KAFELKA, nie do strony. Do 23.09.2026 miala stale
  // `id`, wiec dwa kafelki wykonczenia dalyby dwa elementy o tym samym `id`
  // i Chart.js rysowalby oba w pierwszym z nich.
  function kanwa(kafelek) {
    return kafelek ? kafelek.querySelector('canvas') : null;
  }

  // Wykres szukamy PO KANWIE (Chart.getChart), a nie w slowniku po kluczu
  // kafelka: podglad wymiaru potrafi chwilowo dac dwa kafelki o tym samym
  // kluczu, a wtedy rysowanie drugiego niszczyloby wykres pierwszego.
  function zniszczWykres(plotno) {
    if (!plotno || typeof Chart === 'undefined' || !Chart.getChart) { return; }
    var istniejacy = Chart.getChart(plotno);
    // Dymek tego wykresu nie moze zostac „wiszacy" po wymianie kafelka
    // (podglad, edycja, Anuluj) ani po jego usunieciu.
    if (istniejacy && istniejacy === wykresDymka) { schowajDymekWykresu(); }
    if (istniejacy) { istniejacy.destroy(); }
  }

  // Kafelek wyjmowany ze strony (podglad, anulowanie edycji) zabiera ze soba
  // kanwe, ale NIE wykres: Chart.js trzyma go w swoim rejestrze i dalej
  // obserwuje rozmiar. Bez zniszczenia kazda wymiana zostawialaby wyciek.
  function zniszczWykresyW(kafelek) {
    Array.prototype.forEach.call(kafelek.querySelectorAll('canvas'), zniszczWykres);
  }

  /* ---------- wspolny dymek wykresow (partia E, punkt E3) ---------- */

  // Dymek Chart.js rysuje sie NA KANWIE: ucina go jej krawedz, a tlo ma
  // polprzezroczyste. Kazdy wykres pulpitu wylacza go (`enabled: false`)
  // i oddaje tresc temu JEDNEMU elementowi HTML w <body> (dashboard.html),
  // ktory stoi w ukladzie okna i nie ucina sie na zadnej karcie.
  var dymekWykresu = null;
  var wykresDymka = null;

  function schowajDymekWykresu() {
    if (dymekWykresu) { dymekWykresu.hidden = true; }
    wykresDymka = null;
  }

  // Pozycja w ukladzie OKNA (position: fixed), docisnieta do jego krawedzi:
  // przy prawej krawedzi dymek przechodzi na lewa strone punktu, przy dolnej
  // — nad niego, a gdy i tak by wystawal, staje 8 px od krawedzi.
  function ustawPozycjeWOknie(element, x, y) {
    var odstep = 12;
    var margines = 8;
    element.style.left = '0px';
    element.style.top = '0px';
    var wymiar = element.getBoundingClientRect();
    var lewo = x + odstep;
    if (lewo + wymiar.width > window.innerWidth - margines) { lewo = x - odstep - wymiar.width; }
    if (lewo < margines) { lewo = margines; }
    if (lewo + wymiar.width > window.innerWidth - margines) {
      lewo = Math.max(margines, window.innerWidth - margines - wymiar.width);
    }
    var gora = y + odstep;
    if (gora + wymiar.height > window.innerHeight - margines) { gora = y - odstep - wymiar.height; }
    if (gora < margines) { gora = margines; }
    element.style.left = lewo + 'px';
    element.style.top = gora + 'px';
  }

  // Tresc: tytul (etykieta — RAZ) i lista par nazwa-wartosc. Wartosc to
  // gotowy napis liczby (Mono) plus jednostka z rejestru (Sans). Wylacznie
  // textContent i createElement.
  function wypelnijDymekWykresu(tresc) {
    var tytul = dymekWykresu.querySelector('[data-dymek-tytul]');
    var lista = dymekWykresu.querySelector('[data-dymek-lista]');
    tytul.textContent = tresc.tytul;
    czysc(lista);
    tresc.wiersze.forEach(function (wiersz) {
      lista.appendChild(el('dt', '', wiersz.etykieta));
      var wartosc = el('dd', '', wiersz.wartosc);
      wartosc.appendChild(jednostkaSpan(wiersz.miara));
      lista.appendChild(wartosc);
    });
  }

  // Opcje `plugins.tooltip` dla KAZDEGO wykresu pulpitu. `opisz` dostaje
  // punkty Chart.js i zwraca { tytul, wiersze } — liczby bierze z payloadu,
  // niczego nie liczac.
  function opcjeDymka(opisz) {
    return {
      enabled: false,
      external: function (kontekst) {
        var model = kontekst.tooltip;
        if (!dymekWykresu) { return; }
        if (!model || model.opacity === 0 || !model.dataPoints || !model.dataPoints.length) {
          if (wykresDymka === kontekst.chart) { schowajDymekWykresu(); }
          return;
        }
        wypelnijDymekWykresu(opisz(model.dataPoints));
        dymekWykresu.hidden = false;
        wykresDymka = kontekst.chart;
        var ramka = kontekst.chart.canvas.getBoundingClientRect();
        ustawPozycjeWOknie(dymekWykresu, ramka.left + model.caretX, ramka.top + model.caretY);
      }
    };
  }

  // Dymek znika po przewinieciu (strony albo ciala karty — faza
  // przechwytywania lapie przewijanie kazdego pudelka), po Escape i po
  // dotknieciu albo kliknieciu poza wykresem, ktoremu sluzy. Opuszczenie
  // wykresu mysza chowa go przez sam Chart.js (external z opacity 0).
  function podepnijDymekWykresu() {
    dymekWykresu = document.getElementById('an-dymek');
    if (!dymekWykresu) { return; }
    document.addEventListener('scroll', schowajDymekWykresu, true);
    window.addEventListener('resize', schowajDymekWykresu);
    document.addEventListener('keydown', function (zdarzenie) {
      if (zdarzenie.key === 'Escape') { schowajDymekWykresu(); }
    });
    document.addEventListener('pointerdown', function (zdarzenie) {
      if (wykresDymka && zdarzenie.target !== wykresDymka.canvas) { schowajDymekWykresu(); }
    }, true);
  }

  // Kolory wykresu trendu. Tryby jednej miary („zl", „szt.") — jak dotad
  // (makieta Main.dc.html): miesiace szare, biezacy w akcencie marki, rok
  // poprzedni jasnoszary.
  var KOLOR_SLUPKA = '#C9C2B7';
  var KOLOR_SLUPKA_BIEZACEGO = '#ED6B24';
  var KOLOR_ROKU_POPRZEDNIEGO = '#E3DDD4';
  // Tryb „zl + szt." (dwie osie). Podpis kazdej osi stoi w kolorze jej serii,
  // wiec oba kolory musza dac sie przeczytac jako tekst: slupki (pierwsza
  // miara, lewa os) w szarosci --muted (3,8:1 na bieli), krzywa (druga
  // miara, prawa os) w kolorze tekstu --ink. Walidator palety (skill dataviz,
  // scripts/validate_palette.js) dla zestawu z kolorem segmentu i akcentem
  // biezacego miesiaca: separacja CVD i normalna PASS (najgorsza para 17,2
  // wobec progu 15); „za malo nasycenia" szarosci i czerni jest zamierzone —
  // serie rozni tez znak (slupek / krzywa z punktami).
  var KOLOR_SLUPKOW_DWIE_OSIE = '#8A8278';
  // Podpis osi slupkow to TEKST 10 px — kolor slupkow (#8A8278) ma na bialej
  // karcie kontrast tylko 3,8:1. Ta sama barwa, ciemniejsza: 5,0:1 (WCAG AA 4,5:1).
  var KOLOR_PODPISU_SLUPKOW = '#766E64';
  var KOLOR_KRZYWEJ = '#1C1A17';

  // Napis podzialki osi dla miary: tysiace z „k" (zlotowki, jak dotad) albo
  // cala liczba (sztuki).
  function podzialkaOsi(miara) {
    return MIARY_W_TYSIACACH[miara]
      ? function (v) { return fmt0.format(v / 1000) + 'k'; }
      : function (v) { return fmt0.format(v); };
  }

  // Podpis osi z jednostka Z REJESTRU (payload.jednostki): „szt." albo
  // „tys. …" — os zlotowek ma podzialke w tysiacach.
  // Podzialki osi miary. Sztuki to liczby calkowite — bez `precision: 0`
  // Chart.js przy malych albo pustych danych dzieli os na ulamki i po
  // zaokragleniu w formacie wychodzi „0, 0, 0, 1, 1, 1".
  function podzialkiOsi(czcionka, miara) {
    var podzialki = { font: czcionka, color: '#9C948A', callback: podzialkaOsi(miara) };
    if (!MIARY_W_TYSIACACH[miara]) { podzialki.precision = 0; }
    return podzialki;
  }

  function podpisOsi(miara) {
    return (MIARY_W_TYSIACACH[miara] ? 'tys. ' : '') + (jednostki[miara] || '');
  }

  // WYKRES CZASOWY KAFELKA KPI. `miary` — miary biezacego trybu
  // przelacznika (miaryKafelka).
  //
  // Jedna miara („zl" albo „szt."): slupki miesiecy i nakladka roku
  // poprzedniego (albo segmentu porownawczego) w tej mierze — w trybie „zl"
  // dokladnie ten wykres, co przed przelacznikiem.
  //
  // Dwie miary („zl + szt."): typ MIESZANY — slupki pierwszej miary na LEWEJ
  // osi i krzywa drugiej na PRAWEJ (decyzja uzytkownika: dwie skale, „wykres
  // slupkowy + krzywa z kwotami nalozona na nie"). Wykres dwoch osi latwo
  // czyta sie jako korelacje, ktorej nie ma, wiec zabezpieczenia sa
  // obowiazkowe: obie osie od zera, kazda z podpisem jednostki w kolorze
  // swojej serii, siatka tylko od lewej, legenda nazywa obie serie, a wspolny
  // dymek pokazuje WSZYSTKIE serie miesiaca z prawdziwymi liczbami
  // i jednostkami. Nakladki roku poprzedniego w tym trybie nie ma — trzy
  // zestawy znakow w pudelku 152 px bylyby nieczytelne (ta sama zasada, co
  // przy segmencie); segment porownawczy dostaje waski slupek i przerywana
  // krzywa w swoim kolorze.
  function rysujTrend(kafelek, dane, miary) {
    var plotno = kanwa(kafelek);
    if (!plotno || typeof Chart === 'undefined') { return; }
    zniszczWykres(plotno);
    miary = miary || MIARY_DOMYSLNE;
    var miara = miary[0];
    var drugaMiara = miary[1] || null;
    var trend = dane.trend;
    var segment = dane.porownanie || null;

    function seria(punkty, m) {
      return (punkty || []).map(function (p) { return p[m]; });
    }
    var ostatni = trend.biezacy.length - 1;
    function koloryMiesiecy(kolor) {
      return trend.biezacy.map(function (_, i) {
        return i === ostatni ? KOLOR_SLUPKA_BIEZACEGO : kolor;
      });
    }
    function nazwaMiary(m) { return etykietyMiar[m] || m; }

    // Nazwa dostepna kanwy mowi, co na niej jest — w trybie domyslnym ta,
    // ktora wypisal serwer.
    if (plotno.etykietaDomyslna === undefined) {
      plotno.etykietaDomyslna = plotno.getAttribute('aria-label') || '';
    }
    plotno.setAttribute('aria-label', drugaMiara
      ? 'Sprzedaż miesięcznie: ' + nazwaMiary(miara).toLowerCase() + ' (słupki, lewa oś) i '
        + nazwaMiary(drugaMiara).toLowerCase() + ' (krzywa, prawa oś)'
      : (miara === MIARY_DOMYSLNE[0] ? plotno.etykietaDomyslna
        : 'Sprzedaż miesięcznie: ' + nazwaMiary(miara).toLowerCase()));

    var czcionkaOsi = { family: 'IBM Plex Mono', size: 9 };
    // Kazda seria niesie swoja MIARE (`miara`, wlasciwosc spoza Chart.js,
    // ktora ten ignoruje) — wspolny dymek bierze z niej nazwe i jednostke,
    // wiec sztuki i zlotowki nigdy nie dostana cudzej.
    var zestawy;
    var skale = {
      x: { grid: { display: false }, ticks: { font: czcionkaOsi, color: '#9C948A' } }
    };

    if (!drugaMiara) {
      var bazowa = {
        label: String(trend.biezacy_rok), miara: miara, data: seria(trend.biezacy, miara),
        backgroundColor: koloryMiesiecy(KOLOR_SLUPKA), borderWidth: 0, order: 2
      };
      var nakladkaRokuPoprzedniego = {
        label: String(trend.poprzedni_rok), miara: miara, data: seria(trend.poprzedni, miara),
        backgroundColor: KOLOR_ROKU_POPRZEDNIEGO, borderWidth: 0, barPercentage: 0.28, order: 1
      };
      // Trzy zestawy slupkow w pudelku 152 px sa nieczytelne — przy wlaczonym
      // segmencie nakladka roku poprzedniego USTEPUJE serii porownawczej,
      // nie dokladamy sie do niej (Zadanie 10).
      zestawy = segment
        ? [bazowa, { label: segment.nazwa, miara: miara, data: seria(segment.trend, miara),
                     backgroundColor: segment.kolor, borderWidth: 0,
                     barPercentage: 0.28, order: 1 }]
        : [bazowa, nakladkaRokuPoprzedniego];
      skale.y = { border: { display: false }, grid: { color: '#EDE9E3' },
                  ticks: podzialkiOsi(czcionkaOsi, miara) };
    } else {
      var rok = String(trend.biezacy_rok);
      zestawy = [{
        type: 'bar', label: nazwaMiary(miara) + ' ' + rok, miara: miara, yAxisID: 'y',
        data: seria(trend.biezacy, miara), backgroundColor: koloryMiesiecy(KOLOR_SLUPKOW_DWIE_OSIE),
        borderWidth: 0, order: 2
      }];
      if (segment) {
        zestawy.push({
          type: 'bar', label: nazwaMiary(miara) + ' · ' + segment.nazwa, miara: miara,
          yAxisID: 'y', data: seria(segment.trend, miara), backgroundColor: segment.kolor,
          borderWidth: 0, barPercentage: 0.28, order: 1
        });
      }
      // Krzywa rysuje sie NAD slupkami (mniejszy `order` = pozniej).
      zestawy.push({
        type: 'line', label: nazwaMiary(drugaMiara) + ' ' + rok, miara: drugaMiara,
        yAxisID: 'y1', data: seria(trend.biezacy, drugaMiara),
        borderColor: KOLOR_KRZYWEJ, backgroundColor: KOLOR_KRZYWEJ, borderWidth: 2,
        pointRadius: 3, pointHoverRadius: 4, pointBackgroundColor: '#FFFFFF',
        pointBorderWidth: 1.5, tension: 0, order: 0
      });
      if (segment) {
        zestawy.push({
          type: 'line', label: nazwaMiary(drugaMiara) + ' · ' + segment.nazwa,
          miara: drugaMiara, yAxisID: 'y1', data: seria(segment.trend, drugaMiara),
          borderColor: segment.kolor, backgroundColor: segment.kolor, borderWidth: 2,
          borderDash: [4, 3], pointRadius: 2.5, pointHoverRadius: 4,
          pointBackgroundColor: '#FFFFFF', pointBorderWidth: 1.5, tension: 0, order: 0
        });
      }
      var czcionkaPodpisu = { family: 'IBM Plex Sans', size: 10, weight: '600' };
      skale.y = { position: 'left', beginAtZero: true, border: { display: false },
                  grid: { color: '#EDE9E3' },
                  ticks: podzialkiOsi(czcionkaOsi, miara),
                  title: { display: true, text: podpisOsi(miara), color: KOLOR_PODPISU_SLUPKOW,
                           font: czcionkaPodpisu, padding: { top: 0, bottom: 2 } } };
      // Siatka TYLKO od lewej osi — dwie siatki o roznych podzialkach
      // udawalyby wspolna skale.
      skale.y1 = { type: 'linear', position: 'right', beginAtZero: true,
                   border: { display: false }, grid: { drawOnChartArea: false },
                   ticks: podzialkiOsi(czcionkaOsi, drugaMiara),
                   title: { display: true, text: podpisOsi(drugaMiara), color: KOLOR_KRZYWEJ,
                            font: czcionkaPodpisu, padding: { top: 0, bottom: 2 } } };
    }

    var opcje = {
      responsive: true, maintainAspectRatio: false, animation: false,
      plugins: { legend: { display: false },
        // Wspolny dymek HTML: tytul = miesiac (raz), pod nim serie z wartoscia
        // i jednostka SWOJEJ miary z rejestru. Kolejnosc serii jak w zestawie
        // (slupki przed krzywa, baza przed segmentem) — Chart.js podaje punkty
        // wedlug `order`, czyli krzywa, ktora rysuje sie na wierzchu, jako
        // pierwsza.
        tooltip: opcjeDymka(function (punkty) {
          return {
            tytul: punkty[0].label,
            wiersze: punkty.slice().sort(function (a, b) {
              return a.datasetIndex - b.datasetIndex;
            }).map(function (p) {
              return { etykieta: p.dataset.label, wartosc: fmt0.format(p.parsed.y),
                       miara: p.dataset.miara };
            })
          };
        }) },
      scales: skale
    };
    // Dwie miary: dymek dla CALEGO miesiaca, nie dla trafionego znaku —
    // wskaznik nie musi trafic w kreske krzywej, a dymek pokazuje obie
    // prawdziwe liczby naraz. W trybach jednej miary zostaje dotychczasowe
    // zachowanie (dymek trafionego slupka).
    if (drugaMiara) { opcje.interaction = { mode: 'index', intersect: false }; }

    new Chart(plotno.getContext('2d'), { type: 'bar', data: { labels: trend.etykiety, datasets: zestawy }, options: opcje });
  }

  // PIERSCIEN — JEDEN komponent dla karty wykonczen i dla kola klientow
  // (partia E, punkt E2). Te same kolory (KOLORY_PIERSCIENIA po indeksie
  // z serwera, za encja — patrz kolorKawalka), ta sama dziura,
  // wiersz „Pozostale (N)" jako JEDEN kawalek. Drugi komponent kola
  // znaczylby dwie konwencje w jednej aplikacji.
  //
  // Odstep 2 px miedzy kawalkami: kilka wartosci spoza czolowki stoi obok
  // siebie w tym samym neutralnym kolorze i bez odstepu zlalyby sie w jeden
  // kawalek. Robi go obrys 2 px w kolorze tla karty (`--surface`), wysrodkowany
  // na krawedzi, czyli po 1 px z kazdej strony granicy. NIE `spacing` z Chart.js:
  // tam przerwa rosnie z katem kawalka, wiec miedzy dwoma malymi kawalkami
  // prawie znika. Kolo z jednym kawalkiem nie ma granic — obrys dalby mu tylko
  // szew na godzinie 12, wiec wtedy go nie ma.
  //
  // Malutki kawalek dostaje obrys 0 (kontrola kolor, 24.09.2026): kadr kola to
  // 104x104 px (--wys-pierscien) z cutout 62%, wiec promien wewnetrzny to
  // ok. 32 px. Dlugosc luku na tym promieniu to promien * kat w radianach —
  // przy udziale 1% luk ma juz tylko ok. 2 px, czyli dokladnie tyle, ile obrys
  // zabiera po 1 px z kazdej strony. Ponizej tego udzialu obrys zjada kawalek
  // czesciowo albo (ponizej ok. 0,6%, promien zewnetrzny ~51 px) w calosci —
  // legenda wtedy pokazuje kolor, ktorego na kole nie widac. Prog 1,5% daje
  // przy tym samym promieniu luk ok. 3 px, czyli zapas nad szerokoscia obrysu,
  // wiec kawalek zostaje widoczny. Udzial POCHODZI Z PAYLOADU (w.udzial,
  // liczony na serwerze) — tu tylko porownanie z progiem, zero liczb
  // biznesowych w JS.
  var PROG_WIDOCZNOSCI_OBRYSU = 1.5; // % udzialu kawalka
  //
  // Kawalki to `wiersze` karty — dokladnie to, co widac w legendzie, bez
  // rozpisanego ogona. Liczby przychodza gotowe z serwera; tu tylko rysujemy.
  //
  // PRZELACZNIK (kolo: „zl" albo „szt.", nie pokaze dwoch miar naraz):
  // wiersze przychodza W MIERZE TRYBU (kartaWMierze), wiec wielkosc kawalka
  // i jego udzial % to pola TEJ miary, policzone na serwerze. KOLOR idzie za
  // encja (`indeks_koloru`, jeden na wiersz, niezalezny od miary) —
  // przelaczenie „zl" <-> „szt." zmienia wielkosci kawalkow, nigdy ich barwy.
  // `miara` sluzy wylacznie podpisowi i jednostce w dymku.
  function rysujPierscien(kafelek, wiersze, miara) {
    var plotno = kanwa(kafelek);
    if (!plotno || typeof Chart === 'undefined') { return; }
    zniszczWykres(plotno);
    miara = miara || MIARY_DOMYSLNE[0];
    var tloKarty = getComputedStyle(kafelek).getPropertyValue('--surface').trim() || '#FFFFFF';
    var kawalkow = wiersze.filter(function (w) { return w.netto !== 0; }).length;
    new Chart(plotno.getContext('2d'), {
      type: 'doughnut',
      data: {
        labels: wiersze.map(function (w) { return w.etykieta; }),
        datasets: [{
          data: wiersze.map(function (w) { return w.netto; }),
          backgroundColor: wiersze.map(function (w) { return kolorKawalka(w.indeks_koloru); }),
          borderWidth: wiersze.map(function (w) {
            return kawalkow > 1 && w.udzial >= PROG_WIDOCZNOSCI_OBRYSU ? 2 : 0;
          }),
          borderColor: tloKarty,
          // Bez tego Chart.js przy najezdzie sam szarzy obrys (domyslne
          // getHoverColor(borderColor) z bieli robi #E6E6E6) i szew miedzy
          // dwoma kawalkami przestaje miec kolor tla karty.
          hoverBorderColor: tloKarty
        }]
      },
      options: {
        responsive: true, maintainAspectRatio: false, animation: false, cutout: '62%',
        plugins: { legend: { display: false },
          // Wspolny dymek HTML: tytul = etykieta kawalka (raz), pod nia miara
          // kawalka (nazwa i jednostka miary trybu) i udzial % — oba Z PAYLOADU
          // (w.netto, w.udzial).
          tooltip: opcjeDymka(function (punkty) {
            var w = wiersze[punkty[0].dataIndex];
            return {
              tytul: w.etykieta,
              wiersze: [
                { etykieta: etykietyMiar[miara] || '', wartosc: fmt0.format(w.netto), miara: miara },
                { etykieta: etykietyMiar.udzial || '', wartosc: fmt1.format(w.udzial), miara: 'udzial' }
              ]
            };
          }) }
      }
    });
  }

  function rysujWykonczenie(kafelek, karta, miara) {
    rysujPierscien(kafelek, karta.wiersze, miara);
  }

  // Srodek pierscienia: dominujaca wartosc karty. Chart.js zostawia tam
  // dziure (cutout 62%) i sam niczego nie napisze. KTORY kawalek staje
  // w srodku, rozstrzyga SERWER jedna regula dla obu kol
  // (analiza_service._srodek_kola: najwiekszy nazwany kawalek, nigdy
  // „Pozostale (N)") — ten plik go nie wybiera, tylko wypisuje.
  function rysujSrodekPierscienia(kafelek, najwiekszy) {
    var klucz = kafelek.getAttribute('data-klucz');
    ustawW(kafelek, klucz + '.udzial', najwiekszy ? fmt1.format(najwiekszy.udzial) + '%' : '—');
    ustawW(kafelek, klucz + '.nazwa', najwiekszy ? najwiekszy.etykieta : '—');
  }

  // Kolo karty „Klienci wedlug" — ten sam pierscien i ten sam srodek, co
  // na karcie wykonczen. Karta W MIERZE TRYBU: srodek dla tej miary wskazal
  // serwer (`najwiekszy` albo `najwiekszy_sztuk`, kartaWMierze).
  function rysujKoloKlientow(kafelek, karta, miara) {
    rysujSrodekPierscienia(kafelek, karta.najwiekszy);
    rysujPierscien(kafelek, karta.wiersze, miara);
    // Nazwa dostepna kola idzie za miara trybu: wariant dla miary innej niz
    // domyslna wypisal serwer w atrybucie kanwy (`data-etykieta-sztuki`),
    // domyslna jest ta, ktora stala w aria-label od poczatku — jak w rysujTrend.
    var plotno = kanwa(kafelek);
    if (!plotno) { return; }
    if (plotno.etykietaDomyslna === undefined) {
      plotno.etykietaDomyslna = plotno.getAttribute('aria-label') || '';
    }
    plotno.setAttribute('aria-label',
      plotno.getAttribute('data-etykieta-' + miara) || plotno.etykietaDomyslna);
  }

  // LEGENDA-TABELA POD KOLEM KLIENTOW: probka koloru, etykieta, udzial %
  // i kwota — obie liczby z payloadu. Wiersz „Pozostale (N)" rozwija sie
  // tak samo jak w tabeli miksu: wiersze ogona <tr> chowane pojedynczo,
  // przewija sie kadr. Probki ogona maja kolor kawalka „Pozostale", jak
  // w legendzie wykonczen — ta sama konwencja rozwijania w obu kolach.
  // Karta W MIERZE TRYBU (kartaWMierze): udzial i kwota wiersza to pola
  // miary, ktora pokazuje kolo obok.
  function rysujLegendeKola(kafelek, karta) {
    var cialo = kafelek.querySelector('[data-lista="' + kafelek.getAttribute('data-klucz') + '"]');
    if (!cialo) { return; }
    czysc(cialo);
    var kadr = kafelek.querySelector('[data-kadr]');
    if (kadr) { kadr.classList.remove('an-kadr-listy--rozwiniety'); }
    var ogon = karta.ogon || [];

    function zbudujWiersz(w, rozwijalny) {
      var tr = el('tr');
      var nazwa = el('td', 'an-legenda-kola__nazwa');
      var probka = el('span', 'an-probka');
      probka.style.background = kolorKawalka(w.indeks_koloru);
      nazwa.appendChild(probka);
      if (rozwijalny) {
        tr.przycisk = etykietaRozwijana(w.etykieta);
        nazwa.appendChild(tr.przycisk);
      } else {
        nazwa.appendChild(el('span', '', w.etykieta));
      }
      // Pelna nazwa w podpowiedzi: kolumna jest waska i tnie ja wielokropkiem.
      nazwa.title = w.etykieta;
      tr.appendChild(nazwa);
      tr.appendChild(el('td', 'an-mono', fmt1.format(w.udzial)));
      tr.appendChild(el('td', 'an-mono', fmt0.format(w.netto)));
      return tr;
    }

    karta.wiersze.forEach(function (w, i) {
      var rozwijalny = !!(w.zbiorczy && ogon.length);
      var tr = zbudujWiersz(w, rozwijalny);
      cialo.appendChild(tr);
      if (!rozwijalny) { return; }
      // Wiersze ogona to czesci kawalka „Pozostale" — serwer daje im jego
      // indeks koloru.
      var ukryte = ogon.map(function (o) {
        var wiersz = zbudujWiersz(o, false);
        wiersz.hidden = true;
        // Klasa dla trybu pomiaru ciala zwinietego (analiza.css).
        wiersz.classList.add('an-ogon-wiersz');
        cialo.appendChild(wiersz);
        return wiersz;
      });
      podepnijRozwijanie(tr, tr.przycisk, ukryte, kadr);
    });
  }

  /* ---------- uklad kafelkow ---------- */

  // DOM JEST ZRODLEM PRAWDY O UKLADZIE. Nie trzymamy drugiej kopii w zmiennej:
  // przy przenoszeniu i usuwaniu (tryb edycji) dwie kopie rozjechalyby sie przy
  // pierwszym bledzie, a to DOM widzi uzytkownik.
  function kafelki() {
    return Array.prototype.slice.call(korzen.querySelectorAll('[data-kafelek]'));
  }

  function opisKafelka(wezel) {
    return {
      wezel: wezel,
      klucz: wezel.getAttribute('data-klucz'),
      typ: wezel.getAttribute('data-typ'),
      wymiar: wezel.getAttribute('data-wymiar') || null
    };
  }

  // Wymiar, w ktorym kafelek SKONCZY: w trakcie pobierania — ten, o ktory
  // wlasnie poprosilismy, poza tym — ten, ktory pokazuje. Bez tego zmiana
  // wymiaru w locie bylaby niewidoczna dla licznika zmian i dla blokady
  // zajetych wymiarow: drugi kafelek tego typu moglby w tym samym ulamku
  // sekundy wybrac ten sam wymiar.
  function wymiarKafelka(wezel) {
    if (wezel.getAttribute('aria-busy') === 'true' && wezel.wymiarWLocie) {
      return wezel.wymiarWLocie;
    }
    return wezel.getAttribute('data-wymiar') || null;
  }

  function ukladZeStrony() {
    return kafelki().map(function (wezel) {
      return { typ: wezel.getAttribute('data-typ'), wymiar: wymiarKafelka(wezel) };
    });
  }

  // UKLAD ZAPISANY = ostatni uklad POTWIERDZONY PRZEZ SERWER: z renderu strony
  // (`data-uklad-zapisany`), a potem wylacznie z odpowiedzi udanego zapisu
  // (POST /api/uklad) albo wymiany siatki (/api/siatka po „Odrzuc"
  // i „Przywroc domyslny"). NIGDY z ekranu. Do przegladu galezi (W1) punkt
  // odniesienia licznika zmian byl czytany z DOM-u przy wejsciu w tryb
  // edycji — kafelek dodany z pustego pulpitu poza trybem edycji liczyl sie
  // wtedy jako „zapisany", „Zapisz uklad" nic nie wysylal, a po F5 kafelka
  // nie bylo.
  var ukladZapisany = czytajJson('data-uklad-zapisany', []);

  // Czytelny opis kodu odpowiedzi — po polsku, bo trafia wprost na pasek.
  // Mowi tylko, CO sie stalo, BEZ rady: rade dokłada zdanie paska
  // (`zdanieBledu`), raz. Opis z wlasna rada dawal przy 502 dwie
  // („…spróbuj ponownie za chwilę. Zmiany zostały na ekranie — spróbuj
  // zapisać ponownie.", weryfikacja partii E, D6). Wyjatek to 401: tam opis
  // jest sam rada i `zdanieBledu` niczego juz nie dokłada.
  function opisStatusu(odp) {
    if (odp.status === 401) { return 'sesja wygasła, zaloguj się ponownie'; }
    if (odp.ok) { return 'serwer oddał odpowiedź w nieoczekiwanym formacie'; }
    return 'serwer odpowiedział błędem ' + odp.status;
  }

  // Odpowiedz serwera jako JSON — ALBO blad po polsku. Samo `odp.json()` na
  // stronie bledu z nginx (502 w trakcie restartu po deployu, 504 przy
  // zawieszonym workerze) rzuca ANGIELSKIM komunikatem parsera („Unexpected
  // token <"), ktory ladowal wprost na czerwonym pasku. Dlatego najpierw typ
  // odpowiedzi, potem parsowanie: 400 z tego modulu to JSON z polem
  // `komunikat` po polsku i ten komunikat ma dojsc do uzytkownika.
  function odpowiedzJson(odp) {
    var typ = (odp.headers && odp.headers.get('content-type')) || '';
    if (typ.indexOf('application/json') === -1) {
      throw bladOdpowiedzi(odp, opisStatusu(odp));
    }
    return odp.json().then(function (tresc) {
      if (!odp.ok) { throw bladOdpowiedzi(odp, (tresc && tresc.komunikat) || opisStatusu(odp)); }
      return tresc;
    }, function () {
      throw bladOdpowiedzi(odp, opisStatusu(odp));
    });
  }

  // Blad z kodem odpowiedzi — komunikaty paska rozrozniaja 401 (wygasla
  // sesja: rada „sprobuj ponownie" jest wtedy myląca, trzeba sie zalogowac).
  function bladOdpowiedzi(odp, komunikat) {
    var blad = new Error(komunikat);
    blad.status = odp.status;
    return blad;
  }

  // Komunikat serwera zwykle konczy sie kropka („Sesja wygasla — zaloguj sie
  // ponownie, zeby zmienic uklad pulpitu."), a zdania paska dokladaja po nim
  // wlasna kropke i rade — wychodzilo „..". Kropke konczaca zdejmujemy tutaj.
  function bezKropki(tekst) {
    return String(tekst || '').replace(/[\s.]+$/, '');
  }

  // Zdanie bledu na pasek: poczatek, opis bledu i JEDNA rada. Przy 401 rady
  // nie ma — opis („zaloguj się ponownie") albo komunikat serwera jest nia sam.
  function zdanieBledu(poczatek, blad, rada) {
    var zdanie = poczatek + bezKropki(blad.message) + '.';
    return (blad.status === 401 || !rada) ? zdanie : zdanie + ' ' + rada;
  }

  // Zapis ukladu. Jedyne miejsce, ktore wola POST /reports/api/uklad — woła
  // je WYLACZNIE paczka trybu edycji; selektor „wedlug" poza trybem edycji
  // niczego nie zapisuje (patrz podepnijSelektory). Adres bierzemy
  // z atrybutu wypisanego przez url_for, zeby zmiana prefiksu blueprintu nie
  // zepsula zapisu po cichu.
  //
  // Obietnica konczy sie ZAWSZE (nigdy nie odrzuca): true po udanym zapisie,
  // false po bledzie — komunikat stoi wtedy w pasku edycji, a paczka zmian
  // zostaje na ekranie do ponowienia.
  function zapiszUklad(uklad, poZapisie) {
    return fetch(korzen.getAttribute('data-url-uklad'), {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({ uklad: uklad })
    }).then(odpowiedzJson).then(function (tresc) {
      if (poZapisie) { poZapisie(tresc); }
      return true;
    }).catch(function (blad) {
      if (blad.status === 401) {
        pokazBladPaska('Nie udało się zapisać układu: sesja wygasła. Zaloguj się ponownie '
          + 'w innej karcie przeglądarki i kliknij „Zapisz układ" — zmiany zostały na ekranie.');
      } else {
        pokazBladPaska(zdanieBledu('Nie udało się zapisać układu: ', blad,
          'Zmiany zostały na ekranie — spróbuj zapisać ponownie za chwilę.'));
      }
      return false;
    });
  }

  /* ---------- blad akcji w pasku edycji ---------- */

  // Blad zapisu, odrzucenia zmian, przywrocenia i dodania kafelka stoi
  // W PASKU EDYCJI: pasek jest przyklejony do dolu okna i tam patrzy
  // uzytkownik. Do przegladu galezi (W3) szedl do #an-blad pod tytulem
  // strony, poltora tysiaca pikseli nad oknem — nie bylo go widac wcale.
  // Poza trybem edycji paska nie ma na ekranie, wiec blad idzie tam, gdzie
  // dotad (#an-blad): przywrocenie ze stanu pustego stoi tuz pod nim.
  function pokazBladPaska(komunikat) {
    var blad = document.getElementById('an-edycja-blad');
    if (!blad || !trybEdycji()) { pokazBlad(komunikat); return; }
    tekstZCyframi(blad, komunikat);
    blad.hidden = false;
  }

  function schowajBladPaska() {
    var blad = document.getElementById('an-edycja-blad');
    if (blad) { blad.hidden = true; czysc(blad); }
  }

  // AKCJA PASKA W TOKU: zapis, odrzucenie zmian, przywrocenie domyslnego.
  // Na ten czas siatka jest `inert` (narzedzia kafelkow, selektory, „+"
  // i przeciaganie nie reaguja), przyciski paska sa wylaczone, a Escape
  // i „+" nic nie robia. Bez tego (przeglad galezi, drobne 1) mozna bylo
  // usunac kafelek w trakcie POST-u: ekran pokazywal jedno, baza miala
  // drugie, a tryb edycji sie zamykal.
  var akcjaWToku = false;

  function ustawAkcjeWToku(tak) {
    akcjaWToku = tak;
    var siatka = document.getElementById('an-siatka');
    if (siatka) { siatka.inert = tak; }
    przyciskiPaska(!tak);
  }

  // `dzialanie` zwraca obietnice, ktora konczy sie true (udalo sie) albo
  // false (blad juz pokazany w pasku). Po bledzie fokus trafia na przycisk,
  // ktorym da sie ponowic — wylaczony na czas akcji przycisk zgubil go na
  // <body> (przeglad galezi, W5).
  function akcjaPaska(dzialanie, idPrzyciskuPrzyBledzie) {
    if (akcjaWToku) { return Promise.resolve(null); }
    schowajBladPaska();
    ustawAkcjeWToku(true);
    return dzialanie().then(function (udana) {
      ustawAkcjeWToku(false);
      if (udana === false && trybEdycji()) {
        var przycisk = document.getElementById(idPrzyciskuPrzyBledzie);
        if (przycisk) { przycisk.focus({ preventScroll: true }); }
      }
      return udana;
    }, function (blad) {
      ustawAkcjeWToku(false);
      throw blad;
    });
  }

  /* ---------- tryb edycji ukladu ---------- */

  // Migawka ukladu ZAPISANEGO, zrobiona przy wejsciu w tryb edycji. Sluzy
  // wylacznie do rozpoznania, czy sa niezapisane zmiany — licznik operacji
  // klamalby: przeniesienie w lewo i z powrotem to zero zmian, nie dwie.
  // Stanu siatki z niej NIE odtwarzamy: „Anuluj" bierze zapisana siatke
  // z serwera (/api/siatka), bo znaczniki kafelkow generuje Jinja.
  var migawka = null;

  function trybEdycji() {
    return korzen.classList.contains('analiza--edycja');
  }

  function odciskUkladu(uklad) {
    // Nieznany punkt odniesienia (serwer nie oddal ukladu) ma odcisk, ktory
    // nie pasuje do ZADNEGO ekranu: '#' nie wystepuje w nazwach typow ani
    // wymiarow. Licznik mowi wtedy „Niezapisane zmiany", a „Zapisz uklad"
    // wysyla to, co widac, zamiast udawac, ze nie ma czego zapisac.
    if (!Array.isArray(uklad)) { return '#nieznany'; }
    return uklad.map(function (i) { return i.typ + ':' + (i.wymiar || ''); }).join('|');
  }

  // Nowy punkt odniesienia licznika zmian — WYLACZNIE z odpowiedzi serwera
  // (patrz deklaracja `ukladZapisany`). W trakcie edycji licznik liczy sie od
  // niego od nowa, bo zmienil sie stan zapisany, a ekran jeszcze nie.
  //
  // `bezOdswiezenia`: punkt odniesienia zmienia sie, ale pasek jeszcze nie —
  // przy udanym „Przywroc domyslny" siatka zaraz sie wymieni i tryb edycji
  // zamknie, a przeliczony w tej chwili licznik mignalby bursztynem
  // „Niezapisane zmiany" (partia E, punkt E7). Wolajacy przelicza pasek sam,
  // gdy siatka NIE przyjdzie.
  function ustawUkladZapisany(uklad, bezOdswiezenia) {
    ukladZapisany = Array.isArray(uklad) ? uklad : null;
    if (trybEdycji()) {
      migawka = odciskUkladu(ukladZapisany);
      if (!bezOdswiezenia) { oznaczZmiane(); }
    }
  }

  function saZmiany() {
    return migawka !== null && odciskUkladu(ukladZeStrony()) !== migawka;
  }

  // Stan paska i wszystkiego, co zalezy od ukladu na ekranie. Wolane po
  // KAZDEJ zmianie w trybie edycji: przeniesieniu, usunieciu, dodaniu,
  // zmianie wymiaru (takze w chwili wyslania zadania, nie dopiero po
  // odpowiedzi).
  function oznaczZmiane() {
    if (!trybEdycji()) { return; }
    var pasek = document.getElementById('an-edycja-pasek');
    var licznik = document.getElementById('an-edycja-licznik');
    var zmiany = saZmiany();
    pasek.classList.toggle('an-edycja__pasek--zmiany', zmiany);
    licznik.textContent = zmiany ? 'Niezapisane zmiany w układzie' : 'Bez zmian';
    odswiezZajeteWymiary();
    odswiezGraniceRuchu();
  }

  // KOLIZJA KLUCZY W TRYBIE EDYCJI. Kafelek to para (typ, wymiar) i ta sama
  // para dwa razy to dwa kafelki z identycznymi liczbami — zapis takiego
  // ukladu serwer odrzuca („jest już na pulpicie"). Uzytkownik ma do tego
  // komunikatu NIE dojsc: w trybie edycji selektor „wedlug" wylacza wymiary,
  // ktore ma juz INNY kafelek tego samego typu, i mowi dlaczego. Poza trybem
  // edycji wszystkie opcje wracaja — tam selektor jest podgladem, a podglad
  // tego samego przekroju w dwoch miejscach niczego nie psuje.
  //
  // Etykiete opcji zapamietujemy na wezle przy pierwszym dotknieciu, zeby
  // dopisek dalo sie zdjac bez drugiej listy etykiet w tym pliku.
  function odswiezZajeteWymiary() {
    var edycja = trybEdycji();
    var wszystkie = kafelki();
    var klucze = wszystkie.map(function (w) {
      return w.getAttribute('data-typ') + ':' + (wymiarKafelka(w) || '');
    });
    wszystkie.forEach(function (wezel, i) {
      var wybor = wezel.querySelector('[data-selektor]');
      if (!wybor) { return; }
      var typ = wezel.getAttribute('data-typ');
      Array.prototype.forEach.call(wybor.options, function (opcja) {
        if (opcja.etykietaPierwotna === undefined) { opcja.etykietaPierwotna = opcja.textContent; }
        var klucz = typ + ':' + opcja.value;
        var cudzy = edycja && klucze.some(function (k, j) { return j !== i && k === klucz; });
        opcja.disabled = cudzy;
        opcja.textContent = cudzy
          ? opcja.etykietaPierwotna + ' — już na pulpicie' : opcja.etykietaPierwotna;
      });
    });
  }

  // Pierwszy kafelek nie ma dokad isc „wczesniej", ostatni — „pozniej".
  // aria-disabled, nie `disabled`: przycisk z `disabled` gubi fokus, a to
  // jest dokladnie ten przycisk, ktory naciska sie kilka razy pod rzad.
  function odswiezGraniceRuchu() {
    var wszystkie = kafelki();
    wszystkie.forEach(function (wezel, i) {
      var wczesniej = wezel.querySelector('[data-ruch="wczesniej"]');
      var pozniej = wezel.querySelector('[data-ruch="pozniej"]');
      if (wczesniej) { wczesniej.setAttribute('aria-disabled', String(i === 0)); }
      if (pozniej) { pozniej.setAttribute('aria-disabled', String(i === wszystkie.length - 1)); }
    });
  }

  // Stan trybu edycji NALEZY DO STRONY, nie do kafelka: kafelek przyniesiony
  // z serwera (podglad, dodanie) przychodzi zawsze w trybie spoczynku i musi
  // dostac narzedzia, jesli strona jest w trybie edycji.
  function ustawTrybKafelka(wezel, edycja) {
    var narzedzia = wezel.querySelector('.an-kafelek__narzedzia');
    if (narzedzia) { narzedzia.hidden = !edycja; }
    // Podpowiedz „Wymiar zapisze sie razem z ukladem" — bez niej ten sam
    // selektor znaczylby w dwoch trybach co innego, nie mowiac o tym.
    var podpowiedz = wezel.querySelector('[data-podpowiedz-edycji]');
    if (podpowiedz) { podpowiedz.hidden = !edycja; }
    if (edycja) {
      wezel.setAttribute('draggable', 'true');
      // Plakietka podgladu w trybie edycji klamalaby: tam wymiar sie ZAPISUJE.
      var plakietka = wezel.querySelector('[data-plakietka]');
      if (plakietka) { plakietka.hidden = true; }
    } else {
      wezel.removeAttribute('draggable');
    }
  }

  function wlaczEdycje() {
    if (trybEdycji()) { return; }
    // NAJPIERW podglady wracaja do wymiaru zapisanego. Tryb edycji zaczyna
    // sie od UKLADU ZAPISANEGO: gdyby kafelek wszedl w edycje w wymiarze
    // podgladanym, to, co widac, i to, co jest w bazie, byloby dwoma roznymi
    // punktami startu, a podgladany wymiar moglby juz nalezec do innego
    // kafelka tego typu (kolizja klucza przy zapisie).
    kafelki().forEach(function (wezel) {
      var zapisany = wezel.getAttribute('data-wymiar-zapisany');
      if (!zapisany || wymiarKafelka(wezel) === zapisany) { return; }
      ustawSelektor(wezel, zapisany);
      podgladWymiaru(wezel, zapisany);
    });
    // Przelacznik miary znika w trybie edycji (analiza.css), wiec kafelki
    // wracaja do trybu domyslnego — inaczej kafelek w „szt." nie mialby
    // widocznego powodu, dla ktorego pokazuje sztuki.
    przywrocTrybyDomyslne();
    // Punkt odniesienia licznika zmian: uklad potwierdzony przez serwer,
    // NIE to, co akurat widac (patrz deklaracja `ukladZapisany`).
    migawka = odciskUkladu(ukladZapisany);
    korzen.classList.add('analiza--edycja');
    document.getElementById('an-edycja').setAttribute('data-tryb', 'edycja');
    document.getElementById('an-edytuj').hidden = true;
    document.getElementById('an-edycja-pasek').hidden = false;
    schowajBladPaska();
    kafelki().forEach(function (wezel) { ustawTrybKafelka(wezel, true); });
    // Tu tez chowa sie „Przywroc domyslny" z bloku stanu pustego (W2).
    odswiezStanPusty();
    oznaczZmiane();
    // „Edytuj widok" wlasnie zniknal, wiec fokus nie moze na nim zostac —
    // przechodzi na „Anuluj", czyli na wyjscie z trybu w tym samym miejscu.
    document.getElementById('an-uklad-anuluj').focus({ preventScroll: true });
  }

  // Wyjscie z trybu edycji. Samo zdejmuje tryb — nie cofa zmian w siatce
  // (to robi „Anuluj" przez /api/siatka, a „Zapisz uklad" je utrwala).
  function wylaczEdycje() {
    // Czy fokus trzeba oddac — liczone PRZED jakakolwiek zmiana. Klikniety
    // przycisk paska bywa w tej chwili juz wylaczony (zapis w toku) albo
    // schowany (wiersz potwierdzenia) i przegladarka zdazyla przeniesc fokus
    // na <body>. Do przegladu galezi (W5) sprawdzalismy tylko „fokus w pasku",
    // wiec po „Zapisz", „Odrzuc" i „Przywroc" fokus zostawal na <body>.
    // Narzedzia kafelka za chwile znikna, wiec fokus na nich tez trzeba oddac.
    var aktywny = document.activeElement;
    // Kafelek „+" tez znika razem z trybem edycji — Escape z fokusem na nim
    // zostawial fokus na <body> (partia E, punkt E7).
    var oddajFokus = !aktywny || aktywny === document.body
      || document.getElementById('an-edycja').contains(aktywny)
      || !!(aktywny.closest && aktywny.closest('.an-kafelek__narzedzia'))
      || !!(aktywny.closest && aktywny.closest('#an-dodaj-kafelek'));
    korzen.classList.remove('analiza--edycja');
    document.getElementById('an-edycja').setAttribute('data-tryb', 'podglad');
    document.getElementById('an-edytuj').hidden = false;
    var pasek = document.getElementById('an-edycja-pasek');
    pasek.hidden = true;
    pasek.classList.remove('an-edycja__pasek--zmiany');
    schowajBladPaska();
    document.getElementById('an-edycja-potwierdzenie').hidden = true;
    kafelki().forEach(function (wezel) { ustawTrybKafelka(wezel, false); });
    odswiezZajeteWymiary();
    migawka = null;
    pokazKafelekDodawania(false);
    odswiezStanPusty();
    // preventScroll: poza trybem edycji pasek nie jest juz przyklejony do dolu
    // okna, tylko stoi na samym dole strony — zwykle focus() przewinalby tam
    // cala strone zaraz po zapisie albo anulowaniu.
    if (oddajFokus) { document.getElementById('an-edytuj').focus({ preventScroll: true }); }
  }

  // PRZENOSZENIE W DOMIE. DOM jest jedynym zrodlem prawdy o ukladzie —
  // druga kopia w zmiennej rozjechalaby sie przy pierwszym bledzie, a to DOM
  // widzi uzytkownik. Sasiad musi byc kafelkiem: na koncu siatki stoi
  // kafelek „+", ktorego nie przeskakujemy.
  function przeniesKafelek(wezel, kierunek) {
    var siatka = wezel.parentNode;
    if (kierunek === 'wczesniej') {
      var poprzedni = wezel.previousElementSibling;
      if (!poprzedni || !poprzedni.hasAttribute('data-kafelek')) { return false; }
      siatka.insertBefore(wezel, poprzedni);
    } else {
      var nastepny = wezel.nextElementSibling;
      if (!nastepny || !nastepny.hasAttribute('data-kafelek')) { return false; }
      siatka.insertBefore(nastepny, wezel);
    }
    // Dymek nie moze wisiec nad karta, ktora wlasnie przyjechala na miejsce
    // przeniesionej (weryfikacja partii E, D1): Chrome zeruje najechanie przy
    // przestawieniu wezla, Chart.js nie dostaje `mouseout` i sam go nie
    // schowa. Tak samo jak przy usunieciu kafelka — oba dymki.
    schowajDymekWykresu();
    schowajDymek();
    oznaczZmiane();
    return true;
  }

  function usunKafelek(wezel) {
    var nastepny = wezel.nextElementSibling;
    var poprzedni = wezel.previousElementSibling;
    // Zadanie w locie tego kafelka nie ma juz czego wymieniac.
    wezel.numerZadania = (wezel.numerZadania || 0) + 1;
    zniszczWykresyW(wezel);
    if (wezel.querySelector('[data-mapa]')) { schowajDymek(); }
    wezel.parentNode.removeChild(wezel);
    oznaczZmiane();
    odswiezStanPusty();
    // Fokus nie moze zostac na skasowanym wezle. Przechodzi na PIERWSZY
    // przycisk przenoszenia sasiada, a NIE na jego „Usun": do przegladu galezi
    // (W4) drugi Enter z rozpedu kasowal nastepny kafelek. Nazwa przycisku
    // mowi, ktorego kafelka dotyczy, wiec czytnik od razu podaje, gdzie
    // uzytkownik jest. Gdy sasiadow nie ma — kafelek „+".
    var sasiad = (nastepny && nastepny.hasAttribute('data-kafelek')) ? nastepny
      : ((poprzedni && poprzedni.hasAttribute('data-kafelek')) ? poprzedni : null);
    var cel = sasiad ? sasiad.querySelector('[data-ruch="wczesniej"]') : null;
    if (!cel) {
      var dodaj = document.getElementById('an-dodaj-kafelek');
      cel = (dodaj && !dodaj.hidden) ? dodaj : document.getElementById('an-uklad-zapisz');
    }
    cel.focus({ preventScroll: cel.id === 'an-uklad-zapisz' });
  }

  /* ---------- zapis ukladu, anulowanie, stan pusty ---------- */

  function odswiezStanPusty() {
    var pusty = document.getElementById('an-stan-pusty');
    var pustka = kafelki().length === 0;
    if (pusty) { pusty.hidden = !pustka; }
    // „Przywroc domyslny" z bloku stanu pustego dziala BEZ PYTANIA, wiec
    // w trybie edycji jest schowany: pusty pulpit w edycji to zwykle usuniete,
    // ale niezapisane kafelki, a przycisk skasowalby zapisany uklad bez
    // ostrzezenia (przeglad galezi, W2). Pasek edycji ma wlasny, z pytaniem.
    var przywroc = document.getElementById('an-stan-pusty-domyslny');
    if (przywroc) { przywroc.hidden = trybEdycji(); }
    // Zdanie nie moze obiecywac przycisku, ktorego nie widac — w trybie
    // edycji odsyla do „Przywroc domyslny" na pasku edycji (partia E, E7).
    var zdaniePodglad = document.querySelector('[data-stan-pusty-podglad]');
    var zdanieEdycja = document.querySelector('[data-stan-pusty-edycja]');
    if (zdaniePodglad) { zdaniePodglad.hidden = trybEdycji(); }
    if (zdanieEdycja) { zdanieEdycja.hidden = !trybEdycji(); }
    // Kafelek „+" jest widoczny tylko w trybie edycji — z jednym wyjatkiem:
    // przy pustym pulpicie widac go ZAWSZE, bo inaczej pusta strona nie
    // mialaby zadnego wyjscia poza przyciskiem na samym dole.
    pokazKafelekDodawania(trybEdycji() || pustka);
  }

  function schowajBlad() {
    var blok = document.getElementById('an-blad');
    if (blok) { blok.hidden = true; }
  }

  function pokazPominiete(ile) {
    var pasek = document.getElementById('an-pominiete');
    var liczba = document.getElementById('an-pominiete-liczba');
    if (liczba) { liczba.textContent = String(ile || 0); }
    if (pasek) { pasek.hidden = !ile; }
    korzen.setAttribute('data-pominietych', String(ile || 0));
  }

  // POTWIERDZENIE — WIERSZEM W PASKU, nie `window.confirm`: ta strona ma juz
  // popover filtra i dymek mapy, a trzeci rodzaj okna, narzucony przez
  // przegladarke, bylby obcy i nie da sie go ostylowac. Jeden wiersz sluzy
  // dwom pytaniom (porzucenie zmian, przywrocenie domyslnego), wiec pytanie,
  // etykieta przycisku i akcja przychodza z wywolania.
  var akcjaPotwierdzenia = null;
  var zrodloPotwierdzenia = null;

  function pokazPotwierdzenie(pytanie, etykieta, akcja) {
    akcjaPotwierdzenia = akcja;
    // Przycisk, ktory zadal pytanie — „Wroc" oddaje mu fokus.
    zrodloPotwierdzenia = document.activeElement;
    document.getElementById('an-edycja-pytanie').textContent = pytanie;
    document.getElementById('an-edycja-odrzuc').textContent = etykieta;
    document.getElementById('an-edycja-potwierdzenie').hidden = false;
    document.getElementById('an-edycja-pasek').hidden = true;
    // preventScroll przy KAZDYM fokusie w pasku: pasek jest przyklejony do
    // dolu okna, a zapas przewijania pod nim (scroll-padding-bottom w CSS)
    // kazalby przegladarce podjechac strona o ten zapas przy kazdym fokusie.
    document.getElementById('an-edycja-wroc').focus({ preventScroll: true });
  }

  function schowajPotwierdzenie() {
    akcjaPotwierdzenia = null;
    document.getElementById('an-edycja-potwierdzenie').hidden = true;
    document.getElementById('an-edycja-pasek').hidden = !trybEdycji();
  }

  function wrocZPotwierdzenia() {
    var zrodlo = zrodloPotwierdzenia;
    schowajPotwierdzenie();
    var widoczne = zrodlo && zrodlo.tagName === 'BUTTON' && zrodlo.getClientRects().length;
    (widoczne ? zrodlo : document.getElementById('an-uklad-anuluj')).focus({ preventScroll: true });
  }

  // Zadania kafelkow w locie. Zapis czeka, az wszystkie sie skoncza: kafelek
  // w trakcie zmiany wymiaru albo dodawania pokazuje jeszcze STARY stan,
  // a zapisany ma byc ten, ktory za chwile bedzie widac.
  var zadaniaWLocie = [];

  function sledzZadanie(obietnica) {
    zadaniaWLocie.push(obietnica);
    var usun = function () {
      var i = zadaniaWLocie.indexOf(obietnica);
      if (i !== -1) { zadaniaWLocie.splice(i, 1); }
    };
    obietnica.then(usun, usun);
    return obietnica;
  }

  function poWczytaniuKafelkow() {
    if (!zadaniaWLocie.length) { return Promise.resolve(); }
    return Promise.all(zadaniaWLocie.slice()).then(poWczytaniuKafelkow);
  }

  // Licznik nieudanych zadan kafelkow (dodanie, zmiana wymiaru). Zapis czeka
  // na kafelki w locie; jesli w tym czasie ktorys padl, ekran wrocil juz do
  // stanu, ktorego uzytkownik nie zamierzal zapisac (kafelka nie ma, wymiar
  // wrocil), a komunikat stoi w pasku. Wtedy zapis sie PRZERYWA — do
  // weryfikacji poprawek (znalezisko 5) szedl dalej, zamykal tryb edycji
  // i razem z nim kasowal komunikat: kafelek „migal i znikal" bez slowa.
  var bledyKafelkow = 0;

  // Straz przed duplikatem. Selektor i okno dodawania nie dopuszczaja dwoch
  // kafelkow o tej samej parze (typ, wymiar), wiec tu nie powinno sie nic
  // znalezc — ale zapis NIGDY nie wysyla duplikatu: serwer by go odrzucil,
  // a uzytkownik ma do tego komunikatu nie dojsc.
  function zdublowanyKlucz(uklad) {
    var widziane = {};
    for (var i = 0; i < uklad.length; i++) {
      var klucz = uklad[i].typ + ':' + (uklad[i].wymiar || '');
      if (widziane[klucz]) { return klucz; }
      widziane[klucz] = true;
    }
    return null;
  }

  function przyciskiPaska(wlaczone) {
    ['an-uklad-domyslny', 'an-uklad-anuluj', 'an-uklad-zapisz'].forEach(function (id) {
      document.getElementById(id).disabled = !wlaczone;
    });
  }

  // Przenosi ISTNIEJACE wezly strony (kafelek „+") do nowej siatki. Fragment
  // z /api/siatka ich nie niesie — jeden wezel „+" na stronie, zero
  // znacznikow budowanych w JavaScripcie, nigdy dwa.
  function przeniesDoSiatki(nowa, stara) {
    var plus = stara.querySelector('.an-kafelek--dodaj');
    if (plus) { nowa.appendChild(plus); }
  }

  // Podmienia CALY wezel siatki na przyniesiony z serwera. Stare kafelki
  // odchodza razem ze swoimi zadaniami w locie (licznik) i wykresami (rejestr
  // Chart.js), inaczej spozniona odpowiedz albo wykres zyly dalej w odpietym
  // DOM-ie.
  function podmienSiatke(html) {
    var stara = document.getElementById('an-siatka');
    var zrodlo = new DOMParser().parseFromString(html, 'text/html');
    var z = zrodlo.getElementById('an-siatka');
    if (!stara || !z) { throw new Error('serwer nie oddał siatki'); }
    var nowa = document.importNode(z, true);
    kafelki().forEach(function (wezel) {
      wezel.numerZadania = (wezel.numerZadania || 0) + 1;
      zniszczWykresyW(wezel);
    });
    schowajDymek();
    przeniesDoSiatki(nowa, stara);
    stara.parentNode.replaceChild(nowa, stara);
  }

  // KOTWICA PRZEWINIECIA. Po podmianie siatki przegladarka nie ma jak
  // utrzymac widoku sama (jej zakotwiczenie przewijania trzyma sie WEZLA,
  // a wezly sa nowe), wiec robimy to jawnie: pierwszy kafelek widoczny
  // w oknie ma po podmianie stac tam, gdzie stal — po kluczu instancji, bo
  // ten sam kafelek jest w nowej siatce innym wezlem.
  function kotwicaPrzewiniecia() {
    var gora = korzen.getBoundingClientRect().top;
    var widoczny = kafelki().filter(function (w) {
      return w.getBoundingClientRect().bottom > gora;
    })[0];
    return {
      przewiniecie: korzen.scrollTop,
      klucz: widoczny ? widoczny.getAttribute('data-klucz') : null,
      polozenie: widoczny ? widoczny.getBoundingClientRect().top : 0
    };
  }

  function przywrocKotwice(kotwica) {
    korzen.scrollTop = kotwica.przewiniecie;
    if (!kotwica.klucz) { return; }
    var ten = kafelki().filter(function (w) {
      return w.getAttribute('data-klucz') === kotwica.klucz;
    })[0];
    if (ten) { korzen.scrollTop += ten.getBoundingClientRect().top - kotwica.polozenie; }
  }

  // Wymienia CALA siatke na zapisana wersje z serwera i przerysowuje ja
  // danymi. Wolaja to „Odrzuc" (anulowanie zmian) i „Przywroc domyslny" — obie
  // musza wrocic do stanu ZAPISANEGO, a odtwarzanie go z kopii DOM-u byloby
  // trzecia sciezka budowania tego samego widoku (po stronie i po
  // `/api/kafelek`). Znaczniki rysuje Jinja, liczby liczy serwer.
  //
  // `prefiksBledu` i `rada`: poczatek komunikatu i jedyna rada, gdy siatka
  // nie przyjdzie. „Odrzuc" mowi o nieudanym wczytaniu; „Przywroc domyslny"
  // musi powiedziec, ze samo przywrocenie SIE UDALO (serwer juz skasowal
  // wiersz), tylko widoku nie ma — i ze wystarczy odswiezyc strone.
  function wymienSiatke(prefiksBledu, rada) {
    var adres = korzen.getAttribute('data-url-siatka') + '?' + parametryStanu().toString();
    return fetch(adres, {
      credentials: 'same-origin', headers: { 'Accept': 'application/json' }
    }).then(odpowiedzJson).then(function (tresc) {
      // BEZ SKOKU STRONY. Nowa siatka przychodzi jako szkielet bez danych —
      // przez ulamek sekundy jest duzo nizsza od starej, a przegladarka
      // przycina wtedy przewiniecie do nowej, krotszej strony i uzytkownik
      // laduje gdzie indziej. Trzymamy wiec dawna wysokosc siatki, dopoki
      // dane sie nie narysuja, i oddajemy przewiniecie.
      var kotwica = kotwicaPrzewiniecia();
      var wysokosc = document.getElementById('an-siatka').offsetHeight;
      podmienSiatke(tresc.html);
      var nowa = document.getElementById('an-siatka');
      nowa.style.minHeight = wysokosc + 'px';
      // Serwer oddaje razem z siatka uklad, z ktorego ja zlozyl — to jest od
      // teraz punkt odniesienia licznika zmian (patrz `ukladZapisany`).
      if (Array.isArray(tresc.uklad)) { ukladZapisany = tresc.uklad; }
      pokazPominiete(tresc.pominietych);
      if (trybEdycji()) { wylaczEdycje(); } else { odswiezStanPusty(); }
      schowajBlad();
      przywrocKotwice(kotwica);
      // Selektory i wykresy naleza do WYMIENIONYCH wezlow — zaladuj() pobiera
      // payload i rysuje je od nowa; sluchacze ida przez delegacje na
      // korzeniu, wiec nie wymagaja ponownego podpinania.
      return zaladuj().then(function () {
        nowa.style.minHeight = '';
        przywrocKotwice(kotwica);
        return true;
      });
    }).catch(function (blad) {
      pokazBladPaska(zdanieBledu(prefiksBledu || 'Nie udało się wczytać zapisanego układu: ',
        blad, rada || 'Spróbuj ponownie za chwilę.'));
      return false;
    });
  }

  // Puste ciało `{}` z naglowkiem JSON — serwer odrzuca przywrocenie, ktore
  // nie jest JSON-em (routers_analiza.api_uklad_domyslny). Zwykly formularz
  // z obcej strony takiego naglowka nie ustawi, wiec nie skasuje nikomu ukladu.
  function przywrocDomyslny() {
    return fetch(korzen.getAttribute('data-url-uklad-domyslny'), {
      method: 'POST', credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: '{}'
    }).then(odpowiedzJson).then(function (tresc) {
      // Serwer JUZ skasowal zapisany uklad — od tej chwili punktem odniesienia
      // jest to, co serwer podaje teraz, a NIE to, co jeszcze widac. Do
      // weryfikacji poprawek (znalezisko 2) zmienial go dopiero udany
      // /api/siatka: gdy siatka padla, licznik mowil „Bez zmian" przy
      // wlasnym ukladzie na ekranie i „Zapisz uklad" nic nie wysylal.
      ustawUkladZapisany(tresc && tresc.uklad, true);
      return wymienSiatke('Układ domyślny został przywrócony, ale nie udało się go wczytać: ',
        'Żeby go zobaczyć, odśwież stronę.')
        .then(function (udana) {
          // Siatka nie przyszla: ekran ma wlasny uklad, a zapisany jest juz
          // domyslny — to JEST niezapisana zmiana i licznik ma to powiedziec.
          if (!udana) { oznaczZmiane(); }
          return udana;
        });
    }, function (blad) {
      pokazBladPaska(zdanieBledu('Nie udało się przywrócić układu domyślnego: ', blad,
        'Spróbuj ponownie za chwilę.'));
      return false;
    });
  }

  // „Zapisz uklad". Po zapisie NIE pobieramy siatki od nowa i NIE
  // przeladowujemy strony: DOM jest juz dokladnie tym, co poszlo na serwer
  // (kazdy kafelek przyszedl z /api/kafelek gotowy i z danymi, a przestawienia
  // i usuniecia zmienialy wylacznie kolejnosc wezlow).
  function zapiszPaczke() {
    // Bledy kafelkow sprzed klikniecia sa juz rozstrzygniete na ekranie
    // (i akcjaPaska za chwile schowa ich komunikat) — liczy sie tylko to,
    // co padnie w trakcie czekania na kafelki w locie.
    var bledyPrzed = bledyKafelkow;
    return akcjaPaska(function () {
      return poWczytaniuKafelkow().then(function () {
        if (!trybEdycji()) { return true; }
        if (bledyKafelkow !== bledyPrzed) {
          // Komunikat kafelka zostaje w pasku, tryb edycji tez — uzytkownik
          // widzi, co sie nie udalo, i sam decyduje, czy zapisac bez tego.
          var blad = document.getElementById('an-edycja-blad');
          pokazBladPaska('Układu nie zapisano. ' + (blad ? blad.textContent : ''));
          return false;
        }
        // Bez zmian i bez pominietych nie ma czego zapisywac. Zapis
        // niezmienionego ukladu domyslnego zamrozilby go uzytkownikowi — a brak
        // wiersza w bazie znaczy „idz za ukladem domyslnym, takze jutrzejszym".
        if (!saZmiany() && document.getElementById('an-pominiete').hidden) {
          wylaczEdycje();
          return true;
        }
        var uklad = ukladZeStrony();
        var dubel = zdublowanyKlucz(uklad);
        if (dubel) {
          pokazBladPaska('Dwa kafelki pokazują to samo — zmień wymiar jednego '
            + 'z nich przed zapisem.');
          return false;
        }
        return zapiszUklad(uklad, function (tresc) {
          // Nowy punkt odniesienia: uklad, ktory serwer POTWIERDZIL.
          ukladZapisany = (tresc && Array.isArray(tresc.uklad)) ? tresc.uklad : uklad;
          // Zapisany wymiar KAZDEGO kafelka to od tej chwili ten, ktory widac.
          // Bez tego plakietka podgladu pokazalaby sie po wyjsciu z trybu
          // edycji na kafelku, ktoremu wlasnie zmieniono wymiar NA STALE.
          kafelki().forEach(function (w) {
            var wymiar = w.getAttribute('data-wymiar');
            if (wymiar) { w.setAttribute('data-wymiar-zapisany', wymiar); }
          });
          // Zapis przepisal wiersz — pozycji nie do rozpoznania juz w nim nie ma.
          pokazPominiete(0);
          schowajBlad();
          wylaczEdycje();
        });
      });
    }, 'an-uklad-zapisz');
  }

  function anulujEdycje() {
    if (akcjaWToku) { return; }
    if (saZmiany()) {
      pokazPotwierdzenie('Odrzucić niezapisane zmiany w układzie?', 'Odrzuć', function () {
        return akcjaPaska(wymienSiatke, 'an-uklad-anuluj');
      });
      return;
    }
    wylaczEdycje();
  }

  function podepnijZapisUkladu() {
    document.getElementById('an-uklad-zapisz').addEventListener('click', zapiszPaczke);
    document.getElementById('an-uklad-anuluj').addEventListener('click', anulujEdycje);
    // Przywrocenie domyslnego KASUJE zapisany uklad — z paska edycji pyta
    // o potwierdzenie tym samym wierszem, co porzucenie zmian.
    document.getElementById('an-uklad-domyslny').addEventListener('click', function () {
      pokazPotwierdzenie('Przywrócić układ domyślny? Twój zapisany układ zostanie usunięty.',
                         'Przywróć', function () {
                           return akcjaPaska(przywrocDomyslny, 'an-uklad-domyslny');
                         });
    });
    // Ze stanu pustego — bez pytania, ale WYLACZNIE poza trybem edycji: tam
    // pusty jest ZAPISANY uklad, wiec nie ma czego stracic. W trybie edycji
    // przycisk jest schowany (odswiezStanPusty) — straz ponizej to druga
    // linia obrony, gdyby ktos go kiedys odslonil (przeglad galezi, W2).
    document.getElementById('an-stan-pusty-domyslny').addEventListener('click', function () {
      if (trybEdycji()) { return; }
      akcjaPaska(przywrocDomyslny, 'an-stan-pusty-domyslny').then(function (udana) {
        if (udana) { document.getElementById('an-edytuj').focus({ preventScroll: true }); }
      });
    });
    document.getElementById('an-edycja-odrzuc').addEventListener('click', function () {
      var akcja = akcjaPotwierdzenia;
      schowajPotwierdzenie();
      if (akcja) { akcja(); }
    });
    document.getElementById('an-edycja-wroc').addEventListener('click', wrocZPotwierdzenia);

    // Escape wychodzi z trybu edycji — przez to samo potwierdzenie, co
    // „Anuluj". Okno dodawania ma pierwszenstwo (jego sluchacz w fazie
    // przechwytywania zatrzymuje zdarzenie), a menu zakresu dat i popover
    // filtra zamykaja sie same — wtedy Escape dotyczy ich, nie trybu.
    document.addEventListener('keydown', function (zdarzenie) {
      if (zdarzenie.key !== 'Escape' || !trybEdycji() || modalOtwarty()) { return; }
      // W trakcie zapisu Escape nie moze otworzyc „Odrzucic zmiany?" — ekran
      // i baza rozjechalyby sie (przeglad galezi, drobne 1).
      if (akcjaWToku) { return; }
      var menu = document.getElementById('an-zakres-menu');
      if ((menu && !menu.hidden) || document.querySelector('.an-filtr-popover')) { return; }
      if (!document.getElementById('an-edycja-potwierdzenie').hidden) {
        wrocZPotwierdzenia();
        return;
      }
      anulujEdycje();
    });

    // Opuszczenie strony z niezapisanym ukladem — ta sama ochrona, co
    // w arkuszu (arkusz.js). Przegladarki pokazuja wlasny komunikat.
    window.addEventListener('beforeunload', function (zdarzenie) {
      if (!saZmiany()) { return; }
      zdarzenie.preventDefault();
      zdarzenie.returnValue = 'Masz niezapisane zmiany w układzie pulpitu.';
      return zdarzenie.returnValue;
    });
  }

  // FOKUS NIE MOZE STAC POD PRZYKLEJONYM PASKIEM (WCAG 2.4.11). Tab po
  // narzedziach kafelkow zatrzymywal sie na elemencie, ktory byl w oknie,
  // ale pod paskiem edycji — przegladarka nie przewija, bo element „jest
  // widoczny", a `scroll-padding-bottom` dziala tylko wtedy, gdy przewijac
  // trzeba i tak (przeglad galezi, W5). Tu dosuwamy strone o nachodzenie
  // plus zapas. Okno dodawania ma wlasne przyciemnienie nad paskiem — jego
  // nie dotyczy.
  var ZAPAS_NAD_PASKIEM = 12;

  // Fokus z KLAWIATURY, nie z myszy. Chrome daje fokus przyciskowi juz przy
  // `mousedown` — gdyby odslonFokus przewinal wtedy strone, `mouseup` trafilby
  // w inne miejsce i klikniecie w przycisk wystajacy spod paska by przepadlo:
  // strona podskakiwala, a przycisk nie reagowal (weryfikacja poprawek,
  // znalezisko 1). Przycisk klikniety mysza nie ma `:focus-visible`, a ten
  // sam przycisk osiagniety Tabem — ma.
  function fokusZKlawiatury(cel) {
    try {
      return cel.matches(':focus-visible');
    } catch (blad) {
      // Przegladarka bez `:focus-visible` (Safari < 15.4) rzuca SyntaxError.
      // Zostaje wtedy dawne zachowanie — Tab ma dalej odslaniac fokus.
      return true;
    }
  }

  // Wcisniety wskaznik (mysz, dotyk, pioro). Chrome daje fokus juz przy
  // `mousedown`, a <select> kliknietemu mysza — w odroznieniu od przycisku —
  // takze `:focus-visible`, wiec sam test `fokusZKlawiatury` go nie odroznial:
  // strona podskakiwala przy kliknieciu selektora czesciowo schowanego pod
  // paskiem (partia E, punkt E7). Fokus, ktory przyszedl ze wskaznika, nie
  // przewija niczego.
  var wskaznikWcisniety = false;

  function odslonFokus(zdarzenie) {
    if (!trybEdycji()) { return; }
    var cel = zdarzenie.target;
    var pasek = document.getElementById('an-edycja');
    if (!cel || !cel.getBoundingClientRect || pasek.contains(cel)) { return; }
    if (wskaznikWcisniety) { return; }
    if (!fokusZKlawiatury(cel)) { return; }
    if (cel.closest && cel.closest('#an-modal-dodaj')) { return; }
    var nachodzi = cel.getBoundingClientRect().bottom + ZAPAS_NAD_PASKIEM
      - pasek.getBoundingClientRect().top;
    if (nachodzi <= 0) { return; }
    var przed = korzen.scrollTop;
    korzen.scrollTop = przed + nachodzi;
    // Na waskim ekranie przewija sie okno, nie #analiza.
    if (korzen.scrollTop === przed) { window.scrollBy(0, nachodzi); }
  }

  function podepnijEdycje() {
    document.getElementById('an-edytuj').addEventListener('click', wlaczEdycje);
    korzen.addEventListener('focusin', odslonFokus);
    // Faza przechwytywania: flaga ma byc ustawiona, ZANIM przegladarka nada
    // fokus. Klawiatura ja zdejmuje — Tab po kliknieciu ma dalej odslaniac.
    document.addEventListener('pointerdown', function () { wskaznikWcisniety = true; }, true);
    document.addEventListener('pointerup', function () { wskaznikWcisniety = false; }, true);
    document.addEventListener('pointercancel', function () { wskaznikWcisniety = false; }, true);
    document.addEventListener('keydown', function () { wskaznikWcisniety = false; }, true);

    // Delegacja na KORZENIU, nie na siatce: „Anuluj" i „Przywroc domyslny"
    // podmieniaja caly wezel siatki na przyniesiony z /api/siatka, a sluchacz
    // przypiety do starej siatki zniknalby razem z nia.
    korzen.addEventListener('click', function (zdarzenie) {
      if (!trybEdycji() || !zdarzenie.target.closest) { return; }
      var ruch = zdarzenie.target.closest('[data-ruch]');
      if (ruch) {
        var wezel = ruch.closest('[data-kafelek]');
        var kierunek = ruch.getAttribute('data-ruch');
        if (wezel && przeniesKafelek(wezel, kierunek)) {
          // insertBefore na podpietym wezle USUWA go i wstawia od nowa, wiec
          // fokus ucieka na <body> i DRUGA strzalka z rzedu nie dziala.
          // Bez tej linii przenoszenie z klawiatury jest bezuzyteczne.
          wezel.querySelector('[data-ruch="' + kierunek + '"]').focus();
          // „Przenies pozniej" przy ostatnim rzedzie zsuwa kafelek w dol, a przy
          // „pozniej" przestawiany jest SASIAD — fokus sie nie zmienia, wiec
          // przegladarka nie przewija niczego i fokus zostawal poza oknem
          // (partia E, punkt E7). `nearest` szanuje scroll-padding-bottom trybu
          // edycji, wiec przycisk staje nad przyklejonym paskiem.
          wezel.querySelector('[data-ruch="' + kierunek + '"]')
            .scrollIntoView({ block: 'nearest' });
        }
        return;
      }
      var usun = zdarzenie.target.closest('.an-kafelek__usun');
      if (usun && usun.closest('[data-kafelek]')) { usunKafelek(usun.closest('[data-kafelek]')); }
    });

    // PRZECIAGANIE: natywne HTML5, zero bibliotek (Safari ITP blokuje CDN-y).
    // Dziala mysza. Dotyk obsluguja przyciski wyzej — wlasne przeciaganie
    // dotykiem to kilkaset linii, ktorych nie da sie sprawdzic bez
    // przegladarki, a przyciski pokrywaja ten przypadek w calosci.
    var przeciagany = null;

    function wyczyscCele() {
      kafelki().forEach(function (w) { w.removeAttribute('data-cel-upuszczenia'); });
    }

    korzen.addEventListener('dragstart', function (zdarzenie) {
      if (!trybEdycji() || !zdarzenie.target.closest) { return; }
      przeciagany = zdarzenie.target.closest('[data-kafelek]');
      if (!przeciagany) { return; }
      przeciagany.setAttribute('data-przeciagany', '');
      zdarzenie.dataTransfer.effectAllowed = 'move';
      // Firefox nie zaczyna przeciagania bez ustawionych danych.
      zdarzenie.dataTransfer.setData('text/plain', przeciagany.getAttribute('data-klucz'));
    });
    korzen.addEventListener('dragover', function (zdarzenie) {
      if (!przeciagany) { return; }
      zdarzenie.preventDefault();
      zdarzenie.dataTransfer.dropEffect = 'move';
      var cel = zdarzenie.target.closest ? zdarzenie.target.closest('[data-kafelek]') : null;
      wyczyscCele();
      if (cel && cel !== przeciagany) { cel.setAttribute('data-cel-upuszczenia', ''); }
    });
    korzen.addEventListener('drop', function (zdarzenie) {
      if (!przeciagany) { return; }
      zdarzenie.preventDefault();
      var cel = zdarzenie.target.closest ? zdarzenie.target.closest('[data-kafelek]') : null;
      if (cel && cel !== przeciagany && cel.parentNode === przeciagany.parentNode) {
        // Przeciagany w przod laduje ZA celem, w tyl — PRZED nim. Dzieki temu
        // upuszczenie na sasiada zawsze zamienia je miejscami.
        var wPrzod = (przeciagany.compareDocumentPosition(cel)
                      & Node.DOCUMENT_POSITION_FOLLOWING) !== 0;
        cel.parentNode.insertBefore(przeciagany, wPrzod ? cel.nextSibling : cel);
        oznaczZmiane();
      }
      wyczyscCele();
    });
    korzen.addEventListener('dragend', function () {
      kafelki().forEach(function (w) {
        w.removeAttribute('data-cel-upuszczenia');
        w.removeAttribute('data-przeciagany');
      });
      przeciagany = null;
    });
  }

  /* ---------- modal „Dodaj statystyke" ---------- */

  // Katalog i lista wymiarow przychodza Z SERWERA, w atrybutach danych. Ten
  // plik NIE ma wlasnej listy statystyk ani wlasnych nazw — inaczej modal
  // i karta na pulpicie podpisywalyby to samo na dwa sposoby. Wymiary sa PER
  // TYP (karty kubelkowe maja wlasna, wezsza liste z pseudo-wymiarem spoza
  // rejestru) i z etykietami — dokladnie te, ktore serwer wypisuje
  // w selektorze „wedlug" na kafelku.
  function czytajJson(atrybut, domyslnie) {
    try { return JSON.parse(korzen.getAttribute(atrybut) || '') || domyslnie; }
    catch (blad) { return domyslnie; }
  }
  var katalog = czytajJson('data-katalog', []);
  var wymiaryTypow = czytajJson('data-wymiary', {});
  // Limit jest TWARDY po stronie serwera (uklad.MAKS_KAFELKOW); tutaj tylko
  // o nim mowimy. Liczba przychodzi z atrybutu, zeby nie bylo jej w dwoch
  // miejscach.
  var maksKafelkow = parseInt(korzen.getAttribute('data-maks-kafelkow'), 10);
  var wybranyTyp = null;

  function kluczeNaPulpicie() {
    return kafelki().map(function (w) {
      return w.getAttribute('data-typ') + ':' + (wymiarKafelka(w) || '');
    });
  }

  function typyNaPulpicie() {
    return kafelki().map(function (w) { return w.getAttribute('data-typ'); });
  }

  function kafelekDodawania() {
    return document.getElementById('an-dodaj-kafelek');
  }

  function pokazKafelekDodawania(widoczny) {
    var przycisk = kafelekDodawania();
    if (przycisk) { przycisk.hidden = !widoczny; }
  }

  function odswiezPrzyciskDodaj() {
    var gotowe = !!wybranyTyp && kafelki().length < maksKafelkow;
    if (gotowe && wybranyTyp.wymiarowy) {
      var wybor = document.getElementById('an-modal-wybor-wymiaru');
      var opcja = wybor.options[wybor.selectedIndex];
      gotowe = !!opcja && !opcja.disabled;
    }
    document.getElementById('an-modal-dodaj-potwierdz').disabled = !gotowe;
  }

  function rysujWymiaryModalu() {
    var blok = document.getElementById('an-modal-wymiar');
    var wybor = document.getElementById('an-modal-wybor-wymiaru');
    var uwaga = document.getElementById('an-modal-uwaga');
    uwaga.hidden = true;
    if (!wybranyTyp || !wybranyTyp.wymiarowy) {
      blok.hidden = true;
      odswiezPrzyciskDodaj();
      return;
    }
    blok.hidden = false;
    czysc(wybor);
    var zajete = kluczeNaPulpicie();
    (wymiaryTypow[wybranyTyp.klucz] || []).forEach(function (w) {
      var opcja = el('option', '', w.etykieta);
      opcja.value = w.nazwa;
      // Ta sama para (typ, wymiar) dwa razy to dwa kafelki z identycznymi
      // liczbami — serwer i tak by to odrzucil, wiec mowimy o tym TUTAJ,
      // zanim uzytkownik kliknie „Dodaj".
      if (zajete.indexOf(wybranyTyp.klucz + ':' + w.nazwa) !== -1) {
        opcja.disabled = true;
        opcja.textContent = w.etykieta + ' — już na pulpicie';
      }
      wybor.appendChild(opcja);
    });
    var wolne = Array.prototype.filter.call(wybor.options, function (o) { return !o.disabled; });
    // Najpierw wymiar domyslny typu (ten, ktory ma karta w ukladzie
    // domyslnym), a gdy jest zajety — pierwszy wolny.
    var domyslna = wolne.filter(function (o) { return o.value === wybranyTyp.domyslny_wymiar; })[0];
    if (domyslna || wolne[0]) { wybor.value = (domyslna || wolne[0]).value; }
    if (!wolne.length) {
      uwaga.textContent = 'Ta statystyka jest już na pulpicie we wszystkich '
        + 'dostępnych wymiarach.';
      uwaga.hidden = false;
    }
    odswiezPrzyciskDodaj();
  }

  function rysujListeModalu() {
    var lista = document.getElementById('an-modal-lista');
    var limit = document.getElementById('an-modal-limit');
    var pelny = kafelki().length >= maksKafelkow;
    czysc(lista);
    wybranyTyp = null;
    // Granica, nie blad — bursztyn w modalu, a nie czerwony pasek na stronie.
    limit.hidden = !pelny;
    // Liczba idzie przez tekstZCyframi — kazda cyfra w Mono.
    tekstZCyframi(limit, pelny ? 'Na pulpicie mieści się najwyżej ' + maksKafelkow
      + ' kafelków. Usuń któryś, żeby zrobić miejsce.' : '');
    var typy = typyNaPulpicie();
    katalog.forEach(function (typ) {
      // Zwykly przycisk z `aria-pressed`, nie `role="radio"`: wzorzec radia
      // obiecuje czytnikowi obsluge strzalek, ktorej tu nie ma (przeglad
      // galezi, drobne 6). Lista to kolumna przyciskow chodzona Tabem.
      var pozycja = el('button', 'an-modal__pozycja');
      pozycja.type = 'button';
      pozycja.setAttribute('aria-pressed', 'false');
      pozycja.appendChild(el('span', 'an-modal__nazwa', typ.nazwa));
      pozycja.appendChild(tekstZCyframi(el('span', 'an-modal__opis'), typ.opis));
      // Typ bez wymiaru pokazywalby w drugiej instancji co do cyfry to samo,
      // co w pierwszej, i kosztowalby drugi komplet zapytan. Zostaje na
      // liscie — zeby bylo widac, ze istnieje i gdzie jest — ale nieaktywny.
      if (!typ.wielokrotny && typy.indexOf(typ.klucz) !== -1) {
        pozycja.disabled = true;
        pozycja.appendChild(el('span', 'an-modal__zajete', 'już na pulpicie'));
      }
      if (pelny) { pozycja.disabled = true; }
      pozycja.addEventListener('click', function () {
        wybranyTyp = typ;
        Array.prototype.forEach.call(lista.children, function (w) {
          w.setAttribute('aria-pressed', String(w === pozycja));
        });
        rysujWymiaryModalu();
      });
      lista.appendChild(pozycja);
    });
    rysujWymiaryModalu();
  }

  function modalOtwarty() {
    return !document.getElementById('an-modal-dodaj').hidden;
  }

  function zamknijModal() {
    document.getElementById('an-modal-dodaj').hidden = true;
    document.removeEventListener('keydown', naKlawiszModalu, true);
    // Fokus wraca tam, skad przyszedl — na kafelek „+". preventScroll: strona
    // ma zostac tam, gdzie byla.
    var przycisk = kafelekDodawania();
    if (przycisk && !przycisk.hidden) { przycisk.focus({ preventScroll: true }); }
  }

  // Klawiatura w modalu: Escape zamyka, Tab krazy WEWNATRZ okna — aria-modal
  // mowi czytnikowi, ze reszta strony jest nieaktywna, wiec fokus nie moze
  // na nia uciekac. Sluchacz w fazie PRZECHWYTYWANIA, zeby Escape zamknal
  // modal, zanim zobaczy go wyjscie z trybu edycji.
  function naKlawiszModalu(zdarzenie) {
    if (zdarzenie.key === 'Escape') {
      zdarzenie.preventDefault();
      zdarzenie.stopPropagation();
      zamknijModal();
      return;
    }
    if (zdarzenie.key !== 'Tab') { return; }
    var okno = document.querySelector('#an-modal-dodaj .an-modal__okno');
    var cele = Array.prototype.filter.call(
      okno.querySelectorAll('button, select'),
      function (w) { return !w.disabled && w.getClientRects().length; });
    if (!cele.length) { return; }
    var pierwszy = cele[0];
    var ostatni = cele[cele.length - 1];
    if (zdarzenie.shiftKey && document.activeElement === pierwszy) {
      zdarzenie.preventDefault();
      ostatni.focus();
    } else if (!zdarzenie.shiftKey && document.activeElement === ostatni) {
      zdarzenie.preventDefault();
      pierwszy.focus();
    } else if (!okno.contains(document.activeElement)) {
      zdarzenie.preventDefault();
      pierwszy.focus();
    }
  }

  function otworzModalDodawania() {
    rysujListeModalu();
    var modal = document.getElementById('an-modal-dodaj');
    modal.hidden = false;
    document.addEventListener('keydown', naKlawiszModalu, true);
    var pierwsza = modal.querySelector('.an-modal__pozycja:not([disabled])')
      || modal.querySelector('.an-modal__zamknij');
    pierwsza.focus();
  }

  function dodajKafelek() {
    if (akcjaWToku || !wybranyTyp || kafelki().length >= maksKafelkow) { return; }
    var wymiar = null;
    if (wybranyTyp.wymiarowy) {
      var wybor = document.getElementById('an-modal-wybor-wymiaru');
      var opcja = wybor.options[wybor.selectedIndex];
      if (!opcja || opcja.disabled) { return; }
      wymiar = opcja.value;
    }
    var typ = wybranyTyp;

    // KAFELEK PRZYCHODZI Z SERWERA, GOTOWY I Z DANYMI. Znaczniki generuje
    // Jinja (jedenascie makr w _kafelki.html), a dane liczy `dane_dashboardu`
    // dla tej JEDNEJ instancji — zaden z tych dwoch elementow nie ma prawa
    // powstac w przegladarce, bo byloby to drugie zrodlo prawdy o wygladzie
    // i o liczbach.
    //
    // Tymczasowe miejsce przed kafelkiem „+" pokazuje od razu, gdzie kafelek
    // wyladuje, zajmuje jego miejsce w siatce (nic nie podskakuje) i daje
    // `wymienKafelek` wezel do wymiany. Niesie juz typ i wymiar, wiec liczy
    // sie do paczki zmian od chwili klikniecia.
    var plus = document.querySelector('#an-siatka > .an-kafelek--dodaj');
    var miejsce = el('section', 'an-karta an-kafelek an-kafelek--wczytywanie');
    miejsce.setAttribute('data-kafelek', '');
    miejsce.setAttribute('data-typ', typ.klucz);
    miejsce.setAttribute('data-klucz', typ.klucz + (wymiar ? ':' + wymiar : ''));
    // BEZ `data-wymiar-zapisany`: kafelek nie jest zapisany, dopoki serwer
    // nie potwierdzi zapisu (przeglad galezi, W1). Atrybut dostanie w
    // zapiszPaczke, razem z reszta kafelkow.
    if (wymiar) { miejsce.setAttribute('data-wymiar', wymiar); }
    if (typ.szerokosc === 2) { miejsce.classList.add('an-kafelek--szeroki'); }
    miejsce.appendChild(el('p', 'an-przypis', 'Wczytywanie…'));
    if (plus) { plus.parentNode.insertBefore(miejsce, plus); }
    else { document.getElementById('an-siatka').appendChild(miejsce); }
    schowajBladPaska();
    zamknijModal();

    pobierzKafelek(miejsce, typ.klucz, wymiar);
    oznaczZmiane();
    odswiezStanPusty();
  }

  // Nazwa typu kafelka Z KATALOGU (ta sama, co w oknie dodawania) — do
  // komunikatu o nieudanym dodaniu. Ten plik nie ma wlasnych nazw.
  function nazwaTypu(klucz) {
    var typ = katalog.filter(function (t) { return t.klucz === klucz; })[0];
    return typ ? typ.nazwa : klucz;
  }

  // MIEJSCE NA DODAWANY KAFELEK zbudowane w dodajKafelek: napis „Wczytywanie…"
  // w trakcie zadania, a po awarii — blad i przycisk ponowienia zamiast
  // wiecznego „Wczytywanie…" (przeglad galezi, drobne 4). To nadal tylko
  // miejsce w siatce: prawdziwy kafelek przychodzi z serwera (/api/kafelek).
  function pokazWczytywanieMiejsca(wezel) {
    czysc(wezel);
    wezel.appendChild(el('p', 'an-przypis', 'Wczytywanie…'));
  }

  function pokazBladMiejsca(wezel) {
    czysc(wezel);
    wezel.appendChild(el('p', 'an-kafelek__blad',
      'Nie udało się wczytać danych kafelka „' + nazwaTypu(wezel.getAttribute('data-typ'))
      + '".'));
    var ponow = el('button', 'an-btn', 'Wczytaj ponownie');
    ponow.type = 'button';
    ponow.setAttribute('data-ponow-kafelek', '');
    wezel.appendChild(ponow);
  }

  function podepnijModal() {
    // Delegacja na korzeniu: kafelek „+" jest przenoszony do nowej siatki po
    // „Anuluj" i „Przywroc domyslny" — sluchacz na korzeniu nie musi o tym
    // wiedziec.
    korzen.addEventListener('click', function (zdarzenie) {
      if (!zdarzenie.target.closest || !zdarzenie.target.closest('#an-dodaj-kafelek')) { return; }
      if (akcjaWToku) { return; }
      // „+" poza trybem edycji widac tylko przy pustym pulpicie. Klikniecie
      // NAJPIERW wchodzi w tryb edycji, a dopiero potem otwiera okno — dodany
      // kafelek trafia wtedy do paczki zmian, pasek robi sie bursztynowy
      // i „Zapisz uklad" go zapisuje. Do przegladu galezi (W1) okno otwieralo
      // sie poza trybem edycji, a dodany tak kafelek przepadal po F5.
      if (!trybEdycji()) { wlaczEdycje(); }
      otworzModalDodawania();
    });
    var modal = document.getElementById('an-modal-dodaj');
    Array.prototype.forEach.call(modal.querySelectorAll('[data-zamknij-modal]'),
      function (w) { w.addEventListener('click', zamknijModal); });
    document.getElementById('an-modal-wybor-wymiaru')
      .addEventListener('change', odswiezPrzyciskDodaj);
    document.getElementById('an-modal-dodaj-potwierdz')
      .addEventListener('click', dodajKafelek);
    // „Wczytaj ponownie" w miejscu kafelka, ktorego dane nie przyszly.
    korzen.addEventListener('click', function (zdarzenie) {
      var ponow = zdarzenie.target.closest ? zdarzenie.target.closest('[data-ponow-kafelek]') : null;
      var wezel = ponow ? ponow.closest('[data-kafelek]') : null;
      if (!wezel || akcjaWToku) { return; }
      pobierzKafelek(wezel, wezel.getAttribute('data-typ'), wezel.getAttribute('data-wymiar'));
    });
  }

  // Cialo kafelka — wezel [data-cialo] z kluczem TEGO kafelka.
  function cialoKafelka(kafelek) {
    return kafelek.querySelector('[data-cialo="' + kafelek.getAttribute('data-klucz') + '"]');
  }

  /* ---------- wypelnienie calosci ---------- */

  // Stopki kart („Wyswietl raport kanalow →") maja adres wyrenderowany
  // SERWEROWO, a zmiana okresu leci przez fetch + pushState, bez
  // przeladowania strony. Bez przepisania href kazde wyjscie po pierwszej
  // interakcji prowadzilo do Eksploratora z NIEAKTUALNYM okresem: ustawiam
  // „biezacy rok", klikam „Wyswietl raport kanalow", dostaje wrzesien.
  //
  // Wymiar wyjscia niesie SAMO wyjscie (`data-wyjscie-wymiar`, wymiar jego
  // kafelka) — do 23.09.2026 karty przelaczalne podawaly klucz karty, a wymiar
  // dociagalo sie z mapy wymiarow w adresie, ktorej od Planu D nie ma.
  //
  // Stopka bez data-wyjscie-miara (mapa wojewodztw) zostaje nietknieta.
  //
  // `filtrWyjsc` to wykluczenia pozycji (partia E, punkt E4) w postaci
  // zwyklego filtra — tak rozumie je Eksplorator. Napis sklada SERWER
  // (payload.wykluczenia.filtr); pusty znaczy „bez wykluczen" i parametru
  // wtedy w adresie nie ma.
  function odswiezStopki(kafelek, filtrWyjsc) {
    var wyjscia = (kafelek || korzen).querySelectorAll('a[data-wyjscie-miara]');
    for (var i = 0; i < wyjscia.length; i++) {
      var odnosnik = wyjscia[i];
      var wymiar = odnosnik.getAttribute('data-wyjscie-wymiar');
      if (!wymiar) { continue; }
      var parametry = new URLSearchParams();
      parametry.set('wymiar', wymiar);
      parametry.set('przestawienie', 'miesiac');
      parametry.set('miara', odnosnik.getAttribute('data-wyjscie-miara'));
      parametry.set('od', stan.od);
      parametry.set('do', stan.do);
      if (filtrWyjsc) { parametry.set('filtr', filtrWyjsc); }
      // Sciezke bierzemy z adresu, ktory wypisal serwer — nie sklejamy jej
      // w JavaScripcie, zeby url_for zostal jedynym zrodlem trasy.
      var sciezka = odnosnik.getAttribute('href').split('?')[0];
      odnosnik.setAttribute('href', sciezka + '?' + parametry.toString());
    }
  }

  // Karty, ktorych segment nie dotyczy, mowia to wprost zamiast udawac.
  // Adnotacja z data-zawsze zostaje widoczna TAKZE bez segmentu: karty
  // „Klienci" i „Naleznosci" nie sa liczone za wybrany okres, a wiekszosc
  // uzytkownikow nigdy segmentu nie wlaczy i odczyta je jako dane okresu.
  function ustawAdnotacje(kafelek, maSegment, maWykluczenia) {
    var adnotacje = kafelek.querySelectorAll('[data-bez-segmentu]');
    for (var i = 0; i < adnotacje.length; i++) {
      adnotacje[i].hidden = !maSegment && !adnotacje[i].hasAttribute('data-zawsze');
    }
    // Karty, ktorych wykluczenia pozycji NIE dotycza (lejek liczy wyceny, nie
    // pozycje sprzedazy), mowia to wprost — ale tylko wtedy, gdy wykluczenia
    // sa wlaczone. Tresc stoi w szablonie.
    var bezWykluczen = kafelek.querySelectorAll('[data-bez-wykluczen]');
    for (var j = 0; j < bezWykluczen.length; j++) {
      bezWykluczen[j].hidden = !maWykluczenia;
    }
  }

  // Piec wskaznikow i legenda wykresu trendu. Wyciete z dawnego wypelnij(),
  // bo kafelek KPI da sie od Planu D usunac i dodac z powrotem — wstawiony
  // w miejscu musi umiec narysowac sie sam.
  //
  // Pole „Sprzedaz" ma dwa warianty (szablon, `data-widok-miary`): netto
  // i sztuki. Wypelniamy OBA przy kazdym rysowaniu, a ktory widac, rozstrzyga
  // tryb kafelka w CSS — przelaczenie nie musi wtedy niczego dopisywac.
  function rysujKpi(kafelek, dane, miary) {
    var klucz = kafelek.getAttribute('data-klucz');
    ['netto', 'sztuki', 'objetosc', 'zamowienia', 'srednie_zamowienie',
     'cena_za_m3'].forEach(function (k) {
      var wartosc = dane.kpi[k];
      // Payload bez sztuk (serwer sprzed przelacznika) zostawia wariant
      // sztuk przy kresce ze szkieletu, zamiast pisac „NaN".
      if (wartosc === undefined) { return; }
      var tekst = (k === 'objetosc') ? fmt2.format(wartosc) : fmt0.format(wartosc);
      var wezel = poleW(kafelek, klucz + '.' + k);
      if (wezel) { wezel.textContent = tekst; }
      // Tryb „zl + szt.": pole „Sprzedaz" zostaje w zlotowkach (glowna liczba
      // kafelka), a sztuki ida pod nia drobnym dopiskiem. Dawniej pole
      // pokazywalo w tym trybie same sztuki i kwota netto znikala z naglowka
      // (weryfikacja 24.09.2026). Dopisek widac tylko w tym trybie (CSS).
      if (wezel && k === 'netto' && dane.kpi.sztuki !== undefined) {
        var dopisek = document.createElement('span');
        dopisek.className = 'an-kpi__dopisek-szt';
        dopisek.textContent = fmt0.format(dane.kpi.sztuki) + ' ' + (jednostki.sztuki || '');
        wezel.appendChild(dopisek);
      }
      ustawW(kafelek, klucz + '.zmiana.' + k, zmianaNaTekst(dane.kpi.zmiana[k]),
             klasaZmiany(dane.kpi.zmiana[k]));

      // Druga liczba w kafelku KPI — TYLKO gdy jest segment porownawczy.
      // Chowamy jawnie w przeciwnym razie, inaczej po usunieciu segmentu
      // zostalaby na ekranie stara wartosc z poprzedniego wypelnienia.
      var drugi = poleW(kafelek, klucz + '.' + k + '.porownanie');
      if (drugi) {
        if (dane.porownanie && dane.porownanie.kpi) {
          drugi.textContent = (k === 'objetosc')
            ? fmt2.format(dane.porownanie.kpi[k]) : fmt0.format(dane.porownanie.kpi[k]);
          drugi.hidden = false;
        } else {
          drugi.hidden = true;
        }
      }
    });

    ustawW(kafelek, 'trend.rok_biezacy', String(dane.trend.biezacy_rok));
    // Nakladka roku poprzedniego ustepuje miejsca legendzie segmentu, gdy ten
    // jest wlaczony — patrz komentarz przy rysujTrend.
    ustawW(kafelek, 'trend.rok_poprzedni',
           dane.porownanie ? dane.porownanie.nazwa : String(dane.trend.poprzedni_rok));
    var probkaPoprzedniego = kafelek.querySelector('[data-legenda-probka="poprzedni"]');
    if (probkaPoprzedniego) {
      probkaPoprzedniego.style.background = dane.porownanie ? dane.porownanie.kolor
                                                            : KOLOR_ROKU_POPRZEDNIEGO;
    }
    rysujLegendeDwochOsi(kafelek, dane, miary || MIARY_DOMYSLNE);
  }

  // LEGENDA TRYBU „zl + szt." — nazywa obie serie wykresu (slupki i krzywa),
  // a przy segmencie porownawczym takze jego pare znakow. Nazwy miar z
  // payloadu (etykiety_miar), kolory — te same stale, ktorymi rysuje
  // rysujTrend. Widac ja tylko w trybie dwoch miar (wariant w szablonie),
  // wiec w pozostalych nie ma czego wypelniac: przelaczenie trybu i tak
  // rysuje kafelek od nowa.
  function rysujLegendeDwochOsi(kafelek, dane, miary) {
    if (miary.length < 2) { return; }
    var rok = String(dane.trend.biezacy_rok);
    var slupki = miary[0];
    var krzywa = miary[1];
    function wpis(nazwa, tekst) {
      var wezel = kafelek.querySelector('[data-legenda="' + nazwa + '"]');
      if (wezel) { wezel.textContent = tekst; }
    }
    function probka(nazwa, kolor) {
      var wezel = kafelek.querySelector('[data-legenda-probka="' + nazwa + '"]');
      if (!wezel) { return; }
      // Kwadrat slupka ma kolor w tle, kreska krzywej — w `color` (CSS bierze
      // go przez currentColor, takze w wersji przerywanej).
      if (wezel.classList.contains('an-probka--linia')) { wezel.style.color = kolor; }
      else { wezel.style.background = kolor; }
    }
    wpis('slupki', (etykietyMiar[slupki] || slupki) + ' ' + rok);
    wpis('krzywa', (etykietyMiar[krzywa] || krzywa) + ' ' + rok);
    probka('slupki', KOLOR_SLUPKOW_DWIE_OSIE);
    probka('krzywa', KOLOR_KRZYWEJ);
    var segment = kafelek.querySelector('[data-legenda-segment]');
    if (segment) {
      segment.hidden = !dane.porownanie;
      if (dane.porownanie) {
        wpis('segment', dane.porownanie.nazwa);
        probka('segment', dane.porownanie.kolor);
        probka('segment-krzywa', dane.porownanie.kolor);
      }
    }
  }

  // Obie liczby przychodza POLICZONE z serwera. Liczone tutaj bralyby wiersze
  // juz ZWINIETE, wiec „Najwyzsze sr. zamowienie" potrafiloby wskazac
  // syntetyczny wiersz „Pozostale (7)", a roznica ceny usredniala wykonczenia
  // razem z ogonem. Ten plik niczego nie liczy — patrz naglowek.
  function rysujNajlepszego(kafelek, karta) {
    var sciezka = kafelek.getAttribute('data-klucz') + '.najlepszy';
    var najlepszy = karta.najlepszy;
    if (najlepszy) {
      ustawZJednostka(kafelek, sciezka,
        najlepszy.etykieta + ' ' + fmt0.format(najlepszy.srednie), 'srednie_zamowienie');
    } else {
      ustawW(kafelek, sciezka, '—');
    }
  }

  // Srodek pierscienia idzie za miara trybu — karta przychodzi W MIERZE
  // TRYBU (kartaWMierze), a srodek dla sztuk wskazal serwer. „Cena za m3
  // z wykonczeniem" zostaje ta sama w kazdym trybie: to cena, nie miara
  // sprzedazy.
  function rysujDodatkiWykonczenia(kafelek, karta) {
    var klucz = kafelek.getAttribute('data-klucz');
    var roznica = karta.roznica_do_surowego;
    ustawW(kafelek, klucz + '.roznica',
      (roznica === null || roznica === undefined)
        ? '—' : zmianaNaTekst(roznica) + ' wobec surowego');

    rysujSrodekPierscienia(kafelek, karta.najwiekszy);
  }

  // Rozbicie kanalu recznego — druga os karty kanalow, NIEZALEZNA od wymiaru
  // kafelka. Payload niesie je raz (`kanal_rozbicie`), wiec przy kilku
  // kafelkach kanalow kazdy rysuje to samo rozbicie u siebie.
  function rysujRozbicieKanalu(kafelek, dane, miary) {
    var gniazdo = kafelek.querySelector('[data-rozbicie]');
    if (!gniazdo || !dane.kanal_rozbicie) { return; }
    miary = miary || MIARY_DOMYSLNE;
    // W mierze trybu kafelka, tak jak karta kanalow nad nim.
    rysujWiersze(gniazdo, kartaWMierze(dane.kanal_rozbicie, miary), {
      szerokoscNazwy: 78, niskiTor: true, drugaKolumna: miary.length > 1,
      porownanie: wierszeWMierze(dane.porownanie ? dane.porownanie.kanal_rozbicie : null, miary),
      porownanieOgon: wierszeWMierze(dane.porownanie ? dane.porownanie.kanal_rozbicie_ogon : null,
                                     miary)
    });
  }

  function rysujKosztKuriera(kafelek, dane) {
    var koszt = dane.dostawa_koszt_kuriera;
    if (koszt === null || koszt === undefined) { return; }
    ustawZJednostka(kafelek, kafelek.getAttribute('data-klucz') + '.koszt_kuriera',
      fmt0.format(koszt), 'koszt_kuriera', 'brutto');
  }

  // Karta kubelkowa („Klienci wedlug", „Naleznosci wedlug"). Wiersze przychodza
  // POLICZONE z serwera — tak samo jak wszedzie indziej — tylko w wezszym
  // ksztalcie: jedna liczba (`liczba`) zamiast kompletu netto/objetosc/
  // zamowienia, bo tyle widac w kolumnie. Podpis tej kolumny tez jedzie
  // z serwera, bo zmienia sie razem z wymiarem. Od Planu D blok karty siedzi
  // w `dane.karty[klucz]`, a nie pod kluczem najwyzszego poziomu.
  function rysujKarteKubelkowa(kafelek, typ, karta, miary) {
    var klucz = kafelek.getAttribute('data-klucz');
    rysujNaglowekKolumny(kafelek, karta.naglowek);
    if (typ === 'klienci') {
      // Od partii E (punkt E2) kolo z legenda-tabela zamiast slupkow.
      // Miara kola idzie za przelacznikiem kafelka („zl" albo „szt.");
      // karta jest juz w tej mierze (kartaWMierze w rysujKafelek).
      rysujLegendeKola(kafelek, karta);
      rysujKoloKlientow(kafelek, karta, (miary || MIARY_DOMYSLNE)[0]);
      ustawW(kafelek, klucz + '.konwersja', fmt1.format(karta.konwersja.procent) + '%');
      ustawW(kafelek, klucz + '.nowi', fmt0.format(karta.nowi_w_okresie));
    } else {
      rysujWiersze(cialoKafelka(kafelek), kartaKubelkowa(typ, karta),
                   { szerokoscNazwy: 54, niskiTor: true });
      rysujOstrzezenieSalda(kafelek, karta);
      rysujNadplaty(kafelek, karta);
    }
    ustawW(kafelek, klucz + '.uwaga', karta.uwaga);
  }

  // Rysuje JEDEN kafelek z pelnego payloadu. Wydzielona z petli celowo:
  // podglad wymiaru, dodanie kafelka i anulowanie edycji wstawiaja kafelek
  // w miejscu i wolaja DOKLADNIE te funkcje. Gdyby kazde z nich rysowalo
  // po swojemu, powstalyby cztery sciezki rysowania tego samego.
  //
  // Wszystko, co rysuje, szuka wezlow WEWNATRZ kafelka, nie na calej stronie
  // — ten sam typ moze stac na pulpicie kilka razy.
  //
  // Zwraca true, gdy payload niosl dane TEGO kafelka i kafelek je dostal.
  // false znaczy „serwer o nim nie wie" (kafelek dodany albo przestawiony
  // w trybie edycji, jeszcze niezapisany) — wypelnij() dociaga go wtedy
  // osobno, zamiast zostawic ze starymi liczbami pod nowym okresem.
  //
  // PAYLOAD ZOSTAJE PRZY KAFELKU (`danePulpitu`) — z niego przelacznik miary
  // rysuje kafelek od nowa w innym trybie, bez zadania do serwera. Kafelek
  // rysuje sie w SWOIM trybie (`miaryKafelka`), wiec zmiana okresu, segmentu
  // albo wykluczen nie cofa przelacznika; cofa go dopiero kafelek przyniesiony
  // z serwera od nowa (podglad wymiaru, odswiezenie, „Anuluj").
  function rysujKafelek(wezel, dane) {
    // Miejsce na kafelek w drodze z serwera nie ma czego rysowac — narysuje
    // go wymienKafelek po odpowiedzi. false, bo jego dane jeszcze nie weszly.
    if (wezel.classList.contains('an-kafelek--wczytywanie')) { return false; }
    // Payload, ktory nie niesie tego kafelka, niczego tu nie popsuje:
    // przelaczenie trybu narysuje wtedy tyle, co ponizej — nic — a kafelek
    // i tak dociagnie wlasny (dociagnijBrakujace) i zapamieta jego payload.
    wezel.danePulpitu = dane;
    var miary = miaryKafelka(wezel, dane);
    var opis = opisKafelka(wezel);
    // Karta i wiersze segmentu W MIERZE TRYBU przelacznika (kartaWMierze) —
    // w trybie domyslnym to te same obiekty, co w payloadzie.
    var karta = kartaWMierze((dane.karty && dane.karty[opis.klucz]) || null, miary);
    var segment = wierszeWMierze((dane.porownanie && dane.porownanie.karty)
      ? (dane.porownanie.karty[opis.klucz] || null) : null, miary);
    var segmentOgon = wierszeWMierze((dane.porownanie && dane.porownanie.ogony)
      ? (dane.porownanie.ogony[opis.klucz] || null) : null, miary);
    var drugaKolumna = miary.length > 1;

    if (dane.jednostki) { jednostki = dane.jednostki; }
    if (dane.etykiety_miar) { etykietyMiar = dane.etykiety_miar; }
    var wykluczenia = dane.wykluczenia || {};
    odswiezStopki(wezel, wykluczenia.filtr || '');
    ustawAdnotacje(wezel, !!dane.porownanie, !!wykluczenia.opis);

    // Kafelki bez wymiaru czytaja wlasny blok payloadu, nie `karty`.
    if (opis.typ === 'kpi') {
      if (!dane.kpi || !dane.trend) { return false; }
      rysujKpi(wezel, dane, miary);
      rysujTrend(wezel, dane, miary);
      return true;
    }
    if (opis.typ === 'wnioski') {
      if (!dane.wnioski) { return false; }
      rysujWnioski(wezel, dane.wnioski);
      return true;
    }
    if (opis.typ === 'lejek') {
      if (!dane.lejek) { return false; }
      ostatnieDane = dane;
      rysujOpcjeLejka(dane, wezel);
      rysujLejek(dane, wezel);
      return true;
    }

    // Kafelek, o ktorym serwer nic nie wie (dodany w trybie edycji, jeszcze
    // niezapisany), zostaje szkieletem. Bez tego warunku caly render
    // przewracalby sie na pierwszym takim kafelku.
    if (!karta) { return false; }

    var cialo = cialoKafelka(wezel);
    if (opis.typ === 'klienci' || opis.typ === 'naleznosci') {
      rysujKarteKubelkowa(wezel, opis.typ, karta, miary);
      return true;
    }
    if (opis.typ === 'mix') {
      // Mix i wykonczenie tez biora segment (serwer je liczy), ale maja
      // wlasne funkcje rysujace zamiast rysujWiersze — bez podania im
      // segmentu wygladalyby po jego wlaczeniu identycznie jak bez niego
      // (znalezisko z przegladu Zadania 10).
      rysujTabeleMiksu(wezel, karta, segment, segmentOgon);
      return true;
    }
    if (opis.typ === 'wykonczenie') {
      rysujLegendeWykonczenia(wezel, karta, segment, segmentOgon);
      rysujDodatkiWykonczenia(wezel, karta);
      rysujWykonczenie(wezel, karta, miary[0]);
      return true;
    }
    if (opis.typ === 'wojewodztwo') {
      // KARTOGRAM zamiast listy slupkow, ale tylko wtedy, gdy serwer przyslal
      // klucz `mapa` — czyli dla wymiaru, ktory opisuje wojewodztwa. Przy
      // kazdym innym wymiarze karta wraca do slupkow. rysujWiersze wolamy TAK
      // CZY TAK: z pusta lista kasuje wiersze szkieletu (i wiersze
      // poprzedniego wymiaru), zamiast zostawiac je nad mapa.
      var mapaWojewodztw = rysujMapeWojewodztw(wezel, karta,
        dane.porownanie ? dane.porownanie.mapa : null,
        dane.porownanie ? dane.porownanie.nazwa : '', miary[0]);
      rysujWiersze(cialo,
        mapaWojewodztw ? { wymiar: karta.wymiar, wiersze: [], ogon: [] } : karta,
        {
          szerokoscNazwy: 88, niskiTor: true, drugaKolumna: drugaKolumna,
          porownanie: mapaWojewodztw ? null : segment,
          porownanieOgon: mapaWojewodztw ? null : segmentOgon
        });
      return true;
    }
    if (opis.typ === 'kanal') {
      rysujWiersze(cialo, karta, { szerokoscNazwy: 78, porownanie: segment,
                                   porownanieOgon: segmentOgon, drugaKolumna: drugaKolumna });
      rysujRozbicieKanalu(wezel, dane, miary);
      return true;
    }
    if (opis.typ === 'opiekun') {
      rysujWiersze(cialo, karta, { szerokoscNazwy: 88, drugaKolumna: drugaKolumna,
                                   porownanie: segment, porownanieOgon: segmentOgon });
      rysujNajlepszego(wezel, karta);
      return true;
    }
    if (opis.typ === 'dostawa') {
      rysujWiersze(cialo, karta, { szerokoscNazwy: 96, niskiTor: true, drugaKolumna: drugaKolumna,
                                   porownanie: segment, porownanieOgon: segmentOgon });
      rysujKosztKuriera(wezel, dane);
    }
    return true;
  }

  function wypelnij(dane) {
    // Pierwsza linia: jednostki z payloadu. Wszystko nizej, co doklada napis
    // „zl" albo „%", bierze go stad.
    jednostki = dane.jednostki || {};
    etykietyMiar = dane.etykiety_miar || {};
    ustaw('okres.stan_na', 'Stan na ' + dane.okres.stan_na);
    ustaw('okres.nazwa', dane.okres.nazwa);
    ustaw('okres.opis', dane.okres.opis);
    var polaDat = { 'an-zakres-od': dane.okres.od, 'an-zakres-do': dane.okres.do };
    Object.keys(polaDat).forEach(function (id) {
      var wezel = document.getElementById(id);
      if (wezel) { wezel.value = polaDat[id]; }
    });

    rysujSegmenty(dane);
    rysujWykluczenia(dane.wykluczenia);

    // JEDNA PETLA PO KAFELKACH, zamiast jedenastu wywolan po nazwie. Zaszyta
    // nazwa dziala dla jednego kafelka danego typu i MILCZY przy drugim —
    // a od 23.09.2026 typ moze wystapic kilka razy.
    var brakujace = [];
    kafelki().forEach(function (wezel) {
      if (!rysujKafelek(wezel, dane) && wezel.getAttribute('aria-busy') !== 'true') {
        brakujace.push(wezel);
      }
    });

    korzen.setAttribute('aria-busy', 'false');
    korzen.classList.add('an-gotowe');
    dociagnijBrakujace(brakujace);
  }

  // Kafelki, ktorych payload nie niosl: /api/analytics liczy uklad Z BAZY,
  // a w trybie edycji na ekranie bywaja kafelki dodane albo przestawione na
  // inny wymiar, ktorych w bazie jeszcze nie ma. Bez tego kroku po zmianie
  // okresu w trybie edycji zostawalyby z liczbami starego okresu. Kazdy
  // przychodzi osobno z /api/kafelek — tym samym zadaniem, co podglad.
  function dociagnijBrakujace(wezly) {
    wezly.forEach(function (wezel) {
      pobierzKafelek(wezel, wezel.getAttribute('data-typ'), wezel.getAttribute('data-wymiar'));
    });
  }

  function pokazBlad(komunikat) {
    var blok = document.getElementById('an-blad');
    if (blok) { tekstZCyframi(blok, komunikat); blok.hidden = false; }
    korzen.setAttribute('aria-busy', 'false');
  }

  function pokazSzkielet() {
    korzen.classList.remove('an-gotowe');
    korzen.setAttribute('aria-busy', 'true');
    var blok = document.getElementById('an-blad');
    if (blok) { blok.hidden = true; }
  }

  /* ---------- stan widoku ---------- */

  // Jedyne zrodlo prawdy o parametrach zadania. Inicjujemy go z tego, co SERWER
  // juz zwalidowal i wypisal w szablonie — NIGDY z window.location.search.
  //
  // Powod jest konkretny: trasa HTML po cichu cofa zly parametr do domyslnego
  // („nieaktualna zakladka ma pokazac dashboard, nie strone bledu"), ale adresu
  // nie zmienia. Przepisany doslownie adres ?kanal=payment_date poleciałby do
  // /api/analytics, ktore waliduje twardo i odpowiada 400 — uzytkownik dostalby
  // poprawnie wyrenderowany dashboard, a sekunde pozniej czerwony pasek
  // „HTTP 400" i szkielet, ktory nigdy sie nie wypelni.
  //
  // JUZ BEZ wymiarow kart. Wymiar kafelka jest czescia ZAPISANEGO ukladu, nie
  // adresu — przy trzech kafelkach kanalow parametr `?kanal=` nie ma jak byc
  // jednoznaczny. W adresie zostaja `od`, `do` i `porownanie`; stare adresy
  // z zakladek z `?kanal=` sa po cichu ignorowane (tak samo robi serwer).
  //
  // `wyklucz` — wykluczenia pozycji (partia E, punkty E4 i E8): odznaczone
  // wartosci pol wyboru (lista grup: filters.POLA_WYKLUCZEN, ten plik jej nie
  // zna) w formacie filtra. Tak jak okres i segment:
  // w ADRESIE, przezywa odswiezenie i daje sie udostepnic linkiem, a do
  // zapisanego ukladu NIE trafia (decyzja uzytkownika: zapisujemy wylacznie
  // uklad).
  var stan = { od: null, do: null, porownanie: '', wyklucz: '' };

  function odczytajStanZeStrony() {
    stan.od = korzen.getAttribute('data-od');
    stan.do = korzen.getAttribute('data-do');
    // Zwalidowany serwerowo filtr segmentu porownawczego (Zadanie 10) —
    // tak samo jak od/do, zrodlem jest atrybut wypisany przez trase HTML,
    // nigdy window.location.search wprost.
    stan.porownanie = korzen.getAttribute('data-porownanie') || '';
    stan.wyklucz = korzen.getAttribute('data-wyklucz') || '';
  }

  function parametryStanu() {
    var parametry = new URLSearchParams();
    parametry.set('od', stan.od);
    parametry.set('do', stan.do);
    // Parametr dokladany TYLKO gdy nie jest pusty — pusty 'porownanie' w adresie
    // byloby smieciem (Zadanie 10).
    if (stan.porownanie) { parametry.set('porownanie', stan.porownanie); }
    if (stan.wyklucz) { parametry.set('wyklucz', stan.wyklucz); }
    return parametry;
  }

  function adresDanych() {
    return korzen.getAttribute('data-url-analytics') + '?' + parametryStanu().toString();
  }

  /* ---------- sterowanie: zakres dat, segment i podglad wymiaru ---------- */

  // Presety liczone raz, w jednym miejscu. Rozsypane po handlerze warunki
  // byly w tym module zrodlem rozjazdu miedzy filtrem a naglowkiem.
  var PRESETY = {
    'biezacy-miesiac': function (dzis) {
      return [new Date(dzis.getFullYear(), dzis.getMonth(), 1), dzis];
    },
    'poprzedni-miesiac': function (dzis) {
      return [new Date(dzis.getFullYear(), dzis.getMonth() - 1, 1),
              new Date(dzis.getFullYear(), dzis.getMonth(), 0)];
    },
    'biezacy-kwartal': function (dzis) {
      return [new Date(dzis.getFullYear(), Math.floor(dzis.getMonth() / 3) * 3, 1), dzis];
    },
    'biezacy-rok': function (dzis) {
      return [new Date(dzis.getFullYear(), 0, 1), dzis];
    },
    // „Calosc" to trzy lata wstecz, czyli maksimum, ktore przepusci endpoint
    // (limit 1100 dni). Baza zaczyna sie w maju 2025, wiec to i tak wszystko.
    'calosc': function (dzis) {
      return [new Date(dzis.getFullYear() - 3, dzis.getMonth(), dzis.getDate()), dzis];
    }
  };

  function naISO(data) {
    var m = String(data.getMonth() + 1);
    var d = String(data.getDate());
    return data.getFullYear() + '-' + (m.length < 2 ? '0' + m : m) + '-' + (d.length < 2 ? '0' + d : d);
  }

  function ustawParametry(zmiany) {
    // Zmieniamy STAN, a potem z niego piszemy adres — nie odwrotnie. Dzieki
    // temu adres jest zawsze znormalizowany i zawsze zgodny z tym, co poleci
    // do /api/analytics (patrz komentarz przy deklaracji `stan`).
    Object.keys(zmiany).forEach(function (klucz) {
      if (klucz === 'od' || klucz === 'do') { stan[klucz] = zmiany[klucz]; }
      else if (klucz === 'porownanie') { stan.porownanie = zmiany[klucz]; }
      else if (klucz === 'wyklucz') { stan.wyklucz = zmiany[klucz]; }
    });
    // pushState, nie replaceState: cofniecie w przegladarce ma wrocic
    // do poprzedniego widoku, bo to jest osobny stan analizy.
    history.pushState({}, '', window.location.pathname + '?'
      + parametryStanu().toString());
    zaladuj();
  }

  function odczytajStanZAdresu() {
    // Po cofnieciu w przegladarce zrodlem jest adres — ale mu NIE UFAMY.
    // Data musi miec format RRRR-MM-DD; wartosc, ktorej nie znamy, zostawia
    // dotychczasowa, bo endpoint i tak by ja odrzucil kodem 400. Wymiarow
    // kart w adresie juz nie ma (patrz deklaracja `stan`), wiec nie ma czego
    // z nich odczytywac.
    var parametry = new URLSearchParams(window.location.search);
    ['od', 'do'].forEach(function (klucz) {
      var wartosc = parametry.get(klucz);
      if (wartosc && /^\d{4}-\d{2}-\d{2}$/.test(wartosc)) { stan[klucz] = wartosc; }
    });
    // 'porownanie' nie ma z czym porownac po stronie klienta (lista dozwolonych
    // wymiarow to nie to samo co poprawny filtr) — jesli jest zly, /api/analytics
    // i tak odda 400 i zaladuj() pokaze czerwony pasek bledu zamiast cichej straty.
    var segment = parametry.get('porownanie');
    if (segment !== null) { stan.porownanie = segment; }
    // Brak parametru to brak wykluczen — adres zapisuje go tylko wtedy, gdy
    // cos jest odznaczone (parametryStanu). Zly parametr odbije sie od
    // /api/analytics kodem 400 z komunikatem po polsku.
    var wyklucz = parametry.get('wyklucz');
    stan.wyklucz = wyklucz === null ? '' : wyklucz;
  }

  function podepnijSelektory() {
    // Delegacja na korzeniu, nie sluchacz na kazdym <select>: kafelki przychodza
    // i odchodza (podglad wymienia wezel, tryb edycji dodaje i usuwa), wiec
    // podpinanie sluchacza z osobna trzeba by powtarzac po kazdej zmianie.
    korzen.addEventListener('change', function (zdarzenie) {
      var wybor = zdarzenie.target;
      if (!wybor.hasAttribute || !wybor.hasAttribute('data-selektor')) { return; }
      // Widoczna etykieta jest osobnym elementem i nie zmienia sie sama —
      // bez tego kafelek pokazywalby nowe dane pod STARA nazwa wymiaru.
      ustawEtykieteSelektora(zdarzenie.target);
      var wezel = wybor.closest('[data-kafelek]');
      if (!wezel) { return; }

      // Straz: w trybie edycji wymiar zajety przez INNY kafelek tego typu
      // jest w selektorze wylaczony (odswiezZajeteWymiary), wiec tu nie
      // powinien dojsc. Gdyby jednak doszedl (np. przegladarka pozwolila
      // wybrac opcje z `disabled` klawiatura), selektor wraca na swoje
      // miejsce zamiast budowac duplikat, ktory odrzuci zapis.
      if (trybEdycji() && kafelki().some(function (inny) {
        return inny !== wezel && inny.getAttribute('data-typ') === wezel.getAttribute('data-typ')
          && wymiarKafelka(inny) === wybor.value;
      })) {
        ustawSelektor(wezel, wymiarKafelka(wezel));
        return;
      }

      // SELEKTOR POZA TRYBEM EDYCJI NIE ZAPISUJE NICZEGO. Rozstrzygniecie
      // uzytkownika, doslownie: „Chwilowe zerkniecie, po odswiezeniu wraca".
      // Trwaly wymiar kafelka ustawia sie przy dodawaniu go z modalu albo
      // w trybie edycji — i tam dolacza do paczki niezapisanych zmian.
      podgladWymiaru(wezel, wybor.value);
    });
  }

  /* ---------- podglad wymiaru: chwilowe zerkniecie, nie zapis ---------- */

  // Wymienia kafelek na wersje przyniesiona z serwera i rysuje go TA SAMA
  // funkcja, co przy pelnym ladowaniu strony. Znaczniki generuje Jinja —
  // budowanie ich tutaj byloby drugim zrodlem prawdy o wygladzie pulpitu.
  //
  // `html` z serwera to CZYSTY SZKIELET, zero danych: wszystkie wartosci
  // (w tym wolny tekst z BaseLinkera) wchodza dopiero w `rysujKafelek`,
  // przez textContent. Mimo to NIE przez innerHTML — DOMParser buduje
  // fragment w osobnym, bezczynnym dokumencie, a do strony trafia gotowy
  // wezel. Dzieki temu plik dalej nie ma ani jednego przypisania innerHTML.
  function wymienKafelek(wezel, html, dane) {
    // Kafelek usuniety w trybie edycji albo wymieciony razem z cala siatka
    // („Anuluj", „Przywroc domyslny") nie ma juz czego wymieniac — wezel moze
    // miec jeszcze rodzica, ale w odpietej, starej siatce.
    if (!korzen.contains(wezel)) { return null; }
    var zrodlo = new DOMParser().parseFromString(html, 'text/html');
    var nowy = zrodlo.querySelector('[data-kafelek]');
    if (!nowy) { return null; }
    nowy = document.importNode(nowy, true);
    // Zapisany wymiar NALEZY DO UKLADU, a nie do tego, co wlasnie przyszlo
    // z serwera — fragment renderuje sie z wymiaru, o ktory poprosilismy.
    // Bez tej linii „Wroc" po drugim podgladzie wracaloby do pierwszego
    // podgladu, a nie do ukladu.
    var zapisany = wezel.getAttribute('data-wymiar-zapisany');
    if (zapisany) { nowy.setAttribute('data-wymiar-zapisany', zapisany); }
    // Kafelek jeszcze niezapisany (dodany w trybie edycji) zostaje bez
    // zapisanego wymiaru, choc fragment z serwera go niesie — patrz W1.
    else { nowy.removeAttribute('data-wymiar-zapisany'); }
    // Stan trybu edycji nalezy do STRONY, nie do fragmentu.
    if (trybEdycji()) { ustawTrybKafelka(nowy, true); }
    var fokusWKafelku = wezel.contains(document.activeElement);
    zniszczWykresyW(wezel);
    if (wezel.querySelector('[data-mapa]')) { schowajDymek(); }
    wezel.parentNode.replaceChild(nowy, wezel);
    ujednolicIdentyfikatory(nowy);
    rysujKafelek(nowy, dane);
    // Swiezy selektor ma wszystkie opcje wlaczone — w trybie edycji wymiary
    // zajete przez inne kafelki tego typu trzeba wylaczyc na nowo.
    if (trybEdycji()) { oznaczZmiane(); }
    // Klawiatura nie moze zgubic miejsca: fokus byl na selektorze (albo na
    // „Wroc") starego wezla, ktorego juz nie ma — wraca na selektor nowego.
    var selektor = nowy.querySelector('[data-selektor]');
    if (fokusWKafelku && selektor) { selektor.focus(); }
    return nowy;
  }

  // Podglad potrafi chwilowo postawic na stronie dwa kafelki o tym samym
  // kluczu (np. drugi kafelek wojewodztw przelaczony na wymiar pierwszego),
  // a klucz jest prefiksem `id` kanwy i sciezek mapy. Zdublowane `id` w tym
  // wstawionym dostaja przyrostek — JS nie szuka niczego po `id` (kanwa po
  // kafelku, mapa po `data-obszar`), wiec przyrostek niczego nie psuje.
  var licznikIdentyfikatorow = 0;
  function ujednolicIdentyfikatory(nowy) {
    Array.prototype.forEach.call(nowy.querySelectorAll('[id]'), function (wezel) {
      if (document.querySelectorAll('[id="' + wezel.id + '"]').length > 1) {
        licznikIdentyfikatorow += 1;
        wezel.id = wezel.id + '-podglad' + licznikIdentyfikatorow;
      }
    });
  }

  function adresKafelka(typ, wymiar) {
    var parametry = new URLSearchParams();
    parametry.set('typ', typ);
    if (wymiar) { parametry.set('wymiar', wymiar); }
    parametry.set('od', stan.od);
    parametry.set('do', stan.do);
    if (stan.porownanie) { parametry.set('porownanie', stan.porownanie); }
    if (stan.wyklucz) { parametry.set('wyklucz', stan.wyklucz); }
    return korzen.getAttribute('data-url-kafelek') + '?' + parametry.toString();
  }

  // Ustawia selektor „wedlug" kafelka na podany wymiar razem z widoczna
  // etykieta (ta jest osobnym elementem i sama sie nie zmienia).
  function ustawSelektor(wezel, wymiar) {
    var wybor = wezel.querySelector('[data-selektor]');
    if (!wybor || !wymiar) { return; }
    wybor.value = wymiar;
    ustawEtykieteSelektora(wybor);
  }

  // Selektor stoi juz na nowym wyborze, a kafelek nie przyszedl — selektor
  // wraca do wymiaru, ktory kafelek NAPRAWDE pokazuje. Inaczej etykieta
  // mowilaby jedno, a liczby pod nia drugie.
  function przywrocSelektor(wezel) {
    ustawSelektor(wezel, wezel.getAttribute('data-wymiar'));
  }

  // Przy starcie selektor ma stac na wymiarze, ktory kafelek NAPRAWDE
  // pokazuje. Firefox po F5 przywraca wartosc <select> z poprzedniej wizyty
  // (autocomplete="off" w szablonie to wylacza, ale nie kazda przegladarka
  // honoruje go na <select>) — po podgladzie i odswiezeniu selektor stalby na
  // przekroju podgladanym, a kafelek pokazywalby zapisany.
  function zrownajSelektory() {
    kafelki().forEach(przywrocSelektor);
  }

  // Koniec zadania kafelka — udanego albo przerwanego.
  function zakonczZadanie(wezel) {
    wezel.removeAttribute('aria-busy');
    wezel.wymiarWLocie = null;
  }

  // Pobiera jeden kafelek i wymienia go w miejscu. Zwraca obietnice z nowym
  // wezlem (albo null) — dodawanie i anulowanie w trybie edycji buduja na niej.
  //
  // `numerZadania` na wezle: dwa szybkie wybory w tym samym kafelku to dwa
  // zadania, a odpowiedz na PIERWSZE moze przyjsc po drugim wyborze. Wygrywa
  // wtedy ostatni wybor — spozniona odpowiedz jest pomijana. Ten sam licznik
  // podbija `uniewaznijZadaniaKafelkow` przy zmianie okresu i segmentu.
  //
  // `stanZadania`: okres i segment Z CHWILI ZADANIA. Odpowiedz, ktora
  // przyjdzie po zmianie okresu, niesie liczby STAREGO okresu — wstawiona
  // pokazalaby je pod naglowkiem nowego. Druga linia obrony obok licznika:
  // gdyby kiedys ktos zmienil stan bez przejscia przez zaladuj(), spozniona
  // odpowiedz i tak nie wejdzie na ekran.
  function pobierzKafelek(wezel, typ, wymiar) {
    var numer = (wezel.numerZadania || 0) + 1;
    var stanZadania = parametryStanu().toString();
    wezel.numerZadania = numer;
    wezel.wymiarWLocie = wymiar || null;
    wezel.setAttribute('aria-busy', 'true');
    // Miejsce po nieudanym wczytaniu (blad + „Wczytaj ponownie") wraca do
    // napisu „Wczytywanie…" na czas nowego zadania.
    if (wezel.classList.contains('an-kafelek--wczytywanie')) { pokazWczytywanieMiejsca(wezel); }
    return sledzZadanie(fetch(adresKafelka(typ, wymiar), {
      credentials: 'same-origin', headers: { 'Accept': 'application/json' }
    }).then(odpowiedzJson).then(function (tresc) {
      if (wezel.numerZadania !== numer) { return null; }
      if (parametryStanu().toString() !== stanZadania) {
        zakonczZadanie(wezel);
        przywrocSelektor(wezel);
        return null;
      }
      return wymienKafelek(wezel, tresc.html, tresc.dane);
    }).catch(function (blad) {
      if (wezel.numerZadania !== numer) { return null; }
      zakonczZadanie(wezel);
      // Zapis czekajacy na ten kafelek musi wiedziec, ze kafelek padl
      // (patrz `bledyKafelkow`).
      bledyKafelkow += 1;
      if (wezel.classList.contains('an-kafelek--wczytywanie')) {
        // Dodawany kafelek nie przyszedl — nie zostawiamy w siatce pustego
        // pudelka z napisem „Wczytywanie…" (paczka zmian wraca do stanu
        // sprzed dodania). Kafelek nie znika jednak PO CICHU: komunikat
        // mowi, ktory i dlaczego (przeglad galezi, W3).
        if (wezel.parentNode) { wezel.parentNode.removeChild(wezel); }
        oznaczZmiane();
        odswiezStanPusty();
        var poczatek = 'Nie udało się dodać kafelka „' + nazwaTypu(typ) + '": ';
        pokazBladPaska(blad.status === 401
          ? poczatek + 'sesja wygasła. Zaloguj się ponownie w innej karcie przeglądarki '
            + 'i dodaj go jeszcze raz.'
          : zdanieBledu(poczatek, blad, 'Spróbuj dodać go jeszcze raz.'));
      } else {
        przywrocSelektor(wezel);
        pokazBladPaska(zdanieBledu('Nie udało się wczytać kafelka: ', blad,
          'Spróbuj ponownie za chwilę.'));
      }
      return null;
    }));
  }

  // Uniewaznia WSZYSTKIE zadania kafelkow w locie. Wolane z zaladuj() przed
  // czymkolwiek innym, bo zmiana okresu, segmentu albo cofniecie
  // w przegladarce robi z kazdej odpowiedzi w locie odpowiedz dla STAREGO
  // stanu. Przebieg, ktory to naprawia: podglad B w locie z okresem P1 ->
  // uzytkownik zmienia okres na P2 -> zaladuj() pomijal kafelek (jego
  // `data-wymiar` byl jeszcze zapisany) -> spozniona odpowiedz P1 wymieniala
  // kafelek -> liczby z P1 pod naglowkiem P2.
  //
  // Po uniewaznieniu kafelek zostaje w wymiarze, ktory NAPRAWDE pokazuje,
  // i dorysowuje go wypelnij() z nowego payloadu. Selektor wraca do
  // wymiaru zapisanego — to jest wymiar, w ktorym kafelek skonczy. W trybie
  // edycji wraca do wymiaru, ktory kafelek pokazuje: zmiana w locie przepada
  // (zmiana okresu w tym samym ulamku sekundy), a selektor nie moze udawac,
  // ze jest inaczej.
  function uniewaznijZadaniaKafelkow() {
    kafelki().forEach(function (wezel) {
      if (wezel.getAttribute('aria-busy') !== 'true') { return; }
      wezel.numerZadania = (wezel.numerZadania || 0) + 1;
      zakonczZadanie(wezel);
      ustawSelektor(wezel, trybEdycji() ? wezel.getAttribute('data-wymiar')
                                        : wezel.getAttribute('data-wymiar-zapisany'));
    });
    // Zmiana w locie przestala byc w drodze — licznik i blokada zajetych
    // wymiarow licza sie od nowa (poza trybem edycji to nic nie robi).
    oznaczZmiane();
  }

  function etykietaWymiaru(wezel, nazwa) {
    // Etykieta pochodzi z <option> W TYM kafelku, bo karty kubelkowe maja
    // wlasna, wezsza liste (i pseudo-wymiar spoza rejestru pol).
    var opcja = wezel.querySelector('[data-selektor] option[value="' + nazwa + '"]');
    return opcja ? opcja.textContent : nazwa;
  }

  function odswiezPlakietke(wezel) {
    var plakietka = wezel.querySelector('[data-plakietka]');
    if (!plakietka) { return; }
    var zapisany = wezel.getAttribute('data-wymiar-zapisany');
    var biezacy = wezel.getAttribute('data-wymiar');
    czysc(plakietka);
    // W trybie edycji ten sam selektor ustawia TRWALY wymiar (Zadanie 10),
    // wiec zdanie „po odswiezeniu wroci" byloby tam nieprawda.
    if (trybEdycji() || !zapisany || zapisany === biezacy) {
      plakietka.hidden = true;
      return;
    }
    var etykieta = etykietaWymiaru(wezel, zapisany);
    // Podglad wraca do zapisanego wymiaru takze przy zmianie okresu albo
    // porownania (przywrocPodgladane) — zdanie „po odswiezeniu wroci" samo
    // w sobie klamalo (przeglad galezi, drobne 3).
    plakietka.appendChild(el('span', '',
      'podgląd — wróci „' + etykieta + '" po odświeżeniu lub zmianie okresu albo porównania'));
    var wroc = el('button', '', 'Wróć');
    wroc.type = 'button';
    wroc.setAttribute('data-wroc-do-zapisanego', '');
    wroc.setAttribute('aria-label', 'Wróć do zapisanego wymiaru: ' + etykieta);
    plakietka.appendChild(wroc);
    plakietka.hidden = false;
  }

  // Selektor „wedlug" poza trybem edycji: pokazuje inny przekrój OD RAZU,
  // wymieniajac jeden kafelek, i NICZEGO nie zapisuje. Rozstrzygniecie
  // uzytkownika: „Chwilowe zerkniecie, po odswiezeniu wraca".
  //
  // W TRYBIE EDYCJI ten sam selektor ustawia TRWALY wymiar (rozstrzygniecie
  // R5 planu): plakietka sie nie pojawia, a paczka robi sie brudna JUZ
  // W CHWILI WYBORU, nie po odpowiedzi — inaczej przez ulamek sekundy drugi
  // kafelek tego typu moglby wybrac ten sam wymiar, a „Zapisz uklad"
  // wyslalby stary.
  function podgladWymiaru(wezel, wymiar) {
    var typ = wezel.getAttribute('data-typ');
    var obietnica = pobierzKafelek(wezel, typ, wymiar);
    if (trybEdycji()) { oznaczZmiane(); }
    return obietnica.then(function (nowy) {
      if (trybEdycji()) { oznaczZmiane(); return nowy; }
      if (!nowy) { return null; }
      odswiezPlakietke(nowy);
      return nowy;
    });
  }

  // Kafelki w podgladzie przy KAZDYM przeladowaniu danych (zmiana okresu,
  // segmentu, cofniecie w przegladarce) wracaja do zapisanego wymiaru:
  // /api/analytics czyta uklad z bazy i nie ma czym narysowac przekroju
  // podgladanego — kafelek zostalby ze starymi liczbami pod nowym okresem,
  // a plakietka klamalaby dalej.
  //
  // W trybie edycji zmieniony wymiar to NIEZAPISANA ZMIANA, a nie podglad —
  // zostaje. Jesli payload go nie niesie (nie ma go w ukladzie z bazy),
  // kafelek dociaga osobno wypelnij() (patrz dociagnijBrakujace).
  function przywrocPodgladane() {
    if (trybEdycji()) { return; }
    kafelki().forEach(function (wezel) {
      var zapisany = wezel.getAttribute('data-wymiar-zapisany');
      var biezacy = wezel.getAttribute('data-wymiar');
      if (!zapisany || zapisany === biezacy) { return; }
      podgladWymiaru(wezel, zapisany);
    });
  }

  // „Wroc" w plakietce. Delegacja, bo plakietka powstaje i znika razem
  // z kafelkiem.
  korzen.addEventListener('click', function (zdarzenie) {
    var wroc = zdarzenie.target.closest
      ? zdarzenie.target.closest('[data-wroc-do-zapisanego]') : null;
    if (!wroc) { return; }
    var wezel = wroc.closest('[data-kafelek]');
    if (wezel) { podgladWymiaru(wezel, wezel.getAttribute('data-wymiar-zapisany')); }
  });

  // Selektor podzialu lejka NIE jest selektorem wymiaru karty: nie jedzie do
  // adresu i nie odpytuje serwera, bo wszystkie podzialy przyszly policzone
  // w tym samym payloadzie.
  //
  // Delegacja na korzeniu z tego samego powodu co przy selektorach wymiaru:
  // kafelek lejka da sie usunac i dodac z powrotem, a sluchacz przypiety do
  // starego <select> znikalby razem z nim.
  function podepnijSelektorLejka() {
    korzen.addEventListener('change', function (zdarzenie) {
      var wybor = zdarzenie.target;
      if (!wybor.hasAttribute || !wybor.hasAttribute('data-selektor-lejka')) { return; }
      podzialLejka = wybor.value;
      ustawEtykieteSelektora(wybor);
      if (ostatnieDane) { rysujPodzialLejka(ostatnieDane); }
    });
  }

  function opiszFiltr(wybrane, etykietyWartosci) {
    // Podglad ma mowic tym samym jezykiem, co chip po „Zastosuj": filtr.js
    // wklada do `wybrane` wartosc surowa, wiec etykiety bierzemy z mapy,
    // ktora popover zapamietal z /api/wartosci-wymiaru.
    var etykiety = {};
    wymiaryFiltra().forEach(function (w) { etykiety[w.nazwa] = w.etykieta; });
    var wartosci = etykietyWartosci || {};
    return Object.keys(wybrane).sort().map(function (nazwa) {
      var mapa = wartosci[nazwa] || {};
      var opisane = wybrane[nazwa].map(function (w) { return mapa[w] || w; });
      return (etykiety[nazwa] || nazwa) + ': ' + opisane.join(', ');
    }).join(' · ') || 'brak warunków';
  }

  function wymiaryFiltra() {
    // Lista wymiarow prostych przychodzi z serwera atrybutem data-, nie
    // globalna zmienna: jedno zrodlo (rejestr pol) i zero skryptu inline.
    try {
      return JSON.parse(korzen.getAttribute('data-wymiary-filtra') || '[]');
    } catch (blad) { return []; }
  }

  function podepnijSegmenty() {
    var przycisk = document.getElementById('an-dodaj-porownanie');
    if (!przycisk || !window.FiltrWymiaru) { return; }
    przycisk.addEventListener('click', function () {
      window.FiltrWymiaru.otworz({
        kotwica: przycisk,
        filtr: stan.porownanie || '',
        wymiary: wymiaryFiltra(),
        urlWartosci: korzen.getAttribute('data-url-wartosci'),
        od: stan.od, do: stan.do,
        // Lista wartosci liczy sie z tymi samymi wykluczeniami co pulpit.
        wyklucz: stan.wyklucz,
        opisz: opiszFiltr,
        przyPotwierdzeniu: function (tekst) { ustawParametry({ porownanie: tekst }); }
      });
    });
  }

  // Chipy segmentow: bazowy jest juz w szablonie, tutaj dokladamy ewentualny
  // drugi. Rysujemy je od nowa przy kazdym wypelnieniu — prostsze niz
  // roznicowe aktualizacje, a chipow jest najwyzej dwa.
  function rysujSegmenty(dane) {
    var gniazdo = document.getElementById('an-segmenty');
    var przyciskDodaj = document.getElementById('an-dodaj-porownanie');
    if (!gniazdo) { return; }
    czysc(gniazdo);
    dane.segmenty.forEach(function (segment, i) {
      // Pigulka bazowa przy aktywnych wykluczeniach („Bez: buk, B/B") ma
      // akcent marki — ani blad (czerwien), ani niezapisana zmiana (bursztyn).
      var klasa = i === 0
        ? (segment.wykluczenia ? 'an-chip an-chip--wykluczenia' : 'an-chip')
        : 'an-chip an-chip--porownanie';
      var chip = el('span', klasa);
      var kropka = el('span', 'an-chip__kropka');
      // Kropka pigulki wykluczen jest BIALA z CSS (`.an-chip--wykluczenia
      // .an-chip__kropka`): pomaranczowa zlalaby sie z tlem akcentu. Styl
      // inline wygrywa z arkuszem, wiec tej jednej kropce koloru nie dajemy
      // (weryfikacja E8, D2 — kolor przeskakiwal po wczytaniu danych).
      if (!(i === 0 && segment.wykluczenia)) { kropka.style.background = segment.kolor; }
      chip.appendChild(kropka);
      chip.appendChild(document.createTextNode(segment.nazwa));
      if (i > 0) {
        var zamknij = el('button', 'an-chip__zamknij', '×');
        zamknij.type = 'button';
        zamknij.setAttribute('aria-label', 'Usuń porównanie: ' + segment.nazwa);
        zamknij.addEventListener('click', function () { ustawParametry({ porownanie: '' }); });
        chip.appendChild(zamknij);
      }
      gniazdo.appendChild(chip);
    });
    // Maksymalnie jeden segment porownawczy (decyzja uzytkownika 21.09.2026) —
    // przycisk wraca dopiero po usunieciu chipa.
    if (przyciskDodaj) { przyciskDodaj.hidden = dane.segmenty.length > 1; }
  }

  /* ---------- pola wykluczen (partia E, punkt E4) ---------- */

  // Ile czekamy po kliknieciu pola, zanim poleci zadanie. Szybkie klikniecie
  // trzech pol ma dac JEDNO zadanie, nie trzy.
  var OPOZNIENIE_WYKLUCZEN = 250;
  var czasWykluczen = null;

  function grupyWykluczen() {
    return Array.prototype.slice.call(document.querySelectorAll('[data-pole-wykluczen]'));
  }

  function polaGrupy(grupa) {
    return Array.prototype.slice.call(grupa.querySelectorAll('input[type="checkbox"]'));
  }

  // Podstawa lewej czesci paska = szerokosc NAJSZERSZEJ grupy wykluczen
  // w jednej linii (porzadki koncowe, punkt 3d; uzasadnienie w analiza.css
  // przy .an-pasek__lewy). CSS tej szerokosci nie zna: zalezy od fontu i od
  // wartosci z danych. Mierzymy kazda grupe bez scisniecia — klasa pomiaru
  // z arkusza, nie styl inline (styl inline `flex` jest tu zakazany, patrz
  // test kolumny liczb) — i od razu ja zdejmujemy. To pomiar ukladu, nie
  // liczba do pokazania.
  function ustawPodstaweWykluczen() {
    var lewy = document.querySelector('.an-pasek__lewy');
    var grupy = grupyWykluczen();
    if (!lewy || !grupy.length) { return; }
    var najszersza = 0;
    grupy.forEach(function (grupa) {
      grupa.classList.add('an-wyk-grupa--pomiar');
      najszersza = Math.max(najszersza, grupa.getBoundingClientRect().width);
      grupa.classList.remove('an-wyk-grupa--pomiar');
    });
    lewy.style.setProperty('--an-najszersza-grupa', Math.ceil(najszersza) + 'px');
  }

  // Ostatnie zaznaczone pole grupy jest zablokowane: odznaczone dalo by pulpit
  // z samymi zerami. To stan KONTROLKI, nie liczba z danych — serwer i tak
  // odrzuca adres, ktory probuje to obejsc (400). Tresc podpowiedzi stoi
  // w szablonie (#an-wyk-podpowiedz), tu tylko ja podpinamy.
  function odswiezBlokadyWykluczen() {
    var podpowiedz = document.getElementById('an-wyk-podpowiedz');
    var tekst = podpowiedz ? podpowiedz.textContent : '';
    grupyWykluczen().forEach(function (grupa) {
      var pola = polaGrupy(grupa);
      var zaznaczone = pola.filter(function (p) { return p.checked; });
      pola.forEach(function (p) {
        var zablokowane = zaznaczone.length === 1 && p.checked;
        p.disabled = zablokowane;
        var etykieta = p.closest('label');
        if (zablokowane) {
          p.setAttribute('aria-describedby', 'an-wyk-podpowiedz');
          if (etykieta) { etykieta.title = tekst; }
        } else {
          p.removeAttribute('aria-describedby');
          if (etykieta) { etykieta.removeAttribute('title'); }
        }
      });
    });
  }

  // Parametr adresu z pol. Wartosci sa JUZ ZAKODOWANE przez serwer
  // (`data-czlon`, ten sam kod co filters.zapisz_filtr) — tu tylko je
  // sklejamy. Pola w kolejnosci alfabetycznej, tak jak zapisz_filtr, zeby
  // ten sam stan dawal zawsze ten sam adres.
  function tekstWykluczen() {
    return grupyWykluczen().map(function (grupa) {
      var odznaczone = polaGrupy(grupa).filter(function (p) { return !p.checked; })
        .map(function (p) { return p.getAttribute('data-czlon'); });
      return odznaczone.length
        ? grupa.getAttribute('data-pole-wykluczen') + ':' + odznaczone.join('|') : '';
    }).filter(function (czlon) { return czlon; }).sort().join(',');
  }

  // Pola wedlug stanu Z SERWERA — po cofnieciu w przegladarce albo po
  // odpowiedzi na adres, ktory nie zgadzal sie z ekranem. Pomijane, gdy
  // uzytkownik klika wlasnie dalej (czeka opoznienie): jego nowsze klikniecia
  // wygrywaja, a ich zadanie i tak zaraz poleci.
  function rysujWykluczenia(wykluczenia) {
    var zdanie = document.getElementById('an-wykluczenia-zdanie');
    if (zdanie) {
      zdanie.textContent = (wykluczenia && wykluczenia.zdanie) || '';
      zdanie.hidden = !(wykluczenia && wykluczenia.zdanie);
    }
    if (!wykluczenia || czasWykluczen !== null) { return; }
    var wykluczone = wykluczenia.wykluczone || {};
    grupyWykluczen().forEach(function (grupa) {
      var odznaczone = wykluczone[grupa.getAttribute('data-pole-wykluczen')] || [];
      polaGrupy(grupa).forEach(function (p) {
        p.checked = odznaczone.indexOf(p.value) === -1;
      });
    });
    odswiezBlokadyWykluczen();
  }

  function podepnijWykluczenia() {
    var blok = document.getElementById('an-wykluczenia');
    if (!blok) { return; }
    blok.addEventListener('change', function (zdarzenie) {
      if (!zdarzenie.target || zdarzenie.target.type !== 'checkbox') { return; }
      odswiezBlokadyWykluczen();
      if (czasWykluczen !== null) { window.clearTimeout(czasWykluczen); }
      czasWykluczen = window.setTimeout(function () {
        czasWykluczen = null;
        var tekst = tekstWykluczen();
        if (tekst === stan.wyklucz) { return; }
        // Dane przeladowuja sie BEZ przeladowania strony — tak samo jak przy
        // zmianie okresu. Podglady wymiaru wracaja do zapisanego (zaladuj ->
        // przywrocPodgladane), a paczka zmian trybu edycji zostaje.
        ustawParametry({ wyklucz: tekst });
      }, OPOZNIENIE_WYKLUCZEN);
    });
  }

  function podepnijZakres() {
    var przycisk = document.getElementById('an-zakres');
    var menu = document.getElementById('an-zakres-menu');
    if (!przycisk || !menu) { return; }

    function przelacz(pokaz) {
      menu.hidden = !pokaz;
      przycisk.setAttribute('aria-expanded', pokaz ? 'true' : 'false');
    }

    przycisk.addEventListener('click', function () { przelacz(menu.hidden); });
    document.addEventListener('click', function (zdarzenie) {
      if (!menu.hidden && !menu.contains(zdarzenie.target) && zdarzenie.target !== przycisk
          && !przycisk.contains(zdarzenie.target)) { przelacz(false); }
    });
    document.addEventListener('keydown', function (zdarzenie) {
      if (zdarzenie.key === 'Escape' && !menu.hidden) { przelacz(false); przycisk.focus(); }
    });

    var presety = menu.querySelectorAll('[data-preset]');
    for (var i = 0; i < presety.length; i++) {
      presety[i].addEventListener('click', function (zdarzenie) {
        var zakres = PRESETY[zdarzenie.target.getAttribute('data-preset')](new Date());
        przelacz(false);
        ustawParametry({ od: naISO(zakres[0]), do: naISO(zakres[1]) });
      });
    }

    var zastosuj = document.getElementById('an-zakres-zastosuj');
    if (zastosuj) {
      zastosuj.addEventListener('click', function () {
        var od = document.getElementById('an-zakres-od').value;
        var do_ = document.getElementById('an-zakres-do').value;
        if (!od || !do_) { return; }
        przelacz(false);
        ustawParametry({ od: od, do: do_ });
      });
    }
  }

  window.addEventListener('popstate', function () {
    odczytajStanZAdresu();
    zaladuj();
  });

  // Numer ostatniego zadania o dane pulpitu. Szybkie klikanie pol wykluczen
  // albo presetow okresu daje kilka zadan w locie, a odpowiedzi przychodza
  // w dowolnej kolejnosci — SPOZNIONA odpowiedz nie moze nadpisac nowszej
  // (ten sam wzorzec, co `numerZadania` kafelka).
  var numerLadowania = 0;

  function zaladuj() {
    numerLadowania += 1;
    var numer = numerLadowania;
    pokazSzkielet();
    // NAJPIERW uniewaznienie zadan w locie, dopiero potem powrot podgladow —
    // inaczej spozniona odpowiedz dla starego okresu wymienilaby kafelek juz
    // po narysowaniu nowego payloadu (patrz uniewaznijZadaniaKafelkow).
    uniewaznijZadaniaKafelkow();
    przywrocPodgladane();
    return fetch(adresDanych(), { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
      .then(function (odp) {
        if (numer !== numerLadowania) { return null; }
        // 401 to wygasla sesja — mowimy to wprost, zamiast kazac zawezac okres.
        if (odp.status === 401) { throw new Error('SESJA'); }
        // 400 z tego modulu niesie komunikat po polsku (np. zly parametr
        // wykluczen w adresie po cofnieciu w przegladarce) — ma dojsc do
        // uzytkownika zamiast golego „HTTP 400".
        if (odp.status === 400) {
          return odp.json().then(function (tresc) {
            throw new Error((tresc && tresc.komunikat) || 'HTTP 400');
          }, function () { throw new Error('HTTP 400'); });
        }
        if (!odp.ok) { throw new Error('HTTP ' + odp.status); }
        return odp.json();
      })
      .then(function (dane) {
        if (!dane || numer !== numerLadowania) { return; }
        wypelnij(dane);
      })
      .catch(function (blad) {
        if (numer !== numerLadowania) { return; }
        // Miejsce na dodawany kafelek, ktorego zadanie uniewaznila zmiana
        // okresu, czekalo na wypelnij() — a ta po awarii nie przyjdzie.
        // Zamiast wiecznego „Wczytywanie…" (przeglad galezi, drobne 4):
        // blad w kafelku i przycisk ponowienia.
        kafelki().forEach(function (wezel) {
          if (wezel.classList.contains('an-kafelek--wczytywanie')
              && wezel.getAttribute('aria-busy') !== 'true') {
            pokazBladMiejsca(wezel);
          }
        });
        // Czerwien jest zarezerwowana dla bledow — i to jest wlasnie blad.
        pokazBlad(blad.message === 'SESJA'
          ? 'Sesja wygasła. Zaloguj się ponownie, żeby zobaczyć dane.'
          : 'Nie udało się pobrać danych analizy. Odśwież stronę lub '
            + 'zawęź okres. Szczegóły: ' + blad.message);
      });
  }

  // Udostepniamy na potrzeby selektorow wymiaru (Zadanie 8) i chipa segmentu
  // (Zadanie 10).
  window.AnalizaSprzedazowa = {
    zaladuj: zaladuj, stan: stan, parametryStanu: parametryStanu,
    odczytajStanZeStrony: odczytajStanZeStrony
  };

  document.addEventListener('DOMContentLoaded', function () {
    odczytajStanZeStrony();
    // Adres w pasku ma przestac klamac. Jesli przyszedl z nieaktualnej zakladki
    // ze zlym parametrem, serwer juz go poprawil w szablonie — zapisujemy
    // poprawiona wersje. replaceState, nie pushState: to nie jest nowy stan
    // widoku, wiec przycisk Wstecz ma dzialac tak samo jak przedtem.
    history.replaceState({}, '', window.location.pathname + '?'
      + parametryStanu().toString());
    zrownajSelektory();
    podepnijSelektory();
    podepnijPrzelaczniki();
    podepnijEdycje();
    podepnijModal();
    // Przed podepnijZakres: Escape przy otwartym menu zakresu dat ma zamknac
    // menu, a nie tryb edycji — sluchacz trybu musi je zobaczyc otwarte.
    podepnijZapisUkladu();
    odswiezStanPusty();
    podepnijSelektorLejka();
    podepnijZakres();
    podepnijSegmenty();
    podepnijWykluczenia();
    // Pomiar grup wykluczen teraz i jeszcze raz po zaladowaniu fontow: IBM
    // Plex przychodzi z pliku i do tego czasu napisy maja szerokosc zastepczego.
    ustawPodstaweWykluczen();
    if (document.fonts && document.fonts.ready) {
      document.fonts.ready.then(ustawPodstaweWykluczen);
    }
    // Dymek mapy podpinamy RAZ, delegacja na korzeniu — nie do szesnastu
    // ksztaltow osobno ani do jednego bloku mapy. Kafelek wojewodztw bywa
    // wymieniany w miejscu (podglad wymiaru), a delegacja nie wymaga
    // podpinania niczego na nowo po takiej wymianie.
    podepnijMape();
    podepnijDymekWykresu();
    podepnijPomiarRozwinietych();
    zaladuj();
  });
}());
