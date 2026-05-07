"""
Sentry — inicjalizacja monitoringu błędów

Wywoływane PRZED utworzeniem instancji Flask w `create_app()`.
Konfiguracja czytana z `config/core.json` -> klucz `SENTRY`.

Przykładowa konfiguracja w core.json:
    "SENTRY": {
        "enabled": true,
        "dsn": "https://...@...ingest.de.sentry.io/...",
        "environment": "production",          // "production" | "local"
        "traces_sample_rate": 0.0,            // performance tracing — 0 = wyłączone
        "send_default_pii": false             // jeśli true, wysyła IP/headers
    }
"""

import os
import json
import subprocess
from typing import Any, Dict, Optional

# Pola, które NIGDY nie mogą trafić do Sentry (poza domyślnym scrubbingiem SDK).
_SENSITIVE_KEYS = {
    "password", "passwd", "new_password", "repeat_password", "password2",
    "reset_token", "session_token", "user_session_token", "secret_key",
    "api_key", "jwt_secret", "MAIL_PASSWORD", "PRODUCTION_CRON_SECRET",
    "Authorization", "authorization", "cookie", "Cookie",
}


def _scrub(event: Dict[str, Any], hint: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """before_send hook — dodatkowe usuwanie wrażliwych pól."""
    try:
        request = event.get("request") or {}
        for bucket in ("data", "headers", "cookies", "query_string"):
            payload = request.get(bucket)
            if isinstance(payload, dict):
                for key in list(payload.keys()):
                    if key in _SENSITIVE_KEYS or key.lower() in _SENSITIVE_KEYS:
                        payload[key] = "[Filtered]"
        extra = event.get("extra") or {}
        for key in list(extra.keys()):
            if key in _SENSITIVE_KEYS:
                extra[key] = "[Filtered]"
    except Exception:
        # Cokolwiek pójdzie nie tak w hooku — nie blokuj wysyłki eventu.
        pass
    return event


def _detect_release(app_root: str) -> Optional[str]:
    """Wersja release = krótki SHA bieżącego commita; None jeśli git niedostępny."""
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=app_root,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).decode("utf-8").strip()
        return f"woodpower-crm@{sha}" if sha else None
    except Exception:
        return None


def init_sentry(app_root: str) -> bool:
    """Inicjalizuje Sentry SDK. Zwraca True gdy włączone i poprawnie skonfigurowane."""
    config_path = os.path.join(app_root, "config", "core.json")
    if not os.path.exists(config_path):
        return False

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        return False

    sentry_cfg = config.get("SENTRY") or {}
    if not sentry_cfg.get("enabled"):
        return False

    dsn = sentry_cfg.get("dsn")
    if not dsn:
        return False

    try:
        import sentry_sdk
        from sentry_sdk.integrations.flask import FlaskIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration
        from sentry_sdk.integrations.logging import LoggingIntegration
    except ImportError:
        # SDK nie zainstalowane — nie blokuj uruchomienia aplikacji.
        print("[Sentry] sentry-sdk nie zainstalowane — pomijam init", flush=True)
        return False

    import logging

    environment = sentry_cfg.get(
        "environment",
        "production" if os.environ.get("FLASK_ENV") == "production" else "local",
    )

    sentry_sdk.init(
        dsn=dsn,
        environment=environment,
        release=_detect_release(app_root),
        send_default_pii=bool(sentry_cfg.get("send_default_pii", False)),
        traces_sample_rate=float(sentry_cfg.get("traces_sample_rate", 0.0)),
        integrations=[
            FlaskIntegration(),
            SqlalchemyIntegration(),
            LoggingIntegration(
                level=logging.INFO,           # logi INFO+ jako breadcrumbs (kontekst do eventu)
                event_level=logging.CRITICAL, # tylko CRITICAL log -> event; wyjątki i tak łapie integracja Flask
            ),
        ],
        before_send=_scrub,
        max_breadcrumbs=50,
    )

    try:
        print(f"[Sentry] Zainicjalizowane (env={environment})", flush=True)
    except (BrokenPipeError, OSError):
        # Passenger może mieć zamknięty stdout w trakcie restartu — ignoruj.
        pass
    return True


def get_frontend_config(app_root: str) -> Optional[Dict[str, Any]]:
    """Zwraca konfig Sentry dla frontendu do wstrzyknięcia w template context.
    Zwraca None gdy `SENTRY_FRONTEND` wyłączone, brak DSN lub brak configu."""
    config_path = os.path.join(app_root, "config", "core.json")
    if not os.path.exists(config_path):
        return None

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = json.load(f)
    except Exception:
        return None

    fe_cfg = config.get("SENTRY_FRONTEND") or {}
    if not fe_cfg.get("enabled") or not fe_cfg.get("dsn"):
        return None

    return {
        "enabled": True,
        "dsn": fe_cfg["dsn"],
        "environment": fe_cfg.get(
            "environment",
            "production" if os.environ.get("FLASK_ENV") == "production" else "local",
        ),
        "release": _detect_release(app_root),
        "traces_sample_rate": float(fe_cfg.get("traces_sample_rate", 0.0)),
        "send_default_pii": bool(fe_cfg.get("send_default_pii", False)),
    }
