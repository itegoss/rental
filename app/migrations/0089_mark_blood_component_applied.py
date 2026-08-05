from django.db import migrations


class Migration(migrations.Migration):
    """
    Dummy migration that records the manual addition of the `blood_component`
    column. No schema changes are performed because the column already exists.
    """
    dependencies = [
        ("app", "0088_bloodrequest_blood_component"),
    ]

    operations = []
