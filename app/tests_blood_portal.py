import datetime
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.contrib.auth.models import User
from django.utils import timezone
from django.core.files.uploadedfile import SimpleUploadedFile
from app.models import BloodRequest, CampOrganizer, BloodDonor, EventVolunteer, Notification
from app.forms import BloodRequestForm, CampOrganizerForm, BloodDonorForm, EventVolunteerForm


@override_settings(STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class BloodRequestWorkflowTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user(username='admin', password='password123', is_staff=True)
        self.client = Client()
        self.client.force_login(self.admin)

    def test_status_flow_requires_next_valid_step(self):
        req = BloodRequest.objects.create(
            patient_name='Flow Patient',
            hospital_name='City Hospital',
            hospital_area='Bhayander',
            blood_group='B+',
            coordinator_name='Coordinator',
            coordinator_contact='9876543210',
            consent=True,
            status='Pending',
        )

        response = self.client.post(reverse('admin_edit_blood_request_status', args=[req.id]), {'action': 'accept'})
        self.assertEqual(response.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, 'Accepted')

        volunteer = User.objects.create_user(username='volunteer1', password='password123', is_staff=True)
        response = self.client.post(reverse('admin_edit_blood_request_status', args=[req.id]), {'action': 'assign', 'assigned_employee': volunteer.id})
        self.assertEqual(response.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, 'Assigned')
        self.assertEqual(req.assigned_employee, volunteer)

        response = self.client.post(reverse('admin_edit_blood_request_status', args=[req.id]), {'action': 'advance'})
        self.assertEqual(response.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.status, 'Searching')

        response = self.client.post(reverse('admin_edit_blood_request_status', args=[req.id]), {'action': 'advance'})
        req.refresh_from_db()
        self.assertEqual(req.status, 'Blood Available')

        response = self.client.post(reverse('admin_edit_blood_request_status', args=[req.id]), {'action': 'advance'})
        req.refresh_from_db()
        self.assertEqual(req.status, 'Ready for Pickup')

        response = self.client.post(reverse('admin_edit_blood_request_status', args=[req.id]), {'action': 'advance'})
        req.refresh_from_db()
        self.assertEqual(req.status, 'Received')

        response = self.client.post(reverse('admin_edit_blood_request_status', args=[req.id]), {'action': 'advance'})
        req.refresh_from_db()
        self.assertEqual(req.status, 'Completed')

        response = self.client.post(reverse('admin_edit_blood_request_status', args=[req.id]), {'action': 'advance'})
        req.refresh_from_db()
        self.assertEqual(req.status, 'Completed')

    def test_edit_blood_request_get(self):
        req = BloodRequest.objects.create(
            patient_name='Original Patient',
            hospital_name='Original Hospital',
            hospital_area='Original Area',
            blood_group='A+',
            coordinator_name='Original Coordinator',
            coordinator_contact='9876543210',
            consent=True,
            status='Pending',
        )
        response = self.client.get(reverse('edit_blood_request', args=[req.id]))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Original Patient')
        self.assertContains(response, 'Edit Blood')
        self.assertContains(response, 'Request')

    def test_edit_blood_request_post(self):
        prescription_file = SimpleUploadedFile("prescription.jpg", b"file_content", content_type="image/jpeg")
        req = BloodRequest.objects.create(
            patient_name='Original Patient',
            hospital_name='Original Hospital',
            hospital_area='Original Area',
            blood_group='A+',
            coordinator_name='Original Coordinator',
            coordinator_contact='9876543210',
            consent=True,
            status='Pending',
            prescription=prescription_file,
        )
        data = {
            'patient_name': 'Updated Patient',
            'hospital_name': 'Updated Hospital',
            'hospital_area': 'Updated Area',
            'blood_group': 'B+',
            'units_required': 2,
            'coordinator_name': 'Updated Coordinator',
            'coordinator_contact': '9876543210',
            'consent': True,
        }
        response = self.client.post(reverse('edit_blood_request', args=[req.id]), data=data)
        self.assertEqual(response.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.patient_name, 'Updated Patient')
        self.assertEqual(req.blood_group, 'B+')

    def test_generic_action_handler_edit(self):
        req = BloodRequest.objects.create(
            patient_name='Generic Action Patient',
            hospital_name='Generic Hospital',
            hospital_area='Generic Area',
            blood_group='O+',
            coordinator_name='Coordinator',
            coordinator_contact='9876543210',
            consent=True,
            status='Pending',
        )
        response = self.client.post(reverse('admin_edit_blood_request_status', args=[req.id]), {'action': 'edit'})
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'Generic Action Patient')

@override_settings(STORAGES={'default': {'BACKEND': 'django.core.files.storage.FileSystemStorage'}, 'staticfiles': {'BACKEND': 'django.contrib.staticfiles.storage.StaticFilesStorage'}})
class BloodPortalTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username='testuser', password='password123')
        self.client = Client()

    def test_blood_request_form_valid(self):
        prescription_file = SimpleUploadedFile("prescription.jpg", b"file_content", content_type="image/jpeg")
        data = {
            'patient_name': 'John Doe',
            'hospital_name': 'City Hospital',
            'hospital_area': 'Bhayander East',
            'blood_group': 'B+',
            'coordinator_name': 'Jane Doe',
            'coordinator_contact': '9876543210',
            'reference_name': 'Bob Smith',
            'reference_contact': '9123456789',
            'consent': True,
        }
        form = BloodRequestForm(data=data, files={'prescription': prescription_file})
        self.assertTrue(form.is_valid(), form.errors)

    def test_blood_request_form_invalid_phone(self):
        data = {
            'patient_name': 'John Doe',
            'hospital_name': 'City Hospital',
            'hospital_area': 'Bhayander East',
            'blood_group': 'B+',
            'coordinator_name': 'Jane Doe',
            'coordinator_contact': '12345',  # Invalid contact
            'consent': True,
        }
        form = BloodRequestForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('coordinator_contact', form.errors)

    def test_request_blood_form_renders_units_required_field(self):
        self.client.force_login(self.user)
        response = self.client.get(reverse('request_blood'))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'name="units_required"')

    def test_assign_employee_view_assigns_request_to_active_user(self):
        admin = User.objects.create_user(username='adminassign', password='password123', is_staff=True)
        employee = User.objects.create_user(username='employee1', password='password123', is_active=True, is_staff=True)
        req = BloodRequest.objects.create(
            patient_name='Assign Patient',
            hospital_name='City Hospital',
            hospital_area='Bhayander',
            blood_group='B+',
            coordinator_name='Coordinator',
            coordinator_contact='9876543210',
            consent=True,
            status='Accepted',
        )

        self.client.force_login(admin)
        response = self.client.post(
            reverse('assign_blood_request_employee', args=[req.id]),
            {'assigned_employee': employee.id, 'remarks': 'Please assist'}
        )

        self.assertEqual(response.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.assigned_employee, employee)
        self.assertEqual(req.assigned_by, admin)
        self.assertIsNotNone(req.assigned_at)
        self.assertEqual(req.status, 'Assigned')

        notification = Notification.objects.filter(recipient=employee, title='Blood Request Assigned').first()
        self.assertIsNotNone(notification)
        self.assertEqual(notification.link, f'/request-blood/view/{req.id}/')
        self.assertFalse(notification.is_read)

    def test_assign_employee_creates_notification_for_assigned_user(self):
        admin = User.objects.create_user(username='adminassign2', password='password123', is_staff=True)
        employee = User.objects.create_user(username='employee2', password='password123', is_active=True, is_staff=True)
        req = BloodRequest.objects.create(
            patient_name='Assign Patient 2',
            hospital_name='City Hospital',
            hospital_area='Bhayander',
            blood_group='B+',
            coordinator_name='Coordinator',
            coordinator_contact='9876543210',
            consent=True,
            status='Accepted',
        )

        self.client.force_login(admin)
        response = self.client.post(
            reverse('assign_blood_request_employee', args=[req.id]),
            {'assigned_employee': employee.id, 'remarks': 'Please assist'}
        )

        self.assertEqual(response.status_code, 302)
        req.refresh_from_db()
        self.assertEqual(req.assigned_employee, employee)

        notification = Notification.objects.filter(recipient=employee, title='Blood Request Assigned').first()
        self.assertIsNotNone(notification)
        self.assertEqual(notification.link, f'/request-blood/view/{req.id}/')
        self.assertEqual(notification.message, f'You have been assigned to blood request for {req.patient_name} ({req.blood_group}) at {req.hospital_name}. Please review the request.')
        self.assertFalse(notification.is_read)

    def test_camp_organizer_form_future_date(self):
        data = {
            'organizer_name': 'Organizer Name',
            'organization_name': 'HEMOAID Group',
            'contact_number': '9876543210',
            'email': 'organizer@example.com',
            'proposed_date': timezone.localdate() - datetime.timedelta(days=1),  # Past date
            'proposed_venue': 'Bhayander Hall',
            'expected_donors': 50,
            'mobile_van_required': 'True',
            'volunteers_available': 'False'
        }
        form = CampOrganizerForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('proposed_date', form.errors)

    def test_blood_donor_form_underage(self):
        # Under 18 check
        dob = timezone.localdate() - datetime.timedelta(days=17 * 365)
        data = {
            'first_name': 'Alex',
            'last_name': 'Hunter',
            'contact_number': '9876543210',
            'date_of_birth': dob,
            'gender': 'Male',
            'blood_group': 'O+',
            'area_of_residence': 'Bhayander West',
        }
        form = BloodDonorForm(data=data)
        self.assertFalse(form.is_valid())
        self.assertIn('date_of_birth', form.errors)

    def test_blood_request_view_submission(self):
        self.client.force_login(self.user)
        prescription_file = SimpleUploadedFile("prescription.jpg", b"file_content", content_type="image/jpeg")
        data = {
            'patient_name': 'Test Patient',
            'hospital_name': 'Test Hospital',
            'hospital_area': 'Test Area',
            'blood_group': 'AB+',
            'units_required': 1,
            'coordinator_name': 'Test Coordinator',
            'coordinator_contact': '9988776655',
            'prescription': prescription_file,
            'consent': True,
        }
        response = self.client.post(reverse('request_blood'), data=data)
        self.assertEqual(response.status_code, 302)  # Redirects to home page
        self.assertEqual(BloodRequest.objects.count(), 1)
        self.assertEqual(BloodRequest.objects.first().patient_name, 'Test Patient')

    def test_organize_camp_view_submission(self):
        future_date = timezone.localdate() + datetime.timedelta(days=10)
        data = {
            'organizer_name': 'Test Organizer',
            'organization_name': 'Test Org',
            'contact_number': '9988776655',
            'email': 'org@test.com',
            'proposed_date': future_date,
            'proposed_venue': 'Test Venue',
            'expected_donors': 100,
            'mobile_van_required': 'True',
            'volunteers_available': 'True'
        }
        response = self.client.post(reverse('organize_camp'), data=data)
        self.assertEqual(response.status_code, 302)  # Redirects to home
        self.assertEqual(CampOrganizer.objects.count(), 1)

    def test_be_donor_view_submission(self):
        dob = timezone.localdate() - datetime.timedelta(days=25 * 365)
        data = {
            'first_name': 'Test',
            'last_name': 'Donor',
            'contact_number': '9988776655',
            'date_of_birth': dob,
            'gender': 'Female',
            'blood_group': 'O-',
            'area_of_residence': 'Test Residence',
        }
        response = self.client.post(reverse('be_donor'), data=data)
        self.assertEqual(response.status_code, 302)  # Redirects to home
        self.assertEqual(BloodDonor.objects.count(), 1)

    def test_volunteer_event_view_submission(self):
        data = {
            'full_name': 'Volunteer Hero',
            'contact_number': '9876543210',
            'email': 'volunteer@test.com',
            'date_of_birth': timezone.localdate() - datetime.timedelta(days=20 * 365),
            'area_of_residence': 'Bhayander West',
            'event_interest': 'Blood Camp Support',
        }
        response = self.client.post(reverse('volunteer_event'), data=data)
        self.assertEqual(response.status_code, 302)  # Redirects to home
        self.assertEqual(EventVolunteer.objects.count(), 1)
        self.assertEqual(EventVolunteer.objects.first().full_name, 'Volunteer Hero')

    def test_medical_services_view(self):
        response = self.client.get(reverse('medical_services'))
        self.assertEqual(response.status_code, 200)
        self.assertTemplateUsed(response, 'medical_services.html')
        self.assertContains(response, 'Services')

    def test_update_camp_status(self):
        admin = User.objects.create_user(username='campadmin', password='password123', is_staff=True)
        camp = CampOrganizer.objects.create(
            organizer_name='Camp Org',
            organization_name='Test Org',
            contact_number='9876543210',
            email='test@org.com',
            proposed_date=timezone.localdate() + datetime.timedelta(days=5),
            proposed_venue='Venue',
            expected_donors=50,
            status='Pending'
        )

        # Test valid statuses: Completed, Cancelled, Pending
        self.client.force_login(admin)
        for status_val in ['Completed', 'Cancelled', 'Pending']:
            response = self.client.post(reverse('update_camp_status', args=[camp.id]), {'status': status_val})
            self.assertEqual(response.status_code, 200)
            data = response.json()
            self.assertTrue(data['success'])
            camp.refresh_from_db()
            self.assertEqual(camp.status, status_val)

        # Test invalid status
        response = self.client.post(reverse('update_camp_status', args=[camp.id]), {'status': 'InvalidStatus'})
        self.assertEqual(response.status_code, 400)
        data = response.json()
        self.assertFalse(data['success'])
