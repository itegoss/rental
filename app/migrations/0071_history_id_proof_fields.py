# Generated manually for booking-specific ID proof storage.

import app.models
import django.core.validators
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('app', '0041_notifyrequest'),
    ]

    operations = [
        migrations.AddField(
            model_name='history',
            name='id_proof_file',
            field=models.FileField(
                blank=True,
                null=True,
                upload_to='id_proofs/',
                validators=[
                    django.core.validators.FileExtensionValidator(allowed_extensions=['png', 'jpg', 'jpeg', 'pdf']),
                    app.models.validate_id_proof_file_size,
                ],
            ),
        ),
        migrations.AddField(
            model_name='history',
            name='id_proof_number',
            field=models.CharField(blank=True, max_length=30, null=True),
        ),
        migrations.AddField(
            model_name='history',
            name='id_proof_type',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
    ]
