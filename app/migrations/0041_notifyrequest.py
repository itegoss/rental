# Stale duplicate branch kept as a no-op bridge.

from django.db import migrations

class Migration(migrations.Migration):

    dependencies = [
        ('app', '0070_alter_item_item_name'),
    ]

    operations = []
