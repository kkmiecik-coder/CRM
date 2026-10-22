"""Dziennik zadań agenta (SQLite): przeżywa restart, pilnuje, by nie wysłać zadania drugi raz."""
import logging
import os
import sqlite3
import threading
import time

from . import sciezki

# `nieznany` = wysyłka przerwana awarią procesu (zadanie było w `wysylam`). Celowo NIE jest stanem
# końcowym: wyniku do CRM nie wysyłamy, o „unknown” decyduje dzierżawa po stronie serwera.
STANY = ('pobrane', 'wysylam', 'nieznany', 'wydrukowane', 'blad', 'niewyslane')
STANY_KONCOWE = ('wydrukowane', 'blad', 'niewyslane')
STANY_PO_WYSYLCE_W_TOKU = ('wysylam', 'nieznany')


log = logging.getLogger('agent_druku.dziennik')


class Dziennik:
    def __init__(self, sciezka=None):
        plik = str(sciezka or sciezki.plik_dziennika())
        os.makedirs(os.path.dirname(os.path.abspath(plik)), exist_ok=True)
        self._blokada = threading.RLock()
        try:
            self._otworz(plik)
        except sqlite3.DatabaseError as e:
            # Uszkodzony plik („file is not a database”): na bok i pusty dziennik, bez pętli restartów usługi.
            # Zadania przerwane przed awarią wykryje dzierżawa po stronie CRM (unknown).
            try:
                self._polaczenie.close()
            except Exception:
                pass
            odlozony = sciezki.odloz_uszkodzony(plik)
            log.critical('Dziennik zadań agenta jest uszkodzony (%s) — przeniesiony na %s, start z pustym '
                         'dziennikiem.', e, odlozony or '(nie udało się przenieść)')
            self._otworz(plik)

    def _otworz(self, plik):
        self._polaczenie = sqlite3.connect(plik, check_same_thread=False, timeout=10)
        self._polaczenie.row_factory = sqlite3.Row
        self._polaczenie.execute(
            'CREATE TABLE IF NOT EXISTS dziennik ('
            ' job_id INTEGER PRIMARY KEY, drukarka TEXT NOT NULL, kod TEXT,'
            ' stan TEXT NOT NULL, zmieniono TEXT NOT NULL,'
            ' wynik_wyslany INTEGER NOT NULL DEFAULT 0)')
        kolumny = [w[1] for w in self._polaczenie.execute('PRAGMA table_info(dziennik)')]
        if 'rewizja' not in kolumny:
            self._polaczenie.execute(
                'ALTER TABLE dziennik ADD COLUMN rewizja INTEGER NOT NULL DEFAULT 0')
        self._polaczenie.commit()

    def zapisz(self, job_id, drukarka, kod, stan):
        if stan not in STANY:
            raise ValueError('nieznany stan: %s' % stan)
        teraz = time.strftime('%Y-%m-%d %H:%M:%S')  # czas lokalny, tylko do wyświetlania
        # każda zmiana stanu unieważnia potwierdzenie (wynik_wyslany = 0) i podbija rewizję
        with self._blokada:
            self._polaczenie.execute(
                'INSERT INTO dziennik (job_id, drukarka, kod, stan, zmieniono, wynik_wyslany, rewizja)'
                ' VALUES (?, ?, ?, ?, ?, 0, 1)'
                ' ON CONFLICT(job_id) DO UPDATE SET drukarka=excluded.drukarka,'
                ' kod=excluded.kod, stan=excluded.stan, zmieniono=excluded.zmieniono,'
                ' wynik_wyslany=0, rewizja=dziennik.rewizja + 1',
                (int(job_id), drukarka, kod, stan, teraz))
            self._polaczenie.commit()

    def niepotwierdzone(self):
        """Wyniki w stanach końcowych, o których serwer jeszcze nie wie (z `rewizja`)."""
        with self._blokada:
            wiersze = self._polaczenie.execute(
                'SELECT * FROM dziennik WHERE wynik_wyslany = 0 AND stan IN (?, ?, ?)'
                ' ORDER BY job_id', STANY_KONCOWE).fetchall()
        return [dict(w) for w in wiersze]

    def oznacz_wyslane(self, pary):
        """pary = [(job_id, rewizja)] — oznacza tylko, jeśli wpis nie zmienił się od odczytu."""
        with self._blokada:
            for job_id, rewizja in pary:
                self._polaczenie.execute(
                    'UPDATE dziennik SET wynik_wyslany = 1 WHERE job_id = ? AND rewizja = ?',
                    (int(job_id), int(rewizja)))
            self._polaczenie.commit()

    def ostatnie(self, n):
        with self._blokada:
            wiersze = self._polaczenie.execute(
                'SELECT * FROM dziennik ORDER BY zmieniono DESC, job_id DESC LIMIT ?',
                (int(n),)).fetchall()
        return [dict(w) for w in wiersze]

    def czy_wysylane(self, job_id):
        """True, gdy zadanie jest w `wysylam` albo `nieznany` — nie wysyłać go drugi raz."""
        with self._blokada:
            w = self._polaczenie.execute(
                'SELECT stan FROM dziennik WHERE job_id = ?', (int(job_id),)).fetchone()
        return bool(w and w['stan'] in STANY_PO_WYSYLCE_W_TOKU)

    def oznacz_przerwane(self):
        """Przy starcie agenta: wpisy `wysylam` (proces padł w trakcie wysyłki) → `nieznany`.
        Zwraca liczbę zmienionych wpisów."""
        teraz = time.strftime('%Y-%m-%d %H:%M:%S')
        with self._blokada:
            kursor = self._polaczenie.execute(
                "UPDATE dziennik SET stan = 'nieznany', zmieniono = ?, rewizja = rewizja + 1"
                " WHERE stan = 'wysylam'", (teraz,))
            self._polaczenie.commit()
        return kursor.rowcount

    def zamknij(self):
        with self._blokada:
            self._polaczenie.close()
