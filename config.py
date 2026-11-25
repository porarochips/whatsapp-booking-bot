import os
from dotenv import load_dotenv

load_dotenv()


class Config:
    MONGO_URI = os.getenv("MONGO_URI", "")
    MONGO_DB_NAME = os.getenv("MONGO_DB_NAME", "whatsapp_booking_bot")

    WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN", "")
    WHATSAPP_VERIFY_TOKEN = os.getenv("WHATSAPP_VERIFY_TOKEN", "change_me_verify_token")
    WHATSAPP_API_VERSION = os.getenv("WHATSAPP_API_VERSION", "v21.0")

    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
    SESSION_TTL_MINUTES = int(os.getenv("SESSION_TTL_MINUTES", "45"))

    # Add these right here inside Config:
    SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
    SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
    SMTP_USERNAME = os.getenv("SMTP_USERNAME", "")
    SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
    FROM_EMAIL = os.getenv("FROM_EMAIL", "")