from django.test import TestCase
from django.urls import reverse
from django.contrib.auth.models import User
from app.models import Inventory

class InventoryTests(TestCase):
    def setUp(self):
        self.normal_user = User.objects.create_user(username='normal', password='password123')
        self.admin_user = User.objects.create_superuser(username='admin', password='password123')
        
        self.item = Inventory.objects.create(
            title="Wheelchair",
            description="Comfortable wheelchair",
            price_per_day=50.0,
            deposit=100.0,
            total_quantity=5,
            available_quantity=5,
            booked_quantity=0,
            price=2000.0,
            available=True
        )

    def test_delete_inventory_item_anonymous(self):
        response = self.client.post(reverse('delete_inventory_item', args=[self.item.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Inventory.objects.filter(id=self.item.id).exists())

    def test_delete_inventory_item_normal_user(self):
        self.client.login(username='normal', password='password123')
        response = self.client.post(reverse('delete_inventory_item', args=[self.item.id]))
        self.assertEqual(response.status_code, 302)
        self.assertTrue(Inventory.objects.filter(id=self.item.id).exists())

    def test_delete_inventory_item_admin_user(self):
        self.client.login(username='admin', password='password123')
        response = self.client.post(reverse('delete_inventory_item', args=[self.item.id]))
        self.assertRedirects(response, reverse('inventory'))
        self.assertFalse(Inventory.objects.filter(id=self.item.id).exists())

    def test_edit_inventory_item_anonymous(self):
        response = self.client.post(reverse('edit_inventory_item', args=[self.item.id]), {
            'title': 'Updated Wheelchair'
        })
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, 'Wheelchair')

    def test_edit_inventory_item_normal_user(self):
        self.client.login(username='normal', password='password123')
        response = self.client.post(reverse('edit_inventory_item', args=[self.item.id]), {
            'title': 'Updated Wheelchair'
        })
        self.assertEqual(response.status_code, 302)
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, 'Wheelchair')

    def test_edit_inventory_item_admin_user(self):
        from app.models import History
        from django.utils import timezone
        import datetime
        History.objects.create(
            user=self.normal_user,
            rental_item=self.item,
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + datetime.timedelta(days=5),
            quantity=2,
            deposit=self.item.deposit,
            payment_method='cod',
            status='approved',
            order_id='ORD111111'
        )
        self.client.login(username='admin', password='password123')
        response = self.client.post(reverse('edit_inventory_item', args=[self.item.id]), {
            'title': 'New Title',
            'description': 'New Desc',
            'price_per_day': '45.00',
            'deposit': '90.00',
            'total_quantity': '10',
            'available_quantity': '8',
            'booked_quantity': '2',
            'available': 'on',
            'next_available_date': '',
            'item_qty': '1',
            'price': '1500.00',
            'donation': 'on',
            'donor_name': 'Donor A',
            'donor_contact': '9876543210'
        })
        self.assertRedirects(response, reverse('inventory'))
        self.item.refresh_from_db()
        self.assertEqual(self.item.title, 'New Title')
        self.assertEqual(self.item.description, 'New Desc')
        self.assertEqual(self.item.price_per_day, 45.0)
        self.assertEqual(self.item.deposit, 90.0)
        self.assertEqual(self.item.total_quantity, 10)
        self.assertEqual(self.item.available_quantity, 8)
        self.assertEqual(self.item.booked_quantity, 2)
        self.assertTrue(self.item.available)
        self.assertIsNone(self.item.next_available_date)
        self.assertEqual(self.item.item_qty, 1)
        self.assertEqual(self.item.price, 1500.0)
        self.assertTrue(self.item.donation)
        self.assertEqual(self.item.donor_name, 'Donor A')
        self.assertEqual(self.item.donor_contact, '9876543210')


from app.models import History, Notification
from django.core import mail
from django.utils import timezone
from django.conf import settings
import datetime

class RentalTodayReminderTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='renter', email='renter@example.com', password='password123')
        self.item = Inventory.objects.create(
            title="Oxygen Cylinder",
            description="Medical oxygen cylinder",
            price_per_day=100.0,
            deposit=500.0,
            total_quantity=5,
            available_quantity=4,
            booked_quantity=1,
            available=True
        )
        self.today = timezone.now().date()
        self.rental = History.objects.create(
            user=self.user,
            rental_item=self.item,
            start_date=self.today - datetime.timedelta(days=7),
            end_date=self.today,
            quantity=1,
            deposit=500.0,
            payment_method='cod',
            status='approved',
            order_id='ORD202606001'
        )

    def test_today_reminder_sent_on_index_load(self):
        # Verify initial state
        self.assertFalse(self.rental.is_today_reminder_sent)
        self.assertEqual(Notification.objects.filter(title="Rental Ending Today").count(), 0)
        initial_mail_count = len(mail.outbox)

        # Trigger index page request (which performs checks)
        response = self.client.get(reverse('index'))
        self.assertEqual(response.status_code, 200)

        # Refresh from database
        self.rental.refresh_from_db()
        self.assertTrue(self.rental.is_today_reminder_sent)

        # Check if emails were sent (one to the renter, one to the admin)
        self.assertEqual(len(mail.outbox), initial_mail_count + 2)
        renter_emails = [m for m in mail.outbox[initial_mail_count:] if 'renter@example.com' in m.to]
        self.assertEqual(len(renter_emails), 1)
        self.assertEqual(renter_emails[0].subject, 'Reminder: Your Rental Ends TODAY - Sick Bed Services')
        
        admin_emails = [m for m in mail.outbox[initial_mail_count:] if getattr(settings, 'ADMIN_EMAIL', None) in m.to]
        self.assertEqual(len(admin_emails), 1)
        self.assertEqual(admin_emails[0].subject, 'Admin Notification: Rental Ending Today')

        # Check if Admin Notification was created
        notifications = Notification.objects.filter(title="Rental Ending Today")
        self.assertEqual(notifications.count(), 1)
        self.assertIn('renter', notifications.first().message)
        self.assertIn('Oxygen Cylinder', notifications.first().message)

    def test_no_duplicate_reminders_on_subsequent_load(self):
        # Trigger index request once to send reminder
        response1 = self.client.get(reverse('index'))
        self.assertEqual(response1.status_code, 200)
        self.rental.refresh_from_db()
        self.assertTrue(self.rental.is_today_reminder_sent)
        
        mail_count_after_first = len(mail.outbox)
        notification_count_after_first = Notification.objects.filter(title="Rental Ending Today").count()

        # Trigger index request again
        response2 = self.client.get(reverse('index'))
        self.assertEqual(response2.status_code, 200)

        # Assert no additional emails or notifications were sent/created
        self.assertEqual(len(mail.outbox), mail_count_after_first)
        self.assertEqual(Notification.objects.filter(title="Rental Ending Today").count(), notification_count_after_first)


from app.models import BookingExtension, Receipt
from app.utils import build_booking_receipt_breakdown, generate_receipt
from decimal import Decimal

class ReceiptExtensionTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='tester', email='tester@example.com', password='password123')
        self.item = Inventory.objects.create(
            title="Hospital Bed",
            description="Adjustable hospital bed",
            price_per_day=50.0,
            deposit=1000.0,
            total_quantity=5,
            available_quantity=5,
            booked_quantity=0,
            available=True
        )
        self.today = timezone.now().date()
        self.rental = History.objects.create(
            user=self.user,
            rental_item=self.item,
            start_date=self.today,
            end_date=self.today + datetime.timedelta(days=9),
            quantity=1,
            deposit=1000.0,
            payment_method='cod',
            status='approved',
            order_id='ORD999999'
        )
        
    def test_build_booking_receipt_breakdown_no_extension(self):
        related = History.objects.filter(order_id=self.rental.order_id)
        breakdown = build_booking_receipt_breakdown(self.rental, related)
        
        self.assertEqual(breakdown["original_days"], 10)
        self.assertEqual(breakdown["original_total_rent"], Decimal("500.00"))
        self.assertEqual(breakdown["original_total_deposit"], Decimal("1000.00"))
        self.assertEqual(breakdown["original_total_amount"], Decimal("1500.00"))
        self.assertEqual(len(breakdown["extension_history"]), 0)
        self.assertEqual(breakdown["extension_total"], Decimal("0"))
        self.assertEqual(breakdown["final_total_amount"], Decimal("1500.00"))
        self.assertEqual(breakdown["amount_paid"], Decimal("0"))
        self.assertEqual(breakdown["amount_remaining"], Decimal("1500.00"))

    def test_build_booking_receipt_breakdown_partial_payment(self):
        self.rental.amount_paid = Decimal("500.00")
        self.rental.save()
        
        related = History.objects.filter(order_id=self.rental.order_id)
        breakdown = build_booking_receipt_breakdown(self.rental, related)
        
        self.assertEqual(breakdown["amount_paid"], Decimal("500.00"))
        self.assertEqual(breakdown["amount_remaining"], Decimal("1000.00"))

    def test_build_booking_receipt_breakdown_with_extensions(self):
        BookingExtension.objects.create(
            rental_request=self.rental,
            extension_no=1,
            previous_return_date=self.rental.end_date,
            new_return_date=self.rental.end_date + datetime.timedelta(days=5),
            extra_days=5,
            quantity=1,
            rent_per_day=self.item.price_per_day,
            additional_rent=self.item.price_per_day * 5,
            additional_deposit=0,
            extension_total=self.item.price_per_day * 5
        )
        self.rental.extended_end_date = self.rental.end_date + datetime.timedelta(days=5)
        self.rental.save()

        related = History.objects.filter(order_id=self.rental.order_id)
        breakdown = build_booking_receipt_breakdown(self.rental, related)
        
        self.assertEqual(breakdown["original_days"], 10)
        self.assertEqual(len(breakdown["extension_history"]), 1)
        self.assertEqual(breakdown["extension_history"][0]["extension_no"], 1)
        self.assertEqual(breakdown["extension_history"][0]["extra_days"], 5)
        self.assertEqual(breakdown["extension_history"][0]["extension_total"], Decimal("250.00"))
        self.assertEqual(breakdown["extension_total"], Decimal("250.00"))
        self.assertEqual(breakdown["final_total_amount"], Decimal("1750.00"))

    def test_receipt_regeneration_on_extension(self):
        receipt_file = generate_receipt(self.rental)
        initial_receipt = Receipt.objects.create(rental_request=self.rental, receipt_type='booking')
        initial_receipt.file.save('initial.pdf', receipt_file)
        initial_receipt.save()

        self.assertEqual(self.rental.receipts.filter(receipt_type='booking').count(), 1)
        old_receipt_id = self.rental.receipts.filter(receipt_type='booking').first().id

        self.client.login(username='tester', password='password123')
        new_return_date = (self.rental.end_date + datetime.timedelta(days=5)).strftime('%Y-%m-%d')
        response = self.client.post(
            reverse('extend_return_date', args=[self.rental.order_id]),
            {'extended_end_date': new_return_date}
        )
        self.assertEqual(response.status_code, 302)

        receipts = self.rental.receipts.filter(receipt_type='booking')
        self.assertEqual(receipts.count(), 1)
        self.assertNotEqual(receipts.first().id, old_receipt_id)


from app.utils import send_notification

class NonSuperuserNotificationEmailTests(TestCase):
    def setUp(self):
        self.non_superuser = User.objects.create_user(username='varsha_client', email='varsha@client.com', password='password123')
        self.item = Inventory.objects.create(
            title="Walker",
            description="Mobility walker",
            price_per_day=5.0,
            deposit=500.0,
            total_quantity=2,
            available_quantity=2,
            booked_quantity=0,
            available=True
        )
        self.today = timezone.now().date()
        self.rental = History.objects.create(
            user=self.non_superuser,
            rental_item=self.item,
            start_date=self.today,
            end_date=self.today + datetime.timedelta(days=7),
            quantity=1,
            deposit=500.0,
            payment_method='cod',
            status='pending',
            order_id='ORD202607004'
        )

    def test_non_superuser_booking_request_email(self):
        initial_mail_count = len(mail.outbox)
        send_notification(
            title="New Booking Created",
            message="Some booking message",
            notification_type='booking',
            order_id=self.rental.order_id,
            rental=self.rental
        )
        # Check that email was sent to renter
        renter_emails = [m for m in mail.outbox[initial_mail_count:] if 'varsha@client.com' in m.to]
        self.assertEqual(len(renter_emails), 1)
        email = renter_emails[0]
        self.assertIn("Dear varsha_client,", email.body)
        self.assertIn("Your order id is : ORD202607004 for Walker your request successfully sent to admin.", email.body)
        self.assertIn("For any further assistance call 9867348169 / 9820247550 or login to sickbed.itegoss.in", email.body)
        self.assertIn("Thank you", email.body)

    def test_non_superuser_return_request_email(self):
        initial_mail_count = len(mail.outbox)
        send_notification(
            title="Return Request Submitted for ORD202607004",
            message="Some return request message",
            notification_type='return',
            order_id=self.rental.order_id,
            rental=self.rental
        )
        renter_emails = [m for m in mail.outbox[initial_mail_count:] if 'varsha@client.com' in m.to]
        self.assertEqual(len(renter_emails), 1)
        email = renter_emails[0]
        self.assertIn("Dear varsha_client,", email.body)
        self.assertIn("Your order id is : ORD202607004 for Walker your return request successfully sent to admin.", email.body)
        self.assertIn("For any further assistance call 9867348169 / 9820247550 or login to sickbed.itegoss.in", email.body)
        self.assertIn("Thank you", email.body)

    def test_extension_date_email(self):
        from django.conf import settings
        initial_mail_count = len(mail.outbox)
        send_notification(
            title="Return Date Extended for ORD202607004",
            message="Some extension message",
            notification_type='return',
            order_id=self.rental.order_id,
            rental=self.rental
        )
        renter_emails = [m for m in mail.outbox[initial_mail_count:] if 'varsha@client.com' in m.to]
        self.assertEqual(len(renter_emails), 1)
        email = renter_emails[0]
        self.assertIn("Dear varsha_client,", email.body)
        self.assertIn("Your order id is : ORD202607004 for Walker your return date is extended.", email.body)
        self.assertIn("For any further assistance call 9867348169 / 9820247550 or login to sickbed.itegoss.in", email.body)
        self.assertIn("Thank you", email.body)
        self.assertEqual(email.cc, [settings.ADMIN_EMAIL])


class SuperuserOrderApprovalTests(TestCase):
    def setUp(self):
        from app.models import Cart, CartItem
        # Create user and superuser
        self.normal_user = User.objects.create_user(username='normal_user', email='normal@example.com', password='password123')
        self.superuser = User.objects.create_superuser(username='superuser', email='super@example.com', password='password123')
        
        # Create an item
        self.item = Inventory.objects.create(
            title="Oxygen Concentrator",
            description="High flow concentrator",
            price_per_day=150.0,
            deposit=1000.0,
            total_quantity=5,
            available_quantity=5,
            booked_quantity=0,
            available=True
        )

    def test_superuser_cod_auto_approved(self):
        from app.models import Cart, CartItem, History
        self.client.login(username='superuser', password='password123')
        
        # Set session details
        session = self.client.session
        session['renter_name'] = "Super User"
        session['patient_name'] = "Patient X"
        session['phone'] = "1234567890"
        session['address'] = "Superuser Address"
        session['id_proof_type'] = "Aadhar"
        session['id_proof_number'] = "123412341234"
        session['id_proof_file'] = "some_file.png"
        session['start_date'] = "2026-07-10"
        session['end_date'] = "2026-07-15"
        session.save()
        
        # Set cart
        cart = Cart.objects.create(user=self.superuser)
        CartItem.objects.create(cart=cart, rental_item=self.item, quantity=2)
        
        response = self.client.post(reverse('paymentmethod'), {'payment_method': 'cod'})
        self.assertEqual(response.status_code, 302) # Redirect to success
        
        # Check History object
        rentals = History.objects.filter(user=self.superuser)
        self.assertEqual(rentals.count(), 1)
        rental = rentals.first()
        self.assertEqual(rental.status, 'approved')
        
        # Check Inventory quantities
        self.item.refresh_from_db()
        self.assertEqual(self.item.booked_quantity, 2)
        self.assertEqual(self.item.available_quantity, 3)

    def test_normal_user_cod_remains_pending(self):
        from app.models import Cart, CartItem, History
        self.client.login(username='normal_user', password='password123')
        
        # Set session details
        session = self.client.session
        session['renter_name'] = "Normal User"
        session['patient_name'] = "Patient Y"
        session['phone'] = "0987654321"
        session['address'] = "Normal Address"
        session['id_proof_type'] = "Aadhar"
        session['id_proof_number'] = "432143214321"
        session['id_proof_file'] = "another_file.png"
        session['start_date'] = "2026-07-10"
        session['end_date'] = "2026-07-15"
        session.save()
        
        # Set cart
        cart = Cart.objects.create(user=self.normal_user)
        CartItem.objects.create(cart=cart, rental_item=self.item, quantity=1)
        
        response = self.client.post(reverse('paymentmethod'), {'payment_method': 'cod'})
        self.assertEqual(response.status_code, 302) # Redirect to success
        
        # Check History object
        rentals = History.objects.filter(user=self.normal_user)
        self.assertEqual(rentals.count(), 1)
        rental = rentals.first()
        self.assertEqual(rental.status, 'pending')
        
        # Check Inventory quantities (should NOT have changed for pending order)
        self.item.refresh_from_db()
        self.assertEqual(self.item.booked_quantity, 0)
        self.assertEqual(self.item.available_quantity, 5)





