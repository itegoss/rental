# pyrefly: ignore [missing-import]
from django.contrib import admin
from django.utils.html import format_html
from django.http import FileResponse, Http404, HttpResponse, HttpResponseRedirect
from django.urls import path, reverse
from django.conf import settings
from django import forms
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

from .utils import generate_receipt, receipt_filename, send_notification, send_whatsapp_message, generate_rental_report_pdf

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
                    link=f"/admin/app/history/{rr.id}/change/",
                    order_id=rr.order_id,
                    rental=rr
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
                '<a href="{}">Download</a>',
                reverse("admin:download_receipt", args=[obj.rental_request_id])
            )
        return "—"

    download_receipt.short_description = "Receipt"


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):
    list_display = (
        'title',
        'get_total_quantity',
        'price_per_day',
        'available_quantity',
        'booked_quantity',
        'available',
        'item_qty',
        'price',
        'donation',
        'donor_name',
        'next_available_date',
    )
    search_fields = ('title', 'donor_name')
    list_filter = ('available', 'donation')
    
    fieldsets = (
        ('Item Information', {
            'fields': ('title', 'description', 'image')
        }),
        ('Rental Pricing', {
            'fields': ('price_per_day', 'deposit')
        }),
        ('Inventory Management', {
            'fields': ('total_quantity', 'available_quantity', 'booked_quantity', 'available', 'next_available_date')
        }),
        ('Item Tracking', {
            'fields': ('item_qty', 'price', 'donation', 'donor_name', 'donor_contact')
        }),
    )

    def get_total_quantity(self, obj):
        return (obj.booked_quantity or 0) + (obj.available_quantity or 0)
    get_total_quantity.short_description = 'Total Quantity'


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
    search_fields = ('item_name__title', 'donor_name')
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


from django.contrib.admin.views.main import ChangeList

class HistoryChangeList(ChangeList):
    pass

@admin.register(History)
class HistoryAdmin(admin.ModelAdmin):

    list_display = (
        'serial_number','user','rental_item','renter_name', 'email', 'phone','address', 'patient_name','start_date','end_date',
        'extended_end_date','actual_return_date','get_rental_days',
        'get_per_day_rent','status','total_amount','amount_paid','amount_remaining','is_delivery_paid','is_reminder_sent',
        'is_overdue_email_sent','order_id','deposit','download_receipt',
        'view_id_proof',
        'send_whatsapp','patient_name','delivery_option','delivery_charge',
        'is_return_requested','is_returned','send_reminder_whatsapp',
    )
    list_display_links = ('serial_number',)

    list_filter = ('status','payment_method','start_date','end_date','extended_end_date')
    date_hierarchy = 'start_date'

    search_fields = ('user__username','rental_item__title','patient_name','order_id','email')

    actions = [approve_return]

    fields = (
        'id','user','rental_item','renter_name','email','phone','address', 'patient_name','start_date','end_date',
        'extended_end_date','actual_return_date','quantity','payment_method',
        'deposit','delivery_option','delivery_charge','is_delivery_paid','status',
        'amount_paid','amount_remaining','id_proof_type','id_proof_number','id_proof_file','view_id_proof',
        'is_return_requested','is_returned','deposit_donated',
        'donation_amount','donation_comment','order_id',
    )

    readonly_fields = ('id','order_id','total_amount','view_id_proof','amount_remaining')

    def save_model(self, request, obj, form, change):
        obj._from_admin = True
        super().save_model(request, obj, form, change)

        # Regenerate receipt PDF to match any edits made by the admin
        try:
            from .models import Receipt
            from django.core.files.base import ContentFile
            from .utils import receipt_filename
            
            # Find the existing booking receipt
            existing = obj.receipts.filter(receipt_type="booking").order_by('-created_at').first()
            if existing:
                content_file = generate_receipt(obj)
                existing.file.save(receipt_filename(obj), content_file, save=True)
        except Exception as e:
            print(f"[admin save_model receipt regen error] {e}")

    change_list_template = 'admin/history_changelist.html'

    def get_urls(self):
        urls = super().get_urls()
        custom_urls = [
            path(
                '<int:history_id>/download-receipt/',
                self.admin_site.admin_view(self.download_receipt_file),
                name='download_receipt',
            ),
        ]
        return custom_urls + urls

    def download_receipt_file(self, request, history_id):
        obj = self.get_queryset(request).filter(pk=history_id).first()
        if not obj:
            raise Http404("Rental not found")

        receipt = obj.receipts.order_by('-created_at').first()
        if not receipt or not receipt.file:
            raise Http404("Receipt not found")

        return FileResponse(
            receipt.file.open('rb'),
            as_attachment=True,
            filename=receipt_filename(obj),
        )

    def get_changelist(self, request, **kwargs):
        return HistoryChangeList

    def save_model(self, request, obj, form, change):
        super().save_model(request, obj, form, change)
        if not obj.order_id or not obj.id_proof_file:
            return
        update_fields = {
            'id_proof_type': obj.id_proof_type,
            'id_proof_number': obj.id_proof_number,
            'id_proof_file': obj.id_proof_file.name,
        }
        History.objects.filter(order_id=obj.order_id).exclude(pk=obj.pk).update(**update_fields)

    def changelist_view(self, request, extra_context=None):
        extra_context = extra_context or {}
        
        if request.method == 'POST' and 'generate_report' in request.POST:
            start_date = request.POST.get('start_date')
            end_date = request.POST.get('end_date')
            
            if start_date and end_date:
                from datetime import datetime
                start = datetime.strptime(start_date, '%Y-%m-%d').date()
                end = datetime.strptime(end_date, '%Y-%m-%d').date()
                
                queryset = self.get_queryset(request).filter(
                    start_date__gte=start,
                    start_date__lte=end
                )
                
                return generate_rental_report_pdf(queryset, start, end)
        
        response = super().changelist_view(request, extra_context)
        if hasattr(response, 'context_data') and response.context_data:
            cl = response.context_data.get('cl')
            if cl is not None:
                start = getattr(cl, 'first_result', 0) + 1
                self._serial_numbers = {item.pk: idx for idx, item in enumerate(cl.result_list, start)}
            else:
                self._serial_numbers = {}
        else:
            self._serial_numbers = {}
        return response

    def serial_number(self, obj):
        return getattr(self, '_serial_numbers', {}).get(obj.pk, '')

    serial_number.short_description = 'ID'

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

    def view_id_proof(self, obj):
        if obj.id_proof_file:
            return format_html('<a class="button" href="{}" target="_blank">View ID Proof</a>', obj.id_proof_file.url)
        try:
            if obj.user.userdetail.id_proof_file:
                return format_html(
                    '<a class="button" href="{}" target="_blank">View Profile ID Proof</a>',
                    obj.user.userdetail.id_proof_file.url,
                )
        except Exception:
            pass
        return "No file"

    view_id_proof.short_description = "ID Proof"

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
                f"— Kutch Yuvak Sangh Team"
            )
        else:
            date_val = obj.end_date
            message = (
                f"Hello {obj.user.username},\n\n"
                f"Your rental is approved \n\n"
                f"🛏 Item: {obj.rental_item.title}\n"
                f"Return Date: {date_val.strftime('%d-%m-%Y')}\n\n"
                f"Thank you.\n"
                f"— Kutch Yuvak Sangh Team"
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
            f"— Kutch Yuvak Sangh Team"
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
    list_display = ('user', 'phone', 'id_proof_type', 'id_proof_number', 'city', 'state', 'pincode', 'view_id_proof')
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
        'id_proof_file',
        'email',
        'patient_name',
    )

    def view_id_proof(self, obj):
        if obj.id_proof_file:
            return format_html('<a href="{}" target="_blank">View</a>', obj.id_proof_file.url)
        return "â€”"

    view_id_proof.short_description = "ID Proof File"


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

