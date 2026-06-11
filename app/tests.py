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


