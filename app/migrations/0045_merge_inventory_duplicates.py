from django.db import migrations


def merge_duplicates(apps, schema_editor):
    Inventory = apps.get_model('app', 'Inventory')
    RentalRequest = apps.get_model('app', 'RentalRequest')
    CartItem = apps.get_model('app', 'CartItem')

    # Build mapping of lowercase title -> list of Inventory instances
    duplicates = {}
    for inv in Inventory.objects.all():
        key = (inv.title or '').strip().lower()
        if not key:
            continue
        duplicates.setdefault(key, []).append(inv)

    for key, items in duplicates.items():
        if len(items) <= 1:
            continue

        # choose canonical by lowest id
        items.sort(key=lambda x: x.id)
        canonical = items[0]
        others = items[1:]

        # aggregate quantities
        total_qty = canonical.total_quantity or 0
        available_qty = canonical.available_quantity or 0
        for other in others:
            total_qty += (other.total_quantity or 0)
            available_qty += (other.available_quantity or 0)

        canonical.total_quantity = total_qty
        canonical.available_quantity = available_qty
        canonical.save()

        # re-point FKs from others to canonical
        RentalRequest.objects.filter(rental_item__in=[o.id for o in others]).update(rental_item=canonical)
        CartItem.objects.filter(rental_item__in=[o.id for o in others]).update(rental_item=canonical)

        # delete duplicates
        for other in others:
            other.delete()


class Migration(migrations.Migration):

    dependencies = [
        ("app", "0044_alter_item_id"),
    ]

    operations = [
        migrations.RunPython(merge_duplicates, reverse_code=migrations.RunPython.noop),
    ]
