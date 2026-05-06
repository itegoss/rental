from django.core.mail import send_mail
from django.conf import settings
from django.core.files.base import ContentFile
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from io import BytesIO
import re
from .models import Notification, UserDetail, History
import requests


def send_overdue_email(user, rental):
    subject = "Rental Overdue Notice"
    message = (
        f"Dear {user.get_full_name() or user.username},\n\n"
        f"Your rental order {rental.order_id} was due on {rental.end_date} "
        "and is now overdue.\n\n"
        "QuickNest Team"
    )

    send_mail(
        subject,
        message,
        settings.DEFAULT_FROM_EMAIL,
        [user.email],
        fail_silently=False
    )


def generate_receipt(order):
    buffer = BytesIO()
    p = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    y = height - 50

    p.setFont("Helvetica-Bold", 16)
    p.drawString(180, y, "Rental Receipt")
    y -= 40

    p.setFont("Helvetica", 12)
    p.drawString(50, y, f"Order ID: {order.order_id}"); y -= 20
    p.drawString(50, y, f"User: {order.user.username}"); y -= 20
    p.drawString(50, y, f"Item: {order.rental_item.title}"); y -= 20
    p.drawString(50, y, f"Rental Period: {order.start_date} to {order.end_date}"); y -= 20
    p.drawString(50, y, f"Total Amount: ₹{order.total_amount}"); y -= 20
    if hasattr(order, 'deposit_donated') and order.deposit_donated:
        p.drawString(50, y, "Deposit Donated: Yes"); y -= 20
    p.drawString(50, y, f"Payment Method: {order.payment_method}"); y -= 30

    try:
        d = UserDetail.objects.get(user=order.user)
        p.drawString(50, y, f"Phone: {d.phone or '-'}"); y -= 20
        p.drawString(50, y, f"Address: {d.address_line1 or '-'}"); y -= 20
    except UserDetail.DoesNotExist:
        pass

    p.showPage()
    p.save()
    buffer.seek(0)

    return ContentFile(buffer.getvalue(), f"receipt_{order.order_id}.pdf")


def send_telegram_message(message):
    token = getattr(settings, 'TELEGRAM_BOT_TOKEN', None)
    chat_id = getattr(settings, 'TELEGRAM_CHAT_ID', None)

    if not token or not chat_id:
        print('[telegram] configuration missing, skipping telegram notification')
        return False

    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        'chat_id': chat_id,
        'text': message,
        'parse_mode': 'HTML',
    }

    try:
        resp = requests.post(url, data=payload, timeout=10)
        if resp.status_code in (200, 201):
            print('[telegram] message sent')
            return True
        print(f"[telegram] failed: {resp.status_code} {resp.text}")
    except Exception as e:
        print(f"[telegram] error: {e}")
    return False


def send_notification(title, message, notification_type='info', link=None):
    try:
        Notification.objects.create(
            title=title,
            message=message,
            type=notification_type,
            link=link,
        )
    except Exception as e:
        print(f"[notification db error] {e}")

    admin_email = getattr(settings, 'ADMIN_EMAIL', None)
    if admin_email:
        try:
            send_mail(
                subject=f"Admin Notification: {title}",
                message=message,
                from_email=settings.DEFAULT_FROM_EMAIL,
                recipient_list=[admin_email],
                fail_silently=False,
            )
            print(f"[email notification] sent to {admin_email}")
        except Exception as e:
            print(f"[email notification error] {e}")

    try:
        send_telegram_message(f"<b>{title}</b>\n{message}")
    except Exception as e:
        print(f"[telegram notification error] {e}")

    return True


import datetime
from django.db.models import Max

def generate_sequential_order_id():
    today = datetime.date.today().strftime("%Y%m")
    prefix = f"ORD{today}"

    last_order = (
        History.objects
        .filter(order_id__startswith=prefix)
        .order_by("-order_id")
        .first()
    )

    if last_order and last_order.order_id:
        last_number = int(last_order.order_id[-3:])
        new_number = str(last_number + 1).zfill(3)
    else:
        new_number = "001"

    return f"{prefix}{new_number}"


def send_whatsapp_message(mobile, message):
    """Send a WhatsApp message using Twilio if configured, otherwise log.

    mobile: string digits or with leading +countrycode
    message: text to send
    """
    # Normalize mobile: ensure starts with + and digits only
    m = re.sub(r"\D", "", str(mobile or ""))
    if not m:
        print("[whatsapp] no mobile provided; message not sent")
        return False

    # If looks like 10 digits, assume India +91 as a sensible default
    if len(m) == 10:
        to_number = f"whatsapp:+91{m}"
    elif m.startswith("91") and len(m) > 10:
        to_number = f"whatsapp:+{m}"
    else:
        to_number = f"whatsapp:+{m}"

    # Prefer WhatsApp Cloud API (Meta) if configured
    phone_id = getattr(settings, 'WHATSAPP_PHONE_ID', None)
    access_token = getattr(settings, 'WHATSAPP_ACCESS_TOKEN', None)
    if phone_id and access_token:
        try:
            url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            # WhatsApp Cloud API expects the phone number in E.164 without the leading '+' in some cases;
            # remove any leading plus for the payload value to be safe.
            to_clean = to_number.replace('whatsapp:', '').lstrip('+')
            payload = {
                "messaging_product": "whatsapp",
                "to": to_clean,
                "type": "text",
                "text": {"body": message}
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
            # Log response body for debugging
            try:
                body = resp.json()
            except Exception:
                body = resp.text
            if resp.status_code in (200, 201):
                print(f"[whatsapp cloud sent] To: {to_number} Response: {body}")
                return True
            else:
                print(f"[whatsapp cloud error] status={resp.status_code} body={body}")
        except Exception as e:
            print(f"[whatsapp cloud exception] {e}")

    # Fallback to Twilio if configured
    try:
        from twilio.rest import Client
    except Exception:
        print(f"[whatsapp simulated] To: {to_number} Message: {message}")
        return True

    sid = getattr(settings, "TWILIO_ACCOUNT_SID", None)
    token = getattr(settings, "TWILIO_AUTH_TOKEN", None)
    from_whatsapp = getattr(settings, "TWILIO_WHATSAPP_FROM", None)

    if not all([sid, token, from_whatsapp]):
        print(f"[whatsapp config missing] To: {to_number} Message: {message}")
        return True

    try:
        client = Client(sid, token)
        client.messages.create(body=message, from_=from_whatsapp, to=to_number)
        print(f"[whatsapp sent] To: {to_number}")
        return True
    except Exception as e:
        print(f"[whatsapp error] {e}")
        return False
