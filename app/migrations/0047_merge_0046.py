from django.db import migrations


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0046_add_item_inventory"),
        ("app", "0046_item_inventory"),
    ]

    operations = [
        migrations.RunPython(code=migrations.RunPython.noop, reverse_code=migrations.RunPython.noop),
    ]
