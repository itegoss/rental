from django.contrib import admin
from django.utils.html import format_html
from django.http import HttpResponse, HttpResponseRedirect
from django.urls import path, reverse
from .models import Inventory, History, Payment, UserDetail, Customer
from .utils import generate_receipt
from django.conf import settings
from .models import Cart, CartItem
import urllib.parse
import re
from .utils import send_whatsapp_message

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


@admin.register(Inventory)
class InventoryAdmin(admin.ModelAdmin):

    list_display = (
        'title',
        'price_per_day',
        'total_quantity',
        'available_quantity',
        'booked_quantity',
        'stock_status',
        'available',
        'next_available_date',
    )

    def stock_status(self, obj):
        return obj.stock_status()

    stock_status.short_description = "Stock Status"

from .models import Inventory, History, Receipt, Item

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

    def get_rental_days(self, obj):
        return obj.rental_days
    get_rental_days.short_description = "Rental Days"

    def get_per_day_rent(self, obj):
        return f"₹{obj.rental_item.price_per_day}" if obj.rental_item else "—"
    get_per_day_rent.short_description = "Per Day Rent"

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


from django.contrib import admin
from .models import Services

@admin.register(Services)
class ServicesAdmin(admin.ModelAdmin):
    list_display = ('title', 'contact_number')

from .models import Cart, CartItem

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


from .models import NotifyRequest

@admin.register(NotifyRequest)
class NotifyRequestAdmin(admin.ModelAdmin):
    list_display = ('email', 'mobile', 'item', 'is_notified', 'created_at')
    list_filter = ('is_notified', 'created_at', 'item')
    search_fields = ('email', 'mobile', 'item__title')
    readonly_fields = ('created_at',)



