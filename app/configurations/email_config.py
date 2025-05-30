from typing import List
from pydantic import BaseModel
from fastapi_mail import FastMail, MessageSchema, ConnectionConfig
from app.configurations.config import MAIL_USERNAME, MAIL_PASSWORD, MAIL_SERVER, MAIL_PORT, MAIL_FROM

# Email configuration
class EmailConfig(BaseModel):
    MAIL_USERNAME: str
    MAIL_PASSWORD: str
    MAIL_SERVER: str
    MAIL_PORT: int
    MAIL_FROM: str
    MAIL_FROM_NAME: str

config = EmailConfig(
    MAIL_USERNAME=MAIL_USERNAME,
    MAIL_PASSWORD=MAIL_PASSWORD,
    MAIL_SERVER=MAIL_SERVER,
    MAIL_PORT=MAIL_PORT,
    MAIL_FROM=MAIL_FROM,
    MAIL_FROM_NAME=MAIL_USERNAME
)

# Initialize FastMail
conf = ConnectionConfig(
    MAIL_USERNAME=config.MAIL_USERNAME,
    MAIL_PASSWORD=config.MAIL_PASSWORD,
    MAIL_FROM=config.MAIL_FROM,
    MAIL_PORT=config.MAIL_PORT,
    MAIL_SERVER=config.MAIL_SERVER,
    MAIL_SSL_TLS=False,
    MAIL_STARTTLS=True,
    USE_CREDENTIALS=True,
    VALIDATE_CERTS=True
)

# Create message schema for email sending
def create_message(recipients: List[str], subject: str, body: str):
    message = MessageSchema(
        subject=subject,
        recipients=recipients,  # List of email addresses
        body=body,
        subtype="html"
    )
    return message

# Initialize FastMail instance
mail = FastMail(conf)
