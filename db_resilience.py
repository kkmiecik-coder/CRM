# db_resilience.py
"""
Odporność na zatrute/rozsynchronizowane połączenia MySQL
========================================================

Gdy pula odda połączenie MySQL w stanie "commands out of sync" (poprzedni
statement zostawił nieodczytany wynik), kolejny SELECT wraca z kursorem bez
opisu kolumn. SQLAlchemy buduje wtedy wynik na obiekcie `_NoResultMetaData`,
a próba odczytu wiersza (`.first()`) woła na nim `_indexes_for_keys` i leci
CZYSTYM `AttributeError` — NIE `SQLAlchemyError`.

Przez to wyjątek omija wszystkie handlery DB w app.py (OperationalError,
ResourceClosedError, SQLAlchemyError) oraz invalidację w teardown, więc:
  1. leci do klienta jako nieobsłużony 500,
  2. zatrute połączenie ZOSTAJE w puli i truje kolejne requesty.

`pool_pre_ping` tego nie łapie — sprawdza tylko, czy socket żyje (SELECT 1),
a połączenie jest żywe, tylko rozsynchronizowane.

Ten moduł rozpoznaje konkretny podpis tej awarii, żeby app.py mógł wymusić
invalidację połączenia i zwrócić łagodną odpowiedź — bez mylenia z prawdziwym
bugiem w kodzie.

Autor: Konrad Kmiecik + Claude AI
"""

# Podpisy wewnętrzne SQLAlchemy, które pojawiają się WYŁĄCZNIE przy odczycie
# rozsynchronizowanego kursora — nie w zwykłych AttributeError z kodu aplikacji.
CORRUPTED_RESULT_SIGNATURES = ('_NoResultMetaData', '_indexes_for_keys')


def is_corrupted_result_error(exc) -> bool:
    """Czy wyjątek to objaw zatrutego/rozsynchronizowanego połączenia DB?

    Rozpoznaje TYLKO `AttributeError` z podpisem `_NoResultMetaData` /
    `_indexes_for_keys`. Każdy inny `AttributeError` (np. literówka, None)
    zwraca False, żeby prawdziwe bugi leciały normalnie do Sentry.

    Args:
        exc: Przechwycony wyjątek.

    Returns:
        True gdy to awaria zatrutego połączenia, w przeciwnym razie False.
    """
    if not isinstance(exc, AttributeError):
        return False
    msg = str(exc)
    return any(sig in msg for sig in CORRUPTED_RESULT_SIGNATURES)
