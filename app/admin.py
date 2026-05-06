from django.contrib import admin
from django.utils.html import format_html
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import reverse
from django.conf import settings

import re
import urllib.parse

from .models import (
    Inventory,
    History,
    Payment,
    UserDetail,
    Customer,
    Notification,
    Receipt,
    Item,
    Services,
    Cart,
    CartItem,
    NotifyRequest,
)
from .utils import generate_receipt, send_notification, send_whatsapp_message

@admin.action(description="Approve Return")
def approve_return(modeladmin, request, queryset):
    for rr in queryset:
        if rr.is_return_requested and not rr.is_returned:
            rr.is_returned = True
            rr.is_return_requested = False   
            rr.status = "approved"   
            rr.save()
            try:
                rr.rental_item.update_availability()
            except Exception:
                try:
                    rr.rental_item.save()
                except Exception:
                    pass

            try:
                send_notification(
                    title=f"Product Returned: {rr.rental_item.title}",
                    message=(
                        f"Return approved for order {rr.order_id}. "
                        f"Item: {rr.rental_item.title}, quantity {rr.quantity}."
                    ),
                    notification_type='return',
                    link=f"/admin/app/history/{rr.id}/change/"
                )
            except Exception as e:
                print(f"[admin notification error] {e}")


@admin.register(Receipt)
class ReceiptAdmin(admin.ModelAdmin):
    list_display = (
        "rental_request",
        "receipt_type",
        "created_at",
        "download_receipt",
    )

    list_filter = ("receipt_type", "created_at")
    search_fields = ("rental_request__order_id",)
    readonly_fields = ("rental_request", "receipt_type", "file")

    def download_receipt(self, obj):
        if obj.file:
            return format_html(
                '<a href="{}" target="_blank">Download</a>',
                obj.file.url
            )
        return "—"

    download_receipt.short_description = "Receipt"


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = (
        'item_name',
        'item_qty',
        'price',
        'donation',
        'donor_name',
        'donor_contact',
        'created_at',
    )
    search_fields = ('item_name', 'donor_name')
    list_filter = ('donation',)


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ('title', 'type', 'is_read', 'created_at')
    list_filter = ('type', 'is_read', 'created_at')
    search_fields = ('title', 'message')
    actions = ['mark_as_read']

    @admin.action(description='Mark selected notifications as read')
    def mark_as_read(self, request, queryset):
        queryset.update(is_read=True)


@admin.register(History)
class HistoryAdmin(admin.ModelAdmin):

    list_display = (
        'user','rental_item','renter_name','start_date','end_date',
        'extended_end_date','actual_return_date','get_rental_days',
        'get_per_day_rent','status','total_amount','is_reminder_sent',
        'is_overdue_email_sent','order_id','deposit','download_receipt',
        'send_whatsapp','patient_name','delivery_option','delivery_charge',
        'is_return_requested','is_returned','send_reminder_whatsapp',
    )

    list_filter = ('status','payment_method','start_date','end_date','extended_end_date')

    search_fields = ('user__username','rental_item__title','patient_name','order_id')

    actions = [approve_return]

    fields = (
        'user','rental_item','renter_name','start_date','end_date',
        'extended_end_date','actual_return_date','quantity','payment_method',
        'deposit','delivery_option','delivery_charge','status',
        'is_return_requested','is_returned','order_id','patient_name',
    )

    readonly_fields = ('order_id','total_amount')

    change_list_template = 'admin/history_changelist.html'

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        
        # Handle report generation
        if request.method == 'POST' and 'generate_report' in request.POST:
            start_date = request.POST.get('start_date')
            end_date = request.POST.get('end_date')
            
            if start_date and end_date:
                from datetime import datetime
                start = datetime.strptime(start_date, '%Y-%m-%d').date()
                end = datetime.strptime(end_date, '%Y-%m-%d').date()
                
                # Filter history records
                queryset = self.get_queryset(request).filter(
                    start_date__gte=start,
                    start_date__lte=end
                )
                
                # Generate PDF report
                return self.generate_report_pdf(queryset, start, end)
        
        return super().changelist_view(request, extra_context)

    def generate_report_pdf(self, queryset, start_date, end_date):
        from reportlab.pdfgen import canvas
        from reportlab.lib.pagesizes import letter, A4
        from reportlab.lib.units import inch
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer
        from reportlab.lib import colors
        from io import BytesIO
        from django.http import HttpResponse
        
        buffer = BytesIO()
        doc = SimpleDocTemplate(buffer, pagesize=A4)
        elements = []
        styles = getSampleStyleSheet()
        
        # Title
        title = Paragraph(f"Rental History Report ({start_date} to {end_date})", styles['Heading1'])
        elements.append(title)
        elements.append(Spacer(1, 12))
        
        # Summary
        total_orders = queryset.count()
        total_revenue = sum(q.total_amount or 0 for q in queryset)
        total_deposit = sum(q.deposit * q.quantity for q in queryset)
        
        summary_data = [
            ['Total Orders', str(total_orders)],
            ['Total Revenue', f"₹{total_revenue}"],
            ['Total Deposit', f"₹{total_deposit}"],
        ]
        
        summary_table = Table(summary_data, colWidths=[2*inch, 2*inch])
        summary_table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 14),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(summary_table)
        elements.append(Spacer(1, 24))
        
        # Table data
        data = [['Order ID', 'User', 'Item', 'Start Date', 'End Date', 'Status', 'Total Amount']]
        
        for history in queryset:
            data.append([
                history.order_id or 'N/A',
                history.user.username,
                history.rental_item.title,
                str(history.start_date),
                str(history.end_date),
                history.status,
                f"₹{history.total_amount or 0}",
            ])
        
        table = Table(data, colWidths=[1*inch, 1.5*inch, 2*inch, 1*inch, 1*inch, 1*inch, 1*inch])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.grey),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BOTTOMPADDING', (0, 0), (-1, 0), 12),
            ('BACKGROUND', (0, 1), (-1, -1), colors.beige),
            ('GRID', (0, 0), (-1, -1), 1, colors.black),
        ]))
        elements.append(table)
        
        doc.build(elements)
        buffer.seek(0)
        
        response = HttpResponse(buffer.getvalue(), content_type='application/pdf')
        response['Content-Disposition'] = f'attachment; filename="rental_report_{start_date}_to_{end_date}.pdf"'
        return response

    def get_rental_days(self, obj):
        return obj.rental_days
    get_rental_days.short_description = "Rental Days"

    def get_per_day_rent(self, obj):
        return f"₹{obj.rental_item.price_per_day}" if obj.rental_item else "—"
    get_per_day_rent.short_description = "Per Day Rent"

    def stock_status(self, obj):
        return obj.stock_status()
    stock_status.short_description = "Stock Status"

    def download_receipt(self, obj):
        try:
            first = obj.receipts.order_by('-created_at').first()
            if first and first.file:
                url = reverse("admin:download_receipt", args=[obj.pk])
                return format_html(
                    '<a class="button" href="{}" target="_blank">Download</a>',
                    url
                )
        except:
            pass
        return "—"

    download_receipt.short_description = "Receipt"

    def send_whatsapp(self, obj):
        try:
            phone = obj.user.userdetail.phone
        except:
            return "—"

        if obj.extended_end_date and obj.extended_end_date > obj.end_date:
            date_val = obj.extended_end_date
            message = (
                f"Hello {obj.user.username},\n\n"
                f"Your rental has been extended \n\n"
                f"🛏 Item: {obj.rental_item.title}\n"
                f"New Return Date: {date_val.strftime('%d-%m-%Y')}\n\n"
                f"Thank you.\n"
                f"— Team"
            )
        else:
            date_val = obj.end_date
            message = (
                f"Hello {obj.user.username},\n\n"
                f"Your rental is approved \n\n"
                f"🛏 Item: {obj.rental_item.title}\n"
                f"Return Date: {date_val.strftime('%d-%m-%Y')}\n\n"
                f"Thank you.\n"
                f"— Team"
            )

        encoded = urllib.parse.quote(message)
        url = f"https://wa.me/91{phone}?text={encoded}"

        return format_html(
            '<a href="{}" target="_blank" style="color:green;font-weight:600;">WhatsApp</a>',
            url
        )

    send_whatsapp.short_description = "Send WhatsApp"

    def send_reminder_whatsapp(self, obj):
        try:
            phone = obj.user.userdetail.phone
        except:
            return "—"

        final_date = obj.extended_end_date or obj.end_date

        message = (
            f"Hello {obj.user.username},\n\n"
            f"Reminder \n\n"
            f"🛏 Item: {obj.rental_item.title}\n"
            f" Return Date: {final_date.strftime('%d-%m-%Y')}\n\n"
            f"Please return or extend.\n\n"
            f"Thank you \n"
            f"— Team"
        )

        encoded = urllib.parse.quote(message)
        url = f"https://wa.me/91{phone}?text={encoded}"

        return format_html(
            '<a href="{}" target="_blank" style="color:orange;font-weight:600;">Reminder</a>',
            url
        )

    send_reminder_whatsapp.short_description = "Reminder"

@admin.register(Payment)
class PaymentAdmin(admin.ModelAdmin):
    list_display = (
        'rental_request',
        'payment_id',
        'order_id',
        'payment_status',
        'payment_date',
    )
    search_fields = (
        'payment_id',
        'order_id',
        'rental_request__user__username',
    )
    list_filter = ('payment_status', 'payment_date')

@admin.register(UserDetail)
class UserDetailAdmin(admin.ModelAdmin):
    list_display = ('user', 'phone', 'id_proof_type', 'id_proof_number', 'city', 'state', 'pincode')
    search_fields = ('user__username', 'phone', 'id_proof_type', 'city', 'state')
    list_filter = ('state',)
    fields = (
        'user',
        'phone',
        'address_line1',
        'city',
        'state',
        'pincode',
        'id_proof_type',
        'id_proof_number',
        'email',
        'patient_name',
    )


@admin.register(Services)
class ServicesAdmin(admin.ModelAdmin):
    list_display = ('title', 'contact_number')


class CartItemInline(admin.TabularInline):
    model = CartItem
    extra = 0

@admin.register(Cart)
class CartAdmin(admin.ModelAdmin):
    list_display = ('id', 'user', 'created_at')
    inlines = [CartItemInline]

@admin.register(CartItem)
class CartItemAdmin(admin.ModelAdmin):
    list_display = ('cart', 'rental_item', 'quantity', 'created_at')
    list_filter = ('created_at',)


@admin.register(Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ('name', 'phone', 'patient_name', 'created_at')
    search_fields = ('name', 'phone', 'patient_name')



@admin.register(NotifyRequest)
class NotifyRequestAdmin(admin.ModelAdmin):
    list_display = ('email', 'mobile', 'item', 'is_notified', 'created_at')
    list_filter = ('is_notified', 'created_at', 'item')
    search_fields = ('email', 'mobile', 'item__title')
    readonly_fields = ('created_at',)



