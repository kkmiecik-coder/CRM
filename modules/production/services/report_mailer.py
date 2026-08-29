# -*- coding: utf-8 -*-
"""
Wysyłka dziennego raportu produkcji.

Pierwszy w repo mail z załącznikiem XLSX. Wzorzec załącznika przeniesiony
z modules/quotes/routers.py:547 — Flask-Mail 0.9.1 przyjmuje pozycyjnie
(nazwa, typ MIME, bajty).

Nadawca podawany JAWNIE z MAIL_USERNAME: klucz MAIL_DEFAULT_SENDER nie jest
w tym projekcie nigdzie USTAWIANY (nie ma go w config/core.json; jedyne
trafienie w repo to modules/partner_academy/services.py:276, gdzie służy
wyłącznie jako odczyt z fallbackiem do MAIL_USERNAME). Message() bez sender=
rzuciłby więc wyjątkiem dopiero przy wysyłce.

Błąd SMTP NIE jest tu łapany — propaguje do komendy CLI, która kończy się
niezerowym kodem wyjścia. Cron hostingu mailuje wtedy stderr. Zjedzenie tego
wyjątku sprawiłoby, że awaria wysyłki jest niewidoczna, a w repo jest już
dziesięć miejsc wysyłających maile bez logowania czegokolwiek.
"""

from flask import render_template
from flask_mail import Message

from extensions import mail
from .config_service import get_config

TYP_XLSX = 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet'

_DNI_TYGODNIA = ('poniedziałek', 'wtorek', 'środa', 'czwartek',
                 'piątek', 'sobota', 'niedziela')


def _odbiorcy_z_konfiguracji():
    """Odczyt i rozbicie listy CSV. Prywatny, bo wyslij_raport() ma parametr
    o nazwie `odbiorcy`, który przesłania funkcję publiczną."""
    surowe = get_config('DAILY_REPORT_RECIPIENTS', '') or ''
    return [adres.strip() for adres in surowe.split(',') if adres.strip()]


def odbiorcy():
    """
    Lista adresów z konfiguracji produkcji.

    Pusta lista znaczy „nie wysyłaj" — to jest wyłącznik funkcji, dlatego
    nie ma osobnego klucza DAILY_REPORT_ENABLED.
    """
    return _odbiorcy_z_konfiguracji()


def _dzien_slownie(dzien):
    """„poniedziałek, 10.08.2026" — nazwa dnia po polsku, bez zależności od locale."""
    return f'{_DNI_TYGODNIA[dzien.weekday()]}, {dzien.strftime("%d.%m.%Y")}'


def temat(dzien):
    return (f'Raport produkcji — {dzien.strftime("%d.%m.%Y")} '
            f'({_DNI_TYGODNIA[dzien.weekday()]})')


def wyslij_raport(dane, zalacznik, odbiorcy=None):
    """
    Wysyła raport na skonfigurowaną listę adresów.

    Args:
        dane: dict z daily_report_service.zbierz_dane()
        zalacznik: bajty pliku XLSX z daily_report_export.build_daily_xlsx()
        odbiorcy: lista adresów nadpisująca konfigurację (tryb --do w CLI)

    Returns:
        int: liczba adresów, do których poszedł mail. Zero znaczy „pusta lista,
             nie wysyłano" — to nie jest błąd.
    """
    from .daily_report_export import nazwa_pliku

    # Parametr nazywa się tak samo jak publiczna funkcja odbiorcy() i przesłania
    # ją w całym ciele — dlatego odczyt z konfiguracji idzie przez prywatny alias.
    adresy = odbiorcy if odbiorcy is not None else _odbiorcy_z_konfiguracji()
    if not adresy:
        return 0

    dzien = dane['dzien']
    kolejka_szt = sum(s['kolejka_szt'] or 0 for s in dane['stanowiska'])
    kolejka_m3 = sum(s['kolejka_m3'] or 0 for s in dane['stanowiska'])

    msg = Message(subject=temat(dzien),
                  sender=_nadawca(),
                  recipients=adresy)
    msg.html = render_template(
        'emails/raport_dzienny.html',
        dzien_slownie=_dzien_slownie(dzien),
        zakonczone=dane['zakonczone'],
        ludzie=dane['ludzie'],
        trakownia=dane['trakownia'],
        terminy=dane['terminy'],
        kolejka_szt=kolejka_szt,
        kolejka_m3=kolejka_m3,
    )
    msg.attach(nazwa_pliku(dzien), TYP_XLSX, zalacznik)

    mail.send(msg)
    return len(adresy)


def _nadawca():
    from flask import current_app
    return current_app.config['MAIL_USERNAME']
