"""FAQ entries that answer what people ask about the brand name (and the spellings they type), in English and Hindi."""
from django.db import migrations

FAQS = [
    (1, "What is LenDen Saathi?",
     "LenDen Saathi (also written Lenden Saathi or Len Den Saathi) is a digital khata and sales tracking app for small shops in India. "
     "You record udhaar and payments on your phone, it works offline, and your customer can see and confirm the same entry.",
     "LenDen Saathi क्या है?",
     "LenDen Saathi (लेनदेन साथी) भारत की छोटी दुकानों के लिए डिजिटल खाता और बिक्री ट्रैकिंग ऐप है। आप फ़ोन पर उधार और भुगतान दर्ज करते हैं, "
     "यह बिना इंटरनेट के भी चलता है, और आपका ग्राहक वही एंट्री देख और पुष्टि कर सकता है।"),
    (2, "Is it LenDen Saathi, Lenden Saathi or Len Den Saathi?",
     "They all mean the same app. The official spelling is LenDen Saathi, and people also type Lenden Saathi, Len Den Saathi or LenDenSaathi. "
     "In Hindi it is लेनदेन साथी.",
     "यह LenDen Saathi है, Lenden Saathi या Len Den Saathi?",
     "ये सब एक ही ऐप के नाम हैं। सही वर्तनी LenDen Saathi है, और लोग Lenden Saathi, Len Den Saathi या LenDenSaathi भी लिखते हैं। हिंदी में यह लेनदेन साथी है।"),
    (3, "What does LenDen mean?",
     "LenDen (लेन-देन) is Hindi for give and take, the money that goes out and comes back in business. Saathi (साथी) means companion, "
     "so LenDen Saathi is your companion for every give-and-take in the shop.",
     "LenDen का क्या मतलब है?",
     "LenDen (लेन-देन) का मतलब है लेना और देना, यानी कारोबार में जो पैसा जाता है और वापस आता है। साथी का मतलब है साथ देने वाला, "
     "इसलिए LenDen Saathi दुकान के हर लेन-देन में आपका साथी है।"),
    (4, "Is LenDen Saathi a loan or lending app?",
     "No. LenDen Saathi is a record-keeping tool for your own udhaar. It does not lend money, collect debts or act as a bank, "
     "and it does not connect you with lenders.",
     "क्या LenDen Saathi कर्ज़ या लोन देने वाला ऐप है?",
     "नहीं। LenDen Saathi आपके अपने उधार का हिसाब रखने का औज़ार है। यह पैसे उधार नहीं देता, कर्ज़ वसूल नहीं करता, बैंक की तरह काम नहीं करता "
     "और आपको किसी कर्ज़ देने वाले से नहीं जोड़ता।"),
]


def add(apps, schema_editor):
    FAQ = apps.get_model("web", "FAQ")
    for order, q, a, q_hi, a_hi in FAQS:
        FAQ.objects.update_or_create(question=q, defaults={"answer": a, "order": order, "published": True,
                                                           "question_hi": q_hi, "answer_hi": a_hi})


def remove(apps, schema_editor):
    apps.get_model("web", "FAQ").objects.filter(question__in=[f[1] for f in FAQS]).delete()


class Migration(migrations.Migration):
    dependencies = [("web", "0011_google_token")]
    operations = [migrations.RunPython(add, remove)]
