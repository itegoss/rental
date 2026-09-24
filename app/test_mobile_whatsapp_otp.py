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


@override_settings(STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class UserManagementMobileUsersTests(TestCase):
    def setUp(self):
        self.client = Client()
        # Admin user to access /users/
        self.admin = User.objects.create_superuser(
            username='admin_test',
            email='admin@example.com',
            password='AdminPassword@123',
            first_name='Admin',
            last_name='User',
        )
        self.client.force_login(self.admin)

    def test_mobile_otp_user_appears_in_user_management_list(self):
        otp_mobile = '9876512345'
        otp_user = User.objects.create_user(
            username=f"user_{otp_mobile}",
            email='',
            first_name='Rohan',
            last_name='Sharma',
        )
        otp_user.set_unusable_password()
        otp_user.save()
        UserDetail.objects.create(
            user=otp_user,
            phone=otp_mobile,
            id_proof_type='',
            id_proof_number='',
        )

        response = self.client.get(reverse('users'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Rohan Sharma')
        self.assertContains(response, f"user_{otp_mobile}")
        self.assertContains(response, otp_mobile)
        self.assertContains(response, 'Mobile OTP')

    def test_google_and_mobile_users_both_visible_in_same_user_list(self):
        from social_django.models import UserSocialAuth

        # Google login user
        google_user = User.objects.create_user(
            username='google_user_test',
            email='googleuser@gmail.com',
            first_name='Google',
            last_name='Person',
        )
        google_user.set_unusable_password()
        google_user.save()
        UserSocialAuth.objects.create(
            user=google_user,
            provider='google-oauth2',
            uid='google_uid_99999',
        )

        # Mobile OTP user
        otp_user = User.objects.create_user(
            username='user_9776655443',
            email='',
            first_name='Mobile',
            last_name='Person',
        )
        otp_user.set_unusable_password()
        otp_user.save()
        UserDetail.objects.create(
            user=otp_user,
            phone='9776655443',
            id_proof_type='',
            id_proof_number='',
        )

        response = self.client.get(reverse('users'))
        self.assertEqual(response.status_code, 200)
        # Both Google and Mobile users should be visible in the same list
        self.assertContains(response, 'googleuser@gmail.com')
        self.assertContains(response, 'Google Person')
        self.assertContains(response, 'Google')

        self.assertContains(response, 'Mobile Person')
        self.assertContains(response, '9776655443')
        self.assertContains(response, 'Mobile OTP')

    def test_verify_otp_creates_user_and_shows_in_user_list(self):
        new_mobile = '9812398123'
        otp = '123456'
        salt = 'salttest'
        otp_hash = hashlib.sha256(f"{otp}:{salt}".encode()).hexdigest()

        visitor = Client()
        session = visitor.session
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

        verify_resp = visitor.post(reverse('verify_otp'), {
            'mobile': new_mobile,
            'otp': '123456',
        })
        self.assertEqual(verify_resp.status_code, 302)

        # Check DB user was created
        created_user = User.objects.filter(username__contains=new_mobile).first()
        self.assertIsNotNone(created_user)
        ud = UserDetail.objects.filter(user=created_user).first()
        self.assertIsNotNone(ud)
        self.assertEqual(ud.phone, new_mobile)

        # Admin verifies user appears in User Management list
        users_resp = self.client.get(reverse('users'))
        self.assertEqual(users_resp.status_code, 200)
        self.assertContains(users_resp, created_user.username)
        self.assertContains(users_resp, new_mobile)
        self.assertContains(users_resp, 'Mobile OTP')

    def test_existing_user_reused_without_duplicate(self):
        # Create existing user
        mobile = '9911223344'
        existing_user = User.objects.create_user(
            username='existing_rahul',
            email='rahul@example.com',
            password='Password@123',
            first_name='Rahul',
            last_name='Verma',
        )
        UserDetail.objects.create(
            user=existing_user,
            phone=mobile,
            id_proof_type='',
            id_proof_number='',
        )
        user_count_before = User.objects.count()

        otp = '654321'
        salt = 'salttest2'
        otp_hash = hashlib.sha256(f"{otp}:{salt}".encode()).hexdigest()

        visitor = Client()
        session = visitor.session
        session['login_otp_data'] = {
            'user_id': existing_user.id,
            'mobile': mobile,
            'otp_hash': otp_hash,
            'otp_salt': salt,
            'expires_at': timezone.now().timestamp() + 300,
            'last_sent_at': timezone.now().timestamp(),
            'attempts': 0,
        }
        session.save()

        verify_resp = visitor.post(reverse('verify_otp'), {
            'mobile': mobile,
            'otp': otp,
        })
        self.assertEqual(verify_resp.status_code, 302)

        # User count must NOT increase
        user_count_after = User.objects.count()
        self.assertEqual(user_count_before, user_count_after)

    def test_mobile_number_storage_consistency(self):
        # Test signup with +91 format
        signup_data = {
            'username': 'consistent_user',
            'email': 'consistent@example.com',
            'mobile': '+91 98700 11223',
            'password': 'StrongPassword@123',
            'confirm_password': 'StrongPassword@123',
        }
        response = self.client.post(reverse('signup'), signup_data)
        self.assertEqual(response.status_code, 302)

        user = User.objects.get(username='consistent_user')
        ud = UserDetail.objects.get(user=user)
        # Must be stored consistently as canonical 10-digit number
        self.assertEqual(ud.phone, '9870011223')

        # Attempting signup with 9870011223 should be blocked as duplicate
        dup_data = {
            'username': 'dup_user',
            'email': 'dup@example.com',
            'mobile': '9870011223',
            'password': 'StrongPassword@123',
            'confirm_password': 'StrongPassword@123',
        }
        dup_resp = self.client.post(reverse('signup'), dup_data)
        self.assertContains(dup_resp, "An account with this mobile number already exists")

    def test_user_list_search_by_mobile_and_name(self):
        target_mobile = '9822334455'
        target_user = User.objects.create_user(
            username=f"user_{target_mobile}",
            email='target@example.com',
            first_name='Aarav',
            last_name='Mehta',
        )
        UserDetail.objects.create(
            user=target_user,
            phone=target_mobile,
            id_proof_type='',
            id_proof_number='',
        )

        # 1. Search by 10-digit phone
        resp1 = self.client.get(reverse('users'), {'q': target_mobile})
        self.assertContains(resp1, 'Aarav Mehta')
        self.assertContains(resp1, target_mobile)

        # 2. Search by formatted phone (+91 ...)
        resp2 = self.client.get(reverse('users'), {'q': f"+91 {target_mobile}"})
        self.assertContains(resp2, 'Aarav Mehta')
        self.assertContains(resp2, target_mobile)

        # 3. Search by First Name
        resp3 = self.client.get(reverse('users'), {'q': 'Aarav'})
        self.assertContains(resp3, 'Aarav Mehta')

    def test_user_list_csv_export(self):
        export_resp = self.client.get(reverse('users'), {'export': 'csv'})
        self.assertEqual(export_resp.status_code, 200)
        self.assertEqual(export_resp['Content-Type'], 'text/csv; charset=utf-8')
        content = export_resp.content.decode('utf-8')
        # Verify CSV headers include Mobile and Login Method
        self.assertIn('ID,Username,Name,Email,Mobile,Login Method,Status,Superuser,Staff,Roles', content)

    @patch('app.views.send_login_otp_whatsapp')
    def test_same_mobile_login_logout_relogin_flow(self, mock_send_wa):
        """
        Exact test flow:
        Mobile -> OTP -> Login -> Add Details & Booking -> Logout -> Same Mobile -> OTP -> Login
        Expected: Same user account (same ID), details and history preserved, no duplicate user created.
        """
        self.client.logout()
        mock_send_wa.return_value = {'success': True, 'method': 'template', 'response': {}}
        mobile = '9876500001'

        # --- STEP 1: First Login via Mobile + OTP ---
        res_post = self.client.post(reverse('signin_mobile'), {'mobile': mobile})
        self.assertEqual(res_post.status_code, 302)

        session = self.client.session
        otp_data = session['login_otp_data']
        salt = otp_data['otp_salt']
        otp_val = '654321'
        otp_data['otp_hash'] = hashlib.sha256(f"{otp_val}:{salt}".encode()).hexdigest()
        session.save()

        res_verify = self.client.post(reverse('verify_otp'), {'otp': otp_val})
        self.assertEqual(res_verify.status_code, 302)

        # Confirm user was created
        first_user = User.objects.get(userdetail__phone=mobile)
        self.assertEqual(first_user.username, f"user_{mobile}")
        user_count_after_first_login = User.objects.count()

        # Update user details & create a booking
        first_user.first_name = 'Rohan'
        first_user.last_name = 'Sharma'
        first_user.save()

        ud = first_user.userdetail
        ud.patient_name = 'Rohan Patient'
        ud.address_line1 = 'Flat 101, Galaxy Apts, Mumbai'
        ud.pincode = '400050'
        ud.id_proof_type = 'Aadhaar'
        ud.id_proof_number = '1234-5678-9012'
        ud.save()

        from app.models import Inventory, History
        inventory_item = Inventory.objects.create(
            title="Hospital Bed Model X",
            description="ICU Bed",
            total_quantity=5,
            available_quantity=5,
            price_per_day=500,
            deposit=2000,
        )
        booking = History.objects.create(
            user=first_user,
            rental_item=inventory_item,
            start_date=datetime.date.today(),
            end_date=datetime.date.today() + datetime.timedelta(days=7),
            renter_name='Rohan Sharma',
            phone=mobile,
            address='Flat 101, Galaxy Apts, Mumbai, 400050',
            status='Approved',
            rent=3500,
            deposit=2000,
            total_amount=5500,
        )

        # --- STEP 2: Logout ---
        logout_resp = self.client.get(reverse('logout'))
        self.assertEqual(logout_resp.status_code, 302)
        # Verify session is flushed
        self.assertNotIn('_auth_user_id', self.client.session)

        # --- STEP 3: Re-login using the SAME mobile (+91 format) + OTP ---
        formatted_mobile = f"+91 {mobile}"
        res_post2 = self.client.post(reverse('signin_mobile'), {'mobile': formatted_mobile})
        self.assertEqual(res_post2.status_code, 302)

        session2 = self.client.session
        otp_data2 = session2['login_otp_data']
        salt2 = otp_data2['otp_salt']
        otp_val2 = '789123'
        otp_data2['otp_hash'] = hashlib.sha256(f"{otp_val2}:{salt2}".encode()).hexdigest()
        session2.save()

        res_verify2 = self.client.post(reverse('verify_otp'), {'otp': otp_val2})
        self.assertEqual(res_verify2.status_code, 302)

        # --- STEP 4: Assertions on User Record ---
        # User ID must be identical to first login
        self.assertEqual(int(self.client.session['_auth_user_id']), first_user.id)
        # Total user count in database must NOT increase
        self.assertEqual(User.objects.count(), user_count_after_first_login)

        # Check session preloaded details
        session_after = self.client.session
        self.assertEqual(session_after.get('phone'), mobile)
        self.assertEqual(session_after.get('user_phone'), mobile)
        self.assertEqual(session_after.get('patient_name'), 'Rohan Patient')
        self.assertEqual(session_after.get('id_proof_number'), '1234-5678-9012')
        self.assertEqual(session_after.get('pincode'), '400050')

        # Check booking summary loads existing booking for this user
        resp_bookings = self.client.get(reverse('bookingsammry'))
        self.assertEqual(resp_bookings.status_code, 200)
        self.assertContains(resp_bookings, "Hospital Bed Model X")
        self.assertContains(resp_bookings, "Rohan Sharma")

        # Check userdetail page loads user's saved profile data
        from app.models import Cart, CartItem
        cart = Cart.objects.create(user=first_user)
        CartItem.objects.create(cart=cart, rental_item=inventory_item, quantity=1)
        resp_userdetail = self.client.get(reverse('userdetail'))
        self.assertEqual(resp_userdetail.status_code, 200)
        self.assertContains(resp_userdetail, 'Rohan Patient')
        self.assertContains(resp_userdetail, mobile)
        self.assertContains(resp_userdetail, '1234-5678-9012')
        self.assertContains(resp_userdetail, '400050')

    @patch('app.views.send_login_otp_whatsapp')
    def test_different_mobile_formats_map_to_same_user(self, mock_send_wa):
        """
        Verify +91XXXXXXXXXX, 91XXXXXXXXXX, 0XXXXXXXXXX, and XXXXXXXXXX all map to same user.
        """
        self.client.logout()
        mock_send_wa.return_value = {'success': True, 'method': 'template', 'response': {}}
        canonical_mobile = '9876543299'

        formats = [
            f"+91 {canonical_mobile}",
            f"91{canonical_mobile}",
            f"0{canonical_mobile}",
            canonical_mobile,
        ]

        assigned_user_id = None

        for idx, fmt in enumerate(formats):
            res_post = self.client.post(reverse('signin_mobile'), {'mobile': fmt})
            self.assertEqual(res_post.status_code, 302)

            session = self.client.session
            otp_data = session['login_otp_data']
            salt = otp_data['otp_salt']
            otp_val = f"11122{idx}"
            otp_data['otp_hash'] = hashlib.sha256(f"{otp_val}:{salt}".encode()).hexdigest()
            session.save()

            res_verify = self.client.post(reverse('verify_otp'), {'otp': otp_val})
            self.assertEqual(res_verify.status_code, 302)

            logged_in_id = int(self.client.session['_auth_user_id'])
            if assigned_user_id is None:
                assigned_user_id = logged_in_id
            else:
                self.assertEqual(logged_in_id, assigned_user_id, f"Format '{fmt}' did not map to same user!")

            # Logout before next attempt
            self.client.get(reverse('logout'))

    def test_user_list_deduplicates_same_mobile(self):
        """
        Ensure User Management list and CSV export show the mobile number ONLY ONCE.
        """
        shared_phone = '9822339988'
        # Create user 1
        u1 = User.objects.create_user(username='orig_user_phone', email='u1@test.com', password='Password@123')
        UserDetail.objects.create(user=u1, phone=shared_phone)

        # Create duplicate user 2 with +91 format in phone
        u2 = User.objects.create_user(username=f'user_{shared_phone}_dup', email='u2@test.com')
        UserDetail.objects.create(user=u2, phone=f"+91{shared_phone}")

        # Login as superuser/staff
        admin = User.objects.create_superuser('test_admin_dedup', 'admin_dedup@test.com', 'Pass@123')
        self.client.force_login(admin)

        # Check User List HTML
        resp = self.client.get(reverse('users'))
        self.assertEqual(resp.status_code, 200)
        content = resp.content.decode('utf-8')
        # Count occurrences of shared_phone in table rows (should only appear once in list)
        self.assertEqual(content.count(shared_phone), 1)

        # Check CSV export
        csv_resp = self.client.get(reverse('users'), {'export': 'csv'})
        csv_content = csv_resp.content.decode('utf-8')
        # In CSV, shared_phone should appear in exactly one data row
        self.assertEqual(csv_content.count(shared_phone), 1)



