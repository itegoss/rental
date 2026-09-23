import datetime
import hashlib
from unittest.mock import patch
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from app.models import UserDetail, Notification
from app.views import find_user_by_mobile
from app.whatsapp_service import send_login_otp_whatsapp


@override_settings(STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class MobileWhatsAppOTPLoginTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='varsha_test',
            email='varsha@example.com',
            password='Password@123',
            first_name='Varsha',
            last_name='Patel',
        )
        self.user_detail = UserDetail.objects.create(
            user=self.user,
            phone='9876543210',
            address_line1='123 Test St',
            city='Mumbai',
            state='Maharashtra',
            pincode='400001',
            id_proof_type='Aadhar',
            id_proof_number='123456789012',
        )

    def test_find_user_by_mobile(self):
        # 10-digit exact match
        user, p10 = find_user_by_mobile('9876543210')
        self.assertEqual(user, self.user)
        self.assertEqual(p10, '9876543210')

        # 91 prefix match
        user, p10 = find_user_by_mobile('919876543210')
        self.assertEqual(user, self.user)
        self.assertEqual(p10, '9876543210')

        # +91 with spaces / dashes
        user, p10 = find_user_by_mobile('+91 98765-43210')
        self.assertEqual(user, self.user)
        self.assertEqual(p10, '9876543210')

        # Non-existent user
        user, p10 = find_user_by_mobile('9999999999')
        self.assertIsNone(user)
        self.assertEqual(p10, '9999999999')

        # Invalid phone format
        user, p10 = find_user_by_mobile('12345')
        self.assertIsNone(user)
        self.assertIsNone(p10)

    @patch('app.views.send_login_otp_whatsapp')
    def test_signin_mobile_unregistered_sends_otp_without_error(self, mock_send):
        mock_send.return_value = {'success': True}
        response = self.client.post(reverse('signin_mobile'), {'mobile': '9999999999'})
        # Should NOT show error; should redirect to verify_otp
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('verify_otp'))
        self.assertTrue(mock_send.called)
        # Verify account NOT created before OTP verification
        self.assertFalse(User.objects.filter(username__contains='9999999999').exists())
        # Verify session has mobile with user_id = None
        session = self.client.session
        otp_data = session.get('login_otp_data')
        self.assertIsNotNone(otp_data)
        self.assertIsNone(otp_data['user_id'])
        self.assertEqual(otp_data['mobile'], '9999999999')

    @patch('app.views.send_login_otp_whatsapp')
    def test_signin_mobile_sends_whatsapp_otp(self, mock_send):
        mock_send.return_value = {'success': True}
        response = self.client.post(reverse('signin_mobile'), {'mobile': '9876543210'})
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('verify_otp'))

        # Verify WhatsApp service was called
        self.assertTrue(mock_send.called)
        args, kwargs = mock_send.call_args
        phone_arg = args[0]
        otp_arg = args[1]
        self.assertEqual(phone_arg, '9876543210')
        self.assertEqual(len(otp_arg), 6)
        self.assertTrue(otp_arg.isdigit())

        # Verify session does NOT store plain text OTP
        session = self.client.session
        otp_data = session.get('login_otp_data')
        self.assertIsNotNone(otp_data)
        self.assertNotIn('otp', otp_data)
        self.assertIn('otp_hash', otp_data)
        self.assertIn('otp_salt', otp_data)
        self.assertEqual(otp_data['user_id'], self.user.id)
        self.assertEqual(otp_data['mobile'], '9876543210')

    @patch('app.views.send_login_otp_whatsapp')
    def test_resend_cooldown_enforced(self, mock_send):
        mock_send.return_value = {'success': True}
        # First request
        self.client.post(reverse('signin_mobile'), {'mobile': '9876543210'})
        self.assertEqual(mock_send.call_count, 1)

        # Immediate second request should be blocked by cooldown
        response = self.client.post(reverse('signin_mobile'), {'mobile': '9876543210'})
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('verify_otp'))
        # WhatsApp sending function should NOT have been called a second time
        self.assertEqual(mock_send.call_count, 1)

    def test_verify_otp_success_logs_in_user(self):
        # Setup session with secure hash
        otp = '654321'
        salt = 'abcdef12'
        otp_hash = hashlib.sha256(f"{otp}:{salt}".encode()).hexdigest()
        session = self.client.session
        session['login_otp_data'] = {
            'user_id': self.user.id,
            'mobile': '9876543210',
            'otp_hash': otp_hash,
            'otp_salt': salt,
            'expires_at': timezone.now().timestamp() + 300,
            'last_sent_at': timezone.now().timestamp(),
            'attempts': 0,
        }
        session.save()

        response = self.client.post(reverse('verify_otp'), {
            'mobile': '9876543210',
            'otp': '654321'
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('index'))

        # Verify user is logged in
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.id)
        # Verify OTP session data is wiped
        self.assertNotIn('login_otp_data', self.client.session)

    def test_verify_otp_new_user_auto_creates_account_and_logs_in(self):
        new_mobile = '9988776655'
        otp = '123456'
        salt = 'salt1234'
        otp_hash = hashlib.sha256(f"{otp}:{salt}".encode()).hexdigest()

        session = self.client.session
        session['login_otp_data'] = {
            'user_id': None,
            'mobile': new_mobile,
            'otp_hash': otp_hash,
            'otp_salt': salt,
            'expires_at': timezone.now().timestamp() + 300,
            'last_sent_at': timezone.now().timestamp(),
            'attempts': 0,
        }
        session.save()

        # Before verification: user does not exist
        self.assertFalse(User.objects.filter(username__contains=new_mobile).exists())

        response = self.client.post(reverse('verify_otp'), {
            'mobile': new_mobile,
            'otp': '123456',
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('index'))

        # After verification: User account automatically created
        new_user = User.objects.filter(username__contains=new_mobile).first()
        self.assertIsNotNone(new_user)
        self.assertTrue(new_user.username.startswith('user_9988776655'))
        self.assertTrue(new_user.is_active)

        # Verified mobile saved in UserDetail
        ud = UserDetail.objects.filter(user=new_user).first()
        self.assertIsNotNone(ud)
        self.assertEqual(ud.phone, new_mobile)

        # User is automatically logged in
        self.assertEqual(int(self.client.session['_auth_user_id']), new_user.id)

    def test_verify_otp_existing_user_no_duplicate_created(self):
        initial_user_count = User.objects.count()
        otp = '654321'
        salt = 'abcdef12'
        otp_hash = hashlib.sha256(f"{otp}:{salt}".encode()).hexdigest()
        session = self.client.session
        session['login_otp_data'] = {
            'user_id': self.user.id,
            'mobile': '9876543210',
            'otp_hash': otp_hash,
            'otp_salt': salt,
            'expires_at': timezone.now().timestamp() + 300,
            'last_sent_at': timezone.now().timestamp(),
            'attempts': 0,
        }
        session.save()

        response = self.client.post(reverse('verify_otp'), {
            'mobile': '9876543210',
            'otp': '654321'
        })
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('index'))

        # Existing user logged in
        self.assertEqual(int(self.client.session['_auth_user_id']), self.user.id)
        # Duplicate user was NOT created
        self.assertEqual(User.objects.count(), initial_user_count)

    def test_verify_otp_incorrect_code_and_limit(self):
        otp = '654321'
        salt = 'abcdef12'
        otp_hash = hashlib.sha256(f"{otp}:{salt}".encode()).hexdigest()
        session = self.client.session
        session['login_otp_data'] = {
            'user_id': self.user.id,
            'mobile': '9876543210',
            'otp_hash': otp_hash,
            'otp_salt': salt,
            'expires_at': timezone.now().timestamp() + 300,
            'last_sent_at': timezone.now().timestamp(),
            'attempts': 0,
        }
        session.save()

        # Attempt 1: wrong OTP
        response = self.client.post(reverse('verify_otp'), {'mobile': '9876543210', 'otp': '111111'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid OTP. 2 attempt(s) remaining.')

        # Attempt 2: wrong OTP
        response = self.client.post(reverse('verify_otp'), {'mobile': '9876543210', 'otp': '222222'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid OTP. 1 attempt(s) remaining.')

        # Attempt 3: wrong OTP
        response = self.client.post(reverse('verify_otp'), {'mobile': '9876543210', 'otp': '333333'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Invalid OTP. 0 attempt(s) remaining.')

        # Attempt 4: Exceeded -> Clears session and redirects
        response = self.client.post(reverse('verify_otp'), {'mobile': '9876543210', 'otp': '444444'})
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('signin_mobile'))
        self.assertNotIn('login_otp_data', self.client.session)

    def test_verify_otp_expired(self):
        otp = '654321'
        salt = 'abcdef12'
        otp_hash = hashlib.sha256(f"{otp}:{salt}".encode()).hexdigest()
        session = self.client.session
        session['login_otp_data'] = {
            'user_id': self.user.id,
            'mobile': '9876543210',
            'otp_hash': otp_hash,
            'otp_salt': salt,
            'expires_at': timezone.now().timestamp() - 10, # already expired
            'last_sent_at': timezone.now().timestamp() - 310,
            'attempts': 0,
        }
        session.save()

        response = self.client.post(reverse('verify_otp'), {'mobile': '9876543210', 'otp': '654321'})
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('signin_mobile'))
        self.assertNotIn('login_otp_data', self.client.session)

    @patch('app.whatsapp_service.send_whatsapp_template')
    def test_send_login_otp_whatsapp_service(self, mock_send):
        mock_send.return_value = {'success': True}
        res = send_login_otp_whatsapp('9876543210', '123456', user=self.user)
        self.assertTrue(res['success'])
        self.assertTrue(mock_send.called)
        kwargs = mock_send.call_args.kwargs
        self.assertEqual(kwargs['template_name'], 'login_otp')
        variables = kwargs['variables']
        self.assertEqual(variables[0], 'Varsha Patel')
        self.assertEqual(variables[1], '123456')
        self.assertEqual(variables[2], 'login OTP')
        self.assertEqual(variables[3], 'valid for 5 minutes')
        self.assertEqual(variables[4], 'Sick Bed Services')

    @patch('requests.post')
    def test_audit_log_redacts_otp(self, mock_post):
        from unittest.mock import MagicMock
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"messageId": "msg-otp-123"}
        mock_resp.text = '{"messageId": "msg-otp-123"}'
        mock_post.return_value = mock_resp

        res = send_login_otp_whatsapp('9876543210', '981273', user=self.user)
        self.assertTrue(res['success'])

        # Check Notification table
        audit = Notification.objects.filter(title='WhatsApp: login_otp').last()
        self.assertIsNotNone(audit)
        # Verify plain text OTP is NOT in audit message
        self.assertNotIn('981273', audit.message)
        self.assertIn('******', audit.message)

    def test_signup_creates_account_and_redirects_to_signin_without_otp(self):
        signup_data = {
            'username': 'newuser123',
            'email': 'newuser@example.com',
            'mobile': '9123456780',
            'password': 'StrongPassword@123',
            'confirm_password': 'StrongPassword@123',
        }
        response = self.client.post(reverse('signup'), signup_data)
        # Should redirect directly to signin page
        self.assertEqual(response.status_code, 302)
        self.assertRedirects(response, reverse('signin'))

        # Check User was created
        new_user = User.objects.filter(username='newuser123').first()
        self.assertIsNotNone(new_user)
        self.assertEqual(new_user.email, 'newuser@example.com')

        # Check UserDetail has phone
        ud = UserDetail.objects.filter(user=new_user).first()
        self.assertIsNotNone(ud)
        self.assertEqual(ud.phone, '9123456780')

        # Verify no OTP data in session
        self.assertNotIn('otp_data', self.client.session)
        self.assertNotIn('login_otp_data', self.client.session)

