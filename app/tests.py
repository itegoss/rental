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

        # Check if email was sent to user
        self.assertEqual(len(mail.outbox), initial_mail_count + 1)
        sent_email = mail.outbox[-1]
        self.assertEqual(sent_email.subject, 'Reminder: Your Rental Ends TODAY - Sick Bed Services')
        self.assertIn('renter@example.com', sent_email.to)

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



