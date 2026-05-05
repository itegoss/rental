from app.models import History

def rental_receipt_visibility(request):
    rental_id = None

    if request.user.is_authenticated:
        last_rental = History.objects.filter(
            user=request.user,
            status="approved"
        ).order_by('-id').first()

        if last_rental:
            return {
                "show_receipt": True,
                "receipt_rental_id": last_rental.id
            }

    return {
        "show_receipt": False,
        "receipt_rental_id": None
    }
