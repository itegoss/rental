import requests
from django.conf import settings


def send_whatsapp_test():
    url = settings.WHATSAPP_API

    payload = {
        "authToken": settings.WHATSAPP_ACCESS_TOKEN,
        "name": "Test Customer",
        "sendto": "917798354386",
        "originWebsite": "https://www.itegoss.in/",
        "templateName": "utility_dear_284305",
        "language": "en",
        "buttonValue": "https://www.sickbed.itegoss.in",
        "data": [
            "requestor_name",
            "order_id",
            "request_type",
            "status",
            "HEMOAID",
            "http://www.sickbed.itegoss.in"
        ],
    }

    response = requests.post(settings.WHATSAPP_API,json=payload)


    print("WhatsApp Status:", response.status_code)
    print("WhatsApp Response:", response.text)

    return response


from .models import History


def send_booking_whatsapp(booking_id):
    booking = History.objects.get(id=booking_id)

    requestor_name = booking.renter_name or ""
    order_id = booking.order_id or ""
    request_type = booking.rental_item.title if booking.rental_item else "Medical Equipment"
    phone = booking.phone or ""

    status_map = {
        "pending": "received",
        "approved": "accepted",
        "delivered": "fulfilled",
        "cancelled": "Cancel",
        "rejected": "Cancel",
    }

    whatsapp_status = status_map.get(
        booking.status,
        booking.status
    )

    return send_whatsapp_message(
        phone=phone,
        requestor_name=requestor_name,
        order_id=order_id,
        request_type=request_type,
        status=whatsapp_status,
    )