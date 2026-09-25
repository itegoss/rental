from decimal import Decimal
from datetime import date
from unittest.mock import patch
from django.test import TestCase, Client
from django.urls import reverse
from django.contrib.auth.models import User, Permission
from app.models import History, Inventory

class DeliveredPaymentSectionLogicTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='staff_admin',
            email='staff@example.com',
            password='password123',
            is_staff=True,
            is_superuser=True
        )

        self.item = Inventory.objects.create(
            title='Hospital Fowler Bed',
            price_per_day=Decimal("100.00"),
            deposit=Decimal("500.00"),
            total_quantity=10,
            available_quantity=10,
            booked_quantity=0,
            available=True
        )

    @patch('app.views.send_notification')
    def test_home_delivery_pending_charge_calculation(self, mock_notify):
        """
        When order was originally placed with Home Delivery selected,
        applicable delivery charge (e.g. 500.00) and pending delivery charge are correctly computed.
        """
        # 5 days = 5 * 100 = 500 rent, deposit 500, delivery 500. Total = 1500.
        # User paid rent + deposit = 1000 online upfront.
        rental = History.objects.create(
            user=self.user,
            rental_item=self.item,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),
            quantity=1,
            deposit=Decimal("500.00"),
            delivery_option='delivery',
            delivery_charge=Decimal("500.00"),
            payment_method='online',
            status='approved',
            is_returned=False,
            order_id='ORD-HOME-500',
            amount_paid=Decimal("1000.00")
        )

        self.client.login(username='staff_admin', password='password123')
        response = self.client.get(reverse('bookingsammry'))
        self.assertEqual(response.status_code, 200)

        # Find the summary for ORD-HOME-500
        summaries = response.context['booking_summaries']
        order_summary = next((s for s in summaries if s['order_id'] == 'ORD-HOME-500'), None)
        self.assertIsNotNone(order_summary)
        self.assertTrue(order_summary['is_home_delivery'])
        self.assertEqual(order_summary['delivery_charge'], Decimal("500.00"))
        self.assertEqual(order_summary['pending_delivery_charge'], Decimal("500.00"))
        self.assertEqual(order_summary['total_payable'], Decimal("1500.00"))
        self.assertEqual(order_summary['amount_paid'], Decimal("1000.00"))
        self.assertEqual(order_summary['amount_remaining'], Decimal("500.00"))

        # Verify button attributes in HTML response
        content = response.content.decode('utf-8')
        self.assertIn('data-order-id="ORD-HOME-500"', content)
        self.assertIn('data-is-home-delivery="true"', content)
        self.assertIn('data-delivery="500.00"', content)
        self.assertIn('data-pending-delivery="500.00"', content)

    @patch('app.views.send_notification')
    def test_pickup_delivery_charge_is_zero(self, mock_notify):
        """
        When order was placed with Pickup / Self Pickup,
        the delivery charge must show 0.00, and is_home_delivery is False.
        """
        # 5 days = 5 * 100 = 500 rent, deposit 500, delivery 0. Total = 1000.
        rental = History.objects.create(
            user=self.user,
            rental_item=self.item,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),
            quantity=1,
            deposit=Decimal("500.00"),
            delivery_option='pickup',
            delivery_charge=Decimal("0.00"),
            payment_method='cod',
            status='approved',
            is_returned=False,
            order_id='ORD-PICKUP-001',
            amount_paid=Decimal("0.00")
        )

        self.client.login(username='staff_admin', password='password123')
        response = self.client.get(reverse('bookingsammry'))
        self.assertEqual(response.status_code, 200)

        summaries = response.context['booking_summaries']
        order_summary = next((s for s in summaries if s['order_id'] == 'ORD-PICKUP-001'), None)
        self.assertIsNotNone(order_summary)
        self.assertFalse(order_summary['is_home_delivery'])
        self.assertEqual(order_summary['delivery_charge'], Decimal("0.00"))
        self.assertEqual(order_summary['pending_delivery_charge'], Decimal("0.00"))
        self.assertEqual(order_summary['total_payable'], Decimal("1000.00"))

        content = response.content.decode('utf-8')
        self.assertIn('data-order-id="ORD-PICKUP-001"', content)
        self.assertIn('data-is-home-delivery="false"', content)
        self.assertIn(f'data-delivery="{order_summary["delivery_charge"]}"', content)
        self.assertIn(f'data-pending-delivery="{order_summary["pending_delivery_charge"]}"', content)

    @patch('app.views.send_notification')
    def test_legacy_pickup_with_stale_delivery_charge_shows_zero(self, mock_notify):
        """
        If an existing order has delivery_option='pickup' but delivery_charge in DB has a non-zero value,
        it must still be treated as 0.00 because delivery_option is pickup.
        """
        rental = History.objects.create(
            user=self.user,
            rental_item=self.item,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),
            quantity=1,
            deposit=Decimal("500.00"),
            delivery_option='pickup',
            delivery_charge=Decimal("500.00"),  # Stale/default non-zero value
            payment_method='online',
            status='approved',
            is_returned=False,
            order_id='ORD-LEGACY-PICKUP',
            amount_paid=Decimal("1000.00")
        )

        self.client.login(username='staff_admin', password='password123')
        response = self.client.get(reverse('bookingsammry'))
        self.assertEqual(response.status_code, 200)

        summaries = response.context['booking_summaries']
        order_summary = next((s for s in summaries if s['order_id'] == 'ORD-LEGACY-PICKUP'), None)
        self.assertIsNotNone(order_summary)
        self.assertFalse(order_summary['is_home_delivery'])
        self.assertEqual(order_summary['delivery_charge'], Decimal("0.00"))
        self.assertEqual(order_summary['pending_delivery_charge'], Decimal("0.00"))
        self.assertEqual(order_summary['total_payable'], Decimal("1000.00"))

    @patch('app.views.send_notification')
    def test_custom_delivery_charge_not_hardcoded(self, mock_notify):
        """
        Verify that delivery charge is not hardcoded to 500, but dynamically respects the value
        calculated/selected at order creation (e.g. 350.00).
        """
        rental = History.objects.create(
            user=self.user,
            rental_item=self.item,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),
            quantity=1,
            deposit=Decimal("500.00"),
            delivery_option='delivery',
            delivery_charge=Decimal("350.00"),  # Custom non-500 charge
            payment_method='cod',
            status='approved',
            is_returned=False,
            order_id='ORD-CUSTOM-350',
            amount_paid=Decimal("0.00")
        )

        self.client.login(username='staff_admin', password='password123')
        response = self.client.get(reverse('bookingsammry'))
        self.assertEqual(response.status_code, 200)

        summaries = response.context['booking_summaries']
        order_summary = next((s for s in summaries if s['order_id'] == 'ORD-CUSTOM-350'), None)
        self.assertIsNotNone(order_summary)
        self.assertTrue(order_summary['is_home_delivery'])
        self.assertEqual(order_summary['delivery_charge'], Decimal("350.00"))
        self.assertEqual(order_summary['pending_delivery_charge'], Decimal("350.00"))
        self.assertEqual(order_summary['total_payable'], Decimal("1350.00"))

        content = response.content.decode('utf-8')
        self.assertIn('data-order-id="ORD-CUSTOM-350"', content)
        self.assertIn('data-delivery="350.00"', content)
        self.assertIn('data-pending-delivery="350.00"', content)

    @patch('app.views.send_notification')
    def test_deliver_order_submission_with_delivery_paid(self, mock_notify):
        """
        When confirming delivery with rent_paid, deposit_paid, delivery_paid:
        amount_paid, amount_remaining, and is_delivery_paid update accurately.
        """
        rental = History.objects.create(
            user=self.user,
            rental_item=self.item,
            start_date=date(2026, 9, 1),
            end_date=date(2026, 9, 5),
            quantity=1,
            deposit=Decimal("500.00"),
            delivery_option='delivery',
            delivery_charge=Decimal("400.00"),
            payment_method='cod',
            status='approved',
            is_returned=False,
            order_id='ORD-SUBMIT-400',
            amount_paid=Decimal("0.00")
        )

        self.client.login(username='staff_admin', password='password123')
        # Total payable = 500 rent + 500 deposit + 400 delivery = 1400
        # Post fields: rent=500, deposit=500, delivery=400 -> fully paid
        response = self.client.post(
            reverse('deliver_order', args=['ORD-SUBMIT-400']),
            {
                'rent_paid': '500.00',
                'deposit_paid': '500.00',
                'delivery_paid': '400.00',
                'notes': 'All paid in cash'
            }
        )
        self.assertEqual(response.status_code, 302)
        rental.refresh_from_db()
        self.assertEqual(rental.status, 'delivered')
        self.assertEqual(rental.amount_paid, Decimal("1400.00"))
        self.assertEqual(rental.amount_remaining, Decimal("0.00"))
        self.assertTrue(rental.is_delivery_paid)
