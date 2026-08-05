from django.db import migrations, models
import django.core.exceptions

class Migration(migrations.Migration):
    initial = True

    dependencies = [
        ('app', '0087_add_notification_recipient'),
    ]

    operations = [
        migrations.CreateModel(
            name='SupportService',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('name', models.CharField(max_length=255, unique=True)),
                ('description', models.TextField()),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
            ],
            options={
                'ordering': ['name'],
            },
        ),
        migrations.CreateModel(
            name='SupportServiceContact',
            fields=[
                ('id', models.AutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('contact_name', models.CharField(max_length=255)),
                ('contact_number', models.CharField(max_length=30)),
                ('display_order', models.PositiveSmallIntegerField(default=0)),
                ('service', models.ForeignKey(on_delete=models.deletion.CASCADE, related_name='contacts', to='app.SupportService')),
            ],
            options={
                'ordering': ['display_order'],
                'unique_together': {('service', 'contact_name', 'contact_number')},
            },
        ),
    ]
