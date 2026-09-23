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
from .whatsapp_service import send_whatsapp_template


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
        "returned": "Returned",
        "return_request": "Return Request",
        "return_requested": "Return Request",
        "return request": "Return Request",
    }

    if getattr(booking, "is_return_requested", False) and not getattr(booking, "is_returned", False):
        whatsapp_status = "Return Request"
    else:
        whatsapp_status = status_map.get(
            booking.status,
            booking.status
        )

    if whatsapp_status == "Return Request":
        template_name = "return_request"
        event_key = f"return_request:{order_id}"
    elif whatsapp_status == "accepted":
        template_name = "booking_approved"
        event_key = f"booking_approved:{order_id}"
    elif whatsapp_status == "Cancel":
        template_name = "cancel_booking"
        event_key = f"cancel_booking:{order_id}"
    elif whatsapp_status == "Returned":
        template_name = "return_approved"
        event_key = f"return_approved:{order_id}"
    else:
        template_name = f"booking_{whatsapp_status}"
        event_key = f"booking_{whatsapp_status}:{order_id}"

    return send_whatsapp_template(
        phone_number=phone,
        template_name=template_name,
        variables=[requestor_name, order_id, request_type, whatsapp_status, "HEMOAID"],
        event_key=event_key,
        link=f"/admin/app/history/?order_id={order_id}",
    )