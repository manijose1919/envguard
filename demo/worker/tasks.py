import os

DATABASE_URL = os.environ["DATABASE_URL"]
SMTP_HOST = os.getenv("SMTP_HOST", "localhost")
SMTP_PASSWORD = os.environ.get("SMTP_PASSWORD")


def send_report():
    print(f"sending via {SMTP_HOST} using db {DATABASE_URL}")
