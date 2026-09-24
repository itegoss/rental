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


def send_booking_whatsapp(booking_id, force=False):
    booking = None
    if isinstance(booking_id, History) or (hasattr(booking_id, "rental_item") and hasattr(booking_id, "order_id")):
        booking = booking_id
    elif isinstance(booking_id, int) or (isinstance(booking_id, str) and booking_id.isdigit()):
        booking = History.objects.filter(id=int(booking_id)).first()
    elif isinstance(booking_id, str):
        booking = History.objects.filter(order_id=booking_id).first()

    if not booking:
        booking = History.objects.get(id=booking_id)

    # Resolve renter name with user fallback
    requestor_name = getattr(booking, "renter_name", None)
    if not requestor_name and hasattr(booking, "user") and booking.user:
        requestor_name = (
            booking.user.get_full_name()
            or booking.user.username
        )
    requestor_name = requestor_name or "Customer"

    order_id = getattr(booking, "order_id", "") or ""
    request_type = (
        booking.rental_item.title
        if getattr(booking, "rental_item", None)
        else "Medical Equipment"
    )

    # Resolve phone with UserDetail fallback
    phone = getattr(booking, "phone", None)
    if not phone and hasattr(booking, "user") and booking.user:
        try:
            from .models import UserDetail
            ud = UserDetail.objects.filter(user=booking.user).first()
            if ud and ud.phone:
                phone = ud.phone
        except Exception:
            pass
    phone = phone or ""

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
        template_name = "new_booking"
        event_key = f"booking_{whatsapp_status}:{order_id}"

    return send_whatsapp_template(
        phone_number=phone,
        template_name=template_name,
        variables=[requestor_name, order_id, request_type, whatsapp_status, "HEMOAID"],
        event_key=event_key,
        link=f"/admin/app/history/?order_id={order_id}",
        force=force,
    )


from .whatsapp_service import (
    BLOOD_REQUEST_STATUS_MAP,
    send_blood_request_received_notification,
    send_blood_request_completed_notification,
    send_blood_request_notification,
    send_booking_receipt_whatsapp,
    send_return_receipt_whatsapp,
)

send_blood_request_whatsapp = send_blood_request_notification
