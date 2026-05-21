import os
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

class Config:
    GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
    TWILIO_SID = os.getenv("TWILIO_SID")
    TWILIO_TOKEN = os.getenv("TWILIO_TOKEN")
    TWILIO_FROM_PHONE = os.getenv("TWILIO_FROM_PHONE")
    TARGET_PHONE_NUMBER = os.getenv("TARGET_PHONE_NUMBER")
    EMAIL_ACCOUNT = os.getenv("EMAIL_ACCOUNT")
    EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
    DB_PATH = os.path.join(os.path.dirname(__file__), "jobs.db")

    @classmethod
    def validate(cls):
        missing = []
        for key in ["GEMINI_API_KEY", "TWILIO_SID", "TWILIO_TOKEN", "TWILIO_FROM_PHONE", "TARGET_PHONE_NUMBER", "EMAIL_ACCOUNT", "EMAIL_PASSWORD"]:
            if not getattr(cls, key):
                missing.append(key)
        if missing:
            print(f"Warning: Missing environment variables: {', '.join(missing)}. Some features may not work.")


Config.validate()
