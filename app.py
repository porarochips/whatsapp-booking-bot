from typing import Any, Dict, Optional
from flask import Flask, jsonify, request
import requests
from config import Config
from customer_flow import handle_customer_message
from database import get_business_by_phone_number_id
from owner_commands import handle_owner_command
from scheduler import run_report_for_business
from scheduler import run_report_for_business
app = Flask(__name__)


def send_whatsapp_text(phone_number_id: str, to_phone: str, body: str) -> None:
    if not Config.WHATSAPP_TOKEN:
        print(f"[DEV REPLY -> {to_phone} via {phone_number_id}]: {body}")
        return

    url = f"https://graph.facebook.com/{Config.WHATSAPP_API_VERSION}/{phone_number_id}/messages"
    headers = {
        "Authorization": f"Bearer {Config.WHATSAPP_TOKEN}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "recipient_type": "individual",
        "to": str(to_phone),
        "type": "text",
        "text": {"preview_url": False, "body": body},
    }
    resp = requests.post(url, headers=headers, json=payload, timeout=15)
    if not resp.ok:
        print(f"[WhatsApp Send Error {resp.status_code}]: {resp.text}")


def extract_incoming_message(payload: Dict[str, Any]) -> Optional[Dict[str, str]]:
    try:
        entry = payload["entry"][0]
        change = entry["changes"][0]
        value = change["value"]
        messages = value.get("messages")
        if not messages:
            return None
        msg = messages[0]
        if msg.get("type") != "text":
            return None
        return {
            "phone_number_id": str(value["metadata"]["phone_number_id"]),
            "sender_phone": str(msg["from"]),
            "text": msg["text"]["body"].strip(),
        }
    except (KeyError, IndexError, TypeError):
        return None


@app.route("/health", methods=["GET"])
def health():
    return jsonify({"status": "ok"}), 200


@app.route("/webhook", methods=["GET"])
def verify_webhook():
    mode = request.args.get("hub.mode")
    token = request.args.get("hub.verify_token")
    challenge = request.args.get("hub.challenge")
    if mode == "subscribe" and token == Config.WHATSAPP_VERIFY_TOKEN:
        return challenge, 200
    return "Forbidden", 403


@app.route("/webhook", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}
    incoming = extract_incoming_message(data)
    if not incoming:
        return jsonify({"status": "ignored"}), 200

    business = get_business_by_phone_number_id(incoming["phone_number_id"])
    if not business:
        return jsonify({"status": "unknown_business"}), 200

    sender_phone = incoming["sender_phone"]
    owner_phone = str(business.get("owner_phone", ""))
    text = incoming["text"]

    if owner_phone and sender_phone == owner_phone:
        reply = handle_owner_command(text, business)
    else:
        reply = handle_customer_message(text, sender_phone, business)

    send_whatsapp_text(incoming["phone_number_id"], sender_phone, reply)
    return jsonify({"status": "processed"}), 200
    if owner_phone and sender_phone == owner_phone:
        reply = handle_owner_command(
            text,
            business,
            on_trigger_pdf=run_report_for_business,
        )
    else:
        reply = handle_customer_message(text, sender_phone, business)
    if owner_phone and sender_phone == owner_phone:
        reply = handle_owner_command(
            text,
            business,
            on_trigger_pdf=run_report_for_business,
        )
    else:
        reply = handle_customer_message(text, sender_phone, business)

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)