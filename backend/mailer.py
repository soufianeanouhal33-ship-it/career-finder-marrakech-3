"""Envoi de candidatures (CV en pièce jointe) par SMTP."""
import logging
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, formatdate, make_msgid

logger = logging.getLogger("career_finder.mailer")

EMAIL_RE = re.compile(r"^[^@\s<>\"',;]+@[^@\s<>\"',;]+\.[^@\s<>\"',;]{2,}$")
MAX_CV_BYTES = 5 * 1024 * 1024


class MailError(Exception):
    """Erreur d'envoi, avec un message lisible par l'utilisateur."""


def is_valid_email(value: str) -> bool:
    return bool(value) and len(value) <= 254 and bool(EMAIL_RE.match(value))


def smtp_configured() -> bool:
    return bool(os.getenv("SMTP_HOST") and os.getenv("SMTP_FROM"))


def _safe_header(value: str, max_len: int = 200) -> str:
    """Supprime retours à la ligne et caractères de contrôle (anti-injection d'en-têtes)."""
    return re.sub(r"[\r\n\x00-\x1f]+", " ", value or "").strip()[:max_len]


def _safe_filename(name: str) -> str:
    base = re.sub(r"[^\w.\- ]", "_", os.path.basename(name or "CV.pdf")).strip() or "CV.pdf"
    return base if base.lower().endswith(".pdf") else base + ".pdf"


def build_cv_message(*, to_email: str, subject: str, body: str, cv_bytes: bytes,
                     cv_filename: str, reply_to: str = "") -> EmailMessage:
    from_addr = os.getenv("SMTP_FROM", "")
    msg = EmailMessage()
    msg["From"] = formataddr((_safe_header(os.getenv("SMTP_FROM_NAME", "Career Finder"), 80), from_addr))
    msg["To"] = to_email
    if reply_to:
        msg["Reply-To"] = reply_to
    msg["Subject"] = _safe_header(subject)
    msg["Date"] = formatdate(localtime=True)
    msg["Message-ID"] = make_msgid(domain=from_addr.split("@")[-1] or None)
    msg.set_content(body)
    msg.add_attachment(cv_bytes, maintype="application", subtype="pdf", filename=_safe_filename(cv_filename))
    return msg


def send_message(msg: EmailMessage) -> None:
    """Envoie via SMTP_HOST/PORT. SMTP_SECURITY : 'starttls' (défaut, port 587),
    'ssl' (port 465) ou 'none' (réseau de confiance uniquement)."""
    host = os.getenv("SMTP_HOST", "")
    security = os.getenv("SMTP_SECURITY", "starttls").lower()
    port = int(os.getenv("SMTP_PORT", "465" if security == "ssl" else "587"))
    user = os.getenv("SMTP_USER", "")
    password = os.getenv("SMTP_PASSWORD", "")
    context = ssl.create_default_context()
    try:
        if security == "ssl":
            server = smtplib.SMTP_SSL(host, port, timeout=20, context=context)
        else:
            server = smtplib.SMTP(host, port, timeout=20)
        with server:
            if security == "starttls":
                server.starttls(context=context)
            if user:
                server.login(user, password)
            server.send_message(msg)
    except smtplib.SMTPAuthenticationError:
        logger.error("SMTP : authentification refusée pour %s", user)
        raise MailError("Le serveur e-mail a refusé l'authentification (identifiants SMTP du serveur).")
    except smtplib.SMTPRecipientsRefused:
        raise MailError("L'adresse e-mail de l'entreprise a été refusée par le serveur.")
    except (smtplib.SMTPException, OSError) as e:
        logger.error("SMTP : échec d'envoi (%s)", type(e).__name__)
        raise MailError("Impossible d'envoyer l'e-mail pour le moment (serveur SMTP injoignable ou erreur).")
