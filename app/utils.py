from django.core.mail import send_mail
from django.conf import settings
from django.core.files.base import ContentFile
from django.utils.text import get_valid_filename
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from io import BytesIO
import re
from .models import Notification, UserDetail, History, BookingExtension, Payment
import requests
from decimal import Decimal
from django.utils import timezone

def receipt_filename(order):
    renter_name = (
        getattr(order, "renter_name", None)
        or order.user.get_full_name()
        or order.user.username
        or getattr(order, "order_id", None)
        or "receipt"
    )
    filename = get_valid_filename(str(renter_name).strip()).strip("._")
    return f"{filename or 'receipt'}.pdf"

def send_overdue_email(user, rental):
    subject = "Rental Overdue Notice"
    renter_name = rental.renter_name or (user.get_full_name() or user.username)
    message = (
        f"Dear {renter_name},\n\n"
        f"Your rental order {rental.order_id} was due on {rental.end_date} "
        "and is now overdue.\n\n"
        "QuickNest Team"
    )

    send_mail(
        subject,
        message,
        getattr(settings, 'EMAIL_HOST_USER', settings.DEFAULT_FROM_EMAIL),
        [user.email],
        fail_silently=False
    )

def build_booking_receipt_breakdown(rental, related_rentals):
    rental_rows = list(related_rentals)
    original_item_totals = []
    original_total_rent = Decimal("0")
    original_total_deposit = Decimal("0")
    total_quantity = 0

    for rr in rental_rows:
        original_days = (rr.end_date - rr.start_date).days + 1 if rr.start_date and rr.end_date else 0
        rent_per_day_total = rr.rental_item.price_per_day * rr.quantity
        deposit_total = rr.deposit * rr.quantity
        rent_amount = rent_per_day_total * original_days

        original_item_totals.append({
            "title": rr.rental_item.title,
            "quantity": rr.quantity,
            "deposit": deposit_total,
            "price_per_day": rr.rental_item.price_per_day,
            "days": original_days,
            "rent_amount": rent_amount,
            "total": rent_amount + deposit_total,
        })

        total_quantity += rr.quantity
        original_total_rent += rent_amount
        original_total_deposit += deposit_total

    delivery_charge = rental.delivery_charge if rental.delivery_option == "delivery" else Decimal("0")
    extension_rows = BookingExtension.objects.filter(
        rental_request__in=rental_rows
    ).select_related("rental_request", "rental_request__rental_item")

    grouped_extensions = {}
    for ext in extension_rows:
        item_total_per_day = ext.rent_per_day * ext.quantity
        if ext.extension_no not in grouped_extensions:
            grouped_extensions[ext.extension_no] = {
                "extension_no": ext.extension_no,
                "extended_on": ext.extended_on,
                "previous_return_date": ext.previous_return_date,
                "new_return_date": ext.new_return_date,
                "extra_days": ext.extra_days,
                "rent_per_day": Decimal("0"),
                "additional_rent": Decimal("0"),
                "additional_deposit": Decimal("0"),
                "extension_total": Decimal("0"),
                "is_inferred": False,
            }
        grouped_extensions[ext.extension_no]["rent_per_day"] += item_total_per_day
        grouped_extensions[ext.extension_no]["additional_rent"] += ext.additional_rent
        grouped_extensions[ext.extension_no]["additional_deposit"] += ext.additional_deposit
        grouped_extensions[ext.extension_no]["extension_total"] += ext.extension_total

    if not grouped_extensions and rental.extended_end_date and rental.extended_end_date > rental.end_date:
        extra_days = (rental.extended_end_date - rental.end_date).days
        rent_per_day = sum((rr.rental_item.price_per_day * rr.quantity for rr in rental_rows), Decimal("0"))
        additional_rent = rent_per_day * extra_days
        grouped_extensions[1] = {
            "extension_no": 1,
            "extended_on": None,
            "previous_return_date": rental.end_date,
            "new_return_date": rental.extended_end_date,
            "extra_days": extra_days,
            "rent_per_day": rent_per_day,
            "additional_rent": additional_rent,
            "additional_deposit": Decimal("0"),
            "extension_total": additional_rent,
            "is_inferred": True,
        }

    extension_history = [grouped_extensions[key] for key in sorted(grouped_extensions)]
    extension_total = sum((ext["extension_total"] for ext in extension_history), Decimal("0"))
    original_total_amount = original_total_rent + original_total_deposit + delivery_charge
    final_total_amount = original_total_amount + extension_total
    amount_paid = sum((rr.amount_paid for rr in rental_rows), Decimal("0"))

    # Calculate how much of the delivery charge is paid
    rent_deposit_total = original_total_rent + original_total_deposit
    mathematical_delivery_paid = max(amount_paid - rent_deposit_total, Decimal("0"))
    mathematical_delivery_paid = min(mathematical_delivery_paid, delivery_charge)

    if rental.is_delivery_paid:
        delivery_paid = delivery_charge
        unpaid_delivery = delivery_charge - mathematical_delivery_paid
        amount_remaining = max(final_total_amount - amount_paid - unpaid_delivery, Decimal("0"))
    else:
        delivery_paid = mathematical_delivery_paid
        amount_remaining = max(final_total_amount - amount_paid, Decimal("0"))

    original_days = (rental.end_date - rental.start_date).days + 1 if rental.start_date and rental.end_date else 0
    total_extra_days = sum((ext["extra_days"] for ext in extension_history), 0)
    total_rent_days = original_days + total_extra_days
    effective_return_date = extension_history[-1]["new_return_date"] if extension_history else rental.end_date

    return {
        "original_item_totals": original_item_totals,
        "original_booking_date": rental.created_at.date() if rental.created_at else timezone.now().date(),
        "original_start_date": rental.start_date,
        "original_return_date": rental.end_date,
        "original_days": original_days,
        "total_extra_days": total_extra_days,
        "total_rent_days": total_rent_days,
        "effective_return_date": effective_return_date,
        "original_total_rent": original_total_rent,
        "original_total_deposit": original_total_deposit,
        "original_total_amount": original_total_amount,
        "extension_history": extension_history,
        "extension_total": extension_total,
        "final_total_amount": final_total_amount,
        "amount_paid": amount_paid,
        "amount_remaining": amount_remaining,
        "delivery_paid": delivery_paid,
        "total_quantity": total_quantity,
    }

def generate_receipt(order):
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.lib import colors
    from reportlab.lib.colors import HexColor
    
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=40, bottomMargin=40)
    elements = []
    styles = getSampleStyleSheet()

    # Custom styles
    title_style = ParagraphStyle(
        'ReceiptTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=18,
        leading=22,
        textColor=HexColor('#1b8a4b'),
        alignment=1,
        spaceAfter=10
    )
    section_title_style = ParagraphStyle(
        'SectionTitle',
        parent=styles['Heading2'],
        fontName='Helvetica-Bold',
        fontSize=11,
        leading=14,
        textColor=HexColor('#1b8a4b'),
        spaceBefore=10,
        spaceAfter=5
    )
    normal_style = ParagraphStyle(
        'NormalText',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=12,
        textColor=HexColor('#2c3e50')
    )
    bold_style = ParagraphStyle(
        'BoldText',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=12,
        textColor=HexColor('#2c3e50')
    )
    header_cell_style = ParagraphStyle(
        'HeaderCell',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=8,
        leading=10,
        textColor=colors.whitesmoke,
        alignment=1
    )
    center_cell_style = ParagraphStyle(
        'CenterCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        alignment=1
    )
    item_title_style = ParagraphStyle(
        'ItemTitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10
    )

    # 1. Header Title
    elements.append(Paragraph("Kutch Yuvak Sangh, Bhayandar", title_style))
    elements.append(Paragraph("RENTAL BOOKING RECEIPT", ParagraphStyle('SubTitle', parent=title_style, fontSize=12, textColor=HexColor('#333333'), spaceAfter=15)))
    elements.append(Spacer(1, 10))

    # Fetch breakdown details
    related_rentals = History.objects.filter(order_id=order.order_id).select_related("rental_item")
    breakdown = build_booking_receipt_breakdown(order, related_rentals)

    # 2. Patient & Booking Details
    elements.append(Paragraph("Patient & Booking Details", section_title_style))
    user_detail = UserDetail.objects.filter(user=order.user).first()
    renter_name = order.renter_name or (user_detail.patient_name if user_detail else (order.user.get_full_name() or order.user.username))
    patient_name = order.patient_name or (user_detail.patient_name if user_detail else "N/A")
    address = order.address or (user_detail.address_line1 if user_detail else "N/A")
    phone = order.phone or (user_detail.phone if user_detail else "N/A")

    details_data = [
        [Paragraph("<b>Renter Name:</b>", normal_style), Paragraph(str(renter_name), normal_style), Paragraph("<b>Booking Date:</b>", normal_style), Paragraph(breakdown['original_start_date'].strftime('%d %b %Y'), normal_style)],
        [Paragraph("<b>Address:</b>", normal_style), Paragraph(str(address), normal_style), Paragraph("<b>Return Date:</b>", normal_style), Paragraph(breakdown['effective_return_date'].strftime('%d %b %Y'), normal_style)],
        [Paragraph("<b>Contact No:</b>", normal_style), Paragraph(str(phone), normal_style), Paragraph("<b>Rent Days:</b>", normal_style), Paragraph(f"{breakdown['total_rent_days']} Days", normal_style)],
        [Paragraph("<b>Patient Name:</b>", normal_style), Paragraph(str(patient_name), normal_style), Paragraph("", normal_style), Paragraph("", normal_style)],
    ]
    details_table = Table(details_data, colWidths=[90, 171, 90, 172])
    details_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('LINEBELOW', (0, 0), (-1, -1), 0.5, HexColor('#e5e7eb')),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 2),
        ('TOPPADDING', (0, 0), (-1, -1), 2),
    ]))
    elements.append(details_table)
    elements.append(Spacer(1, 10))

    # 4. Item details table
    item_header = [
        Paragraph("Sr No", header_cell_style),
        Paragraph("Item", header_cell_style),
        Paragraph("Qty", header_cell_style),
        Paragraph("Deposit", header_cell_style),
        Paragraph("Rent / Day", header_cell_style),
        Paragraph("Days", header_cell_style),
        Paragraph("Total", header_cell_style)
    ]
    item_rows = [item_header]
    for idx, it in enumerate(breakdown['original_item_totals'], 1):
        item_rows.append([
            Paragraph(str(idx), center_cell_style),
            Paragraph(it['title'], item_title_style),
            Paragraph(str(it['quantity']), center_cell_style),
            Paragraph(f"Rs. {it['deposit']:.2f}", center_cell_style),
            Paragraph(f"Rs. {it['price_per_day']:.2f}", center_cell_style),
            Paragraph(str(it['days']), center_cell_style),
            Paragraph(f"Rs. {it['rent_amount']:.2f}", center_cell_style),
        ])
    
    item_table = Table(item_rows, colWidths=[40, 160, 40, 70, 70, 50, 93])
    item_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1b8a4b')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ffffff'), HexColor('#f9f9f9')]),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#ccc')),
    ]))
    elements.append(item_table)
    elements.append(Spacer(1, 10))

    # 5. Extension History (if any)
    if breakdown['extension_history']:
        elements.append(Paragraph("Extension History", section_title_style))
        ext_header = [
            Paragraph("Ext No", header_cell_style),
            Paragraph("Extended On", header_cell_style),
            Paragraph("Prev Return Date", header_cell_style),
            Paragraph("New Return Date", header_cell_style),
            Paragraph("Extra Days", header_cell_style),
            Paragraph("Rent / Day", header_cell_style),
            Paragraph("Add. Rent", header_cell_style),
            Paragraph("Add. Deposit", header_cell_style),
            Paragraph("Ext Total", header_cell_style)
        ]
        ext_rows = [ext_header]
        for ext in breakdown['extension_history']:
            ext_date_str = ext['extended_on'].strftime('%d %b %Y %H:%M') if ext['extended_on'] else 'N/A'
            ext_rows.append([
                Paragraph(str(ext['extension_no']), center_cell_style),
                Paragraph(ext_date_str, center_cell_style),
                Paragraph(ext['previous_return_date'].strftime('%d %b %Y'), center_cell_style),
                Paragraph(ext['new_return_date'].strftime('%d %b %Y'), center_cell_style),
                Paragraph(str(ext['extra_days']), center_cell_style),
                Paragraph(f"Rs. {ext['rent_per_day']:.2f}", center_cell_style),
                Paragraph(f"Rs. {ext['additional_rent']:.2f}", center_cell_style),
                Paragraph(f"Rs. {ext['additional_deposit']:.2f}", center_cell_style),
                Paragraph(f"Rs. {ext['extension_total']:.2f}", center_cell_style)
            ])
        ext_table = Table(ext_rows, colWidths=[40, 85, 75, 75, 50, 50, 50, 50, 48])
        ext_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1b8a4b')),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
            ('TOPPADDING', (0, 0), (-1, -1), 4),
            ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
            ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ffffff'), HexColor('#f9f9f9')]),
            ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#ccc')),
        ]))
        elements.append(ext_table)
        elements.append(Spacer(1, 10))

    # 6. Final Summary / Totals
    elements.append(Paragraph("Final Invoice Details", section_title_style))
    delivery_charge = order.delivery_charge if order.delivery_option == "delivery" else Decimal("0")
    return_pickup_charge = getattr(order, 'return_pickup_charge', Decimal("0")) or Decimal("0")
    
    right_normal_style = ParagraphStyle('RightNormal', parent=normal_style, alignment=2)
    
    delivery_paid = breakdown.get("delivery_paid", Decimal("0"))
    if getattr(order, 'is_delivery_paid', False) or (delivery_charge > 0 and delivery_paid >= delivery_charge):
        del_paid_status = " (Paid)"
    elif delivery_paid > 0:
        del_paid_status = f" (Rs. {delivery_paid:.2f} Paid)"
    else:
        del_paid_status = ""
    del_charge_text = f"Rs. {delivery_charge:.2f}{del_paid_status if order.delivery_option == 'delivery' else ''}"

    summary_rows = [
        [Paragraph("<b>Rent Amount:</b>", normal_style), Paragraph(f"Rs. {breakdown['original_total_rent']:.2f}", right_normal_style)],
    ]
    if breakdown['extension_history']:
        summary_rows.append(
            [Paragraph("<b>Extension Rent:</b>", normal_style), Paragraph(f"Rs. {breakdown['extension_total']:.2f}", right_normal_style)]
        )
    summary_rows.append(
        [Paragraph("<b>Delivery Charges:</b>", normal_style), Paragraph(del_charge_text, right_normal_style)]
    )
    if return_pickup_charge > 0:
        summary_rows.append(
            [Paragraph("<b>Return Delivery Charges:</b>", normal_style), Paragraph(f"Rs. {return_pickup_charge:.2f}", right_normal_style)]
        )
    summary_rows.append(
        [Paragraph("<b>Deposit Total:</b>", normal_style), Paragraph(f"Rs. {breakdown['original_total_deposit']:.2f}", right_normal_style)]
    )
    if getattr(order, 'deposit_donated', False) or getattr(order, 'donation_amount', 0):
        don_amt = getattr(order, 'donation_amount', 0) or breakdown['original_total_deposit']
        summary_rows.append(
            [Paragraph("<b>Donation Amount:</b>", normal_style), Paragraph(f"Rs. {don_amt:.2f}", ParagraphStyle('RightGreen', parent=bold_style, textColor=HexColor('#1b8a4b'), alignment=2))]
        )
    
    summary_rows.append(
        [Paragraph("<b>Total Amount:</b>", ParagraphStyle('LargeBold', parent=bold_style, fontSize=10, textColor=HexColor('#1b8a4b'))), 
         Paragraph(f"Rs. {breakdown['final_total_amount']:.2f}", ParagraphStyle('LargeBoldRight', parent=bold_style, fontSize=10, textColor=HexColor('#1b8a4b'), alignment=2))]
    )
    summary_rows.append(
        [Paragraph("<b>Paid Amount:</b>", normal_style), Paragraph(f"Rs. {breakdown['amount_paid']:.2f}", ParagraphStyle('PaidAmtRight', parent=bold_style, textColor=HexColor('#1b8a4b'), alignment=2))]
    )
    summary_rows.append(
        [Paragraph("<b>Balanced Amount:</b>", normal_style), Paragraph(f"Rs. {breakdown['amount_remaining']:.2f}", ParagraphStyle('RemainAmtRight', parent=bold_style, textColor=HexColor('#ec2427'), alignment=2))]
    )

    summary_table = Table(summary_rows, colWidths=[200, 120])
    summary_table.hAlign = 'RIGHT'
    summary_table.setStyle(TableStyle([
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('LINEBELOW', (0, -1), (-1, -1), 1, HexColor('#1b8a4b')),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 15))

    # Terms agreement & Thank you
    elements.append(Paragraph("You hereby agree to all terms & conditions mentioned on our booking portal", 
                              ParagraphStyle('Terms', parent=normal_style, fontSize=8, alignment=1, textColor=HexColor('#7f8c8d'))))
    elements.append(Spacer(1, 5))
    elements.append(Paragraph("Thank you for booking with us.", 
                              ParagraphStyle('ThankYou', parent=bold_style, fontSize=10, alignment=1, textColor=HexColor('#1b8a4b'))))

    doc.build(elements)
    buffer.seek(0)
    return ContentFile(buffer.getvalue(), receipt_filename(order))

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

def send_notification(title, message, notification_type='info', link=None, order_id=None, rental=None):
    raw_message = message

    # Determine order_id dynamically from link, order_id, or rental request
    if not order_id and link and "order_id=" in link:
        import urllib.parse
        try:
            parsed = urllib.parse.urlparse(link)
            q = urllib.parse.parse_qs(parsed.query)
            if "order_id" in q:
                order_id = q["order_id"][0]
        except Exception:
            pass

    # If we have a rental object, use its order_id
    if rental and not order_id:
        order_id = getattr(rental, 'order_id', None)

    # Fetch and append item details if order_id is available
    if order_id:
        try:
            related_rentals = History.objects.filter(order_id=order_id).select_related('rental_item')
            if related_rentals.exists():
                details_list = []
                for rr in related_rentals:
                    details_list.append(
                        f"- {rr.rental_item.title} (Qty: {rr.quantity}) | Rent: ₹{rr.total_rent} (₹{rr.rental_item.price_per_day}/day) | Deposit: ₹{rr.deposit * rr.quantity} (₹{rr.deposit} each)"
                    )
                item_details_str = "\n".join(details_list)
                message = f"{message}\n\nItem Details:\n{item_details_str}"
        except Exception as e:
            print(f"[send_notification append items error] {e}")

    try:
        Notification.objects.create(
            title=title,
            message=message,
            type=notification_type,
            link=link,
        )
    except Exception as e:
        print(f"[notification db error] {e}")

    # Determine renter's email first to prevent duplicate standalone admin notifications
    renter_email = None
    if rental:
        renter_email = getattr(rental, 'email', None) or (rental.user.email if hasattr(rental, 'user') else None)
    elif order_id:
        try:
            first_rr = History.objects.filter(order_id=order_id).first()
            if first_rr:
                renter_email = getattr(first_rr, 'email', None) or (first_rr.user.email if hasattr(first_rr, 'user') else None)
        except Exception:
            pass

    admin_email = getattr(settings, 'ADMIN_EMAIL', 'bhayander@kutchyuvaksangh.org') or 'bhayander@kutchyuvaksangh.org'
    # Standalone admin email notification is sent if:
    # 1. Renter copy will not be sent (because renter_email is not present)
    # 2. OR if it is a system/admin notification type (not in 'booking', 'payment', 'return')
    should_send_admin_standalone = False
    if admin_email:
        if not renter_email:
            should_send_admin_standalone = True
        elif notification_type not in ('booking', 'payment', 'return'):
            should_send_admin_standalone = True

    if should_send_admin_standalone:
        try:
            send_mail(
                subject=f"Admin Notification: {title}",
                message=message,
                from_email=getattr(settings, 'EMAIL_HOST_USER', settings.DEFAULT_FROM_EMAIL),
                recipient_list=[admin_email],
                fail_silently=False,
            )
            print(f"[email notification] sent to admin {admin_email}")
        except Exception as e:
            print(f"[email notification error] {e}")

    if renter_email and notification_type in ('booking', 'payment', 'return'):
        # Determine customer name
        customer_name = "Customer"
        target_rental = rental
        if not target_rental and order_id:
            try:
                target_rental = History.objects.filter(order_id=order_id).first()
            except Exception:
                pass
        
        # Build the detailed receipt section in email if target_rental is available
        action_message = raw_message
        if target_rental:
            try:
                customer_name = getattr(target_rental, 'renter_name', None) or (target_rental.user.get_full_name() or target_rental.user.username if hasattr(target_rental, 'user') else "Customer")
                is_non_superuser = hasattr(target_rental, 'user') and target_rental.user and not target_rental.user.is_superuser
                related_rentals = History.objects.filter(order_id=target_rental.order_id).select_related('rental_item')
                
                # Format custom action prefix message based on title and initiator
                items_names = ", ".join(rr.rental_item.title for rr in related_rentals)
                title_lower = title.lower()
                message_lower = message.lower()
                is_by_admin = ("by kys" in message_lower or "user kys" in message_lower or "admin kys" in message_lower)

                if "return request submitted" in title_lower or "request to return" in title_lower:
                    if is_by_admin:
                        action_message = f"Your order id is : {target_rental.order_id} for {items_names} is return successfully."
                    else:
                        if is_non_superuser:
                            action_message = f"Your order id is : {target_rental.order_id} for {items_names} your return request successfully sent to admin."
                        else:
                            action_message = f"Your order id is : {target_rental.order_id} for {items_names} is request to return."
                elif "return approved" in title_lower or "order returned" in title_lower:
                    action_message = f"Your order id is : {target_rental.order_id} for {items_names} is return successfully."
                elif "return date extended" in title_lower or "extended" in title_lower:
                    action_message = f"Your order id is : {target_rental.order_id} for {items_names} your return date is extended."
                elif "order approved" in title_lower or "approved" in title_lower:
                    action_message = f"Your order id is : {target_rental.order_id} for {items_names} is approve."
                elif "new booking" in title_lower or "booking created" in title_lower or "payment successful" in title_lower:
                    if is_by_admin or target_rental.status == "approved" or "payment successful" in title_lower:
                        action_message = f"Your order id is : {target_rental.order_id} for {items_names} is approve."
                    else:
                        if is_non_superuser:
                            action_message = f"Your order id is : {target_rental.order_id} for {items_names} your request successfully sent to admin."
                        else:
                            action_message = f"Your order id is : {target_rental.order_id} for {items_names} is request for approve."
            except Exception as e:
                print(f"[send_notification customer details formatting error] {e}")

        # Format custom customer message body
        custom_body = (
            f"Dear {customer_name},\n\n"
            f"{action_message}\n\n"
            "For any further assistance call 9867348169 / 9820247550 or login to sickbed.itegoss.in\n\n"
            "Thank you"
        )

        try:
            from django.core.mail import EmailMessage
            
            # Send to renter, CC to admin (unless they are the same address)
            cc_list = [admin_email] if admin_email and admin_email != renter_email else []
            
            email_msg = EmailMessage(
                subject="Sickbed service notifications",
                body=custom_body,
                from_email=getattr(settings, 'EMAIL_HOST_USER', settings.DEFAULT_FROM_EMAIL),
                to=[renter_email],
                cc=cc_list,
            )
            
            # Generate and attach the receipt PDF
            if target_rental:
                try:
                    pdf_file = generate_receipt(target_rental)
                    pdf_content = pdf_file.read()
                    pdf_name = receipt_filename(target_rental)
                    email_msg.attach(pdf_name, pdf_content, "application/pdf")
                except Exception as ex:
                    print(f"[send_notification pdf attachment error] {ex}")
                    
            email_msg.send(fail_silently=False)
            print(f"[email notification] sent renter copy and cc admin for {renter_email}")
        except Exception as e:
            print(f"[email notification renter error] {e}")

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
    m = re.sub(r"\D", "", str(mobile or ""))
    if not m:
        print("[whatsapp] no mobile provided; message not sent")
        return False

    if len(m) == 10:
        to_number = f"whatsapp:+91{m}"
    elif m.startswith("91") and len(m) > 10:
        to_number = f"whatsapp:+{m}"
    else:
        to_number = f"whatsapp:+{m}"

    phone_id = getattr(settings, 'WHATSAPP_PHONE_ID', None)
    access_token = getattr(settings, 'WHATSAPP_ACCESS_TOKEN', None)
    if phone_id and access_token:
        try:
            url = f"https://graph.facebook.com/v17.0/{phone_id}/messages"
            headers = {"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"}
            to_clean = to_number.replace('whatsapp:', '').lstrip('+')
            payload = {
                "messaging_product": "whatsapp",
                "to": to_clean,
                "type": "text",
                "text": {"body": message}
            }
            resp = requests.post(url, json=payload, headers=headers, timeout=10)
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

def generate_rental_report_pdf(queryset, start_date, end_date):
    from reportlab.pdfgen import canvas
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import inch
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
    from reportlab.lib import colors
    from reportlab.lib.colors import HexColor
    from io import BytesIO
    from django.http import HttpResponse
    
    buffer = BytesIO()
    # Use 36-point (0.5 inch) margins for maximum printable A4 width (523 points)
    doc = SimpleDocTemplate(buffer, pagesize=A4, leftMargin=36, rightMargin=36, topMargin=40, bottomMargin=40)
    elements = []
    styles = getSampleStyleSheet()
    
    # Custom Heading Style
    title_style = ParagraphStyle(
        'ReportTitle',
        parent=styles['Heading1'],
        fontName='Helvetica-Bold',
        fontSize=16,
        leading=20,
        textColor=HexColor('#1a365d'),
        alignment=1,  # Center-aligned
        spaceAfter=15
    )
    
    title = Paragraph(f"Rental History Report ({start_date} to {end_date})", title_style)
    elements.append(title)
    elements.append(Spacer(1, 10))
    
    # Calculate Totals
    total_orders = queryset.count()
    total_deposit = sum(q.deposit * q.quantity for q in queryset)
    total_rent = sum(q.total_rent for q in queryset)
    total_donation = sum(q.donation_amount or 0 for q in queryset)
    
    # Summary Styles
    summary_header_style = ParagraphStyle(
        'SummaryHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=10,
        leading=12,
        textColor=colors.whitesmoke,
        alignment=1
    )
    summary_key_style = ParagraphStyle(
        'SummaryKey',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=HexColor('#2c3e50'),
        alignment=0  # Left
    )
    summary_val_style = ParagraphStyle(
        'SummaryVal',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=9,
        leading=11,
        textColor=HexColor('#2c3e50'),
        alignment=1  # Center
    )
    
    summary_data = [
        [Paragraph('Metric', summary_header_style), Paragraph('Value', summary_header_style)],
        [Paragraph('Total Orders', summary_key_style), Paragraph(str(total_orders), summary_val_style)],
        [Paragraph('Total Deposit', summary_key_style), Paragraph(f"Rs. {total_deposit:.2f}", summary_val_style)],
        [Paragraph('Total Revenue (Rent)', summary_key_style), Paragraph(f"Rs. {total_rent:.2f}", summary_val_style)],
        [Paragraph('Total Donation', summary_key_style), Paragraph(f"Rs. {total_donation:.2f}", summary_val_style)],
    ]
    
    summary_table = Table(summary_data, colWidths=[2.5*inch, 2.0*inch])
    summary_table.hAlign = 'CENTER'
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1a365d')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 10),
        ('RIGHTPADDING', (0, 0), (-1, -1), 10),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ffffff'), HexColor('#f8fafc')]),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cbd5e1')),
    ]))
    elements.append(summary_table)
    elements.append(Spacer(1, 20))
    
    # Main Table Styles
    main_header_style = ParagraphStyle(
        'MainHeader',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=9,
        leading=11,
        textColor=colors.whitesmoke,
        alignment=1
    )
    main_cell_style = ParagraphStyle(
        'MainCell',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=HexColor('#2d3748'),
        alignment=1
    )
    
    data = [[
        Paragraph('Order ID', main_header_style),
        Paragraph('Renter Name', main_header_style),
        Paragraph('Item', main_header_style),
        Paragraph('Start Date', main_header_style),
        Paragraph('End Date', main_header_style),
        Paragraph('Rent', main_header_style),
        Paragraph('Donation', main_header_style),
        Paragraph('Deposit', main_header_style),
        Paragraph('Total Amount', main_header_style)
    ]]
    
    for history in queryset:
        renter_name = history.renter_name or (history.user.get_full_name() or history.user.username)
        data.append([
            Paragraph(history.order_id or 'N/A', main_cell_style),
            Paragraph(renter_name, main_cell_style),
            Paragraph(history.rental_item.title, main_cell_style),
            Paragraph(str(history.start_date), main_cell_style),
            Paragraph(str(history.end_date), main_cell_style),
            Paragraph(f"Rs. {history.total_rent:.2f}", main_cell_style),
            Paragraph(f"Rs. {history.donation_amount:.2f}", main_cell_style),
            Paragraph(f"Rs. {(history.deposit * history.quantity):.2f}", main_cell_style),
            Paragraph(f"Rs. {history.total_amount:.2f}", main_cell_style),
        ])
    
    # colWidths sum up to exactly 523 points, matching A4 printable width
    table = Table(data, colWidths=[70, 90, 80, 52, 52, 45, 44, 45, 45])
    table.hAlign = 'CENTER'
    table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, 0), HexColor('#1a365d')),
        ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 6),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 6),
        ('LEFTPADDING', (0, 0), (-1, -1), 6),
        ('RIGHTPADDING', (0, 0), (-1, -1), 6),
        ('ROWBACKGROUNDS', (0, 1), (-1, -1), [HexColor('#ffffff'), HexColor('#f8fafc')]),
        ('GRID', (0, 0), (-1, -1), 0.5, HexColor('#cbd5e1')),
    ]))
    elements.append(table)
    
    doc.build(elements)
    buffer.seek(0)
    
    response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="rental_report_{start_date}_to_{end_date}.pdf"'
    return response
