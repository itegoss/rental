from django.db.models.signals import post_save
from django.dispatch import receiver
from django.db import models
from django.utils import timezone
from datetime import timedelta
from .models import History, Inventory, NotifyRequest
from django.core.mail import send_mail
from django.conf import settings

_previous_quantities = {}

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