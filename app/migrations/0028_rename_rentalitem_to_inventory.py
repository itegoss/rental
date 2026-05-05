from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0027_cart_cartitem"),
    ]

    # This migration was duplicated; the rename is handled by a later migration (0041).
    # Keep as a no-op to avoid duplicate state changes when both rename migrations exist.
    operations = []
