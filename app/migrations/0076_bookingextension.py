# Generated manually on 2026-07-01

from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0075_alter_history_is_today_reminder_sent"),
    ]

    operations = [
        migrations.CreateModel(
            name="BookingExtension",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("extension_no", models.PositiveIntegerField()),
                ("extended_on", models.DateTimeField(auto_now_add=True)),
                ("previous_return_date", models.DateField()),
                ("new_return_date", models.DateField()),
                ("extra_days", models.PositiveIntegerField()),
                ("quantity", models.PositiveIntegerField(default=1)),
                ("rent_per_day", models.DecimalField(decimal_places=2, max_digits=10)),
                ("additional_rent", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("additional_deposit", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                ("extension_total", models.DecimalField(decimal_places=2, default=0, max_digits=10)),
                (
                    "rental_request",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE,
                        related_name="extension_history",
                        to="app.history",
                    ),
                ),
            ],
            options={
                "ordering": ["extension_no", "id"],
                "unique_together": {("rental_request", "extension_no")},
            },
        ),
    ]
