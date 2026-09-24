from decimal import Decimal
import datetime
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from app.models import History, Inventory


@override_settings(STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class ReturnActionVisibilityTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='regular_customer',
            password='Password@123',
            email='customer@example.com'
        )
        self.client.login(username='regular_customer', password='Password@123')

        self.inventory = Inventory.objects.create(
            title='Hospital Bed Deluxe',
            description='Test bed',
            total_quantity=10,
            available_quantity=10,
            price_per_day=Decimal('100.00'),
            deposit=Decimal('500.00'),
        )

        self.booking = History.objects.create(
            user=self.user,
            rental_item=self.inventory,
            order_id='ORD-TEST-001',
            start_date=datetime.date.today(),
            end_date=datetime.date.today() + datetime.timedelta(days=7),
            quantity=1,
            rent=Decimal('100.00'),
            deposit=Decimal('500.00'),
            status='approved',
            is_returned=False,
            is_return_requested=False,
        )

    def test_approved_status_return_action_hidden(self):
        self.booking.status = 'approved'
        self.booking.is_returned = False
        self.booking.is_return_requested = False
        self.booking.save()

        response = self.client.get(reverse('bookingsammry'))
        self.assertEqual(response.status_code, 200)

        # Return action button should be HIDDEN
        self.assertNotContains(response, 'data-tooltip="Request Return"')
        # Extend, Cancel, Receipt should still be visible for Approved
        self.assertContains(response, 'data-tooltip="Extend"')
        self.assertContains(response, 'data-tooltip="Cancel"')
        self.assertContains(response, 'data-tooltip="Receipt"')

    def test_delivered_status_return_action_visible(self):
        self.booking.status = 'delivered'
        self.booking.is_returned = False
        self.booking.is_return_requested = False
        self.booking.save()

        response = self.client.get(reverse('bookingsammry'))
        self.assertEqual(response.status_code, 200)

        # Return action button should be VISIBLE
        self.assertContains(response, 'data-tooltip="Request Return"')
        # Extend and Receipt should still be visible
        self.assertContains(response, 'data-tooltip="Extend"')
        self.assertContains(response, 'data-tooltip="Receipt"')
        # Cancel should NOT be visible once delivered
        self.assertNotContains(response, 'data-tooltip="Cancel"')

    def test_return_request_status_return_action_hidden(self):
        self.booking.status = 'return_request'
        self.booking.is_returned = False
        self.booking.is_return_requested = True
        self.booking.save()

        response = self.client.get(reverse('bookingsammry'))
        self.assertEqual(response.status_code, 200)

        # Return action button should be HIDDEN
        self.assertNotContains(response, 'data-tooltip="Request Return"')

    def test_returned_status_return_action_hidden(self):
        self.booking.status = 'returned'
        self.booking.is_returned = True
        self.booking.is_return_requested = False
        self.booking.save()

        response = self.client.get(reverse('bookingsammry'))
        self.assertEqual(response.status_code, 200)

        # Return action button should be HIDDEN
        self.assertNotContains(response, 'data-tooltip="Request Return"')
        # View Receipt for returned should be visible
        self.assertContains(response, 'data-tooltip="View Receipt"')

    def test_pending_status_return_action_hidden(self):
        self.booking.status = 'pending'
        self.booking.is_returned = False
        self.booking.is_return_requested = False
        self.booking.save()

        response = self.client.get(reverse('bookingsammry'))
        self.assertEqual(response.status_code, 200)

        # Return action button should be HIDDEN
        self.assertNotContains(response, 'data-tooltip="Request Return"')

    def test_completed_status_return_action_hidden(self):
        self.booking.status = 'completed'
        self.booking.is_returned = False
        self.booking.is_return_requested = False
        self.booking.save()

        response = self.client.get(reverse('bookingsammry'))
        self.assertEqual(response.status_code, 200)

        # Return action button should be HIDDEN
        self.assertNotContains(response, 'data-tooltip="Request Return"')
