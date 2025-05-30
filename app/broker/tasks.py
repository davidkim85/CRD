import os
from asgiref.sync import async_to_sync
from app.broker.celery import celery_app
from app.configurations.email_config import create_message, mail
from PIL import Image
import os
@celery_app.task
def send_email(recipients: list[str], subject: str, body: str):
    try:
        print("Sending email...")
        message = create_message(recipients=recipients, subject=subject, body=body)
        async_to_sync(mail.send_message)(message)
        print(f"✅ Email sent to {recipients}")
    except Exception as e:
        print(f"❌ Failed to send email to {recipients}: {e}")



@celery_app.task
def process_image(filename: str):
    try:
        with Image.open(filename) as img:
            print(f"🖼️ Processing image: {filename}")
            original_width, original_height = img.size
            # Determine the smallest side
            min_side = min(original_width, original_height)
            # Resize image by equalizing the sides
            new_size = (min_side, min_side)
            img = img.resize(new_size)
            img=img.resize((1024,1024))
            img.save(filename, optimize=True, quality=85)
            print(f"✅ Image processed and saved: {filename}")
    except Exception as e:
        print(f"❌ Failed to process image {filename}: {e}")

