

from django import forms
from django.contrib.auth.models import User
from django.db.models import Q
import re
from django.core.exceptions import ValidationError
from django.core.validators import FileExtensionValidator
from django.utils import timezone
from .models import BloodRequest, CampOrganizer, BloodDonor, EventVolunteer, Role, UserRole


class AssignEmployeeForm(forms.Form):
    assigned_employee = forms.ModelChoiceField(
        queryset=User.objects.filter(
            Q(role_assignments__isnull=False) | Q(is_staff=True) | Q(is_superuser=True),
            is_active=True
        ).distinct().order_by('username'),
        required=True,
        label='Employee / Volunteer'
    )
    remarks = forms.CharField(required=False, widget=forms.Textarea(attrs={'rows': 3, 'class': 'form-control'}))

class ContactForm(forms.Form):
    name = forms.CharField(
        max_length=100,
        label="Your Name",
        widget=forms.TextInput(attrs={
            'placeholder': 'Enter your name',
            'class': 'form-control'
        })
    )
    email = forms.EmailField(
        label="Your Email",
        widget=forms.EmailInput(attrs={
            'placeholder': 'Enter your email',
            'class': 'form-control'
        })
    )
    message = forms.CharField(
        label="Message",
        widget=forms.Textarea(attrs={
            'placeholder': 'Write your inquiry here',
            'class': 'form-control',
            'rows': 5
        })
    )


class BloodRequestForm(forms.ModelForm):
    blood_group = forms.ChoiceField(choices=BloodRequest.BLOOD_GROUP_CHOICES, required=False, initial='', label='Blood Group')
    blood_component = forms.ChoiceField(choices=BloodRequest.BLOOD_COMPONENT_CHOICES, required=False, initial='', label='Blood Component')
    prescription = forms.FileField(
        required=True,
        widget=forms.FileInput(attrs={'accept': '.jpg,.jpeg,.png,.pdf,.img'}),
        error_messages={'required': "Doctor's prescription image/document is mandatory. Please upload a file."}
    )
    consent = forms.BooleanField(
        required=True,
        error_messages={'required': 'You must consent to the terms before submitting.'}
    )
    units_required = forms.IntegerField(required=False, min_value=1)
    price = forms.DecimalField(required=False, min_value=0, max_digits=10, decimal_places=2, label='Price')
    blood_bank = forms.CharField(required=False, label='Blood Bank')

    class Meta:
        model = BloodRequest
        fields = [
            'patient_name', 'hospital_name', 'hospital_area', 'blood_group', 'blood_component', 'units_required',
            'coordinator_name', 'coordinator_contact', 'reference_name',
            'reference_contact', 'prescription', 'consent',
            'price', 'blood_bank'
        ]

    def clean_blood_group(self):
        bg = self.cleaned_data.get('blood_group')
        return bg if bg else ''

    def clean_blood_component(self):
        bc = self.cleaned_data.get('blood_component')
        return bc if bc else ''

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.pk and self.instance.prescription:
            self.fields['prescription'].required = False

    def clean_coordinator_contact(self):
        contact = self.cleaned_data.get('coordinator_contact', '').strip()
        if not re.match(r'^\d{10}$', contact):
            raise ValidationError("Contact number must be exactly 10 digits.")
        return contact

    def clean_reference_contact(self):
        contact = self.cleaned_data.get('reference_contact', '')
        if contact:
            contact = contact.strip()
            if not re.match(r'^\d{10}$', contact):
                raise ValidationError("Reference contact number must be exactly 10 digits.")
        return contact

    def clean(self):
        cleaned_data = super().clean()
        return cleaned_data


class CampOrganizerForm(forms.ModelForm):
    class Meta:
        model = CampOrganizer
        fields = [
            'organizer_name', 'organization_name', 'contact_number', 'email',
            'proposed_date', 'proposed_venue', 'expected_donors',
            'mobile_van_required', 'volunteers_available'
        ]

    def clean_contact_number(self):
        contact = self.cleaned_data.get('contact_number', '').strip()
        if not re.match(r'^\d{10}$', contact):
            raise ValidationError("Contact number must be exactly 10 digits.")
        return contact

    def clean_proposed_date(self):
        proposed_date = self.cleaned_data.get('proposed_date')
        if proposed_date:
            if proposed_date < timezone.localdate():
                raise ValidationError("Proposed date must be in the future.")
        return proposed_date

    def clean_expected_donors(self):
        donors = self.cleaned_data.get('expected_donors')
        if donors is not None and donors <= 0:
            raise ValidationError("Expected number of donors must be greater than zero.")
        return donors

    def clean(self):
        cleaned_data = super().clean()
        org_name = cleaned_data.get('organization_name')
        proposed_date = cleaned_data.get('proposed_date')
        if org_name and proposed_date:
            duplicates = CampOrganizer.objects.filter(
                organization_name__iexact=org_name,
                proposed_date=proposed_date
            )
            if duplicates.exists():
                raise ValidationError("A camp organization request for this organization on this date has already been submitted.")
        return cleaned_data


class BloodDonorForm(forms.ModelForm):
    full_name = forms.CharField(max_length=255, required=True, label='Full Name')

    class Meta:
        model = BloodDonor
        fields = [
            'full_name', 'contact_number', 'date_of_birth',
            'gender', 'blood_group', 'area_of_residence',
            'reference_name', 'reference_contact'
        ]

    def clean_contact_number(self):
        contact = self.cleaned_data.get('contact_number', '').strip()
        if not re.match(r'^\d{10}$', contact):
            raise ValidationError("Contact number must be exactly 10 digits.")
        one_day_ago = timezone.now() - timezone.timedelta(days=1)
        if BloodDonor.objects.filter(contact_number=contact, created_at__gte=one_day_ago).exists():
            raise ValidationError("A donor with this contact number has already registered today.")
        return contact

    def clean_reference_contact(self):
        contact = self.cleaned_data.get('reference_contact', '')
        if contact:
            contact = contact.strip()
            if not re.match(r'^\d{10}$', contact):
                raise ValidationError("Reference contact number must be exactly 10 digits.")
        return contact

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get('date_of_birth')
        if dob:
            if dob > timezone.localdate():
                raise ValidationError("Date of birth cannot be in the future.")
        return dob


class EventVolunteerForm(forms.ModelForm):
    # Email is optional
    email = forms.EmailField(
        required=False,
        widget=forms.EmailInput(attrs={'placeholder': 'Enter email address'})
    )
    # Date of birth is mandatory
    date_of_birth = forms.DateField(
        required=True,
        widget=forms.DateInput(attrs={'type': 'date'}),
        error_messages={'required': 'Date of birth is required.'}
    )

    class Meta:
        model = EventVolunteer
        fields = [
            'full_name', 'contact_number', 'email', 'date_of_birth',
            'gender', 'area_of_residence', 'event_interest', 'skills_remarks'
        ]

    def clean_contact_number(self):
        contact = self.cleaned_data.get('contact_number', '').strip()
        if not re.match(r'^\d{10}$', contact):
            raise ValidationError("Contact number must be exactly 10 digits.")
        one_day_ago = timezone.now() - timezone.timedelta(days=1)
        if EventVolunteer.objects.filter(contact_number=contact, created_at__gte=one_day_ago).exists():
            raise ValidationError("A volunteer with this contact number has already registered today.")
        return contact

    def clean_date_of_birth(self):
        dob = self.cleaned_data.get('date_of_birth')
        if not dob:
            raise ValidationError("Date of birth is required.")
        if dob > timezone.localdate():
            raise ValidationError("Date of birth cannot be in the future.")
        return dob
