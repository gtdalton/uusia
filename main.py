import os
import smtplib
from email.mime.text import MIMEText

import selenium
from dotenv import load_dotenv

load_dotenv()


def check_books():
    return "Checking books failed"

def send_email(message):
    user = os.getenv("EMAIL_USER")
    password = os.getenv("EMAIL_PASSWORD")
    msg = MIMEText(message)
    msg["Subject"] = "Daily Library"
    msg["From"] = f"Uusia Daily Email<{user}>"
    msg["To"] = user

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(user, password)
        server.send_message(msg)


def main():
    message = check_books()
    send_email(message)
