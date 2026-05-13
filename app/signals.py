from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver
from django.db import models
from django.utils import timezone
from datetime import timedelta
from .models import History, Inventory, Item, NotifyRequest
from django.core.mail import send_mail
from django.conf import settings

_previous_quantities = {}
_previous_item_values = {}

@receiver(pre_save, sender=Item)
def cache_item_previous_values(sender, instance, **kwargs):
    if instance.pk:
        try:
            old_item = Item.objects.get(pk=instance.pk)
            _previous_item_values[instance.pk] = {
                'item_name': old_item.item_name,
                'item_qty': old_item.item_qty,
            }
        except Item.DoesNotExist:
            _previous_item_values.pop(instance.pk, None)

@receiver(post_save, sender=Item)
def sync_item_to_inventory(sender, instance, created, **kwargs):
    previous = _previous_item_values.pop(instance.pk, None)
    old_name = previous['item_name'] if previous else None
    old_qty = previous['item_qty'] if previous else None

    # If the item name changed, decrement the old inventory entry.
    if old_name and old_name != instance.item_name:
        try:
            old_inventory = Inventory.objects.get(title=old_name)
            old_inventory.total_quantity = max(old_inventory.total_quantity - (old_qty or 0), 0)
            old_inventory.update_availability()
        except Inventory.DoesNotExist:
            pass

    try:
        inventory, inventory_created = Inventory.objects.get_or_create(
            title=instance.item_name,
            defaults={
                'description': '',
                'price_per_day': 0,  # Separate from Item.price (buying price)
                'deposit': 0,
                'total_quantity': instance.item_qty,
                'available_quantity': instance.item_qty,
                'booked_quantity': 0,
                'available': instance.item_qty > 0,
            },
        )

        if not inventory_created:
            if created:
                inventory.total_quantity = max(inventory.total_quantity + instance.item_qty, 0)
            else:
                if old_qty is not None:
                    inventory.total_quantity = max(inventory.total_quantity + (instance.item_qty - old_qty), 0)
                else:
                    inventory.total_quantity = max(inventory.total_quantity + instance.item_qty, 0)
            # Removed: inventory.price_per_day = instance.price  # Keep rental price separate
            inventory.save(update_fields=['total_quantity'])
            inventory.update_availability()
    except Exception as e:
        print(f"[signals] sync_item_to_inventory error: {e}")

@receiver(post_save, sender=Inventory)
def send_availability_notification(sender, instance, **kwargs):
    global _previous_quantities
    
    item_id = instance.id
    current_qty = instance.available_quantity
    previous_qty = _previous_quantities.get(item_id, 0)

    if previous_qty == 0 and current_qty > 0:
        send_availability_emails(instance)
    
    _previous_quantities[item_id] = current_qty

def send_availability_emails(item):
    from django.template.loader import render_to_string
    pending_requests = NotifyRequest.objects.filter(item=item, is_notified=False)
    
    if not pending_requests.exists():
        return
    
    for request in pending_requests:
        if request.email:
            subject = f'Item Now Available - {item.title}'
            context = {
                'item': item,
                'user_email': request.email,
                'site_url': getattr(settings, 'SITE_URL', 'http://localhost:8000')
            }
            message = render_to_string('emails/item_available.html', context)
            
            try:
                send_mail(
                    subject,
                    '',
                    settings.DEFAULT_FROM_EMAIL,
                    [request.email],
                    html_message=message
                )
                print(f"✅ Availability email sent to {request.email} for {item.title}")
            except Exception as e:
                print(f"❌ Failed to send availability email to {request.email}: {e}")
        
        request.is_notified = True
        request.save()

@receiver(post_save, sender=History)
def update_inventory_on_booking(sender, instance, **kwargs):
    try:
        inventory = instance.rental_item
    except Exception:
        return

    try:
        inventory.update_availability()
    except Exception:
        try:
            booked_qty = inventory.rentalrequest_set.filter(
                status='approved',
                is_returned=False
            ).aggregate(total=models.Sum('quantity'))['total'] or 0
            new_available_qty = max(inventory.total_quantity - booked_qty, 0)
            inventory.available_quantity = new_available_qty
            inventory.available = new_available_qty > 0
            if new_available_qty == 0:
                if not inventory.next_available_date:
                    inventory.next_available_date = timezone.now().date() + timedelta(days=7)
            else:
                inventory.next_available_date = None
            inventory.save(update_fields=["available_quantity", "available", "next_available_date"])
            try:
                print(f"[signals] post_save History id={instance.id} recomputed inventory id={inventory.id} available_quantity={inventory.available_quantity} booked={booked_qty}")
            except Exception:
                pass
        except Exception:
            pass