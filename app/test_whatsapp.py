from django.test import TestCase
from django.contrib.auth.models import User
from unittest.mock import patch, MagicMock
from app.whatsapp_service import (
    WHATSAPP_TEMPLATES,
    validate_and_format_phone,
    render_template_text,
    send_whatsapp_template,
    register_template,
    send_new_booking_notification,
    send_cancel_booking_notification,
    send_return_request_notification,
    send_return_approved_notification,
    send_return_date_extended_notification,
    send_new_blood_request_notification,
    send_blood_request_accepted_notification,
    send_blood_request_cancelled_notification,
    send_blood_request_fulfilled_notification,
)
from app.models import Notification, History, Inventory, BloodRequest
import datetime
from django.core.cache import cache


class WhatsAppServiceTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user(
            username="varsha_test",
            email="varsha@example.com",
            first_name="Varsha",
            password="testpassword"
        )
        self.item = Inventory.objects.create(
            title="Oxygen Concentrator",
            description="Medical Oxygen Concentrator",
            price_per_day=150.00,
            deposit=1000.00,
            available_quantity=5,
            total_quantity=5
        )

    def test_phone_validation_and_formatting(self):
        # 10-digit Indian numbers
        self.assertEqual(validate_and_format_phone("9876543210"), "919876543210")
        self.assertEqual(validate_and_format_phone(" 98765-43210 "), "919876543210")
        self.assertEqual(validate_and_format_phone("+91 98765 43210"), "919876543210")
        self.assertEqual(validate_and_format_phone("09876543210"), "919876543210")

        # 12-digit numbers starting with 91
        self.assertEqual(validate_and_format_phone("919876543210"), "919876543210")

        # International E.164 numbers
        self.assertEqual(validate_and_format_phone("+14155552671"), "14155552671")

        # Invalid numbers
        self.assertIsNone(validate_and_format_phone(None))
        self.assertIsNone(validate_and_format_phone(""))
        self.assertIsNone(validate_and_format_phone("12345"))  # too short
        self.assertIsNone(validate_and_format_phone("abcdefghij"))

    def test_all_9_templates_with_test_data(self):
        """
        Verify that all 9 templates render exactly the expected message text
        using the specified test data:
        Customer Name: Varsha
        Order ID: ORD-1001
        Blood Request ID: BR-1001
        """
        customer_name = "Varsha"
        order_id = "ORD-1001"
        blood_request_id = "BR-1001"

        # 1. new_booking
        msg1 = render_template_text("new_booking", [customer_name, order_id])
        expected1 = "Dear Varsha,\n\nYour order ORD-1001 for medical equipment is under review. You will receive confirmation soon."
        self.assertEqual(msg1, expected1)

        # 2. cancel_booking
        msg2 = render_template_text("cancel_booking", [customer_name, order_id])
        expected2 = "Dear Varsha,\n\nYour order ORD-1001 for medical equipment has been cancelled per request. For any further details contact support."
        self.assertEqual(msg2, expected2)

        # 3. return_request
        msg3 = render_template_text("return_request", [customer_name, order_id])
        expected3 = "Dear Varsha,\n\nYour return request for order ORD-1001 is under review. You will receive confirmation soon."
        self.assertEqual(msg3, expected3)

        # 4. return_approved
        msg4 = render_template_text("return_approved", [customer_name, order_id])
        expected4 = "Dear Varsha,\n\nYour return request for order ORD-1001 has been approved/completed successfully."
        self.assertEqual(msg4, expected4)

        # 5. return_date_extended
        msg5 = render_template_text("return_date_extended", [customer_name, order_id])
        expected5 = "Dear Varsha,\n\nThe return date for your order ORD-1001 has been extended. Please check your order details for the updated return date."
        self.assertEqual(msg5, expected5)

        # 6. new_blood_request
        msg6 = render_template_text("new_blood_request", [customer_name, blood_request_id])
        expected6 = "Dear Varsha,\n\nA new blood request BR-1001 has been submitted successfully. Our team will review the request and update you soon."
        self.assertEqual(msg6, expected6)

        # 7. blood_request_accepted
        msg7 = render_template_text("blood_request_accepted", [customer_name, blood_request_id])
        expected7 = "Dear Varsha,\n\nYour blood request BR-1001 has been accepted/fulfilled successfully. Our team will provide further details if required."
        self.assertEqual(msg7, expected7)

        # 8. blood_request_cancelled
        msg8 = render_template_text("blood_request_cancelled", [customer_name, blood_request_id])
        expected8 = "Dear Varsha,\n\nYour blood request BR-1001 has been cancelled. For any further details, please contact support."
        self.assertEqual(msg8, expected8)

        # 9. blood_request_fulfilled
        msg9 = render_template_text("blood_request_fulfilled", [customer_name, blood_request_id])
        expected9 = "Dear Varsha,\n\nYour blood request BR-1001 has been fulfilled successfully."
        self.assertEqual(msg9, expected9)

    def test_send_whatsapp_template_simulated_mode(self):
        """
        When API credentials are not set, it should safely simulate dispatch,
        log, and record in Notification table.
        """
        result = send_whatsapp_template(
            phone_number="9876543210",
            template_name="new_booking",
            variables=["Varsha", "ORD-1001"],
            event_key="test_sim_new_booking_1",
            user=self.user,
        )
        self.assertTrue(result["success"])
        self.assertTrue(result.get("simulated"))
        self.assertIn("Varsha", result.get("rendered_message", ""))
        self.assertIn("ORD-1001", result.get("rendered_message", ""))

        # Check Notification table audit
        audit_note = Notification.objects.filter(title="WhatsApp: new_booking").first()
        self.assertIsNotNone(audit_note)
        self.assertIn("919876543210", audit_note.message)
        self.assertIn("ORD-1001", audit_note.message)
        self.assertEqual(audit_note.recipient, self.user)

    def test_duplicate_prevention(self):
        """
        Subsequent calls with the same event_key should be detected as duplicates
        and skipped.
        """
        result1 = send_whatsapp_template(
            phone_number="9876543210",
            template_name="new_booking",
            variables=["Varsha", "ORD-1001"],
            event_key="dedup_event_1001",
        )
        self.assertTrue(result1["success"])
        self.assertFalse(result1.get("duplicate", False))

        # Second call with same event_key
        result2 = send_whatsapp_template(
            phone_number="9876543210",
            template_name="new_booking",
            variables=["Varsha", "ORD-1001"],
            event_key="dedup_event_1001",
        )
        self.assertTrue(result2["success"])
        self.assertTrue(result2.get("duplicate", False))

        # Forced send should bypass deduplication
        result3 = send_whatsapp_template(
            phone_number="9876543210",
            template_name="new_booking",
            variables=["Varsha", "ORD-1001"],
            event_key="dedup_event_1001",
            force=True,
        )
        self.assertTrue(result3["success"])
        self.assertFalse(result3.get("duplicate", False))

    def test_business_event_helpers_direct(self):
        """
        Test calling each of the 9 separate business event functions directly.
        """
        # 1. New Booking
        res1 = send_new_booking_notification(
            customer_name="Varsha",
            order_id="ORD-1001",
            phone_number="9876543210",
            force=True
        )
        self.assertTrue(res1["success"])
        self.assertEqual(
            res1["rendered_message"],
            "Dear Varsha,\n\nYour order ORD-1001 for medical equipment is under review. You will receive confirmation soon."
        )

        # 2. Cancel Booking
        res2 = send_cancel_booking_notification(
            customer_name="Varsha",
            order_id="ORD-1001",
            phone_number="9876543210",
            force=True
        )
        self.assertTrue(res2["success"])
        self.assertEqual(
            res2["rendered_message"],
            "Dear Varsha,\n\nYour order ORD-1001 for medical equipment has been cancelled per request. For any further details contact support."
        )

        # 3. Return Request
        res3 = send_return_request_notification(
            customer_name="Varsha",
            order_id="ORD-1001",
            phone_number="9876543210",
            force=True
        )
        self.assertTrue(res3["success"])
        self.assertEqual(
            res3["rendered_message"],
            "Dear Varsha,\n\nYour return request for order ORD-1001 is under review. You will receive confirmation soon."
        )

        # 4. Return Approved
        res4 = send_return_approved_notification(
            customer_name="Varsha",
            order_id="ORD-1001",
            phone_number="9876543210",
            force=True
        )
        self.assertTrue(res4["success"])
        self.assertEqual(
            res4["rendered_message"],
            "Dear Varsha,\n\nYour return request for order ORD-1001 has been approved/completed successfully."
        )

        # 5. Return Date Extended
        res5 = send_return_date_extended_notification(
            customer_name="Varsha",
            order_id="ORD-1001",
            phone_number="9876543210",
            force=True
        )
        self.assertTrue(res5["success"])
        self.assertEqual(
            res5["rendered_message"],
            "Dear Varsha,\n\nThe return date for your order ORD-1001 has been extended. Please check your order details for the updated return date."
        )

        # 6. New Blood Request
        res6 = send_new_blood_request_notification(
            requester_name="Varsha",
            request_id="BR-1001",
            phone_number="9876543210",
            force=True
        )
        self.assertTrue(res6["success"])
        self.assertEqual(
            res6["rendered_message"],
            "Dear Varsha,\n\nA new blood request BR-1001 has been submitted successfully. Our team will review the request and update you soon."
        )

        # 7. Blood Request Accepted
        res7 = send_blood_request_accepted_notification(
            requester_name="Varsha",
            request_id="BR-1001",
            phone_number="9876543210",
            force=True
        )
        self.assertTrue(res7["success"])
        self.assertEqual(
            res7["rendered_message"],
            "Dear Varsha,\n\nYour blood request BR-1001 has been accepted/fulfilled successfully. Our team will provide further details if required."
        )

        # 8. Blood Request Cancelled
        res8 = send_blood_request_cancelled_notification(
            requester_name="Varsha",
            request_id="BR-1001",
            phone_number="9876543210",
            force=True
        )
        self.assertTrue(res8["success"])
        self.assertEqual(
            res8["rendered_message"],
            "Dear Varsha,\n\nYour blood request BR-1001 has been cancelled. For any further details, please contact support."
        )

        # 9. Blood Request Fulfilled
        res9 = send_blood_request_fulfilled_notification(
            requester_name="Varsha",
            request_id="BR-1001",
            phone_number="9876543210",
            force=True
        )
        self.assertTrue(res9["success"])
        self.assertEqual(
            res9["rendered_message"],
            "Dear Varsha,\n\nYour blood request BR-1001 has been fulfilled successfully."
        )

    def test_business_event_with_model_objects(self):
        """
        Verify that passing History and BloodRequest model instances to helpers
        correctly extracts customer name, order_id / request_id, and mobile number.
        """
        # Create History instance
        rental = History.objects.create(
            user=self.user,
            renter_name="Varsha",
            order_id="ORD-1001",
            phone="9876543210",
            rental_item=self.item,
            start_date=datetime.date.today(),
            end_date=datetime.date.today() + datetime.timedelta(days=7),
            quantity=1
        )

        res_booking = send_new_booking_notification(rental, force=True)
        self.assertTrue(res_booking["success"])
        self.assertIn("Varsha", res_booking["rendered_message"])
        self.assertIn("ORD-1001", res_booking["rendered_message"])

        res_cancel = send_cancel_booking_notification(rental, force=True)
        self.assertTrue(res_cancel["success"])
        self.assertIn("Varsha", res_cancel["rendered_message"])
        self.assertIn("ORD-1001", res_cancel["rendered_message"])

        # Create BloodRequest instance
        blood_req = BloodRequest.objects.create(
            patient_name="Patient Varsha",
            hospital_name="City Hospital",
            hospital_area="West",
            blood_group="O+",
            units_required=1,
            coordinator_name="Varsha",
            coordinator_contact="9876543210",
            created_by=self.user,
            request_id="BR-1001"
        )

        res_br_new = send_new_blood_request_notification(blood_req, force=True)
        self.assertTrue(res_br_new["success"])
        self.assertIn("Varsha", res_br_new["rendered_message"])
        self.assertIn("BR-1001", res_br_new["rendered_message"])

        res_br_acc = send_blood_request_accepted_notification(blood_req, force=True)
        self.assertTrue(res_br_acc["success"])
        self.assertIn("Varsha", res_br_acc["rendered_message"])
        self.assertIn("BR-1001", res_br_acc["rendered_message"])

        res_br_canc = send_blood_request_cancelled_notification(blood_req, force=True)
        self.assertTrue(res_br_canc["success"])
        self.assertIn("Varsha", res_br_canc["rendered_message"])
        self.assertIn("BR-1001", res_br_canc["rendered_message"])

        res_br_ful = send_blood_request_fulfilled_notification(blood_req, force=True)
        self.assertTrue(res_br_ful["success"])
        self.assertIn("Varsha", res_br_ful["rendered_message"])
        self.assertIn("BR-1001", res_br_ful["rendered_message"])

    def test_whatsapp_cloud_api_mock(self):
        """
        Verify that WhatsApp Cloud API payload and headers are constructed properly
        when credentials are provided.
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "messaging_product": "whatsapp",
            "contacts": [{"input": "919876543210", "wa_id": "919876543210"}],
            "messages": [{"id": "wamid.HBgLOTE5ODc2NTQzMjEwFQIAERgSQ0E1..."}]
        }

        with patch("requests.post", return_value=mock_response) as mock_post:
            with patch("app.whatsapp_service.get_whatsapp_config", return_value={
                "access_token": "mock_token_12345",
                "phone_number_id": "100020003000",
                "business_account_id": "999888777",
                "api_version": "v18.0",
            }):
                result = send_whatsapp_template(
                    phone_number="9876543210",
                    template_name="new_booking",
                    variables=["Varsha", "ORD-1001"],
                    event_key="mock_test_1001",
                    force=True
                )

                self.assertTrue(result["success"])
                self.assertEqual(result["message_id"], "wamid.HBgLOTE5ODc2NTQzMjEwFQIAERgSQ0E1...")

                # Verify URL, headers, and payload sent to Meta Graph API
                mock_post.assert_called_once()
                args, kwargs = mock_post.call_args
                url = args[0]
                self.assertEqual(url, "https://graph.facebook.com/v18.0/100020003000/messages")
                headers = kwargs["headers"]
                self.assertEqual(headers["Authorization"], "Bearer mock_token_12345")
                payload = kwargs["json"]
                self.assertEqual(payload["messaging_product"], "whatsapp")
                self.assertEqual(payload["to"], "919876543210")
                self.assertEqual(payload["type"], "template")
                self.assertEqual(payload["template"]["name"], "new_booking")
                body_params = payload["template"]["components"][0]["parameters"]
                self.assertEqual(body_params[0]["text"], "Varsha")
                self.assertEqual(body_params[1]["text"], "ORD-1001")

    def test_failure_resilience(self):
        """
        Verify that network failure or API error does not raise uncaught exception.
        """
        with patch("requests.post", side_effect=Exception("Connection timed out")):
            with patch("app.whatsapp_service.get_whatsapp_config", return_value={
                "access_token": "mock_token",
                "phone_number_id": "mock_phone_id",
                "business_account_id": "mock_biz_id",
                "api_version": "v18.0",
            }):
                result = send_whatsapp_template(
                    phone_number="9876543210",
                    template_name="new_booking",
                    variables=["Varsha", "ORD-1001"],
                    force=True,
                )
                self.assertFalse(result["success"])
                self.assertIn("Connection timed out", result["error"])

    def test_register_template_extensibility(self):
        """
        Verify that new templates can be added to the registry easily.
        """
        custom_name = "test_custom_notification"
        custom_tmpl = "Hello {{1}}, your service ticket is {{2}}."
        register_template(custom_name, custom_tmpl, ["Name", "Ticket ID"], "Custom test template")
        self.assertIn(custom_name, WHATSAPP_TEMPLATES)

        rendered = render_template_text(custom_name, ["Varsha", "TCK-999"])
        self.assertEqual(rendered, "Hello Varsha, your service ticket is TCK-999.")

    def test_event_isolation_and_variable_passing(self):
        """
        Verify that each event function invokes send_whatsapp_template with:
        1. ONLY its specific template name.
        2. Exactly the required variables.
        - New order → only New Booking message
        - Cancel order → only Cancel Booking message
        - Return request → only Return Request message
        - Return approved/completed → Return Approved message
        - Return date changed → Return Date Extended message
        - New blood request → New Blood Request message
        - Blood request accepted → Accepted/Fulfilled message
        - Blood request cancelled → Cancelled message
        - Blood request fulfilled → Fulfilled message
        """
        with patch("app.whatsapp_service.send_whatsapp_template") as mock_send:
            mock_send.return_value = {"success": True}

            # 1. New order → only New Booking message
            send_new_booking_notification(customer_name="Varsha", order_id="ORD-1001", phone_number="9876543210")
            self.assertEqual(mock_send.call_count, 1)
            kwargs = mock_send.call_args[1]
            self.assertEqual(kwargs["template_name"], "new_booking")
            self.assertEqual(kwargs["variables"], ["Varsha", "ORD-1001"])
            mock_send.reset_mock()

            # 2. Cancel order → only Cancel Booking message
            send_cancel_booking_notification(customer_name="Varsha", order_id="ORD-1001", phone_number="9876543210")
            self.assertEqual(mock_send.call_count, 1)
            kwargs = mock_send.call_args[1]
            self.assertEqual(kwargs["template_name"], "cancel_booking")
            self.assertEqual(kwargs["variables"], ["Varsha", "ORD-1001"])
            mock_send.reset_mock()

            # 3. Return request → only Return Request message
            send_return_request_notification(customer_name="Varsha", order_id="ORD-1001", phone_number="9876543210")
            self.assertEqual(mock_send.call_count, 1)
            kwargs = mock_send.call_args[1]
            self.assertEqual(kwargs["template_name"], "return_request")
            self.assertEqual(kwargs["variables"], ["Varsha", "ORD-1001"])
            mock_send.reset_mock()

            # 4. Return approved/completed → Return Approved message
            send_return_approved_notification(customer_name="Varsha", order_id="ORD-1001", phone_number="9876543210")
            self.assertEqual(mock_send.call_count, 1)
            kwargs = mock_send.call_args[1]
            self.assertEqual(kwargs["template_name"], "return_approved")
            self.assertEqual(kwargs["variables"], ["Varsha", "ORD-1001"])
            mock_send.reset_mock()

            # 5. Return date changed → Return Date Extended message
            send_return_date_extended_notification(customer_name="Varsha", order_id="ORD-1001", phone_number="9876543210")
            self.assertEqual(mock_send.call_count, 1)
            kwargs = mock_send.call_args[1]
            self.assertEqual(kwargs["template_name"], "return_date_extended")
            self.assertEqual(kwargs["variables"], ["Varsha", "ORD-1001"])
            mock_send.reset_mock()

            # 6. New blood request → New Blood Request message
            send_new_blood_request_notification(requester_name="Varsha", request_id="BR-1001", phone_number="9876543210")
            self.assertEqual(mock_send.call_count, 1)
            kwargs = mock_send.call_args[1]
            self.assertEqual(kwargs["template_name"], "new_blood_request")
            self.assertEqual(kwargs["variables"], ["Varsha", "BR-1001"])
            mock_send.reset_mock()

            # 7. Blood request accepted → Accepted/Fulfilled message
            send_blood_request_accepted_notification(requester_name="Varsha", request_id="BR-1001", phone_number="9876543210")
            self.assertEqual(mock_send.call_count, 1)
            kwargs = mock_send.call_args[1]
            self.assertEqual(kwargs["template_name"], "blood_request_accepted")
            self.assertEqual(kwargs["variables"], ["Varsha", "BR-1001"])
            mock_send.reset_mock()

            # 8. Blood request cancelled → Cancelled message
            send_blood_request_cancelled_notification(requester_name="Varsha", request_id="BR-1001", phone_number="9876543210")
            self.assertEqual(mock_send.call_count, 1)
            kwargs = mock_send.call_args[1]
            self.assertEqual(kwargs["template_name"], "blood_request_cancelled")
            self.assertEqual(kwargs["variables"], ["Varsha", "BR-1001"])
            mock_send.reset_mock()

            # 9. Blood request fulfilled → Fulfilled message
            send_blood_request_fulfilled_notification(requester_name="Varsha", request_id="BR-1001", phone_number="9876543210")
            self.assertEqual(mock_send.call_count, 1)
            kwargs = mock_send.call_args[1]
            self.assertEqual(kwargs["template_name"], "blood_request_fulfilled")
            self.assertEqual(kwargs["variables"], ["Varsha", "BR-1001"])
            mock_send.reset_mock()
