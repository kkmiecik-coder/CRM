/* modules/reports/static/js/eksplorator.js
   Panel miar i panel przestawienia. Zero liczenia — wszystko przychodzi
   policzone z /reports/api/eksplorator. Wartosci wchodza przez textContent,
   bo wartosci wymiarow to wolny tekst z BaseLinkera. */
(function () {
  'use strict';

  var korzen = document.getElementById('eksplorator');
  if (!korzen) { return; }

  // roundingMode: 'halfEven' — ta sama regula, co serwerowe formatuj_liczbe
  // (Python Decimal domyslnie zaokragla do parzystej). Bez tego Intl.Number
  // Format domyslnie zaokragla „od zera" (2,5 -> 3, serwer da 2) — ten sam
  // eksplorowany wymiar mogloby wtedy pokazywac inna liczbe niz analiza.js
  // na dashboardzie, z ktorego przyszlo sie tu przez wyjscie z karty
  // (przeglad dashboardu, WAZNE 7 — ten sam problem, na wszelki wypadek
  // naprawiony tez tutaj, choc Eksplorator nie ma wlasnych zdan-wnioskow).
  //
  // useGrouping: 'always' — spacja tysiecy od CZTERECH cyfr, tak samo jak na
  // pulpicie (analiza.js) i w serwerowym formatuj_liczbe. Polska regula Intl
  // grupuje dopiero od pieciu, wiec pulpit pisal „2 361" zamowien, a
  // Eksplorator, do ktorego prowadza stopki kafelkow, „2361 zamowienia"
  // (kontrola koncowa, DROBNE 5). Silnik bez Intl NumberFormat v3 traktuje
  // napis jak `true` i wraca do reguly polskiej — nic sie nie psuje. Eksport
  // CSV formatterow nie uzywa, wiec spacja do pliku nie trafia.
  var fmt0 = new Intl.NumberFormat('pl-PL',
    { maximumFractionDigits: 0, roundingMode: 'halfEven', useGrouping: 'always' });
  var fmt1 = new Intl.NumberFormat('pl-PL',
    { minimumFractionDigits: 1, maximumFractionDigits: 1, roundingMode: 'halfEven',
      useGrouping: 'always' });
  var fmt2 = new Intl.NumberFormat('pl-PL',
    { minimumFractionDigits: 2, maximumFractionDigits: 2, roundingMode: 'halfEven',
      useGrouping: 'always' });
  var SVG = 'http://www.w3.org/2000/svg';

  var KOLORY = ['#0F7D94', '#ED6B24', '#6B5B8A', '#C2BAAF', '#F0A473', '#2C6E4B', '#A8420E'];

  // Kolor idzie za ENCJA (wartoscia wymiaru), nigdy za jej pozycja w rankingu —
  // zasada wiodaca projektu. KOLORY[i % dlugosc] (i = indeks PO POSORTOWANIU)
  // klamalo: ta sama wartosc miala rozne kolory w panelu miar i w panelu
  // przestawienia, bo kazdy panel sortuje/liczy indeks osobno, i zmienial
  // kolor pod uzytkownikiem po samym kliknieciu naglowka do sortowania.
  // Hash tekstu etykiety jest DETERMINISTYCZNY i identyczny w obu panelach
  // (i niezalezny od kolejnosci wierszy), bo etykieta tej samej wartosci
  // wymiaru jest ta sama wszedzie — patrz niezmiennik miedzypanelowy
  // w analiza_service.dane_eksploratora.
  function kolorWartosci(etykieta) {
    var tekst = String(etykieta === null || etykieta === undefined ? '' : etykieta);
    var hash = 0;
    for (var i = 0; i < tekst.length; i++) {
      hash = ((hash << 5) - hash + tekst.charCodeAt(i)) | 0;
    }
    return KOLORY[Math.abs(hash) % KOLORY.length];
  }

  // Parametry biora sie z KONTROLEK, ktore serwer juz zwalidowal i wyrenderowal
  // — nigdy z window.location.search. Trasa HTML po cichu cofa zly parametr do
  // domyslnego, ale adresu nie zmienia; przepisany doslownie poleciałby do
  // /api/eksplorator, ktore waliduje twardo i odpowiada 400 (np. ?miara=saldo).
  // Uzytkownik dostalby poprawnie wyrenderowany Eksplorator i czerwony pasek
  // sekunde pozniej.
  var stan = { dane: null, sortuj: 'netto', malejaco: true, filtr: '' };

  function wartoscKontrolki(id) {
    var wezel = document.getElementById(id);
    return wezel ? wezel.value : '';
  }

  // Etykieta aktualnie wybranej opcji (np. "Miesiąc" albo "Opiekun") —
  // /api/eksplorator nie zwraca osobnego pola na nazwe osi kolumn
  // przestawienia, ale <select> juz ja ma wyrenderowana przez serwer (ten sam
  // rejestr POLA, ktorego uzylby endpoint). Kontrolki sa zrodlem prawdy,
  // tak samo jak w parametryStanu().
  function etykietaKontrolki(id) {
    var wezel = document.getElementById(id);
    if (!wezel || wezel.selectedIndex < 0) { return ''; }
    return wezel.options[wezel.selectedIndex].textContent;
  }

  function parametryStanu() {
    var parametry = new URLSearchParams();
    parametry.set('wymiar', wartoscKontrolki('eks-wymiar'));
    parametry.set('przestawienie', wartoscKontrolki('eks-przestawienie-wybor'));
    parametry.set('miara', wartoscKontrolki('eks-miara'));
    parametry.set('od', wartoscKontrolki('eks-od'));
    parametry.set('do', wartoscKontrolki('eks-do'));
    if (stan.filtr) { parametry.set('filtr', stan.filtr); }
    return parametry;
  }

  function adresDanych() {
    return korzen.getAttribute('data-url-eksplorator') + '?'
      + parametryStanu().toString();
  }

  function el(znacznik, klasa, tekst) {
    var w = document.createElement(znacznik);
    if (klasa) { w.className = klasa; }
    if (tekst !== undefined && tekst !== null) { w.textContent = tekst; }
    return w;
  }

  function czysc(wezel) { while (wezel.firstChild) { wezel.removeChild(wezel.firstChild); } }

  function komorka(wartosc, miara) {
    if (wartosc === null || wartosc === undefined) {
      var pusta = el('td', 'an-mono eks-pusty', '—');
      return pusta;
    }
    if (miara === 'udzial') { return el('td', 'an-mono', fmt1.format(wartosc) + '%'); }
    if (miara === 'objetosc') { return el('td', 'an-mono', fmt2.format(wartosc)); }
    if (miara === 'zamowienia' || miara === 'klienci' || miara === 'nowi_klienci') {
      return el('td', 'an-mono', fmt0.format(wartosc));
    }
    return el('td', 'an-mono', fmt0.format(wartosc));
  }

  function probka(kolor) {
    var s = el('span', 'eks-probka');
    s.style.background = kolor;
    return s;
  }

  function pasek(udzial, kolor) {
    var tor = el('span', 'eks-mini');
    var wyp = document.createElement('i');
    wyp.style.width = Math.max(0, Math.min(100, udzial)) + '%';
    wyp.style.background = kolor;
    tor.appendChild(wyp);
    return tor;
  }

  function iskierka(szereg, kolor) {
    // Inline SVG, tak jak w makiecie. Chart.js na kilkadziesiat wierszy
    // oznaczalby kilkadziesiat instancji wykresu na jednej stronie.
    var svg = document.createElementNS(SVG, 'svg');
    svg.setAttribute('viewBox', '0 0 60 18');
    svg.setAttribute('width', '78');
    svg.setAttribute('height', '18');
    svg.setAttribute('role', 'img');
    if (szereg.length < 2) { return svg; }
    var maks = Math.max.apply(null, szereg);
    var min = Math.min.apply(null, szereg);
    var rozpietosc = (maks - min) || 1;
    var punkty = szereg.map(function (w, i) {
      var x = (i / (szereg.length - 1)) * 60;
      var y = 17 - ((w - min) / rozpietosc) * 16;
      return x.toFixed(1) + ',' + y.toFixed(1);
    }).join(' ');
    var linia = document.createElementNS(SVG, 'polyline');
    linia.setAttribute('points', punkty);
    linia.setAttribute('fill', 'none');
    linia.setAttribute('stroke', kolor);
    linia.setAttribute('stroke-width', '1.6');
    linia.setAttribute('stroke-linejoin', 'round');
    svg.appendChild(linia);
    return svg;
  }

  function zmianaKomorka(wartosc) {
    if (wartosc === null || wartosc === undefined) { return el('td', 'an-mono eks-pusty', '—'); }
    var td = el('td', 'an-mono', (wartosc >= 0 ? '+' : '−') + fmt0.format(Math.abs(wartosc)) + '%');
    td.style.fontWeight = '700';
    td.style.color = wartosc >= 0 ? '#2C6E4B' : '#B33A2B';
    return td;
  }

  /* ---------- panel miar ---------- */

  function rysujMiary() {
    var dane = stan.dane;
    var cialo = document.getElementById('eks-miary-cialo');
    var stopka = document.getElementById('eks-miary-stopka');
    czysc(cialo); czysc(stopka);

    var wiersze = dane.miary.wiersze.slice();
    wiersze.sort(function (a, b) {
      var x = a[stan.sortuj], y = b[stan.sortuj];
      if (x === null || x === undefined) { x = -Infinity; }
      if (y === null || y === undefined) { y = -Infinity; }
      if (typeof x === 'string') { return stan.malejaco ? y.localeCompare(x, 'pl') : x.localeCompare(y, 'pl'); }
      return stan.malejaco ? y - x : x - y;
    });

    wiersze.forEach(function (w) {
      var tr = el('tr');
      var nazwa = el('td');
      var kolor = kolorWartosci(w.etykieta);
      nazwa.appendChild(probka(kolor));
      nazwa.appendChild(pasek(Number(w.udzial), kolor));
      nazwa.appendChild(document.createTextNode(w.etykieta));
      tr.appendChild(nazwa);
      dane.miary.kolejnosc.forEach(function (m) { tr.appendChild(komorka(w[m], m)); });
      cialo.appendChild(tr);
    });

    var trSuma = el('tr');
    trSuma.appendChild(el('td', '', dane.miary.suma.etykieta));
    dane.miary.kolejnosc.forEach(function (m) { trSuma.appendChild(komorka(dane.miary.suma[m], m)); });
    stopka.appendChild(trSuma);
  }

  /* ---------- panel przestawienia ---------- */

  function rysujPrzestawienie() {
    var p = stan.dane.przestawienie;
    var glowa = document.getElementById('eks-przestawienie-glowa');
    var cialo = document.getElementById('eks-przestawienie-cialo');
    var stopka = document.getElementById('eks-przestawienie-stopka');
    czysc(glowa); czysc(cialo); czysc(stopka);

    // Iskierka i „Zmiana" mowia o UPLYWIE CZASU. Przy drugim wymiarze na osi
    // kolumn liczylyby pierwsza kolumne kontra ostatnia, czyli np. sprzedaz
    // jednego opiekuna kontra sprzedaz drugiego — podane jako trend, na
    // zielono. Serwer mowi wprost, czy os jest czasowa.
    var zTrendem = p.trend !== false;

    var trGlowa = el('tr');
    var thWymiar = el('th', '', stan.dane.wymiar.etykieta);
    thWymiar.setAttribute('scope', 'col');
    thWymiar.style.width = '210px';
    trGlowa.appendChild(thWymiar);
    // Wyroznienie „kolumna biezaca" ma sens WYLACZNIE na osi czasu: ostatnia
    // wartosc drugiego wymiaru nie jest niczym biezacym, a od limitu kolumn
    // bywa nia kolumna zbiorcza „Pozostale".
    function biezaca(i) {
      return zTrendem && i === p.kolumny.length - 1 ? 'eks-kolumna-biezaca' : '';
    }

    p.kolumny.forEach(function (k, i) {
      var th = el('th', biezaca(i), k.etykieta);
      th.setAttribute('scope', 'col');
      trGlowa.appendChild(th);
    });
    if (zTrendem) {
      var thTrend = el('th', '', 'Trend'); thTrend.setAttribute('scope', 'col'); thTrend.style.width = '92px';
      var thZmiana = el('th', '', 'Zmiana'); thZmiana.setAttribute('scope', 'col');
      trGlowa.appendChild(thTrend); trGlowa.appendChild(thZmiana);
    }
    glowa.appendChild(trGlowa);

    p.wiersze.forEach(function (w) {
      var kolor = kolorWartosci(w.etykieta);
      var tr = el('tr');
      var nazwa = el('td');
      nazwa.appendChild(probka(kolor));
      nazwa.appendChild(document.createTextNode(w.etykieta));
      tr.appendChild(nazwa);
      p.kolumny.forEach(function (k, j) {
        var td = komorka(w.komorki[k.klucz], p.miara);
        if (biezaca(j)) { td.className += ' eks-kolumna-biezaca'; }
        tr.appendChild(td);
      });
      if (zTrendem) {
        var tdTrend = el('td');
        tdTrend.appendChild(iskierka((w.szereg || []).map(Number), kolor));
        tr.appendChild(tdTrend);
        tr.appendChild(zmianaKomorka(w.zmiana));
      }
      cialo.appendChild(tr);
    });

    var trSuma = el('tr');
    trSuma.appendChild(el('td', '', p.suma.etykieta));
    p.kolumny.forEach(function (k, j) {
      var td = komorka(p.suma.komorki[k.klucz], p.miara);
      if (biezaca(j)) { td.className += ' eks-kolumna-biezaca'; }
      trSuma.appendChild(td);
    });
    if (zTrendem) {
      trSuma.appendChild(el('td'));
      trSuma.appendChild(zmianaKomorka(p.suma.zmiana));
    }
    stopka.appendChild(trSuma);
  }

  /* ---------- eksport ---------- */

  function eksportujCSV() {
    if (!stan.dane) { return; }
    var dane = stan.dane;
    var linie = [];
    linie.push([dane.wymiar.etykieta].concat(
      dane.miary.kolejnosc.map(function (m) { return dane.miary.etykiety[m]; })).join(';'));
    dane.miary.wiersze.forEach(function (w) {
      linie.push([w.etykieta].concat(dane.miary.kolejnosc.map(function (m) {
        return w[m] === null || w[m] === undefined ? '' : String(w[m]).replace('.', ',');
      })).join(';'));
    });

    // Srednik + BOM: polski Excel inaczej wrzuca wszystko do jednej kolumny
    // i gubi ogonki. To ta sama pulapka, co w eksporcie starego raportu.
    //
    // BOM zapisany JAKO ESCAPE, nie jako niewidzialny znak w zrodle.
    // Wklejony doslownie znika przy pierwszym przejsciu przez edytor,
    // ktory normalizuje BOM — eksport po cichu przestaje sie otwierac
    // w polskim Excelu i nikt nie widzi, co zniknelo.
    var tresc = '\ufeff' + linie.join('\r\n');
    var plik = new Blob([tresc], { type: 'text/csv;charset=utf-8' });
    var odnosnik = document.createElement('a');
    odnosnik.href = URL.createObjectURL(plik);
    odnosnik.download = 'eksplorator-' + dane.wymiar.nazwa + '-'
      + dane.okres.od + '_' + dane.okres.do + '.csv';
    document.body.appendChild(odnosnik);
    odnosnik.click();
    document.body.removeChild(odnosnik);
    URL.revokeObjectURL(odnosnik.href);
  }

  /* ---------- ladowanie i sterowanie ---------- */

  function ustaw(sciezka, tekst) {
    var wezel = korzen.querySelector('[data-pole="' + sciezka + '"]');
    if (wezel) { wezel.textContent = tekst; }
  }

  function wypelnij(dane) {
    stan.dane = dane;
    ustaw('okres.stan_na', 'Stan na ' + dane.okres.stan_na);
    ustaw('liczniki', fmt0.format(dane.liczniki.zamowienia) + ' zamówienia · '
      + fmt0.format(dane.liczniki.pozycje) + ' pozycji');
    ustaw('miary.tytul', dane.wymiar.etykieta + ' — wszystkie miary');
    // Naglowek pierwszej kolumny panelu miar: rysujMiary() czysci wylacznie
    // cialo i stopke (thead zostaje), wiec bez tego po zmianie wymiaru
    // naglowek kolumny nadal pokazywalby POPRZEDNI wymiar.
    ustaw('miary.naglowek', dane.wymiar.etykieta);
    // Tytul panelu przestawienia: ta sama pulapka co wyzej, plus druga os
    // (przestawienie), ktorej etykiety /api/eksplorator w ogole nie zwraca —
    // bierzemy ja z kontrolki, ktora serwer juz wyrenderowal poprawnie.
    // Miara z jednostka („· Netto zl") idzie Z SERWERA — komorki panelu to
    // jedna miara powtorzona w kilkunastu kolumnach, wiec jednostka jest
    // podpisana raz, tutaj, a nie przy kazdej liczbie.
    ustaw('przestawienie.tytul', dane.wymiar.etykieta + ' × '
      + etykietaKontrolki('eks-przestawienie-wybor')
      + ' · ' + (dane.przestawienie.etykieta_miary || ''));
    var kontrolkaFiltra = document.getElementById('eks-filtr');
    if (kontrolkaFiltra) {
      kontrolkaFiltra.textContent = dane.filtr.opis;
      kontrolkaFiltra.setAttribute('data-filtr', dane.filtr.tekst);
      stan.filtr = dane.filtr.tekst;
    }
    // Stan kontrolki filtra (wyroznienie na turkusowo + krzyzyk czyszczenia)
    // renderuje sie serwerowo tylko przy pelnym przeladowaniu strony. Zmiana
    // filtra przez popover leci przez ten sam fetch co reszta parametrow,
    // wiec bez tego kontrolka zostawalaby wizualnie wylaczona/wlaczona
    // niezgodnie z tym, co pokazuja juz dane pod spodem.
    var kotwicaFiltra = document.getElementById('eks-kotwica-filtra');
    if (kotwicaFiltra) {
      kotwicaFiltra.classList.toggle('eks-ctl--wlaczony', !!dane.filtr.tekst);
    }
    var wyczyscFiltr = document.getElementById('eks-filtr-wyczysc');
    if (wyczyscFiltr) { wyczyscFiltr.hidden = !dane.filtr.tekst; }
    rysujMiary();
    rysujPrzestawienie();
    korzen.setAttribute('aria-busy', 'false');
    korzen.classList.add('an-gotowe');
  }

  function zaladuj() {
    korzen.classList.remove('an-gotowe');
    korzen.setAttribute('aria-busy', 'true');
    var blok = document.getElementById('eks-blad');
    if (blok) { blok.hidden = true; }

    fetch(adresDanych(), {
      credentials: 'same-origin', headers: { 'Accept': 'application/json' }
    })
      .then(function (odp) {
        // 401 to wygasla sesja, nie zly parametr — kierowanie uzytkownika na
        // „Sprawdz parametry w adresie" kazalo mu szukac bledu tam, gdzie go
        // nie ma.
        if (odp.status === 401) { throw new Error('SESJA'); }
        if (!odp.ok) { throw new Error('HTTP ' + odp.status); }
        return odp.json();
      })
      .then(wypelnij)
      .catch(function (blad) {
        if (blok) {
          blok.textContent = blad.message === 'SESJA'
            ? 'Sesja wygasła. Zaloguj się ponownie, żeby zobaczyć dane.'
            : 'Nie udało się pobrać danych Eksploratora. '
              + 'Sprawdź parametry w adresie. Szczegóły: ' + blad.message;
          blok.hidden = false;
        }
        korzen.setAttribute('aria-busy', 'false');
      });
  }

  function ustawParametry(zmiany) {
    // Kontrolki sa zrodlem prawdy; „zmiany" najpierw w nie wpisujemy, a adres
    // budujemy z nich — dzieki temu adres jest zawsze znormalizowany i zawsze
    // zgodny z tym, co poleci do /api/eksplorator.
    var pola = { wymiar: 'eks-wymiar', przestawienie: 'eks-przestawienie-wybor',
                 miara: 'eks-miara', od: 'eks-od', do: 'eks-do' };
    Object.keys(zmiany).forEach(function (klucz) {
      if (klucz === 'filtr') { stan.filtr = zmiany[klucz]; return; }
      var wezel = document.getElementById(pola[klucz]);
      if (wezel) { wezel.value = zmiany[klucz]; }
    });
    history.pushState({}, '', window.location.pathname + '?'
      + parametryStanu().toString());
    zaladuj();
  }

  function podepnij() {
    var mapa = { 'eks-wymiar': 'wymiar', 'eks-przestawienie-wybor': 'przestawienie',
                 'eks-miara': 'miara' };
    Object.keys(mapa).forEach(function (id) {
      var wezel = document.getElementById(id);
      if (!wezel) { return; }
      wezel.addEventListener('change', function () {
        var zmiana = {};
        zmiana[mapa[id]] = wezel.value;
        ustawParametry(zmiana);
      });
    });

    var zakres = document.getElementById('eks-zakres');
    if (zakres) {
      zakres.addEventListener('click', function () {
        var od = document.getElementById('eks-od').value;
        var do_ = document.getElementById('eks-do').value;
        if (od && do_) { ustawParametry({ od: od, do: do_ }); }
      });
    }

    var naglowki = korzen.querySelectorAll('[data-sortuj]');
    for (var i = 0; i < naglowki.length; i++) {
      naglowki[i].addEventListener('click', function (zdarzenie) {
        var miara = zdarzenie.target.getAttribute('data-sortuj');
        if (stan.sortuj === miara) { stan.malejaco = !stan.malejaco; }
        else { stan.sortuj = miara; stan.malejaco = true; }
        for (var j = 0; j < naglowki.length; j++) { naglowki[j].removeAttribute('aria-sort'); }
        zdarzenie.target.setAttribute('aria-sort', stan.malejaco ? 'descending' : 'ascending');
        if (stan.dane) { rysujMiary(); }
      });
    }

    var eksport = document.getElementById('eks-eksport');
    if (eksport) { eksport.addEventListener('click', eksportujCSV); }

    podepnijFiltr();

    // Po cofnieciu w przegladarce przeladowujemy CALA strone. Brzmi tepo, ale
    // kontrolki sa renderowane serwerowo i to serwer waliduje parametry —
    // recznego przepisywania ich z adresu do kontrolek nie chcemy mieć w dwoch
    // miejscach. Na dashboardzie jest inaczej, bo tam stan jest w JS-ie.
    window.addEventListener('popstate', function () { window.location.reload(); });
  }

  function wymiaryFiltra() {
    try {
      return JSON.parse(korzen.getAttribute('data-wymiary-filtra') || '[]');
    } catch (blad) { return []; }
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

  function podepnijFiltr() {
    var przycisk = document.getElementById('eks-filtr');
    if (!przycisk || !window.FiltrWymiaru) { return; }
    stan.filtr = przycisk.getAttribute('data-filtr') || '';

    przycisk.addEventListener('click', function () {
      window.FiltrWymiaru.otworz({
        kotwica: przycisk,
        filtr: stan.filtr,
        wymiary: wymiaryFiltra(),
        urlWartosci: korzen.getAttribute('data-url-wartosci'),
        od: wartoscKontrolki('eks-od'), do: wartoscKontrolki('eks-do'),
        opisz: opiszFiltr,
        // W Eksploratorze filtr ZAWEZA widok — na dashboardzie ten sam popover
        // dokłada druga serie. Rozni sie wylacznie to, co robimy z wynikiem.
        przyPotwierdzeniu: function (tekst) { ustawParametry({ filtr: tekst }); }
      });
    });

    var wyczysc = document.getElementById('eks-filtr-wyczysc');
    if (wyczysc) {
      wyczysc.addEventListener('click', function () { ustawParametry({ filtr: '' }); });
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    podepnij();
    // Adres w pasku ma przestac klamac — dokladnie tak, jak robi to dashboard.
    // Trasa HTML po cichu cofa zly parametr do domyslnego, ale adresu nie
    // zmienia: po wejsciu z ?miara=saldo strona pokazuje netto, a pasek adresu
    // dalej mowi „saldo" i taka wlasnie zakladka zostaje zapisana.
    // replaceState, nie pushState: to nie jest nowy stan widoku.
    history.replaceState({}, '', window.location.pathname + '?'
      + parametryStanu().toString());
    zaladuj();
  });
}());
