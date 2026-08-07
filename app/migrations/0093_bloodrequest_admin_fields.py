from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0092_supportservicecontact_service_name"),
    ]

    operations = [
        migrations.AddField(
            model_name="bloodrequest",
            name="blood_type",
            field=models.CharField(blank=True, max_length=100, null=True),
        ),
        migrations.AddField(
            model_name="bloodrequest",
            name="price",
            field=models.DecimalField(blank=True, decimal_places=2, default=0, max_digits=10, null=True),
        ),
        migrations.AddField(
            model_name="bloodrequest",
            name="blood_bank",
            field=models.CharField(blank=True, max_length=255, null=True),
        ),
    ]
