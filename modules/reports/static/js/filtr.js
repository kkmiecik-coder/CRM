/* modules/reports/static/js/filtr.js
   Popover wyboru filtra — JEDEN komponent, dwa zastosowania.

   Uzywaja go: chip „Dodaj porownanie +" na dashboardzie (segment porownawczy)
   i kontrolka „Filtr" w Eksploratorze (zawezenie widoku). Rozni sie tylko to,
   co wolajacy robi z wynikiem — format jest ten sam co w
   modules/reports/filters.py, bo inaczej adres przestalby byc czytelny
   dla serwera.

   Wartosci wymiarow to WOLNY TEKST z BaseLinkera („680 zl za nasz transport
   jesli chce"), wiec wszystko wchodzi przez textContent, nigdy przez innerHTML.
*/
(function () {
  'use strict';

  var otwarty = null;

  // Liczniki zamowien przy wartosciach — ten sam format liczb, co na pulpicie
  // (analiza.js) i w Eksploratorze (eksplorator.js): zaokraglenie do parzystej
  // jak serwerowe formatuj_liczbe i spacja tysiecy od czterech cyfr. Z golym
  // String() popover pisal „2361", a karta obok „2 361" (kontrola koncowa,
  // DROBNE 5). Komponent laduje sie tez bez analiza.js (Eksplorator, Arkusz),
  // wiec ma wlasny formatter.
  var fmt0 = new Intl.NumberFormat('pl-PL',
    { maximumFractionDigits: 0, roundingMode: 'halfEven', useGrouping: 'always' });

  function el(znacznik, klasa, tekst) {
    var w = document.createElement(znacznik);
    if (klasa) { w.className = klasa; }
    if (tekst !== undefined && tekst !== null) { w.textContent = tekst; }
    return w;
  }

  function czysc(wezel) { while (wezel.firstChild) { wezel.removeChild(wezel.firstChild); } }

  /* Format taki sam jak w modules/reports/filters.py:
     pole:wartosc|wartosc,pole:wartosc — wartosci kodowane osobno. */
  function doTekstu(wybrane) {
    return Object.keys(wybrane).sort().filter(function (nazwa) {
      return wybrane[nazwa].length;
    }).map(function (nazwa) {
      return nazwa + ':' + wybrane[nazwa].map(encodeURIComponent).join('|');
    }).join(',');
  }

  function zTekstu(tekst) {
    var wybrane = {};
    if (!tekst) { return wybrane; }
    tekst.split(',').forEach(function (czlon) {
      var i = czlon.indexOf(':');
      if (i < 0) { return; }
      wybrane[czlon.slice(0, i)] = czlon.slice(i + 1).split('|').map(decodeURIComponent);
    });
    return wybrane;
  }

  function zamknij(oddajFokus) {
    if (!otwarty) { return; }
    var kotwica = otwarty.kotwica;
    document.removeEventListener('keydown', otwarty.naKlawisz, true);
    document.removeEventListener('click', otwarty.naKlikniecie, true);
    if (otwarty.okno.parentNode) { otwarty.okno.parentNode.removeChild(otwarty.okno); }
    otwarty = null;
    if (oddajFokus && kotwica) { kotwica.focus(); }
  }

  function otworz(opcje) {
    zamknij(false);

    var wybrane = zTekstu(opcje.filtr || '');
    var okno = el('div', 'an-filtr-popover');
    okno.setAttribute('role', 'dialog');
    okno.setAttribute('aria-label', 'Wybór filtra');

    // 1. Wymiar
    var wybor = el('select', 'an-filtr-wymiar');
    wybor.setAttribute('aria-label', 'Wymiar filtra');
    opcje.wymiary.forEach(function (w) {
      var opcja = el('option', '', w.etykieta);
      opcja.value = w.nazwa;
      wybor.appendChild(opcja);
    });

    // Popover otwarty z ISTNIEJACYM filtrem ma pokazac ten wymiar, ktory
    // faktycznie ma zaznaczone wartosci. Bez tego select startowal na
    // pierwszej opcji (Data) i uzytkownik widzial chip „Kanal sprzedazy:
    // Sklep", otwieral go i dostawal liste dat z niczym zaznaczonym — nie
    // majac jak odznaczyc tego, co wybral, bez zgadniecia wymiaru.
    var juzWybrany = Object.keys(wybrane).filter(function (nazwa) {
      return wybrane[nazwa].length
        && opcje.wymiary.some(function (w) { return w.nazwa === nazwa; });
    })[0];
    if (juzWybrany) { wybor.value = juzWybrany; }

    // 2. Wartosci
    var lista = el('div', 'an-filtr-lista');
    var podglad = el('div', 'an-filtr-podglad');

    // Mapa wartosc -> etykieta po polsku, zapamietywana z /api/wartosci-wymiaru.
    // Bez niej podglad w popoverze sklada sie z SUROWYCH wartosci, wiec
    // uzytkownik widzi „Kanał sprzedaży: shop, personal", klika „Zastosuj"
    // i sekunde pozniej dostaje chip „Kanał sprzedaży: Sklep, Ręczne w BL".
    var etykietyWartosci = {};
    // wymiar -> { wartość -> klucz grupy bazy z serwera }; przeżywa zmianę okresu.
    var kluczeWartosci = {};

    function odswiezPodglad() {
      var tekst = doTekstu(wybrane);
      podglad.textContent = tekst ? opcje.opisz(wybrane, etykietyWartosci) : 'brak warunków';
    }

    // Numer ostatniego zadania o liste wartosci. Szybka zmiana wymiaru w
    // selekcie daje kilka zadan w locie, a odpowiedzi przychodza w dowolnej
    // kolejnosci — SPOZNIONA lista starego wymiaru nie moze zastapic nowszej
    // (ten sam wzorzec, co `numerLadowania` w analiza.js).
    var numerWartosci = 0;

    function wczytajWartosci() {
      numerWartosci += 1;
      var numer = numerWartosci;
      czysc(lista);
      lista.appendChild(el('div', 'an-filtr-info', 'Wczytywanie…'));
      // `wyklucz` podaje tylko pulpit (pola wykluczen): lista i jej liczniki
      // maja sie zgadzac z liczbami obok (partia E8, punkt 4f). Eksplorator
      // i Arkusz wykluczen nie maja — adres zostaje bez parametru.
      var adres = opcje.urlWartosci + '?wymiar=' + encodeURIComponent(wybor.value)
        + '&od=' + encodeURIComponent(opcje.od) + '&do=' + encodeURIComponent(opcje.do)
        + (opcje.wyklucz ? '&wyklucz=' + encodeURIComponent(opcje.wyklucz) : '');
      fetch(adres, { credentials: 'same-origin', headers: { 'Accept': 'application/json' } })
        .then(function (odp) {
          if (numer !== numerWartosci) { return null; }
          if (!odp.ok) { throw new Error('HTTP ' + odp.status); }
          return odp.json();
        })
        .then(function (dane) {
          if (!dane || numer !== numerWartosci) { return; }
          czysc(lista);
          var nazwa = dane.wymiar.nazwa;
          etykietyWartosci[nazwa] = etykietyWartosci[nazwa] || {};
          kluczeWartosci[nazwa] = kluczeWartosci[nazwa] || {};
          dane.wartosci.forEach(function (w) {
            etykietyWartosci[nazwa][w.wartosc] = w.etykieta;
            kluczeWartosci[nazwa][w.wartosc] = w.klucz;
          });
          // Ta sama grupa bazy, choć inny zapis („Kurier" wybrany w jednym
          // okresie, „kurier" na liście innego). Klucz liczy SERWER; tu tylko
          // porównanie. Wartość bez znanego klucza (np. z adresu) — po napisie.
          function tejSamejGrupy(v, w) {
            var k = kluczeWartosci[nazwa][v];
            return v === w.wartosc || (k !== undefined && k === w.klucz);
          }
          dane.wartosci.forEach(function (w) {
            var wiersz = el('label', 'an-filtr-wartosc');
            var pole = document.createElement('input');
            pole.type = 'checkbox';
            pole.value = w.wartosc;
            pole.checked = (wybrane[nazwa] || []).some(function (v) { return tejSamejGrupy(v, w); });
            pole.addEventListener('change', function () {
              var biezace = (wybrane[nazwa] || []).filter(function (v) { return !tejSamejGrupy(v, w); });
              if (pole.checked) { biezace = biezace.concat([w.wartosc]); }
              if (biezace.length) { wybrane[nazwa] = biezace; }
              else { delete wybrane[nazwa]; }
              odswiezPodglad();
            });
            wiersz.appendChild(pole);
            wiersz.appendChild(el('span', 'an-filtr-nazwa', w.etykieta));
            wiersz.appendChild(el('span', 'an-mono an-filtr-licznik', fmt0.format(w.zamowienia)));
            lista.appendChild(wiersz);
          });
          if (dane.uciete) {
            // Zdanie o ucieciu sklada SERWER — tylko on wie, ktorym porzadkiem
            // ucinal. Przy porzadku po sprzedazy wypada to, co sprzedaje sie
            // najslabiej; przy chronologicznym — NAJSTARSZE daty, wiec jeden
            // napis dla obu przypadkow musialby jednemu z nich klamac.
            lista.appendChild(el('div', 'an-filtr-info', dane.opis_uciecia
              || 'Część wartości jest poza listą. Zawęź okres, żeby do nich dojść.'));
          }
          if (!dane.wartosci.length) {
            lista.appendChild(el('div', 'an-filtr-info',
              'W tym okresie nie ma żadnej wartości tego wymiaru.'));
          }
          // Etykiety dopiero teraz sa znane — podglad zlozony przed fetchem
          // pokazywalby wartosci surowe.
          odswiezPodglad();
        })
        .catch(function (blad) {
          if (numer !== numerWartosci) { return; }
          czysc(lista);
          lista.appendChild(el('div', 'an-filtr-info',
            'Nie udało się pobrać wartości. Szczegóły: ' + blad.message));
        });
    }

    wybor.addEventListener('change', wczytajWartosci);

    // 3. Stopka
    var stopka = el('div', 'an-filtr-stopka');
    var zastosuj = el('button', 'an-btn an-btn--ciemny', 'Zastosuj');
    zastosuj.type = 'button';
    var wyczysc = el('button', 'an-btn', 'Wyczyść');
    wyczysc.type = 'button';
    var anuluj = el('button', 'an-btn', 'Anuluj');
    anuluj.type = 'button';

    zastosuj.addEventListener('click', function () {
      var tekst = doTekstu(wybrane);
      zamknij(true);
      opcje.przyPotwierdzeniu(tekst);
    });
    wyczysc.addEventListener('click', function () {
      zamknij(true);
      opcje.przyPotwierdzeniu('');
    });
    anuluj.addEventListener('click', function () { zamknij(true); });

    stopka.appendChild(zastosuj);
    stopka.appendChild(wyczysc);
    stopka.appendChild(anuluj);

    okno.appendChild(wybor);
    okno.appendChild(lista);
    okno.appendChild(podglad);
    okno.appendChild(stopka);
    opcje.kotwica.parentNode.appendChild(okno);

    function naKlawisz(zdarzenie) {
      if (zdarzenie.key === 'Escape') { zdarzenie.stopPropagation(); zamknij(true); }
    }
    function naKlikniecie(zdarzenie) {
      if (!okno.contains(zdarzenie.target) && zdarzenie.target !== opcje.kotwica
          && !opcje.kotwica.contains(zdarzenie.target)) { zamknij(false); }
    }
    document.addEventListener('keydown', naKlawisz, true);
    document.addEventListener('click', naKlikniecie, true);

    otwarty = { okno: okno, kotwica: opcje.kotwica,
                naKlawisz: naKlawisz, naKlikniecie: naKlikniecie };

    odswiezPodglad();
    wczytajWartosci();
    wybor.focus();
  }

  window.FiltrWymiaru = { otworz: otworz, zamknij: zamknij,
                          doTekstu: doTekstu, zTekstu: zTekstu };
}());
