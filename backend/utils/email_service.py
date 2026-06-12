import asyncio
import logging
import os

import resend

logger = logging.getLogger(__name__)
EMAIL_SEND_TIMEOUT_SECONDS = 12


class EmailDeliveryError(RuntimeError):
    def __init__(self, message: str, reason: str = "send_failed"):
        super().__init__(message)
        self.reason = reason


def build_driver_verification_html(driver_name: str, code: str) -> str:
    return f"""
    <div style="font-family:Arial,sans-serif;background:#f8fafc;padding:24px;color:#0f172a">
      <div style="max-width:520px;margin:0 auto;background:#ffffff;border:1px solid #e2e8f0;border-radius:12px;padding:24px">
        <p style="font-size:12px;text-transform:uppercase;letter-spacing:0.12em;color:#64748b;margin:0 0 12px">ProDelivery Bacău</p>
        <h1 style="font-size:24px;line-height:1.2;margin:0 0 12px">Confirmare email livrator</h1>
        <p style="font-size:15px;line-height:1.6;margin:0 0 18px">Salut, {driver_name}. Folosește codul de mai jos pentru a confirma adresa de email în aplicație.</p>
        <div style="font-size:34px;font-weight:700;letter-spacing:0.18em;text-align:center;background:#0f172a;color:#ffffff;border-radius:10px;padding:16px 20px;margin:18px 0">{code}</div>
        <p style="font-size:13px;line-height:1.6;color:#64748b;margin:0">Codul expiră în 30 de minute. Dacă nu ai cerut acest cont, poți ignora emailul.</p>
      </div>
    </div>
    """


async def send_driver_verification_email(recipient_email: str, driver_name: str, code: str) -> dict:
    api_key = os.environ.get("RESEND_API_KEY")
    sender_email = os.environ.get("SENDER_EMAIL")
    if not api_key or not sender_email:
        logger.warning("Driver verification email skipped because Resend is not configured")
        raise EmailDeliveryError("Serviciul de email nu este configurat", reason="not_configured")
    resend.api_key = api_key
    params = {
        "from": sender_email,
        "to": [recipient_email],
        "subject": "Cod verificare ProDelivery Bacău",
        "html": build_driver_verification_html(driver_name, code),
    }
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(resend.Emails.send, params),
            timeout=EMAIL_SEND_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        logger.exception("Timed out sending driver verification email")
        raise EmailDeliveryError("Emailul de verificare nu a putut fi trimis la timp", reason="timeout") from exc
    except Exception as exc:
        error_text = str(exc)
        normalized_error = error_text.lower()
        logger.exception("Failed to send driver verification email")
        if (
            "testing domain restriction" in normalized_error
            or "only send testing emails to your own email address" in normalized_error
            or "verify a domain at resend.com/domains" in normalized_error
            or "resend.dev" in normalized_error
        ):
            raise EmailDeliveryError(
                "Senderul de test Resend poate trimite doar către emailul owner până la verificarea domeniului.",
                reason="test_domain_restricted",
            ) from exc
        raise EmailDeliveryError("Emailul de verificare nu a putut fi trimis", reason="send_failed") from exc
