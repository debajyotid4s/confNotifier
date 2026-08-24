"""
Reusable SMTP mailer for Firebase custom flows (OTP, password reset, etc.)
Reads config from env — works with any SMTP (Gmail, SendGrid, Mailgun, your domain).
Also supports Resend API as alternative (RESEND_API_KEY).

Env:
  SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASS, SMTP_FROM, SMTP_TLS (1/0)
  # or
  RESEND_API_KEY, RESEND_FROM
"""
import os
import logging
import smtplib
import ssl
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

logger = logging.getLogger(__name__)


def _smtp_configured() -> bool:
    return bool(os.environ.get("SMTP_HOST") and os.environ.get("SMTP_FROM"))


def _resend_configured() -> bool:
    return bool(os.environ.get("RESEND_API_KEY"))


def send_email(to: str, subject: str, html: str, text: str | None = None) -> bool:
    # Prefer Resend API if configured (simpler DNS, better deliverability)
    if _resend_configured():
        try:
            import requests
            api_key = os.environ["RESEND_API_KEY"]
            from_addr = os.environ.get("RESEND_FROM") or os.environ.get("SMTP_FROM") or "Call4Paper <verify@call4paper.com>"
            r = requests.post(
                "https://api.resend.com/emails",
                headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
                json={"from": from_addr, "to": [to], "subject": subject, "html": html, "text": text or html},
                timeout=10,
            )
            if r.status_code in (200, 201):
                logger.info("email sent via Resend to %s id=%s", to, r.json().get("id"))
                return True
            logger.warning("Resend failed %s %s", r.status_code, r.text[:500])
        except Exception as e:
            logger.warning("Resend send failed to %s: %s", to, e)
            # fall through to SMTP if available

    if not _smtp_configured():
        logger.warning("SMTP not configured — set SMTP_HOST/SMTP_FROM or RESEND_API_KEY")
        return False

    host = os.environ["SMTP_HOST"]
    port = int(os.environ.get("SMTP_PORT", "587"))
    user = os.environ.get("SMTP_USER")
    password = os.environ.get("SMTP_PASS")
    from_addr = os.environ["SMTP_FROM"]
    use_tls = os.environ.get("SMTP_TLS", "1") == "1"

    msg = MIMEMultipart("alternative")
    msg["From"] = from_addr
    msg["To"] = to
    msg["Subject"] = subject
    if text:
        msg.attach(MIMEText(text, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP(host, port, timeout=10) as s:
            if use_tls:
                s.starttls(context=ctx)
            if user and password:
                s.login(user, password)
            s.sendmail(from_addr, [to], msg.as_string())
        logger.info("email sent via SMTP %s:%s to %s", host, port, to)
        return True
    except Exception as e:
        logger.error("SMTP send failed to %s via %s:%s: %s", to, host, port, e)
        return False


def send_verification_otp(to: str, code: str) -> bool:
    subject = "Verify your Call4Paper account — code inside"
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto;color:#1a1a1a">
      <div style="background:#53192D;color:#fff;padding:20px;text-align:center;border-radius:12px 12px 0 0">
        <h1 style="margin:0;font-size:22px">Call4Paper</h1>
        <p style="margin:4px 0 0;opacity:0.9;font-size:13px">Conference Tracker</p>
      </div>
      <div style="padding:24px;background:#fff;border:1px solid #e5e5e5;border-top:none;border-radius:0 0 12px 12px">
        <p style="font-size:15px">You signed up with <b>{to}</b>. Use this code to verify your email:</p>
        <p style="text-align:center;font-size:32px;letter-spacing:8px;font-weight:700;background:#f5f0f2;padding:16px;border-radius:10px;margin:16px 0">{code}</p>
        <p style="font-size:13px;color:#666">Code expires in 10 minutes. If you didn't request this, ignore.</p>
      </div>
      <p style="font-size:11px;color:#999;text-align:center;margin-top:12px">This is an automated message from Call4Paper — please don't reply.</p>
    </div>
    """
    text = f"Your Call4Paper verification code is {code} (expires in 10 min) for {to}."
    return send_email(to, subject, html, text)


def send_password_reset_otp(to: str, code: str) -> bool:
    subject = "Reset your Call4Paper password"
    html = f"""
    <div style="font-family:system-ui,sans-serif;max-width:480px;margin:0 auto;color:#1a1a1a">
      <div style="background:#53192D;color:#fff;padding:20px;text-align:center;border-radius:12px 12px 0 0">
        <h1 style="margin:0;font-size:22px">Call4Paper</h1>
      </div>
      <div style="padding:24px;background:#fff;border:1px solid #e5e5e5;border-top:none;border-radius:0 0 12px 12px">
        <p>Reset code for <b>{to}</b>:</p>
        <p style="text-align:center;font-size:32px;letter-spacing:8px;font-weight:700;background:#f5f0f2;padding:16px;border-radius:10px">{code}</p>
        <p style="font-size:13px;color:#666">Expires in 10 minutes. If you didn't ask, ignore.</p>
      </div>
    </div>
    """
    text = f"Your Call4Paper reset code is {code} for {to}."
    return send_email(to, subject, html, text)
