/* Arkusz wewnętrzny Analizy sprzedażowej — siatka, przewijanie, nawigacja.
 *
 * ŻADNA WARTOŚĆ BIZNESOWA NIE JEST TU LICZONA ANI FORMATOWANA. Kwoty,
 * objętości, daty i sumy przychodzą z /reports/api/arkusz/dane jako gotowy
 * tekst. Jedyne liczby, które ten plik wylicza, są w PIKSELACH i służą
 * układowi: zastępcza wysokość bloku zamówienia przy wirtualizacji oraz
 * przesunięcie drugiej zamrożonej kolumny. Serwer ich nie zna, bo zależą
 * od CSS-a.
 *
 * WIRTUALIZACJA: jedno <tbody> na zamówienie plus content-visibility: auto
 * w arkusz.css. Przeglądarka pomija układ i rysowanie dla zamówień poza
 * ekranem, a rowspan zostaje nietknięty.
 */
(function () {
  'use strict';

  var korzen = document.getElementById('arkusz');
  if (!korzen) { return; }

  /* Wysokość wiersza z makiety. Musi się zgadzać z .ark-tabela td { height }
     w arkusz.css — służy wyłącznie do zastępczej wysokości bloku, więc
     rozjazd o piksel objawia się drgnięciem paska przewijania, nie błędem. */
  var WYSOKOSC_WIERSZA = 29;
  var OPOZNIENIE_SZUKANIA = 300;
  var MARGINES_DOCZYTANIA = 600;

  var siatka = document.getElementById('ark-siatka');
  var glowa = document.getElementById('ark-glowa');
  var cialo = document.getElementById('ark-cialo');
  var poleSzukania = document.getElementById('ark-szukaj');

  var stan = {
    okno: JSON.parse(korzen.dataset.okno || '{}'),
    kolumnyWszystkie: JSON.parse(korzen.dataset.kolumnyWszystkie || '[]'),
    kolumnyWybrane: (korzen.dataset.kolumnyWybrane || '').split(',').filter(Boolean),
    mozeWysylac: korzen.dataset.mozeWysylac === 'true',
    szukaj: '',
    filtr: '',
    kolumny: [],
    zamowienia: [],
    stronicowanie: null,
    doczytywanie: false
  };

  var opisyKolumn = {};

  function opisKolumny(nazwa) { return opisyKolumn[nazwa] || null; }

  /* Klucz zmiany. TEN SAM FORMAT produkuje serwis zapisu na serwerze
     (modules/reports/arkusz_zapis.py) i po nim odnajdujemy komórkę, gdy
     wraca wynik wysyłki. Rozjazd tutaj oznacza „zapisano" nad komórką,
     której nikt nie zapisał. */
  function klucz(poziom, id, nazwa) {
    return poziom + ':' + id + ':' + nazwa;
  }

  function komorkaPoKluczu(wartoscKlucza) {
    return cialo.querySelector('[data-klucz="' + wartoscKlucza + '"]');
  }

  /* Wstawia TEKST do elementu, owijajac KAZDY ciag cyfr w <span class="m">
     — reszta zostaje w zwyklych wezlach tekstowych (dziedzicza IBM Plex
     Sans po .ark-narzedziownik/.ark-kontekst). Licznik zmian
     (#ark-licznik-zmian) i pasek kontekstowy (#ark-kontekst) buduja gotowe
     zdania jako zwykle stringi ("4 zmienione komórki w 2 zamówieniach" —
     odmiana() dokleja slowo do liczby), wiec cyfry ladowaly sie w Sans, nie
     w Mono. Makieta ArkuszZmiany.dc.html tez nie daje tam klasy monospace
     (formalnie bylby to zgodny render), ALE wiazaca zasada projektu „IBM
     Plex Mono na KAZDA cyfre" jest nadrzedna i spojna z reszta arkusza —
     patrz `.ark .m` w arkusz.css, ktora dziala dla kazdej komorki siatki.
     Zmierzone przez getComputedStyle. */
  function ustawTekstZCyframi(element, tekst) {
    while (element.firstChild) { element.removeChild(element.firstChild); }
    String(tekst).split(/(\d+)/).forEach(function (czesc) {
      if (!czesc) { return; }
      if (/^\d+$/.test(czesc)) {
        var cyfry = document.createElement('span');
        cyfry.className = 'm';
        cyfry.textContent = czesc;
        element.appendChild(cyfry);
      } else {
        element.appendChild(document.createTextNode(czesc));
      }
    });
  }

  function pokazBlad(tekst) {
    var pasek = document.getElementById('ark-kontekst');
    ustawTekstZCyframi(pasek, tekst);
    pasek.classList.add('ark-kontekst--blad');
    pasek.hidden = false;
  }

  function schowajBlad() {
    var pasek = document.getElementById('ark-kontekst');
    if (pasek.classList.contains('ark-kontekst--blad')) {
      pasek.classList.remove('ark-kontekst--blad');
      pasek.hidden = true;
      pasek.textContent = '';
    }
  }

  /* ===== ADRES ========================================================= */

  function parametry(offset) {
    var szukane = new URLSearchParams();
    if (stan.okno.preset && stan.okno.preset !== 'wlasne') {
      szukane.set('okno', stan.okno.preset);
    } else {
      szukane.set('od', stan.okno.od);
      szukane.set('do', stan.okno.do);
    }
    if (stan.szukaj) { szukane.set('szukaj', stan.szukaj); }
    if (stan.filtr) { szukane.set('filtr', stan.filtr); }
    if (stan.kolumnyWybrane.length) {
      szukane.set('kolumny', stan.kolumnyWybrane.join(','));
    }
    if (offset) { szukane.set('offset', String(offset)); }
    return szukane;
  }

  function zapiszAdres() {
    var szukane = parametry(0);
    szukane.delete('offset');
    window.history.replaceState(null, '', window.location.pathname + '?' + szukane.toString());
  }

  /* ===== POBRANIE ====================================================== */

  function wczytaj(odZera) {
    if (odZera === undefined) { odZera = true; }
    var offset = odZera ? 0 : (stan.stronicowanie ? stan.stronicowanie.offset + stan.stronicowanie.limit : 0);
    if (!odZera) { stan.doczytywanie = true; }
    korzen.setAttribute('aria-busy', 'true');

    return fetch(korzen.dataset.urlDane + '?' + parametry(offset).toString(), {
      headers: { 'Accept': 'application/json' },
      credentials: 'same-origin'
    }).then(function (odpowiedz) {
      if (odpowiedz.status === 401) {
        pokazBlad('Sesja wygasła. Zaloguj się ponownie, żeby zobaczyć dane.');
        return null;
      }
      return odpowiedz.json().then(function (dane) {
        if (!odpowiedz.ok) {
          pokazBlad(dane.komunikat || 'Nie udało się pobrać danych arkusza.');
          return null;
        }
        return dane;
      });
    }).then(function (dane) {
      if (dane) { schowajBlad(); przyjmij(dane, odZera); }
      return dane;
    }).catch(function (blad) {
      pokazBlad('Nie udało się pobrać danych arkusza: ' + blad.message);
      return null;
    }).then(function (wynik) {
      stan.doczytywanie = false;
      korzen.setAttribute('aria-busy', 'false');
      return wynik;
    });
  }

  function przyjmij(dane, odZera) {
    stan.kolumny = dane.kolumny;
    stan.stronicowanie = dane.stronicowanie;
    stan.okno = dane.okno;
    opisyKolumn = {};
    dane.kolumny.forEach(function (kolumna) { opisyKolumn[kolumna.nazwa] = kolumna; });

    if (odZera) {
      stan.zamowienia = dane.zamowienia;
      rysujGlowe();
      wyczyscCialo();
      wstawTbody(cialo, dane.zamowienia);
    } else {
      stan.zamowienia = stan.zamowienia.concat(dane.zamowienia);
      wstawTbody(cialo, dane.zamowienia);
    }

    rysujStopke(dane.podsumowanie);
    document.getElementById('ark-okno-etykieta').textContent = dane.okno.etykieta;
    zamrozDrugaKolumne();
    pokazPustyStan(dane);
    /* Siatka wlasnie zostala narysowana od zera (szukajka, zmiana okna
       dat, zmiana filtra — kazda z nich wola wczytaj(true)) i nowe komorki
       sa „czyste": bez klasy 'edytowana' i bez dataset.surowa ustawionego
       na wartosc uzytkownika. Niezapisane zmiany w `zmienione` PRZEZYWAJA
       to przeladowanie (mapa nie jest czyszczona), ale bez tego kroku
       znikalyby z ekranu, mimo ze licznik i bursztynowy narzedziownik
       dalej twierdzilyby, ze cos jest zmienione. */
    odtworzZmianyPoPrzeladowaniu();
  }

  function pokazPustyStan(dane) {
    var podpowiedz = document.getElementById('ark-stopka-podpowiedz');
    if (!dane.zamowienia.length && !stan.zamowienia.length) {
      podpowiedz.textContent = 'Brak zamówień w tym oknie dat';
    } else {
      podpowiedz.textContent = 'Przewijanie wirtualne — w pamięci tylko widoczne wiersze';
    }
  }

  /* ===== RENDER ======================================================== */

  function rysujGlowe() {
    var wiersz = glowa.querySelector('tr');
    while (wiersz.firstChild) { wiersz.removeChild(wiersz.firstChild); }
    stan.kolumny.forEach(function (kolumna, indeks) {
      var komorka = document.createElement('th');
      komorka.scope = 'col';
      komorka.textContent = kolumna.etykieta;
      komorka.dataset.kolumna = kolumna.nazwa;
      komorka.dataset.typ = kolumna.typ;
      /* Podpowiedź przy kolumnach, których wartość nie jest tym, czym
         wygląda — np. „Data płatności" jest przy imporcie przybliżeniem,
         bo BaseLinker nie zwraca daty wpłaty w getOrders. Tekst przychodzi
         z serwera, tutaj go tylko wieszamy. */
      if (kolumna.podpowiedz) {
        komorka.title = kolumna.podpowiedz;
        komorka.classList.add('ma-podpowiedz');
      }
      nadajKlasyRodzaju(komorka, kolumna);
      zamroz(komorka, indeks);
      if (kolumna.liczbowa) { komorka.classList.add('num'); }
      wiersz.appendChild(komorka);
    });
  }

  function nadajKlasyRodzaju(element, kolumna) {
    if (kolumna.rodzaj === 'crm') { element.classList.add('crm'); }
    if (kolumna.rodzaj === 'wyliczana') { element.classList.add('calc'); }
    if (kolumna.rodzaj === 'produkcja') { element.classList.add('prod'); }
  }

  function zamroz(element, indeks) {
    if (indeks === 0) { element.classList.add('zamrozona-1'); }
    if (indeks === 1) { element.classList.add('zamrozona-2'); }
  }

  /* Przesunięcie drugiej zamrożonej kolumny to szerokość pierwszej —
     wymiar układu, którego serwer nie zna, bo zależy od CSS-a. */
  function zamrozDrugaKolumne() {
    var pierwsza = glowa.querySelector('.zamrozona-1');
    if (!pierwsza) { return; }
    var lewa = pierwsza.offsetWidth + 'px';
    Array.prototype.forEach.call(
      korzen.querySelectorAll('.zamrozona-2'),
      function (element) { element.style.left = lewa; });
  }

  /* Usuwa WYLACZNIE bloki zamowien, nigdy <thead>. `cialo` to sama
     <table id="ark-cialo"> (patrz arkusz.html) — bezmyslne czyszczenie
     wszystkich dzieci zabralo(by) ze soba naglowek. */
  function wyczyscCialo() {
    Array.prototype.forEach.call(
      cialo.querySelectorAll('tbody.ark-zamowienie'),
      function (blok) { cialo.removeChild(blok); });
  }

  function wstawTbody(rodzic, zamowienia) {
    zamowienia.forEach(function (zamowienie) {
      var blok = document.createElement('tbody');
      blok.className = 'ark-zamowienie';
      blok.dataset.zamowienie = String(zamowienie.id);
      var wierszyBloku = zamowienie.wierszy;
      /* ZAMÓWIENIE POZA SPRZEDAŻĄ (partia E, punkt E5): anulowane albo
         nieopłacone. Zostaje na liście, bo Arkusz zastępuje Excela, ale jest
         wyszarzone, a nad jego wierszami stoi zdanie ze statusem. Zdanie
         składa serwer (`poza_sprzedaza`) — tutaj tylko je wstawiamy.
         Wiersz statusu idzie na POCZĄTEK bloku, PRZED pierwszy wiersz
         zamówienia: rowspan komórek zamówienia liczy się od tamtego wiersza
         w dół, więc nie obejmie tego (ten sam powód, dla którego wiersz
         błędu idzie na sam koniec bloku — patrz oznaczOdrzucone). Szary,
         nie czerwony: to nie jest błąd. */
      if (zamowienie.poza_sprzedaza) {
        blok.classList.add('poza-sprzedaza');
        var wierszStatusu = document.createElement('tr');
        wierszStatusu.className = 'ark-wiersz-statusu';
        var komorkaStatusu = document.createElement('td');
        komorkaStatusu.colSpan = stan.kolumny.length;
        var napisStatusu = document.createElement('span');
        napisStatusu.className = 'ark-wiersz-statusu__napis';
        napisStatusu.textContent = zamowienie.poza_sprzedaza;
        komorkaStatusu.appendChild(napisStatusu);
        wierszStatusu.appendChild(komorkaStatusu);
        blok.appendChild(wierszStatusu);
        wierszyBloku += 1;
      }
      /* Zastępcza wysokość bloku: bez niej pasek przewijania skacze przy
         każdym wejściu zamówienia w widok. Piksele, nie dane. */
      blok.style.containIntrinsicSize = 'auto ' + (wierszyBloku * WYSOKOSC_WIERSZA) + 'px';

      var pozycje = zamowienie.pozycje.length ? zamowienie.pozycje : [null];
      pozycje.forEach(function (pozycja, numerWiersza) {
        blok.appendChild(rysujWiersz(zamowienie, pozycja, numerWiersza === 0));
      });
      rodzic.appendChild(blok);
    });
  }

  function rysujWiersz(zamowienie, pozycja, pierwszy) {
    var wiersz = document.createElement('tr');
    stan.kolumny.forEach(function (kolumna, indeks) {
      if (kolumna.poziom === 'zamowienie') {
        /* Komórka poziomu zamówienia stoi TYLKO w pierwszym wierszu — na tym
           polega rowspan. Puste <td> w kolejnych wierszach rozjechałyby tabelę. */
        if (!pierwszy) { return; }
        wiersz.appendChild(rysujKomorke(kolumna, indeks, zamowienie, 'zamowienie',
                                        zamowienie.id, zamowienie.wierszy));
      } else {
        wiersz.appendChild(rysujKomorke(kolumna, indeks, pozycja, 'pozycja',
                                        pozycja ? pozycja.id : null, 1));
      }
    });
    return wiersz;
  }

  function rysujKomorke(kolumna, indeks, zrodlo, poziom, id, wierszy) {
    var komorka = document.createElement('td');
    var tekst = zrodlo ? zrodlo.pola[kolumna.nazwa] : '—';

    komorka.textContent = tekst;
    komorka.dataset.kolumna = kolumna.nazwa;
    nadajKlasyRodzaju(komorka, kolumna);
    zamroz(komorka, indeks);

    if (poziom === 'zamowienie') {
      komorka.classList.add('ord');
      /* Zamówienie jednopozycyjne nie dostaje atrybutu wcale — tak jest
         w makiecie (zamówienie 50839911). */
      if (wierszy > 1) { komorka.rowSpan = wierszy; }
    }
    /* 'liczbowa' i 'monospace' to DWA rozne pytania: 'liczbowa' pyta, czy
       wartosc sie sumuje i porownuje kolumna w kolumne (wyrownanie do
       prawej, separator tysiecy), 'monospace' pyta tylko o czcionke pod
       cyfry. 'Nr BaseLinker' jest identyfikatorem — same cyfry, ale NIE
       wielkosc liczbowa: dostaje 'm' bez 'num', tak jak w makiecie
       (przeglad zadan 7+8, [WAZNE] nr 5). Serwer juz rozstrzyga oba
       pytania (arkusz_service._opis_kolumny) — JS tylko wiesza klasy. */
    if (kolumna.liczbowa) { komorka.classList.add('m', 'num'); }
    else if (kolumna.monospace) { komorka.classList.add('m'); }
    if (tekst === '—') { komorka.classList.add('pusta'); }

    /* Komórka edytowalna dostaje klucz i staje się celem nawigacji.
       Sama edycja przychodzi w Zadaniu 9. */
    var edytowalna = kolumna.edytowalne && zrodlo && id !== null;
    /* KOMÓRKA ZABLOKOWANA MUSI SIĘ WYTŁUMACZYĆ. Milcząco nieklikalna
       komórka wygląda jak błąd aplikacji — użytkownik ma zobaczyć, dlaczego
       akurat tu nie może pisać i co z tym zrobić. Stąd i klasa (widać ją
       gołym okiem), i `title` (mówi, o co chodzi), i `aria-label`
       (to samo dla czytnika ekranu). */
    if (edytowalna && kolumna.metoda_api === 'setOrderProductFields' && zrodlo.bez_id_bl) {
      /* Bez order_product_id z BaseLinkera setOrderProductFields nie zadziała.
         Dotyczy wszystkiego, co przyszło z backfillu — stara tabela nie
         miała tej kolumny. */
      edytowalna = false;
      zablokuj(komorka, 'Tej pozycji nie da się zmienić w BaseLinkerze: nie mamy '
                      + 'jej identyfikatora, bo pochodzi sprzed przebudowy. '
                      + 'Naprawi to ponowne pobranie tego zamówienia '
                      + '(menu „⋯" → „Pobierz zamówienia z BaseLinkera").');
    }
    if (edytowalna && kolumna.rodzaj === 'bl' && !stan.mozeWysylac) {
      edytowalna = false;
      zablokuj(komorka, 'Kolumna z BaseLinkera. Zmiana wychodzi poza CRM, '
                      + 'więc może ją wprowadzić tylko administrator.');
    }
    if (edytowalna) {
      komorka.dataset.klucz = klucz(poziom, id, kolumna.nazwa);
      komorka.dataset.surowa = zrodlo.surowe[kolumna.nazwa] || '';
      komorka.dataset.tekstPierwotny = tekst;
      komorka.tabIndex = -1;
      komorka.classList.add('edytowalna');
    }
    return komorka;
  }

  /* Jedno miejsce na „ta komórka jest zablokowana i oto dlaczego". */
  function zablokuj(komorka, powod) {
    komorka.classList.add('zablokowana');
    komorka.title = powod;
    komorka.setAttribute('aria-label',
      komorka.textContent + ' — pole zablokowane. ' + powod);
  }

  function rysujStopke(podsumowanie) {
    document.getElementById('ark-stopka-pozycje').textContent = podsumowanie.pozycje;
    document.getElementById('ark-stopka-zamowienia').textContent = podsumowanie.zamowienia;
    document.getElementById('ark-stopka-netto').textContent = podsumowanie.netto;
    document.getElementById('ark-stopka-objetosc').textContent = podsumowanie.objetosc;
  }

  /* ===== NAWIGACJA KLAWIATURA ========================================== */

  function komorkiEdytowalne() {
    return Array.prototype.slice.call(cialo.querySelectorAll('td.edytowalna'));
  }

  function przesunFokus(od, krok) {
    var wszystkie = komorkiEdytowalne();
    var pozycja = wszystkie.indexOf(od);
    var cel = wszystkie[pozycja + krok];
    if (cel) { cel.focus(); }
  }

  function przesunPionowo(od, kierunek) {
    var kolumna = od.dataset.kolumna;
    var wszystkie = komorkiEdytowalne().filter(function (element) {
      return element.dataset.kolumna === kolumna;
    });
    var pozycja = wszystkie.indexOf(od);
    var cel = wszystkie[pozycja + kierunek];
    if (cel) { cel.focus(); }
  }

  siatka.addEventListener('keydown', function (zdarzenie) {
    var komorka = zdarzenie.target;
    if (!komorka.classList || !komorka.classList.contains('edytowalna')) { return; }
    if (komorka.querySelector('input, select')) { return; }

    if (zdarzenie.key === 'ArrowRight') { zdarzenie.preventDefault(); przesunFokus(komorka, 1); }
    else if (zdarzenie.key === 'ArrowLeft') { zdarzenie.preventDefault(); przesunFokus(komorka, -1); }
    else if (zdarzenie.key === 'ArrowDown') { zdarzenie.preventDefault(); przesunPionowo(komorka, 1); }
    else if (zdarzenie.key === 'ArrowUp') { zdarzenie.preventDefault(); przesunPionowo(komorka, -1); }
    else if (zdarzenie.key === 'Tab') {
      zdarzenie.preventDefault();
      przesunFokus(komorka, zdarzenie.shiftKey ? -1 : 1);
    } else if (zdarzenie.key === 'Enter') {
      zdarzenie.preventDefault();
      wejdzWEdycje(komorka);
    }
  });

  /* ===== DOCZYTYWANIE KOLEJNYCH STRON ================================== */

  siatka.addEventListener('scroll', function () {
    if (stan.doczytywanie || !stan.stronicowanie || !stan.stronicowanie.wiecej) { return; }
    var doKonca = siatka.scrollHeight - siatka.scrollTop - siatka.clientHeight;
    if (doKonca < MARGINES_DOCZYTANIA) { wczytaj(false); }
  });

  /* ===== KONTROLKI NARZĘDZIOWNIKA ====================================== */

  var zegarSzukania = null;
  poleSzukania.addEventListener('input', function () {
    window.clearTimeout(zegarSzukania);
    zegarSzukania = window.setTimeout(function () {
      stan.szukaj = poleSzukania.value.trim();
      zapiszAdres();
      wczytaj(true);
    }, OPOZNIENIE_SZUKANIA);
  });

  document.getElementById('ark-okno').addEventListener('click', function () {
    /* Menu okna dat: cztery presety plus zakres własny. Buduje je ten sam
       mechanizm menu, co „Eksport" i „Więcej" w Zadaniu 15. */
    pokazMenu(this, [
      { etykieta: 'Bieżący miesiąc', akcja: function () { ustawOkno('miesiac'); } },
      { etykieta: 'Bieżący kwartał', akcja: function () { ustawOkno('kwartal'); } },
      { etykieta: 'Bieżący rok', akcja: function () { ustawOkno('rok'); } },
      { etykieta: 'Cała historia', akcja: function () { ustawOkno('calosc'); } }
    ]);
  });

  function ustawOkno(preset) {
    stan.okno = { preset: preset };
    zapiszAdres();
    wczytaj(true);
  }

  document.getElementById('ark-kolumny').addEventListener('click', function () {
    pokazWyborKolumn(this);
  });

  document.getElementById('ark-filtry').addEventListener('click', function () {
    pokazWyborFiltru(this);
  });

  /* ===== MENU I OKIENKA ================================================ */

  function zamknijMenu() {
    var otwarte = korzen.querySelector('.ark-menu');
    if (otwarte) { otwarte.parentNode.removeChild(otwarte); }
    Array.prototype.forEach.call(
      korzen.querySelectorAll('[aria-expanded="true"]'),
      function (przycisk) { przycisk.setAttribute('aria-expanded', 'false'); });
  }

  function pokazMenu(przycisk, pozycje) {
    var bylo = przycisk.getAttribute('aria-expanded') === 'true';
    zamknijMenu();
    if (bylo) { return; }

    var menu = document.createElement('div');
    menu.className = 'ark-menu';
    menu.setAttribute('role', 'menu');
    pozycje.forEach(function (pozycja) {
      var element = document.createElement('button');
      element.type = 'button';
      element.className = 'ark-menu__pozycja';
      element.setAttribute('role', 'menuitem');
      element.textContent = pozycja.etykieta;
      element.addEventListener('click', function () { zamknijMenu(); pozycja.akcja(); });
      menu.appendChild(element);
    });
    menu.style.left = przycisk.offsetLeft + 'px';
    przycisk.parentNode.appendChild(menu);
    przycisk.setAttribute('aria-expanded', 'true');
    return menu;
  }

  function pokazWyborKolumn(przycisk) {
    var bylo = przycisk.getAttribute('aria-expanded') === 'true';
    zamknijMenu();
    if (bylo) { return; }

    var menu = document.createElement('div');
    menu.className = 'ark-menu ark-menu--kolumny';
    stan.kolumnyWszystkie.forEach(function (kolumna) {
      var etykieta = document.createElement('label');
      etykieta.className = 'ark-menu__pozycja';
      var pole = document.createElement('input');
      pole.type = 'checkbox';
      pole.value = kolumna.nazwa;
      pole.checked = stan.kolumnyWybrane.indexOf(kolumna.nazwa) !== -1;
      pole.addEventListener('change', function () {
        if (pole.checked) { stan.kolumnyWybrane.push(kolumna.nazwa); }
        else { stan.kolumnyWybrane = stan.kolumnyWybrane.filter(function (n) { return n !== kolumna.nazwa; }); }
        /* Kolejność kolumn jest kolejnością rejestru, nie kolejnością
           klikania — inaczej dwie osoby z tym samym zestawem widziałyby
           inną tabelę. */
        var porzadek = stan.kolumnyWszystkie.map(function (k) { return k.nazwa; });
        stan.kolumnyWybrane.sort(function (a, b) { return porzadek.indexOf(a) - porzadek.indexOf(b); });
        document.getElementById('ark-licznik-kolumn').textContent =
          stan.kolumnyWybrane.length + '/' + stan.kolumnyWszystkie.length;
        zapiszAdres();
        wczytaj(true);
      });
      etykieta.appendChild(pole);
      var nazwa = document.createElement('span');
      nazwa.textContent = kolumna.etykieta;
      etykieta.appendChild(nazwa);
      menu.appendChild(etykieta);
    });
    menu.style.left = przycisk.offsetLeft + 'px';
    przycisk.parentNode.appendChild(menu);
    przycisk.setAttribute('aria-expanded', 'true');
  }

  /* Filtr to TEN SAM popover, ktorego uzywa chip „Dodaj porownanie +"
     na dashboardzie i kontrolka „Filtr" w Eksploratorze (filtr.js z Planu B).
     Jeden format, jedna implementacja, trzy zastosowania — drugi komponent
     oznaczalby drugi format i rozjazd adresow. */
  var wymiaryFiltra = JSON.parse(korzen.dataset.wymiaryFiltra || '[]');

  function opiszFiltr(wybrane) {
    var etykiety = {};
    wymiaryFiltra.forEach(function (w) { etykiety[w.nazwa] = w.etykieta; });
    return Object.keys(wybrane).map(function (nazwa) {
      return (etykiety[nazwa] || nazwa) + ': ' + wybrane[nazwa].join(', ');
    }).join(' · ');
  }

  function pokazWyborFiltru(przycisk) {
    if (!window.FiltrWymiaru) {
      pokazBlad('Nie udało się wczytać komponentu filtra.');
      return;
    }
    window.FiltrWymiaru.otworz({
      kotwica: przycisk,
      filtr: stan.filtr,
      wymiary: wymiaryFiltra,
      urlWartosci: korzen.dataset.urlWartosci,
      od: stan.okno.od,
      do: stan.okno.do,
      opisz: opiszFiltr,
      przyPotwierdzeniu: function (tekst) {
        stan.filtr = tekst;
        document.getElementById('ark-filtr-opis').textContent =
          tekst ? ': ' + opiszFiltr(window.FiltrWymiaru.zTekstu(tekst)) : '';
        zapiszAdres();
        wczytaj(true);
      }
    });
  }

  document.addEventListener('click', function (zdarzenie) {
    if (!zdarzenie.target.closest || !zdarzenie.target.closest('.ark-menu, #ark-okno, #ark-kolumny, #ark-eksport, #ark-wiecej')) {
      zamknijMenu();
    }
  });
  document.addEventListener('keydown', function (zdarzenie) {
    if (zdarzenie.key === 'Escape') { zamknijMenu(); zamknijDialog(); }
  });

  window.addEventListener('resize', zamrozDrugaKolumne);

  /* Fonty IBM Plex doladuja sie asynchronicznie (`font-display: swap`
     w analiza.css). Nawet z jawna szerokoscia tabeli (patrz komentarz przy
     `.ark-tabela` w arkusz.css) dogranie fontu miedzy pierwszym wywolaniem
     `zamrozDrugaKolumne()` a properym layoutem to realny, zaobserwowany
     scenariusz („nie trzyma pozycji" — przeglad zadan 7+8, [WAZNE] nr 4).
     `document.fonts` moze nie istniec w bardzo starych przegladarkach —
     wywolanie jest wiec osloniete, nie zalozeniem. */
  if (window.document.fonts && window.document.fonts.ready) {
    window.document.fonts.ready.then(zamrozDrugaKolumne);
  }

  /* ===== ŚLEDZENIE ZMIAN ==============================================
     Wzorzec przejęty z modules/settings/static/js/settings.js (spec §6.5):
     mapa wartości pierwotnych, mapa zmian, wpis znika ze zbioru zmian, gdy
     wartość wróci do pierwotnej. Stopka zamieniona na narzędziownik.

     UWAGA: liczniki niżej powstają w przeglądarce i to jest JEDYNY wyjątek
     od zasady „żadna liczba nie jest liczona w przeglądarce". Ile komórek
     użytkownik zmienił — tego serwer nie wie i nie ma jak wiedzieć. Wszystkie
     wartości DANYCH nadal przychodzą gotowe z /api/arkusz/dane. */

  var oryginalne = {};
  var zmienione = new Map();
  var historia = [];

  function odmiana(liczba, formy) {
    if (liczba === 1) { return formy[0]; }
    var reszta10 = liczba % 10, reszta100 = liczba % 100;
    if (reszta10 >= 2 && reszta10 <= 4 && (reszta100 < 12 || reszta100 > 14)) {
      return formy[1];
    }
    return formy[2];
  }

  function zapamietajPierwotna(komorka) {
    if (!(komorka.dataset.klucz in oryginalne)) {
      oryginalne[komorka.dataset.klucz] = komorka.dataset.surowa;
    }
  }

  function malujKomorke(komorka, zmiana) {
    while (komorka.firstChild) { komorka.removeChild(komorka.firstChild); }
    if (zmiana) {
      var stare = document.createElement('span');
      stare.className = 'was';
      stare.textContent = zmiana.byloTekst;
      komorka.appendChild(stare);
      komorka.appendChild(document.createTextNode(zmiana.jestTekst));
      komorka.classList.add('edytowana');
      /* Komorka raz zapisana ('zapisana', zielony akcent inset-shadow)
         NIE moze zostac zielona przy kolejnej, jeszcze NIEZAPISANEJ
         edycji. W arkusz.css `.zapisana` stoi PO `.edytowana` przy tej
         samej specyficznosci ([WAZNE], przeglad Zadania 12) — bez zdjecia
         starej klasy tutaj zielony wygrywalby kolejnoscia regul i lamal
         wiazaca zasade „bursztyn dla niezapisanych zmian". */
      komorka.classList.remove('zapisana');
    } else {
      komorka.textContent = komorka.dataset.tekstPierwotny;
      komorka.classList.remove('edytowana');
    }
  }

  /* Tekst do pokazania w komórce. Serwer przysłał sformatowaną wartość
     PIERWOTNĄ; dla nowej, jeszcze niezapisanej, pokazujemy to, co wpisał
     użytkownik. Nie formatujemy tego — formatowanie przyjdzie z serwera
     razem z odpowiedzią na zapis. */
  function ustawZmiane(komorka, nowaSurowa, nowyTekst) {
    var wartoscKlucza = komorka.dataset.klucz;
    zapamietajPierwotna(komorka);
    var pierwotna = oryginalne[wartoscKlucza];

    /* Tekst „przed" do historii cofania NIE moze byc odczytany wprost
       z zawartosci komorki: w chwili wywolania komorka zawiera jeszcze
       edytor (<input>/<select>), ktorego wartosc nie jest tekstem dziecka
       DOM-u (input daje pusty napis), a przy drugiej edycji tej samej
       komorki bez powrotu do oryginalu bylby to jeszcze gorszy przypadek —
       sklejenie starych fragmentow bez separatora ('A'+'B'='AB'). Poprawne
       „przed" to jestTekst istniejacego wpisu w `zmienione`, a przy
       pierwszej edycji — tekst pierwotny zapamietany w dataset. */
    var wczesniejszaZmiana = zmienione.get(wartoscKlucza);
    var poprzedniTekst = wczesniejszaZmiana
      ? wczesniejszaZmiana.jestTekst
      : komorka.dataset.tekstPierwotny;

    historia.push({ klucz: wartoscKlucza, poprzednia: komorka.dataset.surowa,
                    poprzedniTekst: poprzedniTekst });

    komorka.dataset.surowa = nowaSurowa;

    if (nowaSurowa === pierwotna) {
      /* Wartość wróciła do pierwotnej — wpis znika ze zbioru zmian.
         settings.js:240 robi dokładnie to samo. Bez tego licznik rośnie,
         a zapis wysyła do BaseLinkera wartość, która się nie zmieniła. */
      zmienione.delete(wartoscKlucza);
      malujKomorke(komorka, null);
    } else {
      var czesci = wartoscKlucza.split(':');
      var opis = opisKolumny(czesci[2]);
      zmienione.set(wartoscKlucza, {
        poziom: czesci[0], id: parseInt(czesci[1], 10), nazwa: czesci[2],
        bylo: pierwotna, jest: nowaSurowa,
        byloTekst: komorka.dataset.tekstPierwotny,
        jestTekst: nowyTekst,
        metoda: opis ? opis.metoda_api : null,
        wrazliwe: opis ? opis.wrazliwe : false,
        etykieta: opis ? opis.etykieta : czesci[2]
      });
      malujKomorke(komorka, zmienione.get(wartoscKlucza));
    }
    odswiezStan();
  }

  /* Uwaga o edycji scalonej komórki: klucz komórki poziomu zamówienia to
     zamowienie:<id>:<pole> niezależnie od tego, ile wierszy scala rowspan.
     Dwie edycje tej samej komórki dają ten sam klucz, a serwis zapisu robi
     z tego JEDEN UPDATE na sales_orders, nie po jednym na każdą pozycję
     pod spodem. Nie dodawaj tu żadnej pętli po pozycjach. */

  function idaDoBl() {
    return Array.from(zmienione.values()).filter(function (z) { return z.metoda; });
  }
  function zostajaWCrm() {
    return Array.from(zmienione.values()).filter(function (z) { return !z.metoda; });
  }

  function odswiezStan() {
    var komorek = zmienione.size;
    var zamowieniaZeZmianami = new Set();
    /* Zmiany „w ukryciu": komorka z `zmienione`, ktorej nie ma na biezaco
       narysowanej siatce (inne okno dat/szukajka/filtr niz w chwili edycji —
       patrz odtworzZmianyPoPrzeladowaniu). Liczone na biezaco w TEJ SAMEJ
       petli, ktora juz i tak sprawdza kazda komorke przez komorkaPoKluczu —
       zero dodatkowego kosztu i zero szansy na rozjazd ze stanem naprawde
       namalowanym na ekranie. */
    var ukryte = 0;
    zmienione.forEach(function (zmiana, wartoscKlucza) {
      var komorka = komorkaPoKluczu(wartoscKlucza);
      if (!komorka) { ukryte += 1; }
      var blok = komorka ? komorka.closest('tbody') : null;
      zamowieniaZeZmianami.add(blok ? blok.dataset.zamowienie : wartoscKlucza);
    });

    korzen.classList.toggle('ark-brudny', komorek > 0);
    document.getElementById('ark-odrzuc').disabled = komorek === 0;
    document.getElementById('ark-zapisz').disabled = komorek === 0;

    var licznik = document.getElementById('ark-licznik-zmian');
    licznik.hidden = komorek === 0;
    if (komorek) {
      ustawTekstZCyframi(licznik, komorek + ' '
        + odmiana(komorek, ['zmieniona komórka', 'zmienione komórki', 'zmienionych komórek'])
        + ' w ' + zamowieniaZeZmianami.size + ' '
        + odmiana(zamowieniaZeZmianami.size, ['zamówieniu', 'zamówieniach', 'zamówieniach']));
    }

    var doBl = idaDoBl();
    var wrazliwych = doBl.filter(function (z) { return z.wrazliwe; }).length;
    document.getElementById('ark-zapisz').textContent =
      doBl.length ? 'Zapisz i wyślij do BaseLinkera' : 'Zapisz';

    var pasek = document.getElementById('ark-kontekst');
    if (komorek && !pasek.classList.contains('ark-kontekst--blad')) {
      pasek.hidden = false;
      ustawTekstZCyframi(pasek, doBl.length + ' '
        + odmiana(doBl.length, ['zmiana poleci do BaseLinkera', 'zmiany polecą do BaseLinkera',
                                'zmian poleci do BaseLinkera'])
        + (wrazliwych ? ' (' + wrazliwych + ' '
            + odmiana(wrazliwych, ['wymaga potwierdzenia', 'wymagają potwierdzenia',
                                   'wymaga potwierdzenia']) + ')' : '')
        + ', ' + zostajaWCrm().length + ' '
        + odmiana(zostajaWCrm().length, ['zostanie tylko w CRM', 'zostaną tylko w CRM',
                                         'zostanie tylko w CRM'])
        /* WAZNE (przeglad fali 3, nr 3): zamiast po cichu kasowac zmiany
           komorek, ktorych nie ma na aktualnie narysowanej siatce (patrz
           odtworzZmianyPoPrzeladowaniu), mowimy o nich wprost — nadal
           BURSZTYN, nie czerwien, bo to nie blad, tylko normalny stan
           pracy. */
        + (ukryte ? '. ' + ukryte + ' '
            + odmiana(ukryte, ['zmiana czeka poza bieżącym widokiem',
                               'zmiany czekają poza bieżącym widokiem',
                               'zmian czeka poza bieżącym widokiem'])
            + ' (inne okno dat, szukajka albo filtr) — nic nie zginęło' : '')
        + '. Zamknięcie karty teraz spowoduje utratę zmian.');
    } else if (!komorek && !pasek.classList.contains('ark-kontekst--blad')) {
      pasek.hidden = true;
    }

    document.getElementById('ark-stopka-podpowiedz').textContent = komorek
      ? 'Cofnij zmianę: Ctrl+Z'
      : 'Przewijanie wirtualne — w pamięci tylko widoczne wiersze';
  }

  /* Nowe komorki narysowane po przeladowaniu (szukajka, zmiana okna dat,
     zmiana filtra — kazda z nich wola wczytaj(true) -> przyjmij()) nie
     wiedza nic o niezapisanych zmianach z poprzedniego rysowania: `zmienione`
     przezywa przeladowanie, ale DOM wraca „czysty". Nakladamy wiec kazda
     zmiane z mapy na jej komorke z nowej siatki; komorki, ktorych po
     przeladowaniu juz nie ma (zamowienie wypadlo z biezacej strony albo
     wyniku szukania/filtra), zostaja w `zmienione` NIETKNIETE — patrz
     uzasadnienie w funkcji nizej. */
  function odtworzZmianyPoPrzeladowaniu() {
    /* WAZNE (przeglad fali 3, nr 3): wersja sprzed poprawki KASOWALA tu wpis
       z `zmienione` (i pamiec wartosci pierwotnej w `oryginalne`) dla kazdej
       komorki, ktorej nie ma na nowo narysowanej siatce — uzytkownik tracil
       niezapisana prace BEZ ZADNEGO OSTRZEZENIA, jednym klikniciem w zmiane
       okna dat/filtra/szukajki. Naprawa: zmiana NIE GINIE — zostaje
       w `zmienione` (i w `oryginalne`) i wraca na ekran SAMA, gdy komorka
       znow sie pojawi (np. po cofnieciu filtra: kazde kolejne wywolanie tej
       funkcji probuje ja ponownie namalowac). Ile zmian jest dzis „w ukryciu"
       liczy na biezaco odswiezStan() (ten sam warunek `!komorka`, wiec nie ma
       jak sie rozjechac z tym, co ponizej naprawde maluje) — uzytkownik
       dostaje bursztynowe (NIE czerwone) ostrzezenie zamiast cichego
       kasowania. */
    zmienione.forEach(function (zmiana, wartoscKlucza) {
      var komorka = komorkaPoKluczu(wartoscKlucza);
      if (!komorka) { return; }
      komorka.dataset.surowa = zmiana.jest;
      malujKomorke(komorka, zmiana);
    });
    odswiezStan();
  }

  /* ===== EDYTOR KOMÓRKI =============================================== */

  var edytowanaKomorka = null;

  function edytor(kolumna, wartosc) {
    var pole;
    if (kolumna.typ === 'wybor') {
      pole = document.createElement('select');
      (kolumna.opcje || []).forEach(function (opcja) {
        var element = document.createElement('option');
        element.value = opcja;
        element.textContent = opcja;
        pole.appendChild(element);
      });
      /* Status spoza slownika („Status 417343", 131 wierszy na produkcji)
         nie jest na liscie — dokladamy go jako wylaczona opcje, zeby
         uzytkownik widzial, co jest teraz, i wiedzial, ze tego nie wyśle. */
      if (wartosc && (kolumna.opcje || []).indexOf(wartosc) === -1) {
        var obcy = document.createElement('option');
        obcy.value = wartosc;
        obcy.textContent = wartosc + ' (nieznany BaseLinkerowi)';
        obcy.disabled = true;
        pole.appendChild(obcy);
      }
      pole.value = wartosc;
    } else if (kolumna.typ === 'logiczna') {
      pole = document.createElement('select');
      [['true', 'tak'], ['false', 'nie']].forEach(function (para) {
        var element = document.createElement('option');
        element.value = para[0];
        element.textContent = para[1];
        pole.appendChild(element);
      });
      pole.value = wartosc === 'true' ? 'true' : 'false';
    } else {
      pole = document.createElement('input');
      if (kolumna.typ === 'data') { pole.type = 'date'; }
      else if (kolumna.typ === 'kwota' || kolumna.typ === 'liczba') {
        /* type="text", NIE "number": input[type=number] jest zwiazany ze
           standardem HTML, ktory jako separator dziesietny dopuszcza
           WYLACZNIE kropke. Przy polskim przecinku (klawiatura, wklejenie
           z arkusza kalkulacyjnego) .value takiego pola zwraca PUSTY
           string ('badInput') — wpisana kwota po cichu znika (zmierzone
           na paid_cash: pole pokazuje „0,", wysylane 'nowa' jest '').
           Tu tylko POZWALAMY przecinek wpisac; jednoznaczna postac
           z kropka (ktorej wymaga arkusz_zapis.na_wartosc — patrz komentarz
           tamtej funkcji: „Przecinek dziesietny odrzucamy świadomie")
           powstaje w znormalizujWartosc() przy zatwierdzeniu edycji, wiec
           do serwera zawsze leci to samo, niezaleznie od tego, ktorego
           separatora uzyl uzytkownik. inputMode daje klawiature numeryczna
           na telefonie/tablecie mimo type="text". Walidacje ZAKRESU
           (min/maks, nieujemnosc) i tak robi wylacznie serwer — przegladarce
           nie wolno ufac (patrz max_dlugosc nizej) — wiec zmiana typu na
           "text" niczego tu nie osłabia. */
        pole.type = 'text';
        pole.inputMode = kolumna.typ === 'kwota' ? 'decimal' : 'numeric';
      }
      else { pole.type = 'text'; }
      /* Limit z rejestru pól, egzekwowany PRZED wysyłką do BaseLinkera
         (spec §9: 200 znaków na admin_comments). Serwis zapisu sprawdza
         to drugi raz — przeglądarce nie wolno ufać. */
      if (kolumna.max_dlugosc) { pole.maxLength = kolumna.max_dlugosc; }
      pole.value = wartosc;
    }
    pole.className = 'ark-edytor';
    return pole;
  }

  function wejdzWEdycje(komorka) {
    if (edytowanaKomorka) { zatwierdzEdycje(); }
    var kolumna = opisKolumny(komorka.dataset.kolumna);
    if (!kolumna || !kolumna.edytowalne) { return; }

    if (!('tekstPierwotny' in komorka.dataset)) {
      komorka.dataset.tekstPierwotny = komorka.textContent;
    }
    zapamietajPierwotna(komorka);

    var pole = edytor(kolumna, komorka.dataset.surowa);
    while (komorka.firstChild) { komorka.removeChild(komorka.firstChild); }
    komorka.appendChild(pole);
    pole.focus();
    if (pole.select) { pole.select(); }
    edytowanaKomorka = komorka;

    pole.addEventListener('keydown', function (zdarzenie) {
      if (zdarzenie.key === 'Enter') { zdarzenie.preventDefault(); zatwierdzEdycje(); komorka.focus(); }
      if (zdarzenie.key === 'Escape') { zdarzenie.preventDefault(); anulujEdycje(); komorka.focus(); }
    });
    pole.addEventListener('blur', function () { zatwierdzEdycje(); });
  }

  /* Tekst z pola edytora do wyslania na serwer. Serwer (arkusz_zapis.na_wartosc)
     wprost dokumentuje format wejscia: kropka dziesietna, przecinek
     odrzuca swiadomie. Pole 'kwota'/'liczba' (patrz edytor() — type="text",
     nie "number") przyjmuje WPIS po polsku (przecinek) i po angielsku
     (kropka); tu robimy z niego JEDNOZNACZNA postac przed wyslaniem —
     przecinek na kropke. Inne typy zostaja NIETKNIETE: w polu 'tekst'
     przecinek jest zwyklym znakiem interpunkcyjnym ("Zapłacono, ale
     później") i zamiana zepsulaby tresc. */
  function znormalizujWartosc(surowyTekst, kolumna) {
    var tekst = (surowyTekst || '').trim();
    if (kolumna && (kolumna.typ === 'kwota' || kolumna.typ === 'liczba')) {
      tekst = tekst.replace(',', '.');
    }
    return tekst;
  }

  function zatwierdzEdycje() {
    if (!edytowanaKomorka) { return; }
    var komorka = edytowanaKomorka;
    var pole = komorka.querySelector('.ark-edytor');
    edytowanaKomorka = null;
    if (!pole) { return; }
    var kolumna = opisKolumny(komorka.dataset.kolumna);
    var nowa = znormalizujWartosc(pole.value, kolumna);
    var widoczna = pole.tagName === 'SELECT'
      ? pole.options[pole.selectedIndex].textContent
      : (nowa || '—');
    ustawZmiane(komorka, nowa, widoczna);
  }

  function anulujEdycje() {
    if (!edytowanaKomorka) { return; }
    var komorka = edytowanaKomorka;
    edytowanaKomorka = null;
    malujKomorke(komorka, zmienione.get(komorka.dataset.klucz) || null);
  }

  siatka.addEventListener('dblclick', function (zdarzenie) {
    var komorka = zdarzenie.target.closest('td.edytowalna');
    if (komorka) { wejdzWEdycje(komorka); }
  });

  /* ===== COFANIE, ODRZUCANIE, GUARD =================================== */

  function odrzucZmiany() {
    zmienione.forEach(function (zmiana, wartoscKlucza) {
      var komorka = komorkaPoKluczu(wartoscKlucza);
      if (!komorka) { return; }
      komorka.dataset.surowa = oryginalne[wartoscKlucza];
      malujKomorke(komorka, null);
    });
    zmienione.clear();
    historia.length = 0;
    odswiezStan();
  }

  function cofnij() {
    var ostatnia = historia.pop();
    if (!ostatnia) { return; }
    var komorka = komorkaPoKluczu(ostatnia.klucz);
    if (!komorka) { return; }
    komorka.dataset.surowa = ostatnia.poprzednia;
    if (ostatnia.poprzednia === oryginalne[ostatnia.klucz]) {
      zmienione.delete(ostatnia.klucz);
      malujKomorke(komorka, null);
    } else {
      /* Wpis w `zmienione` moze juz nie istniec — np. uzytkownik recznie
         wpisal z powrotem wartosc pierwotna (co poprawnie skasowalo wpis
         powyzej), a teraz Ctrl+Z ma cofnac WLASNIE to. Trzeba go wiec
         ODTWORZYC, nie tylko zmodyfikowac gdy juz jest w mapie —
         etykiete/metode/wrazliwosc czytamy ponownie z rejestru kolumn. */
      var czesciKlucza = ostatnia.klucz.split(':');
      var opis = opisKolumny(czesciKlucza[2]);
      var wpis = zmienione.get(ostatnia.klucz) || {
        poziom: czesciKlucza[0], id: parseInt(czesciKlucza[1], 10), nazwa: czesciKlucza[2],
        bylo: oryginalne[ostatnia.klucz],
        etykieta: opis ? opis.etykieta : czesciKlucza[2],
        metoda: opis ? opis.metoda_api : null,
        wrazliwe: opis ? opis.wrazliwe : false
      };
      wpis.jest = ostatnia.poprzednia;
      wpis.jestTekst = ostatnia.poprzedniTekst;
      zmienione.set(ostatnia.klucz, wpis);
      malujKomorke(komorka, wpis);
    }
    odswiezStan();
  }

  document.getElementById('ark-odrzuc').addEventListener('click', function () {
    if (korzen.classList.contains('ark-porazka')) { odrzucNieudane(); }
    else { odrzucZmiany(); }
  });

  document.addEventListener('keydown', function (zdarzenie) {
    /* Bez tej strazy Ctrl+Z w otwartym edytorze komorki blokuje natywne
       cofanie w polu tekstowym (preventDefault dziala), a cofnij() w tym
       samym momencie przemalowuje jakas komorke i kasuje zmiane —
       uzytkownik traci to, co wlasnie pisal. To samo dzieje sie z fokusem
       w szukajce #ark-szukaj: Ctrl+Z nie cofa wpisanej frazy, tylko po
       cichu cofa zmiane w jakiejs komorce arkusza. */
    var cel = zdarzenie.target;
    if (cel && (cel.closest('.ark-edytor') || cel.matches('input, select, textarea'))) {
      return;
    }
    if ((zdarzenie.ctrlKey || zdarzenie.metaKey) && zdarzenie.key.toLowerCase() === 'z') {
      zdarzenie.preventDefault();
      cofnij();
    }
  });

  /* settings.js:741 robi dokladnie to samo. Przegladarki ignoruja tresc
     komunikatu i pokazuja swoj, ale returnValue musi byc ustawione. */
  window.addEventListener('beforeunload', function (zdarzenie) {
    if (zmienione.size === 0) { return; }
    zdarzenie.preventDefault();
    zdarzenie.returnValue = 'Masz niezapisane zmiany. Czy na pewno chcesz opuścić stronę?';
    return zdarzenie.returnValue;
  });

  /* ===== DIALOG POTWIERDZENIA ========================================= */
  /* Spec 5.3 pkt 1: dialog musi wymieniac IMIENNIE kazde pole lecace do
     BaseLinkera — LACZNIE z polami DOROZUMIANYMI, ktorych zaznaczone
     komorki same nie niosa (setOrderPayment podmienia cala platnosc naraz).
     Sklada to wylacznie serwer (arkusz_zapis.pozycje_potwierdzenia) — dialog
     dociaga gotowa liste z /api/arkusz/potwierdzenie PRZED pokazaniem sie,
     zamiast skladac ja samemu z lokalnej mapy `zmienione`. */

  var niePytajWTejSesji = false;
  var ostatniWynik = null;
  // Chroni przed podwojnym zapytaniem, gdyby drugie klikniecie „Zapisz"
  // zdazylo przejsc przez event loop zanim przycisk zdazyl sie zablokowac.
  var pobieranieDialogu = false;

  function wierszDialogu(zmiana) {
    var wiersz = document.createElement('tr');
    [String(zmiana.numerBl || '—'), null, zmiana.byloTekst, zmiana.jestTekst,
     zmiana.metoda].forEach(function (tresc, kolumna) {
      var komorka = document.createElement('td');
      if (kolumna === 1) {
        komorka.textContent = zmiana.etykieta;
        if (zmiana.wrazliwe) {
          var znacznik = document.createElement('span');
          znacznik.className = 'ark-znacznik-wrazliwe';
          znacznik.textContent = 'wrażliwe';
          komorka.appendChild(znacznik);
        }
        // Pole DOROZUMIANE: uzytkownik go nie edytowal, a i tak poleci do
        // BaseLinkera razem z tym, co zmienil. NIE ukrywamy takiego wiersza
        // — dostaje wlasny, bursztynowy znacznik obok etykiety.
        if (zmiana.dorozumiane) { komorka.appendChild(znacznikDorozumiane()); }
      } else {
        komorka.textContent = tresc;
      }
      if (kolumna === 0 || kolumna === 4) { komorka.classList.add('m'); }
      wiersz.appendChild(komorka);
    });
    return wiersz;
  }

  /* Znacznik pola dorozumianego. BURSZTYN, NIE CZERWIEN — to nie blad,
     tylko normalny efekt uboczny edycji sasiedniego pola (ta sama zasada
     projektu co przy stanie „niezapisane"). Kolory sa INLINE, nie wlasna
     klasa CSS: arkusz.css/arkusz.html leza poza pasmem tego zadania, wiec
     zamiast dopisywac tam nowa regule, uzywamy DOKLADNIE tych samych
     literalow, ktorych .ark-licznik/.ark-kontekst juz uzywaja w arkusz.css
     (var(--warn-bg)=#FDEDCF, var(--warn-line)=#D98A16, tusz #7A4E05) —
     zaden nowy kolor nie wchodzi do gry. */
  function znacznikDorozumiane() {
    var znacznik = document.createElement('span');
    znacznik.style.cssText = 'display:inline-block;margin-left:6px;padding:2px 6px;'
      + 'border-radius:3px;background:var(--warn-bg,#FDEDCF);color:#7A4E05;'
      + 'border:1px solid var(--warn-line,#D98A16);font:700 9.5px "IBM Plex Sans",'
      + 'system-ui,sans-serif;letter-spacing:.05em;text-transform:uppercase;';
    znacznik.textContent = 'dokłada BaseLinker';
    znacznik.title = 'Tego pola nikt nie edytował — BaseLinker i tak je wyśle '
      + 'razem z tą zmianą, patrz kolumna „Będzie".';
    return znacznik;
  }

  /* Numer zamówienia w BaseLinkerze dla wiersza, w którym siedzi komórka
     o podanym KLUCZU (poziom:id:nazwa). Bierzemy go ze stanu, nie z DOM-u
     — w DOM-ie jest tylko sformatowany tekst, a numer bywa poza wybranymi
     kolumnami. Osobna funkcja od klucza (a nie tylko od obiektu `zmiana`),
     bo wynik zapisu z serwera (`odswiezStanPorazki`) niesie klucz jako
     goly string, bez pol .poziom/.id/.nazwa, jakie ma wpis w `zmienione`. */
  function numerBlPoKluczu(wartoscKlucza) {
    var komorka = komorkaPoKluczu(wartoscKlucza);
    var blok = komorka ? komorka.closest('tbody') : null;
    if (!blok) { return null; }
    var znalezione = stan.zamowienia.filter(function (z) {
      return String(z.id) === blok.dataset.zamowienie;
    })[0];
    return znalezione ? znalezione.bl_id : null;
  }

  function numerBl(zmiana) {
    return numerBlPoKluczu(zmiana.poziom + ':' + zmiana.id + ':' + zmiana.nazwa);
  }

  /* Zestaw zmian do wyslania w formacie, ktorego oczekuje serwer. TA SAMA
     lista karmi zarowno podglad potwierdzenia (nizej), jak i wlasciwy zapis
     (wyslijZmiany) — jedno miejsce budowania „bylo/jest" z mapy zmienione,
     zeby oba zadania zawsze niosly dokladnie to samo. */
  function paczkaZmian() {
    return Array.from(zmienione.values()).map(function (zmiana) {
      /* `bylo` to strażnik optymistyczny: wartość, którą ta komórka miała,
         gdy ją wczytaliśmy. Serwer odrzuci zmianę, jeśli w bazie jest już
         co innego — czyli jeśli ktoś edytował ten sam arkusz równolegle. */
      return { poziom: zmiana.poziom, id: zmiana.id, nazwa: zmiana.nazwa,
               jest: zmiana.jest, bylo: zmiana.bylo };
    });
  }

  /* Adres podgladu potwierdzenia. Szablon nie niesie dla niego wlasnego
     atrybutu data-url-... (arkusz.html jest poza pasmem tego zadania) —
     wyprowadzamy go wiec z adresu zapisu: ten sam blueprint, siostrzana
     trasa, rozni sie wylacznie ostatnim segmentem sciezki. */
  function adresPotwierdzenia() {
    return korzen.dataset.urlZapis.replace(/\/zapisz$/, '/potwierdzenie');
  }

  /* Jeden wiersz z odpowiedzi /api/arkusz/potwierdzenie (klucz, zamowienie,
     nazwa, etykieta, bylo, bedzie, metoda, dorozumiane — patrz
     arkusz_zapis.pozycje_potwierdzenia) zamieniony na ksztalt, ktorego
     oczekuje wierszDialogu(). „wrazliwe" nie przychodzi z tego endpointu
     (ladunek BaseLinkera go nie niesie) — bierzemy je z opisu kolumny,
     ktory arkusz juz ma w pamieci z /api/arkusz/dane. */
  function wierszZPozycji(pozycja) {
    var opis = opisKolumny(pozycja.nazwa);
    return {
      numerBl: pozycja.zamowienie, etykieta: pozycja.etykieta,
      byloTekst: pozycja.bylo, jestTekst: pozycja.bedzie, metoda: pozycja.metoda,
      wrazliwe: !!(opis && opis.wrazliwe), dorozumiane: !!pozycja.dorozumiane
    };
  }

  function pokazDialog() {
    if (pobieranieDialogu) { return; }
    pobieranieDialogu = true;
    var przyciskZapisz = document.getElementById('ark-zapisz');
    przyciskZapisz.disabled = true;
    schowajBlad();

    fetch(adresPotwierdzenia(), {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({ zmiany: paczkaZmian() })
    }).then(function (odpowiedz) {
      if (!odpowiedz.ok) { throw new Error('zly-status-potwierdzenia'); }
      return odpowiedz.json();
    }).then(function (dane) {
      if (!dane || !Array.isArray(dane.pozycje)) { throw new Error('zly-ksztalt-potwierdzenia'); }

      var doBl = dane.pozycje.map(wierszZPozycji);
      var lista = document.getElementById('ark-dialog-lista');
      while (lista.firstChild) { lista.removeChild(lista.firstChild); }
      doBl.forEach(function (zmiana) { lista.appendChild(wierszDialogu(zmiana)); });

      var wrazliwe = doBl.filter(function (z) { return z.wrazliwe; });
      var ostrzezenie = document.getElementById('ark-dialog-ostrzezenie');
      ostrzezenie.hidden = wrazliwe.length === 0;
      if (wrazliwe.length) {
        /* Makieta pokazuje w tym miejscu numer faktury. CRM nie zna dokumentow
           BaseLinkera — sales_orders takiej kolumny nie ma — wiec mowimy to,
           co wiemy naprawde: ktore pole jest wrazliwe i co zmiana uruchomi. */
        ostrzezenie.textContent =
          'Pola oznaczone jako wrażliwe (' + wrazliwe.map(function (z) {
            return z.etykieta;
          }).join(', ') + ') ruszają dokumenty poza CRM-em. Zmiana kwoty wpłaty '
          + 'albo statusu może oznaczyć zamówienie jako opłacone, wystawić '
          + 'dokument i uruchomić powiadomienie do klienta.';
      }

      var wCrm = zostajaWCrm();
      var pudelko = document.getElementById('ark-dialog-crm');
      var listaCrm = document.getElementById('ark-dialog-crm-lista');
      while (listaCrm.firstChild) { listaCrm.removeChild(listaCrm.firstChild); }
      pudelko.hidden = wCrm.length === 0;
      wCrm.forEach(function (zmiana) {
        var wiersz = document.createElement('div');
        wiersz.className = 'ark-dialog__crm-wiersz';
        [String(numerBl(zmiana) || '—'), zmiana.etykieta,
         zmiana.byloTekst, zmiana.jestTekst].forEach(function (tresc, i) {
          var pole = document.createElement('span');
          pole.textContent = tresc;
          /* Numer zamowienia to cyfry — IBM Plex Mono jak wszedzie indziej
             w arkuszu (makieta ma tu `class="m"`, przeglad Zadania 12,
             [WAZNE]). 'was' dostaje WYLACZNIE kolumna „bylo" (i===2):
             przekreslenie + wyciszony kolor odrozniaja ja od „bedzie". */
          if (i === 0) { pole.className = 'm'; }
          if (i === 2) { pole.className = 'was'; }
          wiersz.appendChild(pole);
        });
        listaCrm.appendChild(wiersz);
      });

      /* Licznik na guziku wysylki liczy PRAWDZIWE edycje uzytkownika
         (idaDoBl(), niezmienione tym zadaniem) — nie wiersze dialogu:
         pole dorozumiane nie jest „zmiana", ktora ktos wpisal, wiec nie ma
         wchodzic do „Wyslij N zmian". */
      document.getElementById('ark-dialog-wyslij').textContent =
        'Wyślij ' + idaDoBl().length + ' '
        + odmiana(idaDoBl().length, ['zmianę', 'zmiany', 'zmian']) + ' i zapisz pozostałe';

      document.getElementById('ark-przyciemnienie').hidden = false;
      document.getElementById('ark-dialog').hidden = false;
      /* `.ark-dialog` ma `overflow: auto` i `max-height: calc(100vh - 48px)`
         (arkusz.css) — zwykle `.focus()` przewija swojego najblizszego
         przewijalnego przodka tak, zeby element byl widoczny, a przycisk
         „Anuluj" stoi w STOPCE dialogu. Bez `preventScroll` user widzialby
         od razu stopke z przyciskami zamiast tytulu i listy zmian, czyli
         dokladnie to, po co ten dialog istnieje (przeglad Zadania 12,
         [WAZNE]; zmierzone: scrollTop=1035 przy scrollHeight=1707). */
      document.getElementById('ark-dialog-anuluj').focus({ preventScroll: true });
    }).catch(function () {
      /* Bez pelnej listy z serwera dialog klamalby, ze pokazuje wszystko,
         co poleci do BaseLinkera (spec 5.3 pkt 1 wymaga tego wprost) —
         zamiast niepelnego podgladu odmawiamy wyslania w ciemno: dialog
         zostaje ZAMKNIETY, a przycisk „Zapisz" nie wysyla niczego samemu. */
      pokazBlad('Nie udało się pobrać pełnej listy zmian dla BaseLinkera — '
        + 'wysyłka wstrzymana. Spróbuj ponownie.');
    }).then(function () {
      pobieranieDialogu = false;
      przyciskZapisz.disabled = zmienione.size === 0;
    });
  }

  function zamknijDialog() {
    document.getElementById('ark-przyciemnienie').hidden = true;
    document.getElementById('ark-dialog').hidden = true;
  }

  document.getElementById('ark-dialog-anuluj').addEventListener('click', zamknijDialog);
  document.getElementById('ark-dialog-wyslij').addEventListener('click', function () {
    niePytajWTejSesji = document.getElementById('ark-dialog-niepytaj').checked;
    zamknijDialog();
    wyslijZmiany();
  });

  /* ===== ZAPIS ======================================================== */

  document.getElementById('ark-zapisz').addEventListener('click', function () {
    if (idaDoBl().length && !niePytajWTejSesji) { pokazDialog(); return; }
    wyslijZmiany();
  });

  function wyslijZmiany() {
    var przycisk = document.getElementById('ark-zapisz');
    przycisk.disabled = true;
    var paczka = paczkaZmian();

    return fetch(korzen.dataset.urlZapis, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({ zmiany: paczka })
    }).then(function (odpowiedz) {
      if (odpowiedz.status === 401) {
        pokazBlad('Sesja wygasła. Zaloguj się ponownie — zmiany zostają w arkuszu.');
        return null;
      }
      return odpowiedz.json().then(function (dane) {
        if (!odpowiedz.ok) {
          pokazBlad(dane.komunikat || 'Zapis się nie powiódł.');
          return null;
        }
        return dane;
      });
    }).then(function (dane) {
      if (dane) { przyjmijWynik(dane); }
      przycisk.disabled = zmienione.size === 0;
      return dane;
    }).catch(function (blad) {
      pokazBlad('Zapis się nie powiódł: ' + blad.message);
      przycisk.disabled = false;
    });
  }

  function przyjmijWynik(dane) {
    ostatniWynik = dane;
    var zapisane = dane.wyniki.filter(function (w) { return w.status === 'zapisane'; });
    var odrzucone = dane.wyniki.filter(function (w) { return w.status === 'odrzucone'; });
    oznaczZapisane(zapisane);
    oznaczOdrzucone(odrzucone);
    odswiezStan();
    odswiezStanPorazki(zapisane, odrzucone);
  }

  function oznaczZapisane(wyniki) {
    wyniki.forEach(function (wynik) {
      var komorka = komorkaPoKluczu(wynik.klucz);
      zmienione.delete(wynik.klucz);
      if (!komorka) { return; }
      /* Tekst przychodzi z serwera sformatowany — przegladarka nie sklada
         liczb sama. */
      komorka.dataset.tekstPierwotny = wynik.tekst;
      oryginalne[wynik.klucz] = komorka.dataset.surowa;
      malujKomorke(komorka, null);
      usunWierszBledu(komorka);
      komorka.classList.remove('odrzucona');
      komorka.classList.add('zapisana');
    });
  }

  function oznaczOdrzucone(wyniki) {
    wyniki.forEach(function (wynik) {
      var komorka = komorkaPoKluczu(wynik.klucz);
      if (!komorka) { return; }
      komorka.classList.remove('zapisana');
      komorka.classList.add('odrzucona');
      komorka.title = wynik.blad;
      usunWierszBledu(komorka);
      var wiersz = document.createElement('tr');
      wiersz.className = 'ark-wiersz-bledu';
      /* Klucz KONKRETNEJ komorki, ktorej ten wiersz dotyczy — patrz
         usunWierszBledu nizej: wiersz stoi teraz na koncu bloku, wiec
         "sasiedztwo w DOM-ie" juz nic o przynaleznosci nie mowi. */
      wiersz.dataset.dlaKlucza = wynik.klucz;
      var komorkaBledu = document.createElement('td');
      komorkaBledu.colSpan = stan.kolumny.length;
      komorkaBledu.textContent = (opisKolumny(komorka.dataset.kolumna) || {}).etykieta
        + ' — ' + wynik.blad + ' Ponów wysyłkę albo odrzuć.';
      wiersz.appendChild(komorkaBledu);
      /* KRYTYCZNE, przeglad Zadania 12: komorka poziomu zamowienia (np.
         odrzucone paid_amount) ma rowspan i siedzi WYLACZNIE w PIERWSZYM
         <tr> bloku. Wstawienie wiersza bledu zaraz za tym pierwszym <tr>
         (jak wczesniej) wsuwalo go W SRODEK zakresu rowspan — blok mial
         wtedy o jeden wiersz wiecej, rowspan=N obejmowal juz i wiersz
         bledu, a OSTATNI wiersz pozycji zostawal bez kolumn zamowienia
         i renderowal sie przesuniety, pod zlymi naglowkami (zmierzone:
         zamowienie id=3292, 4 pozycje, wood_species na x=-10 zamiast
         x=985). Wiersz bledu musi wiec isc na sam KONIEC <tbody> bloku
         zamowienia — poza zasieg jakiegokolwiek rowspana. */
      komorka.closest('tbody').appendChild(wiersz);
    });
  }

  function usunWierszBledu(komorka) {
    var blok = komorka.closest('tbody');
    if (!blok) { return; }
    /* Szukamy PO KLUCZU (patrz oznaczOdrzucone), nie po pozycji w DOM-ie:
       wiersz bledu stoi na koncu bloku, wiec `nextSibling` komorki juz nic
       nie mowi o tym, czy dany wiersz bledu do niej nalezy. Po kluczu
       trafiamy dokladnie w SWOJ wiersz, nawet gdy w tym samym bloku
       zawiodlo rownoczesnie kilka pol. */
    var istniejacy = blok.querySelector(
      'tr.ark-wiersz-bledu[data-dla-klucza="' + komorka.dataset.klucz + '"]');
    if (istniejacy) { istniejacy.parentNode.removeChild(istniejacy); }
  }

  function odrzucNieudane() {
    Array.prototype.forEach.call(
      cialo.querySelectorAll('td.odrzucona'), function (komorka) {
        zmienione.delete(komorka.dataset.klucz);
        komorka.dataset.surowa = oryginalne[komorka.dataset.klucz];
        komorka.classList.remove('odrzucona');
        komorka.title = '';
        malujKomorke(komorka, null);
        usunWierszBledu(komorka);
      });
    Array.prototype.forEach.call(
      cialo.querySelectorAll('tr.ark-wiersz-bledu'),
      function (wiersz) { wiersz.parentNode.removeChild(wiersz); });
    odswiezStan();
    korzen.classList.remove('ark-porazka');
    /* NIE nadpisuj tu etykiety #ark-zapisz: odswiezStan() wyzej juz ja
       poprawnie ustawil — 'Zapisz' albo 'Zapisz i wyslij do BaseLinkera',
       zaleznie od tego, czy w `zmienione` zostala jeszcze choc jedna
       zmiana idaca do BL. Bezwarunkowe 'Zapisz' tutaj chowalo ta druga,
       wiazaca etykiete (przeglad Zadania 12, [WAZNE]). */
    document.getElementById('ark-odrzuc').textContent = 'Odrzuć zmiany';
    /* Klikniecie „Odrzuc nieudana" znosi ark-porazka, wiec kolejne
       klikniecie #ark-odrzuc wywola juz odrzucZmiany() (handler nizej) —
       etykieta MUSI wiec wrocic do prawdy, inaczej user, ktory chcial
       odrzucic „te jedna nieudana", straci CALA niezapisana prace bez
       ostrzezenia (przeglad Zadania 12, [WAZNE]). Ten sam powod zdejmuje
       tu czerwony pasek bledu: stanu awarii (ark-porazka) juz nie ma. */
    schowajBlad();
  }

  function odswiezStanPorazki(zapisane, odrzucone) {
    var przycisk = document.getElementById('ark-zapisz');
    var licznik = document.getElementById('ark-licznik-zmian');
    var pasek = document.getElementById('ark-kontekst');
    var podpowiedz = document.getElementById('ark-stopka-podpowiedz');

    korzen.classList.toggle('ark-porazka', odrzucone.length > 0);

    if (!odrzucone.length) {
      przycisk.textContent = 'Zapisz';
      /* WAZNE, przeglad Zadania 12: ta galaz („w pelni udane ponowienie")
         resetowala tylko #ark-zapisz. Etykieta #ark-odrzuc zostawala przy
         'Odrzuć nieudaną' (myląca — nie ma juz nic nieudanego), a czerwony
         pasek #ark-kontekst z ostatnim bledem BaseLinkera zostawal
         WIDOCZNY, mimo ze bledu juz nie ma — i, gorzej, GASIL bursztynowy
         pasek kontekstowy dla WSZYSTKICH kolejnych zmian do konca sesji
         (odswiezStan() ma straz `!pasek.classList.contains('ark-kontekst--blad')`). */
      document.getElementById('ark-odrzuc').textContent = 'Odrzuć zmiany';
      schowajBlad();
      podpowiedz.textContent = 'Przewijanie wirtualne — w pamięci tylko widoczne wiersze';
      return;
    }

    var wszystkich = zapisane.length + odrzucone.length;
    licznik.hidden = false;
    /* Napis dosłownie z makiety BladCzesciowy.dc.html: „3 z 4 zmian zapisane
       · 1 nie przeszła". Odmieniamy tylko ostatni człon, bo tylko on zmienia
       formę przy większej liczbie odrzuceń. */
    ustawTekstZCyframi(licznik, zapisane.length + ' z ' + wszystkich + ' zmian zapisane · '
      + odrzucone.length + ' '
      + odmiana(odrzucone.length, ['nie przeszła', 'nie przeszły', 'nie przeszło']));

    pasek.classList.add('ark-kontekst--blad');
    pasek.hidden = false;
    /* WAZNE, przeglad Zadania 12: bez numeru zamowienia (makieta
       BladCzesciowy.dc.html: „Zamowienie 50827145, pole Zaplacono — ...")
       user nie wie, KTORE z 200 zamowien na ekranie nie przeszlo. */
    ustawTekstZCyframi(pasek, odrzucone.map(function (w) {
      var numer = numerBlPoKluczu(w.klucz);
      return 'Zamówienie ' + (numer || '—') + ', pole '
        + ((opisKolumny(w.klucz.split(':')[2]) || {}).etykieta || w.klucz)
        + ' — BaseLinker odrzucił ' + (w.metoda || 'zapis') + ': ' + w.blad;
    }).join(' · '));

    przycisk.textContent = 'Ponów wysyłkę';
    przycisk.disabled = false;
    document.getElementById('ark-odrzuc').textContent = 'Odrzuć nieudaną';

    podpowiedz.textContent = zapisane.length + ' zapisane: '
      + zapisane.map(function (w) {
          return (opisKolumny(w.klucz.split(':')[2]) || {}).etykieta;
        }).join(', ')
      + '. Nieudane zmiany czekają w komórkach — popraw wartość albo odrzuć.';
  }

  /* ===== EKSPORT I MENU „WIĘCEJ" ====================================== */

  function adresEksportu(bazowy) {
    var szukane = parametry(0);
    szukane.delete('offset');
    return bazowy + '?' + szukane.toString();
  }

  /* Jedna pozycja to nie menu — „Eksport" jest zwykłym przyciskiem
     i ściąga dokładnie to, co widać na ekranie: te kolumny, to okno dat,
     tę szukajkę i ten filtr. */
  document.getElementById('ark-eksport').addEventListener('click', function () {
    window.location.href = adresEksportu(korzen.dataset.urlEksport);
  });

  document.getElementById('ark-wiecej').addEventListener('click', function () {
    pokazMenu(this, [
      { etykieta: 'Pobierz zamówienia z BaseLinkera…', akcja: pobierzZamowienia },
      { etykieta: 'Dotychczasowa tabela ↗', akcja: function () {
          /* Decyzja użytkownika 22.09.2026: stary widok otwiera się
             w NOWEJ KARCIE i jest tylko do odczytu. noopener, bo to
             zwykłe okno aplikacji, a nie miejsce na dostęp do naszego
             `window` z drugiej karty. */
          window.open(korzen.dataset.urlStaraTabela, '_blank', 'noopener');
        } }
    ]);
  });

  function pobierzZamowienia() {
    /* BaseLinker przenosi zamówienia starsze niż 3 miesiące do archiwum,
       którego `getOrders` nie widzi ŻADNYM parametrem. Mówimy o tym PRZED
       kliknięciem, a nie błędem 400 po nim. */
    var potwierdzone = window.confirm(
      'Pobrać zamówienia z BaseLinkera za okres ' + stan.okno.od + ' – ' + stan.okno.do
      + '?\n\nOkno nie może być dłuższe niż 92 dni — starszych zamówień '
      + 'BaseLinker nie udostępnia przez API, bo trafiają do archiwum.\n\n'
      + 'Pobranie zapisuje wyłącznie do analizy sprzedażowej. Nie rusza '
      + 'modułu produkcji ani dotychczasowej tabeli.');
    if (!potwierdzone) { return; }

    korzen.setAttribute('aria-busy', 'true');
    fetch(korzen.dataset.urlPobierz, {
      method: 'POST',
      credentials: 'same-origin',
      headers: { 'Content-Type': 'application/json', 'Accept': 'application/json' },
      body: JSON.stringify({ od: stan.okno.od, do: stan.okno.do })
    }).then(function (odpowiedz) {
      return odpowiedz.json().then(function (dane) {
        if (!odpowiedz.ok) {
          pokazBlad(dane.komunikat || 'Pobieranie się nie powiodło.');
          return null;
        }
        return dane;
      });
    }).then(function (dane) {
      korzen.setAttribute('aria-busy', 'false');
      if (!dane) { return; }
      window.alert('Pobrano ' + dane.pobranych + ' zamówień. Nowych: '
                   + dane.zapis.nowe + ', zaktualizowanych: '
                   + dane.zapis.zaktualizowane + '.');
      /* Zapis do sales_* moze byc CZESCIOWY, nawet gdy BaseLinker oddal
         wszystkie zamowienia — np. 5 z 120 wywraca sie przy upsercie.
         Bez tego uzytkownik czyta sam sukces i nie wie, ze arkusz i sumy
         w stopce sa ubozsze niz BaseLinker. Czerwien jest tu na miejscu —
         to realny blad zapisu, nie niezapisana zmiana. */
      if (dane.zapis && dane.zapis.ostrzezenie) {
        pokazBlad(dane.zapis.ostrzezenie);
      }
      wczytaj(true);
    }).catch(function (blad) {
      korzen.setAttribute('aria-busy', 'false');
      pokazBlad('Pobieranie się nie powiodło: ' + blad.message);
    });
  }

  window.Arkusz = {
    stan: stan,
    wczytaj: wczytaj,
    klucz: klucz,
    komorkaPoKluczu: komorkaPoKluczu,
    opisKolumny: opisKolumny,
    pokazBlad: pokazBlad,
    pokazMenu: pokazMenu,
    zamknijMenu: zamknijMenu,
    zmienione: zmienione,
    odswiezStan: odswiezStan,
    odrzucZmiany: odrzucZmiany,
    idaDoBl: idaDoBl,
    zostajaWCrm: zostajaWCrm,
    malujKomorke: malujKomorke,
    oryginalne: oryginalne,
    zapisz: wyslijZmiany,
    pokazDialog: pokazDialog,
    oznaczZapisane: oznaczZapisane,
    oznaczOdrzucone: oznaczOdrzucone,
    odrzucNieudane: odrzucNieudane
  };

  wczytaj(true);
})();
