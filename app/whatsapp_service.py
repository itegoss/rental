import os
import re
import uuid
import logging
import requests
from django.conf import settings
from django.core.cache import cache

logger = logging.getLogger(__name__)

# ==============================================================================
# 1. TEMPLATE REGISTRY
# ==============================================================================
WHATSAPP_TEMPLATES = {
    "new_booking": {
        "name": "new_booking",
        "description": "Triggered when a new medical equipment booking/order is successfully created",
        "template": (
            "Dear {{1}},\n\n"
            "Your order {{2}} for medical equipment is under review. You will receive confirmation soon."
        ),
        "variables": ["Customer Name", "Order ID / Order Number"],
    },
    "booking_approved": {
        "name": "booking_approved",
        "description": "Triggered when a booking/order is approved by admin",
        "template": (
            "Dear {{1}},\n\n"
            "Your order {{2}} for medical equipment has been approved. Our team will coordinate delivery/pickup."
        ),
        "variables": ["Customer Name", "Order ID / Order Number"],
    },
    "cancel_booking": {
        "name": "cancel_booking",
        "description": "Triggered when an existing booking/order is cancelled",
        "template": (
            "Dear {{1}},\n\n"
            "Your order {{2}} for medical equipment has been cancelled per request. For any further details contact support."
        ),
        "variables": ["Customer Name", "Order ID / Order Number"],
    },
    "return_request": {
        "name": "return_request",
        "description": "Triggered when the customer submits a return request",
        "template": (
            "Dear {{1}},\n\n"
            "Your return request for order {{2}} is under review. You will receive confirmation soon."
        ),
        "variables": ["Customer Name", "Order ID / Order Number"],
    },
    "return_approved": {
        "name": "return_approved",
        "description": "Triggered when the return request status changes to Approved/Completed",
        "template": (
            "Dear {{1}},\n\n"
            "Your return request for order {{2}} has been approved/completed successfully."
        ),
        "variables": ["Customer Name", "Order ID / Order Number"],
    },
    "return_date_extended": {
        "name": "return_date_extended",
        "description": "Triggered when the return/due date of an order is extended",
        "template": (
            "Dear {{1}},\n\n"
            "The return date for your order {{2}} has been extended. Please check your order details for the updated return date."
        ),
        "variables": ["Customer Name", "Order ID / Order Number"],
    },
    "new_blood_request": {
        "name": "new_blood_request",
        "description": "Triggered when a new blood request is submitted successfully",
        "template": (
            "Dear {{1}},\n\n"
            "A new blood request {{2}} has been submitted successfully. Our team will review the request and update you soon."
        ),
        "variables": ["Requester's Name", "Blood Request ID"],
    },
    "blood_request_accepted": {
        "name": "blood_request_accepted",
        "description": "Triggered when the blood request status changes to Accepted/Fulfilled",
        "template": (
            "Dear {{1}},\n\n"
            "Your blood request {{2}} has been accepted/fulfilled successfully. Our team will provide further details if required."
        ),
        "variables": ["Requester's Name", "Blood Request ID"],
    },
    "blood_request_cancelled": {
        "name": "blood_request_cancelled",
        "description": "Triggered when a blood request is cancelled",
        "template": (
            "Dear {{1}},\n\n"
            "Your blood request {{2}} has been cancelled. For any further details, please contact support."
        ),
        "variables": ["Requester's Name", "Blood Request ID"],
    },
    "blood_request_fulfilled": {
        "name": "blood_request_fulfilled",
        "description": "Triggered when the blood request is marked as Fulfilled",
        "template": (
            "Dear {{1}},\n\n"
            "Your blood request {{2}} has been fulfilled successfully."
        ),
        "variables": ["Requester's Name", "Blood Request ID"],
    },
    "blood_request_received": {
        "name": "blood_request_received",
        "description": "Triggered when blood is marked as received by the customer",
        "template": (
            "Dear {{1}},\n\n"
            "Blood for your request {{2}} has been confirmed as received."
        ),
        "variables": ["Requester's Name", "Blood Request ID"],
    },
    "blood_request_completed": {
        "name": "blood_request_completed",
        "description": "Triggered when the blood request is marked as Completed",
        "template": (
            "Dear {{1}},\n\n"
            "Your blood request {{2}} has been completed successfully."
        ),
        "variables": ["Requester's Name", "Blood Request ID"],
    },
}


def register_template(name, template_text, variables, description=""):
    """
    Registers a new WhatsApp template into the registry for extensibility.
    """
    WHATSAPP_TEMPLATES[name] = {
        "name": name,
        "description": description,
        "template": template_text,
        "variables": variables,
    }
    logger.info(f"[whatsapp] Registered new template: {name}")


def render_template_text(template_name, variables):
    """
    Renders template message text by replacing {{1}}, {{2}}, etc. with values.
    """
    tmpl = WHATSAPP_TEMPLATES.get(template_name)
    if not tmpl:
        return f"[Template {template_name}] " + " | ".join(str(v) for v in variables)
    
    text = tmpl["template"]
    for idx, val in enumerate(variables, start=1):
        text = text.replace(f"{{{{{idx}}}}}", str(val if val is not None else ""))
    return text


# ==============================================================================
# 2. CONFIGURATION & HELPERS
# ==============================================================================
def get_whatsapp_config():
    """
    Retrieves 11za WhatsApp API credentials from Django settings or environment.
    """
    return {
        "access_token": (
            getattr(settings, "WHATSAPP_ACCESS_TOKEN", None)
            or os.environ.get("WHATSAPP_ACCESS_TOKEN")
        ),
        "api_url": (
            getattr(settings, "WHATSAPP_API", None)
            or os.environ.get("WHATSAPP_API")
            or "https://api.11za.in/apis/template/sendTemplate"
        ),
        "origin_website": (
            getattr(settings, "WHATSAPP_ORIGIN_WEBSITE", None)
            or os.environ.get("WHATSAPP_ORIGIN_WEBSITE")
            or "https://www.itegoss.in/"
        ),
        "template_name": (
            getattr(settings, "WHATSAPP_TEMPLATE_NAME", None)
            or os.environ.get("WHATSAPP_TEMPLATE_NAME")
            or "new_booking"
        ),
        "button_value": (
            getattr(settings, "WHATSAPP_BUTTON_VALUE", None)
            or os.environ.get("WHATSAPP_BUTTON_VALUE")
            or "https://www.itegoss.in/"
        ),
    }


def validate_and_format_phone(phone):
    """
    Validates and formats a phone number for WhatsApp Business Cloud API.
    - Strips non-digit characters.
    - Normalizes Indian 10-digit mobile numbers with 91 prefix.
    - Accepts valid international format (11 to 15 digits).
    - Returns standardized digits string without '+' or spaces, or None if invalid.
    """
    if not phone:
        return None

    raw_str = str(phone).strip()
    digits = re.sub(r"\D", "", raw_str)

    # Remove leading zeros (e.g. 09876543210 -> 9876543210)
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]

    # 10-digit standard Indian phone number
    if len(digits) == 10:
        return f"91{digits}"
    # 12-digit Indian number already prefixed with 91
    elif len(digits) == 12 and digits.startswith("91"):
        return digits
    # General E.164 phone numbers (11 to 15 digits)
    elif 11 <= len(digits) <= 15:
        return digits

    return None


# ==============================================================================
# 3. DEDUPLICATION & AUDIT STORAGE
# ==============================================================================
def is_duplicate_notification(event_key):
    """
    Checks if this event notification was already sent using cache and DB.
    """
    if not event_key:
        return False

    cache_key = f"wa_sent:{event_key}"
    if cache.get(cache_key):
        return True

    # Check Notification table
    try:
        from .models import Notification
        exists = Notification.objects.filter(
            title__startswith="WhatsApp:",
            message__contains=f"EventKey: {event_key}",
        ).exists()
        if exists:
            cache.set(cache_key, True, timeout=86400)
            return True
    except Exception as e:
        logger.warning(f"[whatsapp dedup check error] {e}")

    return False


def record_notification_audit(
    phone_number,
    template_name,
    variables,
    event_key=None,
    message_id=None,
    user=None,
    link=None,
    status="SENT",
):
    """
    Records audit entry in the existing Notification table and cache.
    Reuses the existing Notification model without creating unnecessary tables.
    """
    if event_key:
        cache_key = f"wa_sent:{event_key}"
        cache.set(cache_key, True, timeout=86400)

    try:
        from .models import Notification

        rendered_text = render_template_text(template_name, variables)
        audit_message = (
            f"Template: {template_name}\n"
            f"Phone: {phone_number}\n"
            f"Status: {status}\n"
            f"Message ID: {message_id or 'N/A'}\n"
            f"EventKey: {event_key or 'N/A'}\n\n"
            f"{rendered_text}"
        )

        Notification.objects.create(
            type="info",
            title=f"WhatsApp: {template_name}",
            message=audit_message,
            recipient=user,
            link=link,
        )
    except Exception as e:
        logger.warning(f"[whatsapp audit db error] {e}")


# ==============================================================================
# 4. REUSABLE CORE SEND FUNCTION
# ==============================================================================
def send_whatsapp_template(
    phone_number,
    template_name,
    variables,
    event_key=None,
    user=None,
    link=None,
    force=False,
):
    """
    Core 11za WhatsApp template sender.

    The existing business notification functions call this function, so the
    booking/return/blood flows do not need to call the 11za API directly.
    """
    try:
        print(f"[DEBUG WA] Stage A: WhatsApp notification function entered | template={template_name} | phone={phone_number}")
        if not phone_number:
            logger.warning(
                f"[whatsapp warning] Missing phone number for template {template_name}"
            )
            print(f"[DEBUG WA] Stage B Failed: Exits before API request - Missing phone number for template {template_name}")
            return {"success": False, "error": "Missing phone number"}

        formatted_phone = validate_and_format_phone(phone_number)
        if not formatted_phone:
            logger.warning(
                f"[whatsapp warning] Invalid phone number: {phone_number}"
            )
            print(f"[DEBUG WA] Stage B Failed: Exits before API request - Invalid phone number: {phone_number}")
            return {"success": False, "error": f"Invalid phone number: {phone_number}"}

        if event_key and not force and is_duplicate_notification(event_key):
            logger.info(
                f"[whatsapp dedup] Skipping duplicate message for event_key: {event_key}"
            )
            print(f"[DEBUG WA] Stage B Skipped: Exits before API request - Duplicate event_key: {event_key}")
            return {
                "success": True,
                "duplicate": True,
                "message": "Duplicate skipped",
            }

        config = get_whatsapp_config()
        auth_token = config["access_token"]
        api_url = config["api_url"]
        origin_website = config["origin_website"]
        api_template_name = config["template_name"]
        button_value = config["button_value"]

        if not auth_token:
            logger.error("[whatsapp error] WHATSAPP_ACCESS_TOKEN is missing")
            print(f"[DEBUG WA] Stage C Failed: API request attempted but configuration missing (WHATSAPP_ACCESS_TOKEN is missing)")
            return {"success": False, "error": "WHATSAPP_ACCESS_TOKEN is missing"}

        # The 11za template used by this project has 5 variables:
        # 1 = Requestor name
        # 2 = Order / Request ID
        # 3 = Medical equipment / Blood request
        # 4 = Status
        # 5 = HEMOAID
        padded_variables = list(variables or [])
        while len(padded_variables) < 5:
            padded_variables.append("")

        payload = {
            "authToken": auth_token,
            "name": str(padded_variables[0] or "Customer"),
            "sendto": formatted_phone,
            "originWebsite": origin_website,
            "templateName": api_template_name,
            "language": "en",
            "buttonValue": button_value,
            "headerdata": "",
            "myfile": "",
            "myfileName": "",
            "data": [str(v if v is not None else "") for v in padded_variables[:5]],
            "tags": "",
        }

        print(f"[DEBUG WA] Stage C Passed: API request about to be sent | URL={api_url} | To={formatted_phone} | Template={api_template_name} | Origin={origin_website}")

        try:
            response = requests.post(
                api_url,
                json=payload,
                timeout=15,
            )

            print(f"[DEBUG WA] API response status code: {response.status_code}")
            print(f"[DEBUG WA] API response body: {response.text}")

            try:
                res_json = response.json()
            except Exception:
                res_json = {"raw": response.text}

            if 200 <= response.status_code < 300:
                message_id = None
                if isinstance(res_json, dict):
                    message_id = (
                        res_json.get("messageId")
                        or res_json.get("message_id")
                        or res_json.get("id")
                    )

                logger.info(
                    f"[whatsapp 11za sent] To: {formatted_phone} "
                    f"Template: {api_template_name} Response: {res_json}"
                )
                print(f"[DEBUG WA] Stage D/E: API request succeeded | message_id={message_id}")

                record_notification_audit(
                    formatted_phone,
                    template_name,
                    padded_variables[:5],
                    event_key=event_key,
                    message_id=message_id,
                    user=user,
                    link=link,
                    status="SENT",
                )

                return {
                    "success": True,
                    "message_id": message_id,
                    "response": res_json,
                }

            logger.error(
                f"[whatsapp 11za error] status={response.status_code} "
                f"body={response.text}"
            )
            print(f"[DEBUG WA] Stage D Failed: API request returned error status={response.status_code}")

            record_notification_audit(
                formatted_phone,
                template_name,
                padded_variables[:5],
                event_key=event_key,
                user=user,
                link=link,
                status=f"FAILED_{response.status_code}",
            )

            return {
                "success": False,
                "error": f"11za API error {response.status_code}: {response.text}",
            }

        except requests.RequestException as ex:
            logger.error(f"[whatsapp 11za request exception] {ex}")
            print(f"[DEBUG WA] Stage D Failed: RequestException - {ex}")
            return {"success": False, "error": str(ex)}

    except Exception as e:
        logger.error(f"[whatsapp service unhandled exception] {e}", exc_info=True)
        print(f"[DEBUG WA] Exception details: {type(e).__name__}: {e}")
        return {"success": False, "error": str(e)}


# ==============================================================================
# 5. BUSINESS EVENT NOTIFICATION FUNCTIONS
# ==============================================================================

# Helper to resolve rental / order details
def _resolve_order_details(rental_or_order, customer_name=None, order_id=None, phone_number=None, user=None):
    extracted_order_id = order_id
    extracted_name = customer_name
    extracted_phone = phone_number
    extracted_user = user

    # If an object was provided
    if rental_or_order is not None:
        if hasattr(rental_or_order, "order_id"):
            extracted_order_id = extracted_order_id or getattr(rental_or_order, "order_id", None)
        if hasattr(rental_or_order, "renter_name"):
            extracted_name = extracted_name or getattr(rental_or_order, "renter_name", None)
        if hasattr(rental_or_order, "phone"):
            extracted_phone = extracted_phone or getattr(rental_or_order, "phone", None)
        if hasattr(rental_or_order, "user") and getattr(rental_or_order, "user", None):
            extracted_user = extracted_user or rental_or_order.user
            if not extracted_name:
                extracted_name = (
                    rental_or_order.user.get_full_name()
                    or rental_or_order.user.username
                )
            if not extracted_phone:
                try:
                    from .models import UserDetail
                    ud = UserDetail.objects.filter(user=rental_or_order.user).first()
                    if ud and ud.phone:
                        extracted_phone = ud.phone
                except Exception:
                    pass

    # If rental_or_order was passed as a plain string order_id
    if not extracted_order_id and isinstance(rental_or_order, str):
        extracted_order_id = rental_or_order

    return (
        extracted_name or "Customer",
        extracted_order_id or "N/A",
        extracted_phone,
        extracted_user,
    )


# Helper to resolve blood request details
def _resolve_blood_request_details(blood_request, requester_name=None, request_id=None, phone_number=None):
    extracted_req_id = request_id
    extracted_name = requester_name
    extracted_phone = phone_number
    extracted_user = None

    if blood_request is not None:
        if hasattr(blood_request, "request_id") and blood_request.request_id:
            extracted_req_id = extracted_req_id or blood_request.request_id
        elif hasattr(blood_request, "formatted_request_id"):
            extracted_req_id = extracted_req_id or blood_request.formatted_request_id
        elif hasattr(blood_request, "id") and blood_request.id:
            extracted_req_id = extracted_req_id or f"BR-{blood_request.id}"

        if hasattr(blood_request, "coordinator_name") and blood_request.coordinator_name:
            extracted_name = extracted_name or blood_request.coordinator_name
        elif hasattr(blood_request, "created_by") and blood_request.created_by:
            extracted_name = extracted_name or (
                blood_request.created_by.get_full_name()
                or blood_request.created_by.username
            )

        if hasattr(blood_request, "coordinator_contact") and blood_request.coordinator_contact:
            extracted_phone = extracted_phone or blood_request.coordinator_contact
        elif hasattr(blood_request, "reference_contact") and blood_request.reference_contact:
            extracted_phone = extracted_phone or blood_request.reference_contact

        if hasattr(blood_request, "created_by"):
            extracted_user = blood_request.created_by

    if not extracted_req_id and isinstance(blood_request, str):
        extracted_req_id = blood_request

    return (
        extracted_name or "Requester",
        extracted_req_id or "N/A",
        extracted_phone,
        extracted_user,
    )


# ------------------------------------------------------------------------------
# 1. NEW BOOKING / PLACE ORDER
# ------------------------------------------------------------------------------
def send_new_booking_notification(rental_or_order=None, customer_name=None, order_id=None, phone_number=None, user=None, force=False):
    """
    Template: new_booking
    Variables: {{1}} = Customer Name, {{2}} = Order ID
    Trigger: When a new medical equipment booking/order is successfully created.
    """
    name, oid, phone, usr = _resolve_order_details(
        rental_or_order, customer_name, order_id, phone_number, user
    )
    event_key = f"new_booking:{oid}"
    return send_whatsapp_template(
        phone_number=phone,
        template_name="new_booking",
        variables=[name, oid, "medical equipment", "received", "HEMOAID"],
        event_key=event_key,
        user=usr,
        link=f"/admin/app/history/?order_id={oid}",
        force=force,
    )


# ------------------------------------------------------------------------------
# 1B. BOOKING APPROVED BY ADMIN
# ------------------------------------------------------------------------------
def send_booking_approved_notification(rental_or_order=None, customer_name=None, order_id=None, phone_number=None, user=None, force=False):
    """
    Template: booking_approved
    Variables: {{1}} = Customer Name, {{2}} = Order ID
    Trigger: When an existing booking/order is approved by admin.
    """
    name, oid, phone, usr = _resolve_order_details(
        rental_or_order, customer_name, order_id, phone_number, user
    )
    event_key = f"booking_approved:{oid}"
    return send_whatsapp_template(
        phone_number=phone,
        template_name="booking_approved",
        variables=[name, oid, "medical equipment", "accepted", "HEMOAID"],
        event_key=event_key,
        user=usr,
        link=f"/admin/app/history/?order_id={oid}",
        force=force,
    )


# ------------------------------------------------------------------------------
# 2. CANCEL BOOKING
# ------------------------------------------------------------------------------
def send_cancel_booking_notification(rental_or_order=None, customer_name=None, order_id=None, phone_number=None, user=None, force=False):
    """
    Template: cancel_booking
    Variables: {{1}} = Customer Name, {{2}} = Order ID
    Trigger: When an existing booking/order is cancelled.
    """
    name, oid, phone, usr = _resolve_order_details(
        rental_or_order, customer_name, order_id, phone_number, user
    )
    event_key = f"cancel_booking:{oid}"
    return send_whatsapp_template(
        phone_number=phone,
        template_name="cancel_booking",
        variables=[name, oid, "medical equipment", "Cancel", "HEMOAID"],
        event_key=event_key,
        user=usr,
        link=f"/admin/app/history/?order_id={oid}",
        force=force,
    )


# ------------------------------------------------------------------------------
# 3. RETURN REQUEST
# ------------------------------------------------------------------------------
def send_return_request_notification(rental_or_order=None, customer_name=None, order_id=None, phone_number=None, user=None, force=False):
    """
    Template: return_request
    Variables: {{1}} = Customer Name, {{2}} = Order ID
    Trigger: When the customer submits a return request.
    """
    name, oid, phone, usr = _resolve_order_details(
        rental_or_order, customer_name, order_id, phone_number, user
    )
    event_key = f"return_request:{oid}"
    return send_whatsapp_template(
        phone_number=phone,
        template_name="return_request",
        variables=[name, oid, "medical equipment", "Return Request", "HEMOAID"],
        event_key=event_key,
        user=usr,
        link=f"/admin/app/history/?order_id={oid}",
        force=force,
    )


# ------------------------------------------------------------------------------
# 4. RETURN APPROVED / COMPLETED
# ------------------------------------------------------------------------------
def send_return_approved_notification(rental_or_order=None, customer_name=None, order_id=None, phone_number=None, user=None, force=False):
    """
    Template: return_approved
    Variables: {{1}} = Customer Name, {{2}} = Order ID
    Trigger: When the return request status changes to Approved/Completed.
    """
    name, oid, phone, usr = _resolve_order_details(
        rental_or_order, customer_name, order_id, phone_number, user
    )
    event_key = f"return_approved:{oid}"
    return send_whatsapp_template(
        phone_number=phone,
        template_name="return_approved",
        variables=[name, oid, "medical equipment", "Returned", "HEMOAID"],
        event_key=event_key,
        user=usr,
        link=f"/admin/app/history/?order_id={oid}",
        force=force,
    )


# ------------------------------------------------------------------------------
# 5. RETURN DATE EXTENDED
# ------------------------------------------------------------------------------
def send_return_date_extended_notification(rental_or_order=None, customer_name=None, order_id=None, phone_number=None, user=None, extension_id=None, force=False):
    """
    Template: return_date_extended
    Variables: {{1}} = Customer Name, {{2}} = Order ID
    Trigger: When the return/due date of an order is extended.
    """
    name, oid, phone, usr = _resolve_order_details(
        rental_or_order, customer_name, order_id, phone_number, user
    )
    ext_suffix = f"_{extension_id}" if extension_id else ""
    event_key = f"return_date_extended:{oid}{ext_suffix}"
    return send_whatsapp_template(
        phone_number=phone,
        template_name="return_date_extended",
        variables=[name, oid, "medical equipment", "Extended", "HEMOAID"],
        event_key=event_key,
        user=usr,
        link=f"/admin/app/history/?order_id={oid}",
        force=force,
    )


# ------------------------------------------------------------------------------
# 6. NEW BLOOD REQUEST SUBMITTED
# ------------------------------------------------------------------------------
def send_new_blood_request_notification(blood_request=None, requester_name=None, request_id=None, phone_number=None, force=False):
    """
    Template: new_blood_request
    Variables: {{1}} = Requester's Name, {{2}} = Blood Request ID
    Trigger: When a new blood request is submitted successfully.
    """
    name, req_id, phone, usr = _resolve_blood_request_details(
        blood_request, requester_name, request_id, phone_number
    )
    event_key = f"new_blood_request:{req_id}"
    return send_whatsapp_template(
        phone_number=phone,
        template_name="new_blood_request",
        variables=[name, req_id, "blood request", "received", "HEMOAID"],
        event_key=event_key,
        user=usr,
        link=f"/request-blood/view/{getattr(blood_request, 'id', '')}/" if blood_request and hasattr(blood_request, 'id') else None,
        force=force,
    )


# ------------------------------------------------------------------------------
# 7. BLOOD REQUEST ACCEPTED / FULFILLED
# ------------------------------------------------------------------------------
def send_blood_request_accepted_notification(blood_request=None, requester_name=None, request_id=None, phone_number=None, force=False):
    """
    Template: blood_request_accepted
    Variables: {{1}} = Requester's Name, {{2}} = Blood Request ID
    Trigger: When the blood request status changes to Accepted/Fulfilled.
    """
    name, req_id, phone, usr = _resolve_blood_request_details(
        blood_request, requester_name, request_id, phone_number
    )
    event_key = f"blood_request_accepted:{req_id}"
    return send_whatsapp_template(
        phone_number=phone,
        template_name="blood_request_accepted",
        variables=[name, req_id, "blood request", "accepted", "HEMOAID"],
        event_key=event_key,
        user=usr,
        link=f"/request-blood/view/{getattr(blood_request, 'id', '')}/" if blood_request and hasattr(blood_request, 'id') else None,
        force=force,
    )


# ------------------------------------------------------------------------------
# 8. BLOOD REQUEST CANCELLED
# ------------------------------------------------------------------------------
def send_blood_request_cancelled_notification(blood_request=None, requester_name=None, request_id=None, phone_number=None, force=False):
    """
    Template: blood_request_cancelled
    Variables: {{1}} = Requester's Name, {{2}} = Blood Request ID
    Trigger: When a blood request is cancelled.
    """
    name, req_id, phone, usr = _resolve_blood_request_details(
        blood_request, requester_name, request_id, phone_number
    )
    event_key = f"blood_request_cancelled:{req_id}"
    return send_whatsapp_template(
        phone_number=phone,
        template_name="blood_request_cancelled",
        variables=[name, req_id, "blood request", "Cancel", "HEMOAID"],
        event_key=event_key,
        user=usr,
        link=f"/request-blood/view/{getattr(blood_request, 'id', '')}/" if blood_request and hasattr(blood_request, 'id') else None,
        force=force,
    )


# ------------------------------------------------------------------------------
# 9. BLOOD REQUEST FULFILLED
# ------------------------------------------------------------------------------
def send_blood_request_fulfilled_notification(blood_request=None, requester_name=None, request_id=None, phone_number=None, force=False):
    """
    Template: blood_request_fulfilled
    Variables: {{1}} = Requester's Name, {{2}} = Blood Request ID
    Trigger: When the blood request is marked as Fulfilled.
    """
    name, req_id, phone, usr = _resolve_blood_request_details(
        blood_request, requester_name, request_id, phone_number
    )
    event_key = f"blood_request_fulfilled:{req_id}"
    return send_whatsapp_template(
        phone_number=phone,
        template_name="blood_request_fulfilled",
        variables=[name, req_id, "blood request", "fulfilled", "HEMOAID"],
        event_key=event_key,
        user=usr,
        link=f"/request-blood/view/{getattr(blood_request, 'id', '')}/" if blood_request and hasattr(blood_request, 'id') else None,
        force=force,
    )


# ------------------------------------------------------------------------------
# 10. BLOOD REQUEST RECEIVED (CUSTOMER RECEIVED)
# ------------------------------------------------------------------------------
def send_blood_request_received_notification(blood_request=None, requester_name=None, request_id=None, phone_number=None, force=False):
    """
    Template: blood_request_received
    Variables: {{1}} = Requester's Name, {{2}} = Blood Request ID
    Trigger: When the blood is marked as received by the customer.
    WhatsApp var4 = "Blood Received"
    """
    name, req_id, phone, usr = _resolve_blood_request_details(
        blood_request, requester_name, request_id, phone_number
    )
    event_key = f"blood_request_received:{req_id}"
    return send_whatsapp_template(
        phone_number=phone,
        template_name="blood_request_received",
        variables=[name, req_id, "blood request", "Blood Received", "HEMOAID"],
        event_key=event_key,
        user=usr,
        link=f"/request-blood/view/{getattr(blood_request, 'id', '')}/" if blood_request and hasattr(blood_request, 'id') else None,
        force=force,
    )


# ------------------------------------------------------------------------------
# 11. BLOOD REQUEST COMPLETED
# ------------------------------------------------------------------------------
def send_blood_request_completed_notification(blood_request=None, requester_name=None, request_id=None, phone_number=None, force=False):
    """
    Template: blood_request_completed
    Variables: {{1}} = Requester's Name, {{2}} = Blood Request ID
    Trigger: When the blood request is marked as Completed.
    WhatsApp var4 = "Completed"
    """
    name, req_id, phone, usr = _resolve_blood_request_details(
        blood_request, requester_name, request_id, phone_number
    )
    event_key = f"blood_request_completed:{req_id}"
    return send_whatsapp_template(
        phone_number=phone,
        template_name="blood_request_completed",
        variables=[name, req_id, "blood request", "Completed", "HEMOAID"],
        event_key=event_key,
        user=usr,
        link=f"/request-blood/view/{getattr(blood_request, 'id', '')}/" if blood_request and hasattr(blood_request, 'id') else None,
        force=force,
    )


BLOOD_REQUEST_STATUS_MAP = {
    "pending": "received",
    "accepted": "accepted",
    "fulfilled": "fulfilled",
    "cancelled": "Cancel",
    "rejected": "Cancel",
    "received": "Blood Received",
    "blood_received": "Blood Received",
    "blood received": "Blood Received",
    "completed": "Completed",
}


def send_blood_request_notification(blood_request, status=None, force=False):
    """
    Unified dispatcher for blood request status notifications.
    Maps database status to WhatsApp status and dispatches via send_whatsapp_template.
    """
    current_status = status or getattr(blood_request, "status", None) or "pending"
    normalized_key = str(current_status).strip().lower().replace(" ", "_")
    wa_status = BLOOD_REQUEST_STATUS_MAP.get(
        normalized_key,
        BLOOD_REQUEST_STATUS_MAP.get(str(current_status).strip().lower(), current_status)
    )

    if wa_status == "Blood Received":
        return send_blood_request_received_notification(blood_request, force=force)
    elif wa_status == "Completed":
        return send_blood_request_completed_notification(blood_request, force=force)
    elif wa_status == "accepted":
        return send_blood_request_accepted_notification(blood_request, force=force)
    elif wa_status == "fulfilled":
        return send_blood_request_fulfilled_notification(blood_request, force=force)
    elif wa_status == "Cancel":
        return send_blood_request_cancelled_notification(blood_request, force=force)
    else:
        return send_new_blood_request_notification(blood_request, force=force)
