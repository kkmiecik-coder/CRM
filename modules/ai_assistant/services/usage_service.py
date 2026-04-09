"""Logowanie użycia AI — tokeny, model, czas odpowiedzi"""

from extensions import db
from modules.ai_assistant.models import AIUsageLog


class UsageService:

    @staticmethod
    def log_usage(user_id: int, provider: str, model: str,
                  response_time_ms: int, message_id: int = None,
                  tokens_input: int = None, tokens_output: int = None,
                  was_fallback: bool = False) -> AIUsageLog:
        log = AIUsageLog(
            user_id=user_id,
            message_id=message_id,
            provider=provider,
            model=model,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            response_time_ms=response_time_ms,
            was_fallback=was_fallback
        )
        db.session.add(log)
        db.session.commit()
        return log
