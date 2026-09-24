from django.test import TestCase, RequestFactory
from django.contrib.auth.models import User
from django.utils import timezone
from unittest.mock import patch, MagicMock
from decimal import Decimal
from app.models import History, Inventory, Receipt, Notification, UserDetail
from app.utils import generate_receipt, receipt_filename
from app.whatsapp_service import (
    send_whatsapp_document,
    send_booking_receipt_whatsapp,
    send_return_receipt_whatsapp,
    send_booking_approved_notification,
    send_booking_delivered_notification,
    send_return_approved_notification,
    send_whatsapp_template,
)
from app.views import approve_order, deliver_order, approve_return_order, return_order
from django.core.cache import cache
import os


class WhatsAppReceiptNotificationTests(TestCase):
    def setUp(self):
        cache.clear()
        self.factory = RequestFactory()

        # Admin user
        self.admin_user = User.objects.create_superuser(
            username="admin_user",
            email="admin@example.com",
            password="adminpassword"
        )

        # Customer user
        self.customer = User.objects.create_user(
            username="varsha_customer",
            email="varsha@example.com",
            first_name="Varsha",
            last_name="Sharma",
            password="customerpassword"
        )
        self.user_detail = UserDetail.objects.create(
            user=self.customer,
            phone="9876543210",
            address_line1="123 Care Street, Mumbai",
            patient_name="Varsha Sharma"
        )

        # Inventory item
        self.item = Inventory.objects.create(
            title="Hospital Bed Full Fowler",
            description="Adjustable Medical Bed",
            price_per_day=Decimal("100.00"),
            deposit=Decimal("2000.00"),
            available_quantity=5,
            total_quantity=5
        )

        # Booking order
        self.order_id = "ORD202609099"
        self.rental = History.objects.create(
            user=self.customer,
            rental_item=self.item,
            order_id=self.order_id,
            renter_name="Varsha Sharma",
            phone="9876543210",
            address="123 Care Street, Mumbai",
            start_date=timezone.now().date(),
            end_date=timezone.now().date() + timezone.timedelta(days=7),
            quantity=1,
            rent=Decimal("100.00"),
            deposit=Decimal("2000.00"),
            amount_paid=Decimal("2800.00"),
            status="pending",
            delivery_option="self_pickup",
            delivery_charge=Decimal("0.00"),
        )

    def test_receipt_filename_booking_and_return(self):
        booking_fn = receipt_filename(self.rental, receipt_type="booking")
        return_fn = receipt_filename(self.rental, receipt_type="return")
        self.assertTrue(booking_fn.endswith(".pdf"))
        self.assertTrue(return_fn.startswith("Return_"))
        self.assertTrue(return_fn.endswith(".pdf"))

    def test_generate_receipt_booking_and_return_pdf(self):
        # 1. Booking receipt
        booking_pdf = generate_receipt(self.rental, receipt_type="booking")
        self.assertIsNotNone(booking_pdf)
        pdf_bytes = booking_pdf.read()
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

        # 2. Return receipt
        self.rental.is_returned = True
        self.rental.actual_return_date = timezone.now().date()
        self.rental.save()
        return_pdf = generate_receipt(self.rental, receipt_type="return")
        self.assertIsNotNone(return_pdf)
        ret_pdf_bytes = return_pdf.read()
        self.assertTrue(ret_pdf_bytes.startswith(b"%PDF"))

    @patch("requests.post")
    def test_send_whatsapp_document_11za_payload(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messageId": "wamid.DOC12345", "status": "success"}
        mock_response.text = '{"messageId": "wamid.DOC12345"}'
        mock_post.return_value = mock_response

        with patch("app.whatsapp_service.get_whatsapp_config") as mock_config:
            mock_config.return_value = {
                "access_token": "TEST_TOKEN_11ZA",
                "api_url": "https://api.11za.in/apis/template/sendTemplate",
                "origin_website": "https://www.itegoss.in/",
                "template_name": "utility_dear_284305",
                "document_template_name": "utility_dear_284305",
                "button_value": "https://www.itegoss.in/",
            }

            result = send_whatsapp_document(
                phone_number="9876543210",
                document_url="https://www.itegoss.in/media/receipts/Varsha_Receipt.pdf",
                filename="Varsha_Receipt.pdf",
                caption="Your receipt",
                event_key="test_doc_event_1",
                user=self.customer,
                variables=["Varsha", "ORD202609099", "Booking Receipt", "Approved", "HEMOAID"],
            )

            self.assertTrue(result["success"])
            self.assertEqual(result["message_id"], "wamid.DOC12345")
            self.assertEqual(mock_post.call_count, 1)

            # Verify 11za payload format
            call_kwargs = mock_post.call_args[1]
            payload = call_kwargs["json"]
            self.assertEqual(payload["authToken"], "TEST_TOKEN_11ZA")
            self.assertEqual(payload["sendto"], "919876543210")
            self.assertEqual(payload["myfile"], "https://www.itegoss.in/media/receipts/Varsha_Receipt.pdf")
            self.assertEqual(payload["myfileName"], "Varsha_Receipt.pdf")
            self.assertEqual(payload["tags"], "receipt")

    @patch("requests.post")
    def test_send_whatsapp_document_deduplication(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messageId": "wamid.DEDUP1", "status": "success"}
        mock_post.return_value = mock_response

        with patch("app.whatsapp_service.get_whatsapp_config") as mock_config:
            mock_config.return_value = {
                "access_token": "TEST_TOKEN_11ZA",
                "api_url": "https://api.11za.in/apis/template/sendTemplate",
                "origin_website": "https://www.itegoss.in/",
                "template_name": "utility_dear_284305",
            }

            res1 = send_whatsapp_document(
                phone_number="9876543210",
                document_url="https://www.itegoss.in/media/receipts/test.pdf",
                filename="test.pdf",
                event_key="dedup_doc_test",
                user=self.customer,
            )
            self.assertTrue(res1["success"])
            self.assertEqual(mock_post.call_count, 1)

            # Second call with same event_key must be skipped (no duplicate HTTP call)
            res2 = send_whatsapp_document(
                phone_number="9876543210",
                document_url="https://www.itegoss.in/media/receipts/test.pdf",
                filename="test.pdf",
                event_key="dedup_doc_test",
                user=self.customer,
            )
            self.assertTrue(res2["success"])
            self.assertTrue(res2.get("duplicate"))
            self.assertEqual(mock_post.call_count, 1)

    @patch("requests.post")
    def test_send_booking_receipt_whatsapp_reuses_existing_receipt(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messageId": "wamid.BOOKING_REC", "status": "success"}
        mock_post.return_value = mock_response

        with patch("app.whatsapp_service.get_whatsapp_config") as mock_config:
            mock_config.return_value = {
                "access_token": "TEST_TOKEN_11ZA",
                "api_url": "https://api.11za.in/apis/template/sendTemplate",
                "origin_website": "https://www.itegoss.in/",
                "template_name": "utility_dear_284305",
            }

            # 1. First call generates receipt and saves Receipt object
            res1 = send_booking_receipt_whatsapp(self.rental)
            self.assertTrue(res1["success"])
            self.assertEqual(self.rental.receipts.filter(receipt_type="booking").count(), 1)
            first_receipt_id = self.rental.receipts.filter(receipt_type="booking").first().id

            # 2. Second call (with force=True to bypass dedup) must reuse the same receipt object
            res2 = send_booking_receipt_whatsapp(self.rental, force=True)
            self.assertTrue(res2["success"])
            self.assertEqual(self.rental.receipts.filter(receipt_type="booking").count(), 1)
            self.assertEqual(self.rental.receipts.filter(receipt_type="booking").first().id, first_receipt_id)

    @patch("requests.post")
    def test_send_return_receipt_whatsapp_creates_and_sends_return_receipt(self, mock_post):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"messageId": "wamid.RET_REC", "status": "success"}
        mock_post.return_value = mock_response

        self.rental.is_returned = True
        self.rental.actual_return_date = timezone.now().date()
        self.rental.save()

        with patch("app.whatsapp_service.get_whatsapp_config") as mock_config:
            mock_config.return_value = {
                "access_token": "TEST_TOKEN_11ZA",
                "api_url": "https://api.11za.in/apis/template/sendTemplate",
                "origin_website": "https://www.itegoss.in/",
                "template_name": "utility_dear_284305",
            }

            res = send_return_receipt_whatsapp(self.rental)
            self.assertTrue(res["success"])
            self.assertEqual(self.rental.receipts.filter(receipt_type="return").count(), 1)
            ret_receipt = self.rental.receipts.filter(receipt_type="return").first()
            self.assertIn("Return_", ret_receipt.file.name)

    @patch("app.views.send_booking_receipt_whatsapp")
    @patch("app.views.send_booking_approved_notification")
    def test_approve_order_flow_order_and_receipt_dispatch(self, mock_approved_notif, mock_receipt_wa):
        """
        Verify Approve Flow:
        Approve action -> status updated -> receipt generated -> status notification sent -> receipt sent
        """
        request = self.factory.post(f"/approve-order/{self.order_id}/")
        request.user = self.admin_user
        from django.contrib.messages.storage.cookie import CookieStorage
        setattr(request, '_messages', CookieStorage(request))

        # Mock permission checks
        with patch("app.views.user_has_permission", return_value=True):
            response = approve_order(request, self.order_id)
            self.assertEqual(response.status_code, 302)

        # 1. Booking status updated
        self.rental.refresh_from_db()
        self.assertEqual(self.rental.status, "approved")

        # 2. Receipt generated and saved in database
        receipt = self.rental.receipts.filter(receipt_type="booking").first()
        self.assertIsNotNone(receipt)

        # 3. Notification and WhatsApp calls were made in order
        mock_approved_notif.assert_called_once()
        mock_receipt_wa.assert_called_once()

    @patch("app.views.send_return_receipt_whatsapp")
    @patch("app.views.send_return_approved_notification")
    def test_approve_return_order_flow_and_receipt_dispatch(self, mock_ret_notif, mock_ret_receipt_wa):
        """
        Verify Return Flow:
        Return action -> status updated -> return receipt generated -> return notification sent -> receipt sent
        """
        self.rental.is_return_requested = True
        self.rental.save()

        request = self.factory.post(f"/approve-return-order/{self.order_id}/")
        request.user = self.admin_user
        from django.contrib.messages.storage.cookie import CookieStorage
        setattr(request, '_messages', CookieStorage(request))

        with patch("app.views.user_has_permission", return_value=True):
            response = approve_return_order(request, self.order_id)
            self.assertEqual(response.status_code, 302)

        # 1. Return status updated
        self.rental.refresh_from_db()
        self.assertTrue(self.rental.is_returned)
        self.assertFalse(self.rental.is_return_requested)
        self.assertIsNotNone(self.rental.actual_return_date)

        # 2. Return receipt generated and saved in database
        ret_receipt = self.rental.receipts.filter(receipt_type="return").first()
        self.assertIsNotNone(ret_receipt)

        # 3. Notifications were called
        mock_ret_notif.assert_called_once()
        mock_ret_receipt_wa.assert_called_once()

    @patch("app.admin.send_return_receipt_whatsapp")
    @patch("app.admin.send_return_approved_notification")
    def test_admin_approve_return_flow_and_receipt_dispatch(self, mock_admin_ret_notif, mock_admin_ret_receipt_wa):
        """
        Verify Django Admin Approve Return Action:
        Admin action -> status updated -> return receipt generated -> return notification sent -> receipt sent
        """
        from app.admin import approve_return
        self.rental.is_return_requested = True
        self.rental.save()

        queryset = History.objects.filter(id=self.rental.id)
        approve_return(None, None, queryset)

        # 1. Return status updated
        self.rental.refresh_from_db()
        self.assertTrue(self.rental.is_returned)
        self.assertFalse(self.rental.is_return_requested)

        # 2. Return receipt generated and saved in database
        ret_receipt = self.rental.receipts.filter(receipt_type="return").first()
        self.assertIsNotNone(ret_receipt)

        # 3. WhatsApp notification and receipt sent
        mock_admin_ret_notif.assert_called_once()
        mock_admin_ret_receipt_wa.assert_called_once()

    @patch("app.views.send_booking_delivered_notification")
    @patch("app.views.send_booking_approved_notification")
    def test_deliver_order_flow_sends_delivered_whatsapp(self, mock_approved_notif, mock_delivered_notif):
        """
        Verify Delivery Flow:
        Mark as Delivered -> status becomes 'delivered' -> Delivered WhatsApp notification sent.
        Accepted WhatsApp is NOT sent.
        """
        self.rental.status = "approved"
        self.rental.save()

        request = self.factory.post(
            f"/deliver-order/{self.order_id}/",
            {"amount_paid": "2800.00"}
        )
        request.user = self.admin_user
        from django.contrib.messages.storage.cookie import CookieStorage
        setattr(request, '_messages', CookieStorage(request))

        with patch("app.views.user_has_permission", return_value=True):
            response = deliver_order(request, self.order_id)
            self.assertEqual(response.status_code, 302)

        self.rental.refresh_from_db()
        self.assertEqual(self.rental.status, "delivered")

        # Delivered notification was called with the updated order
        mock_delivered_notif.assert_called_once()
        delivered_arg = mock_delivered_notif.call_args[0][0]
        self.assertEqual(delivered_arg.status, "delivered")

        # Accepted notification was NOT called
        mock_approved_notif.assert_not_called()

    @patch("app.whatsapp_service.send_whatsapp_template")
    def test_template_variables_status_accepted_delivered_returned(self, mock_send_template):
        """
        Verify that:
        - Accepted action passes status variable 'accepted'
        - Delivery action passes status variable 'delivered'
        - Return action passes status variable 'returned'
        """
        mock_send_template.return_value = {"success": True, "message_id": "test_mid"}

        # 1. Accepted action
        self.rental.status = "approved"
        self.rental.save()
        send_booking_approved_notification(self.rental, force=True)
        call_args_accepted = mock_send_template.call_args
        self.assertEqual(call_args_accepted.kwargs["template_name"], "booking_approved")
        # variables: [name, order_id, request_type, status, HEMOAID]
        self.assertEqual(call_args_accepted.kwargs["variables"][3], "accepted")

        # 2. Delivered action
        self.rental.status = "delivered"
        self.rental.save()
        send_booking_delivered_notification(self.rental, force=True)
        call_args_delivered = mock_send_template.call_args
        self.assertEqual(call_args_delivered.kwargs["template_name"], "booking_delivered")
        self.assertEqual(call_args_delivered.kwargs["variables"][3], "delivered")

        # 3. Returned action
        self.rental.status = "returned"
        self.rental.is_returned = True
        self.rental.save()
        send_return_approved_notification(self.rental, force=True)
        call_args_returned = mock_send_template.call_args
        self.assertEqual(call_args_returned.kwargs["template_name"], "return_approved")
        self.assertEqual(call_args_returned.kwargs["variables"][3], "returned")

    @patch("app.whatsapp.send_whatsapp_template")
    def test_send_booking_whatsapp_routes_to_correct_status(self, mock_send_template):
        """
        Verify send_booking_whatsapp accurately maps:
        - approved -> accepted
        - delivered -> delivered
        - returned -> returned
        """
        from app.whatsapp import send_booking_whatsapp
        mock_send_template.return_value = {"success": True}

        # Delivered order
        self.rental.status = "delivered"
        self.rental.is_returned = False
        self.rental.save()
        send_booking_whatsapp(self.rental, force=True)
        self.assertEqual(mock_send_template.call_args.kwargs["template_name"], "booking_delivered")
        self.assertEqual(mock_send_template.call_args.kwargs["variables"][3], "delivered")

        # Approved order
        self.rental.status = "approved"
        self.rental.is_returned = False
        self.rental.save()
        send_booking_whatsapp(self.rental, force=True)
        self.assertEqual(mock_send_template.call_args.kwargs["template_name"], "booking_approved")
        self.assertEqual(mock_send_template.call_args.kwargs["variables"][3], "accepted")

        # Returned order
        self.rental.status = "returned"
        self.rental.is_returned = True
        self.rental.save()
        send_booking_whatsapp(self.rental, force=True)
        self.assertEqual(mock_send_template.call_args.kwargs["template_name"], "return_approved")
        self.assertEqual(mock_send_template.call_args.kwargs["variables"][3], "returned")

