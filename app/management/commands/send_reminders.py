from django.core.management.base import BaseCommand
from django.utils import timezone
from datetime import timedelta
from app.models import History
from app.utils import send_whatsapp_message
import re


class Command(BaseCommand):
    help = "Send WhatsApp reminder before due date"

    def handle(self, *args, **kwargs):
        today = timezone.now().date()

        # 🔥 CHANGE HERE:
        DAYS_BEFORE = 0   # 👉 test ke liye 0, production ke liye 7

        target_date = today + timedelta(days=DAYS_BEFORE)

        orders = History.objects.filter(
            status='approved',
            is_reminder_sent=False
        )

        for obj in orders:
            try:
                final_date = obj.extended_end_date or obj.end_date

                print(f"Checking order: {obj.order_id}, final_date: {final_date}, target: {target_date}")

                # ✅ match check
                if final_date != target_date:
                    continue

                # ✅ phone safe fetch
                try:
                    phone = obj.user.userdetail.phone
                except:
                    print(f"No phone for {obj.user.username}")
                    continue

                to_digits = re.sub(r"\D", "", str(phone))

                # ✅ dynamic message
                if DAYS_BEFORE == 0:
                    message = (
                        f"Hello {obj.user.username},\n\n"
                        f"Reminder 📢\n"
                        f"Your rental item is due TODAY.\n\n"
                        f"🛏 Item: {obj.rental_item.title}\n"
                        f"📅 Return Date: {final_date.strftime('%d-%m-%Y')}\n\n"
                        f"Please return or extend immediately to avoid extra charges.\n\n"
                        f"Thank you 💙\n"
                        f"— Team Sick Bed Service"
                    )
                else:
                    message = (
                        f"Hello {obj.user.username},\n\n"
                        f"This is a reminder from Sick Bed Service 📢\n\n"
                        f"Your rental item is due in {DAYS_BEFORE} days.\n\n"
                        f"🛏 Item: {obj.rental_item.title}\n"
                        f"📅 Return Date: {final_date.strftime('%d-%m-%Y')}\n\n"
                        f"Please return the item on time or contact us if you wish to extend.\n\n"
                        f"Thank you 💙\n"
                        f"— Team Sick Bed Service"
                    )

                # ✅ send message
                send_whatsapp_message(to_digits, message)

                # ✅ mark as sent
                obj.is_reminder_sent = True
                obj.save()

                self.stdout.write(
                    self.style.SUCCESS(f"Reminder sent to {obj.user.username}")
                )

            except Exception as e:
                print(f"Error: {e}")