# -*- coding: utf-8 -*-
"""
Osłona kasowania indeksu wiedzy.

sync_index kasuje chunki, zanim sprawdzi, czy ma czym je zastąpić. Osłona
„embeduj przed usunięciem" działa tylko gdy `new` jest niepuste — przy
cw_articles() zwracającym [] (chwilowy błąd sieci, rails jeszcze nie wstał)
`new` też jest puste, więc pętla kasująca leci bez osłony i czyści bazę wiedzy.
Efekt na produkcji: 0 chunków przy 76 opublikowanych artykułach, przez dwa miesiące.
"""
import bots.knowledge as k


class TestSyncIndexOslona:
    def test_brak_artykulow_nie_kasuje_istniejacego_indeksu(self, monkeypatch):
        skasowane = []

        class _Polaczenie:
            def execute(self, sql, parametry=()):
                if sql.strip().upper().startswith("DELETE"):
                    skasowane.append(parametry)
                return self

            def fetchall(self):
                return [{"hash": "istniejacy-hash"}]

            def commit(self):
                pass

            def close(self):
                pass

        monkeypatch.setattr(k, "cw_articles", lambda slug: [])       # awaria pobrania
        monkeypatch.setattr(k, "db", lambda: _Polaczenie())
        monkeypatch.setattr(k, "init_db", lambda: None)

        k.sync_index()

        assert skasowane == [], "Pusta lista artykulow skasowala indeks wiedzy"

    def test_pusty_indeks_przy_artykulach_jest_zglaszany(self, monkeypatch):
        komunikaty = []
        monkeypatch.setattr(k, "log", lambda *a: komunikaty.append(" ".join(str(x) for x in a)))
        monkeypatch.setattr(k, "cw_articles", lambda slug: [])
        monkeypatch.setattr(k, "init_db", lambda: None)

        class _Puste:
            def execute(self, *a, **kw):
                return self

            def fetchall(self):
                return []

            def commit(self):
                pass

            def close(self):
                pass

        monkeypatch.setattr(k, "db", lambda: _Puste())
        k.sync_index()

        assert any("pobranie artykulow" in m.lower() or "kb sync" in m.lower()
                   for m in komunikaty)
