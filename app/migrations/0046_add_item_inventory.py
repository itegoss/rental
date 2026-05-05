from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0045_alter_inventory_title"),
    ]

    operations = [
        migrations.AddField(
            model_name='item',
            name='inventory',
            field=models.ForeignKey(blank=True, null=True, on_delete=models.deletion.CASCADE, to='app.inventory'),
        ),
    ]
