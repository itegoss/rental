from django.db import migrations, models


def create_sample_blood_banks(apps, schema_editor):
    BloodBank = apps.get_model('app', 'BloodBank')
    samples = [
        {
            'name': 'KYS Blood Bank',
            'address': 'Station Road, Bhayander West, Thane, Maharashtra 401101',
            'person_name': 'Rajesh Sharma',
            'contact': '9820247550'
        },
        {
            'name': 'Red Cross Blood Center',
            'address': 'Main Road, Mira Road East, Thane, Maharashtra 401107',
            'person_name': 'Amit Patel',
            'contact': '9867348169'
        }
    ]
    for data in samples:
        BloodBank.objects.get_or_create(name=data['name'], defaults=data)


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0093_bloodrequest_admin_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="BloodBank",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=255, verbose_name="Blood Bank Name")),
                ("address", models.TextField(blank=True, null=True, verbose_name="Address")),
                ("person_name", models.CharField(blank=True, max_length=255, null=True, verbose_name="Contact Person Name")),
                ("contact", models.CharField(blank=True, max_length=20, null=True, verbose_name="Contact Number")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "Blood Bank",
                "verbose_name_plural": "Blood Banks",
                "ordering": ["name"],
            },
        ),
        migrations.RunPython(create_sample_blood_banks, reverse_code=migrations.RunPython.noop),
    ]
