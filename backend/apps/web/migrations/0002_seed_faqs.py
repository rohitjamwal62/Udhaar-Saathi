from django.db import migrations

# Starter FAQ, written from the UdhaarSaathi master blueprint. Edit or add questions later in Django admin.
FAQS = [
    ("What is UdhaarSaathi?",
     "UdhaarSaathi is a digital khata for small shops in India. A shopkeeper records goods sold on credit and payments received, "
     "sees what each customer owes, and can ask the customer to confirm an entry. Customers can see their own entries and raise a dispute."),
    ("What does it cost?",
     "Registration is free. Every new shop gets one 3-month free trial. After that the plan is ₹49 per month. The price, any applicable taxes "
     "and the payment-gateway terms are shown before you pay. Nothing is added silently."),
    ("Does it work without internet?",
     "Yes, for the core work. On Android you can add customers, record credit and record payments offline. They are saved on the phone and "
     "sent to the server when the connection returns, exactly once. Sending OTP, reminders and customer confirmation links needs internet."),
    ("Is a customer confirmation legal proof of a debt?",
     "No. UdhaarSaathi gives you an acknowledgement and an evidence trail: the exact entry the customer saw, the time, and how they confirmed it. "
     "It is not guaranteed legal proof, and an OTP or a drawn signature alone may not settle a dispute in court. Ask a lawyer about your case."),
    ("Can a shopkeeper mark an entry as confirmed by the customer?",
     "No. Entries the shopkeeper records are shown as shopkeeper-recorded. An entry becomes customer-confirmed only after the customer "
     "themselves confirms it. A sent message, an OTP or an uploaded bill is never treated as confirmation."),
    ("Can entries be edited or deleted?",
     "Posted money entries are never silently changed or removed. A mistake is fixed with a reversal or an adjustment that keeps the original "
     "visible, with a reason and a time. This keeps the record trustworthy for both sides."),
    ("What happens if I stop paying?",
     "Paid features become read-only after a 7-day grace period. Your records, history and exports stay available. Nothing is deleted because a payment failed."),
    ("Is UdhaarSaathi a bank or a lender?",
     "No. It is a record-keeping tool. It does not lend money, collect debts or move your money between accounts."),
    ("Which languages are supported?",
     "The app stores your preferred language and is built for English, Hindi and Punjabi. The first release is in English; Hindi and Punjabi screens are being added."),
]


def add_faqs(apps, schema_editor):
    FAQ = apps.get_model("web", "FAQ")
    if FAQ.objects.exists():
        return
    for i, (q, a) in enumerate(FAQS, start=1):
        FAQ.objects.create(question=q, answer=a, order=i * 10, published=True)


def remove_faqs(apps, schema_editor):
    apps.get_model("web", "FAQ").objects.filter(question__in=[q for q, _ in FAQS]).delete()


class Migration(migrations.Migration):
    dependencies = [("web", "0001_initial")]
    operations = [migrations.RunPython(add_faqs, remove_faqs)]
