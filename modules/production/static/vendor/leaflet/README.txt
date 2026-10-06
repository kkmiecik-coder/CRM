Leaflet 1.9.4 (https://leafletjs.com, licencja BSD-2-Clause - plik LICENSE obok), pliki z paczki npm
leaflet@1.9.4 (dist/). Vendorowane lokalnie, bo Safari (ITP) blokuje biblioteki z CDN.

Odstępstwo od oryginału (przegląd końcowy logistyki, 4.10.2026):
- leaflet.js - usunięta ostatnia linia "//# sourceMappingURL=leaflet.js.map". Mapy źródeł nie vendorujemy,
  a odwołanie dawało 404 w narzędziach deweloperskich przeglądarki. Poza tą linią plik jest bajt w bajt
  oryginałem (sha256 do sprawdzenia z unpkg.com/leaflet@1.9.4/dist/leaflet.js po usunięciu tej linii).
Pozostałe pliki (leaflet.css, images/) bez zmian.
