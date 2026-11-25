import os
import smtplib
from email.message import EmailMessage
from typing import Any, Dict
import requests
from config import Config


def send_whatsapp_document(
    phone_number_id: str,
    to_phone: str,
    file_path: str,
    caption: str = "",
) -> bool:
    if not Config.WHATSAPP_TOKEN:
        print(f"[DEV WHATSAPP PDF -> {to_phone} via {phone_number_id}]: {file_path} | {caption}")
        return True

    base_url = f"https://graph.facebook.com/{Config.WHATSAPP_API_VERSION}/{phone_number_id}"
    headers_auth = {"Authorization": f"Bearer {Config.WHATSAPP_TOKEN}"}

    with open(file_path, "rb") as f:
        upload_resp = requests.post(
            f"{base_url}/media",
            headers=headers_auth,
            files={"file": (os.path.basename(file_path), f, "application/pdf")},
            data={"messaging_product": "whatsapp"},
            timeout=30,
        )

    if not upload_resp.ok:
        print(f"[WhatsApp Media Upload Error {upload_resp.status_code}]: {upload_resp.text}")
        return False

    media_id = upload_resp.json().get("id")
    if not media_id:
        print(f"[WhatsApp Media Missing ID]: {upload_resp.text}")
        return False

    msg_resp = requests.post(
        f"{base_url}/messages",
        headers={**headers_auth, "Content-Type": "application/json"},
        json={
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": str(to_phone),
            "type": "document",
            "document": {
                "id": media_id,
                "filename": os.path.basename(file_path),
                "caption": caption[:1024],
            },
        },
        timeout=20,
    )
    if not msg_resp.ok:
        print(f"[WhatsApp Document Send Error {msg_resp.status_code}]: {msg_resp.text}")
        return False
    return True


def send_email_with_pdf(
    to_email: str,
    subject: str,
    body_text: str,
    file_path: str,
) -> bool:
    if not to_email:
        return False
    if not Config.SMTP_USERNAME or not Config.SMTP_PASSWORD or not Config.FROM_EMAIL:
        print(f"[DEV EMAIL -> {to_email}]: {subject} | {file_path}")
        return True

    msg = EmailMessage()
    msg["Subject"] = subject
    msg["From"] = Config.FROM_EMAIL
    msg["To"] = to_email
    msg.set_content(body_text)

    with open(file_path, "rb") as f:
        pdf_bytes = f.read()

    msg.add_attachment(
        pdf_bytes,
        maintype="application",
        subtype="pdf",
        filename=os.path.basename(file_path),
    )

    with smtplib.SMTP(Config.SMTP_HOST, Config.SMTP_PORT, timeout=20) as server:
        server.starttls()
        server.login(Config.SMTP_USERNAME, Config.SMTP_PASSWORD)
        server.send_message(msg)
    return True


def deliver_daily_report(
    business: Dict[str, Any],
    date_str: str,
    bookings_count: int,
    pdf_path: str,
) -> None:
    biz_name = business.get("business_name", "Business")
    summary_line = f"{biz_name} — {bookings_count} booking(s) for {date_str}."

    owner_phone = business.get("owner_phone")
    if owner_phone:
        send_whatsapp_document(
            phone_number_id=str(business["phone_number_id"]),
            to_phone=str(owner_phone),
            file_path=pdf_path,
            caption=summary_line,
        )

    owner_email = business.get("owner_email")
    if owner_email:
        send_email_with_pdf(
            to_email=str(owner_email),
            subject=f"Daily Bookings Report — {biz_name} ({date_str})",
            body_text=f"Hi,\n\nAttached is {summary_line}\n",
            file_path=pdf_path,
        )