# -*- coding: utf-8 -*-
# Polaczenie z baza PrestaShop (PyMySQL, DictCursor). Odczyt katalogu + zapis szkicu bloga.
# Nowe polaczenie per operacja (job krotki, jednowatkowy) — prosto i bez puli.
import pymysql
from config import PS_DB_HOST, PS_DB_NAME, PS_DB_USER, PS_DB_PASS
from core.log import log


def conn():
    return pymysql.connect(host=PS_DB_HOST, user=PS_DB_USER, password=PS_DB_PASS,
                           database=PS_DB_NAME, charset="utf8mb4",
                           cursorclass=pymysql.cursors.DictCursor, autocommit=False)


def query(sql, params=()):
    # Odczyt — zwraca liste slownikow. Blad -> log + pusta lista (nie wywracamy pipeline).
    c = None
    try:
        c = conn()
        with c.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    except Exception as e:
        log("shop_db.query blad:", repr(e)); return []
    finally:
        if c:
            c.close()


def execute(sql, params=()):
    # Zapis — zwraca lastrowid (id nowego wiersza) albo 0 przy bledzie. Commit tylko przy sukcesie.
    c = None
    try:
        c = conn()
        with c.cursor() as cur:
            cur.execute(sql, params)
            rid = cur.lastrowid
        c.commit()
        return rid
    except Exception as e:
        log("shop_db.execute blad:", repr(e))
        if c:
            try:
                c.rollback()
            except Exception:
                pass
        return 0
    finally:
        if c:
            c.close()
