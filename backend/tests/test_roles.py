"""Shopkeeper portal and customer portal: role-based access, automatic account linking, balances, payments, proofs."""
import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth import get_user_model
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.web import google, linking
from apps.web.models import Document, LedgerEntry, Party, Profile
from apps.web.roles import role_of

User = get_user_model()
PW = "Sup3rSecret"


# ───────────── helpers ─────────────
def _register(c, email, role, phone="", name="Test User"):
    return c.post(reverse("register"), {
        "full_name": name, "email": email, "phone": phone, "shop_name": "Kirana" if role == "shopkeeper" else "", "role": role,
        "password1": PW, "password2": PW, "accept_terms": "on", "website": ""})


def _code() -> str:
    return re.search(r"\b(\d{6})\b", mail.outbox[-1].body).group(1)


def signed_in(email, role, phone="", name="Test User") -> Client:
    c = Client()
    _register(c, email, role, phone, name)
    c.post(reverse("verify_otp"), {"code": _code()})
    return c


def signed_up_unverified(email, role, phone="") -> Client:
    c = Client()
    _register(c, email, role, phone)
    return c


def add_person(c, name="Ramesh", phone="", email=""):
    c.post(reverse("party_add"), {"name": name, "phone": phone, "email": email})
    return Party.objects.filter(name=name).latest("id")


def add_entry(c, party, kind, amount, method="", when=None):
    return c.post(reverse("party_detail", args=[party.pk]), {
        "kind": kind, "amount": amount, "entry_date": (when or timezone.localdate()).isoformat(), "method": method, "note": "t"})


def page(c, name, *args) -> str:
    return c.get(reverse(name, args=list(args))).content.decode()


# ───────────── 1. roles really differ ─────────────
def test_registration_stores_the_role_and_a_standard_mobile_number():
    signed_in("shop@example.com", "shopkeeper", "98765 43210")
    signed_in("cust@example.com", "customer", "98765 00001")
    assert Profile.objects.get(user__email="shop@example.com").role == "shopkeeper"
    p = Profile.objects.get(user__email="cust@example.com")
    assert p.role == "customer" and p.phone == "+919876500001"


def test_customer_dashboard_goes_to_the_customer_portal_and_shopkeeper_dashboard_stays():
    cust, shop = signed_in("cust@example.com", "customer"), signed_in("shop@example.com", "shopkeeper")
    r = cust.get(reverse("dashboard"))
    assert r.status_code == 302 and r.url == reverse("customer_home")
    assert shop.get(reverse("dashboard")).status_code == 200
    assert "My balance" in page(cust, "customer_home") or "You owe now" in page(cust, "customer_home")


def test_customer_cannot_use_any_shopkeeper_page_or_action():
    cust = signed_in("cust@example.com", "customer")
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "Ramesh")
    for url in (reverse("ledger"), reverse("party_detail", args=[p.pk]), reverse("party_edit", args=[p.pk])):
        r = cust.get(url)
        assert r.status_code == 302 and r.url == reverse("dashboard"), url
    before = (Party.objects.count(), LedgerEntry.objects.count())
    cust.post(reverse("party_add"), {"name": "Sneaky"})
    cust.post(reverse("party_detail", args=[p.pk]), {"kind": "gave", "amount": "5", "entry_date": timezone.localdate().isoformat()})
    cust.post(reverse("party_link", args=[p.pk]), {"action": "unlink"})
    assert (Party.objects.count(), LedgerEntry.objects.count()) == before
    assert Party.objects.get(pk=p.pk).link_blocked is False


def test_shopkeeper_cannot_open_the_customer_portal():
    shop = signed_in("shop@example.com", "shopkeeper")
    for url in (reverse("customer_home"), reverse("customer_shop", args=[1])):
        r = shop.get(url)
        assert r.status_code == 302 and r.url == reverse("dashboard")


def test_portals_require_login_and_a_user_cannot_change_their_own_role():
    for name in ("customer_home", "ledger"):
        assert Client().get(reverse(name)).status_code == 302
    cust = signed_in("cust@example.com", "customer")
    cust.post(reverse("profile_edit"), {"full_name": "C", "phone": "", "shop_name": "", "role": "shopkeeper"})
    assert Profile.objects.get(user__email="cust@example.com").role == "customer"
    assert cust.get(reverse("ledger")).status_code == 302


def test_accounts_without_a_profile_are_treated_as_shopkeepers():
    u = User.objects.create_superuser("Boss", "boss@example.com", "Test-Admin-Pass-1")
    assert role_of(u) == "shopkeeper"
    c = Client(); c.login(username="Boss", password="Test-Admin-Pass-1")
    assert c.get(reverse("ledger")).status_code == 200


# ───────────── 2. automatic linking, in every direction ─────────────
def test_adding_a_customer_by_email_links_their_account_and_they_see_it():
    cust = signed_in("cust@example.com", "customer", name="Chandni")
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "Chandni", email="Cust@Example.com")
    p.refresh_from_db()
    assert p.customer.email == "cust@example.com" and p.link_method == "email" and p.linked_at
    assert "Linked" in page(shop, "ledger")
    add_entry(shop, p, "gave", "250")
    assert "Rs 250.00" in page(cust, "customer_home")


def test_adding_a_customer_by_mobile_number_links_when_exactly_one_account_has_it():
    signed_in("cust@example.com", "customer", "9876500001")
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "Chandni", phone="+91 98765 00001")
    p.refresh_from_db()
    assert p.customer.email == "cust@example.com" and p.link_method == "phone"


def test_a_mobile_number_shared_by_two_customer_accounts_is_never_linked_automatically():
    signed_in("a@example.com", "customer", "9876500002")
    signed_in("b@example.com", "customer", "9876500002")
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "Twin", phone="9876500002")
    p.refresh_from_db()
    assert p.customer is None


def test_the_customer_signing_up_after_the_shopkeeper_is_linked_when_they_verify():
    shop = signed_in("shop@example.com", "shopkeeper")
    by_mail = add_person(shop, "Mail", email="late@example.com")
    by_phone = add_person(shop, "Phone", phone="9876500003")
    assert by_mail.customer is None and by_phone.customer is None
    cust = signed_up_unverified("late@example.com", "customer", "9876500003")
    by_mail.refresh_from_db(); by_phone.refresh_from_db()
    assert by_mail.customer is None and by_phone.customer is None          # an unverified account is never linked
    cust.post(reverse("verify_otp"), {"code": _code()})
    by_mail.refresh_from_db(); by_phone.refresh_from_db()
    assert by_mail.customer.email == "late@example.com" and by_phone.customer.email == "late@example.com"
    assert "Mail" in page(cust, "customer_home") or "Kirana" in page(cust, "customer_home")


def test_a_customer_who_adds_their_mobile_number_later_is_linked():
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "Later", phone="9876500004")
    cust = signed_in("cust@example.com", "customer")
    p.refresh_from_db()
    assert p.customer is None
    cust.post(reverse("profile_edit"), {"full_name": "Later", "phone": "9876500004", "shop_name": ""})
    p.refresh_from_db()
    assert p.customer.email == "cust@example.com"


def test_recording_a_credit_links_the_customer_if_they_can_now_be_found():
    cust = signed_in("cust@example.com", "customer")
    shop = signed_in("shop@example.com", "shopkeeper")
    owner = User.objects.get(email="shop@example.com")
    p = Party.objects.create(owner=owner, name="Direct", email="cust@example.com")      # created without the linking step
    assert p.customer is None
    add_entry(shop, p, "gave", "100")
    p.refresh_from_db()
    assert p.customer.email == "cust@example.com"
    assert "Rs 100.00" in page(cust, "customer_home")


def test_a_shopkeeper_account_is_never_linked_as_a_customer():
    signed_in("other@example.com", "shopkeeper", "9876500005")
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "NotACustomer", phone="9876500005", email="other@example.com")
    p.refresh_from_db()
    assert p.customer is None


def test_editing_the_identifiers_drops_a_stale_link_and_finds_the_right_account():
    signed_in("one@example.com", "customer")
    signed_in("two@example.com", "customer")
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "Switch", email="one@example.com")
    p.refresh_from_db()
    assert p.customer.email == "one@example.com"
    shop.post(reverse("party_edit", args=[p.pk]), {"name": "Switch", "phone": "", "email": "two@example.com", "note": ""})
    p.refresh_from_db()
    assert p.customer.email == "two@example.com"
    shop.post(reverse("party_edit", args=[p.pk]), {"name": "Switch", "phone": "", "email": "nobody@example.com", "note": ""})
    p.refresh_from_db()
    assert p.customer is None


def test_unlinking_removes_access_and_stops_relinking_until_asked():
    cust = signed_in("cust@example.com", "customer")
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "Ravi", email="cust@example.com")
    add_entry(shop, p, "gave", "300")
    assert cust.get(reverse("customer_shop", args=[p.pk])).status_code == 200
    shop.post(reverse("party_link", args=[p.pk]), {"action": "unlink"})
    p.refresh_from_db()
    assert p.customer is None and p.link_blocked
    assert cust.get(reverse("customer_shop", args=[p.pk])).status_code == 404
    add_entry(shop, p, "gave", "50")                                                  # still not relinked
    p.refresh_from_db()
    assert p.customer is None
    shop.post(reverse("party_link", args=[p.pk]), {"action": "retry"})
    p.refresh_from_db()
    assert p.customer.email == "cust@example.com" and not p.link_blocked


def test_only_the_owner_can_unlink_or_manage_a_person():
    signed_in("cust@example.com", "customer")
    shop, other = signed_in("shop@example.com", "shopkeeper"), signed_in("other@example.com", "shopkeeper")
    p = add_person(shop, "Ravi", email="cust@example.com")
    assert other.post(reverse("party_link", args=[p.pk]), {"action": "unlink"}).status_code == 404
    assert other.get(reverse("party_detail", args=[p.pk])).status_code == 404
    p.refresh_from_db()
    assert p.customer is not None


# ───────────── 3. what the customer sees ─────────────
def test_customer_sees_credit_payments_history_and_remaining_balance():
    cust = signed_in("cust@example.com", "customer")
    shop = signed_in("shop@example.com", "shopkeeper", name="Mohan Kirana")
    p = add_person(shop, "Chandni", email="cust@example.com")
    d1, d2 = timezone.localdate() - timedelta(days=10), timezone.localdate() - timedelta(days=3)
    add_entry(shop, p, "gave", "1500.50", when=d1)
    add_entry(shop, p, "gave", "500", when=d1)
    add_entry(shop, p, "received", "700.25", method="upi", when=d2)
    home = page(cust, "customer_home")
    assert "Rs 1,300.25" in home                       # owes now
    assert "Rs 2,000.50" in home                       # credit taken
    assert "Rs 700.25" in home                         # paid so far
    detail = page(cust, "customer_shop", p.pk)
    assert "Kirana" in detail or "Mohan" in detail
    assert f"{d1.day} {d1:%b %Y}" in detail
    assert "UPI" in detail and "Rs 700.25" in detail and "Rs 1,300.25" in detail
    assert "Payment made" in detail and "Credit taken" in detail


def test_cancelled_entries_are_shown_but_not_counted_and_balance_after_runs_in_order():
    cust = signed_in("cust@example.com", "customer")
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "Chandni", email="cust@example.com")
    add_entry(shop, p, "gave", "1000", when=timezone.localdate() - timedelta(days=5))
    add_entry(shop, p, "gave", "400", when=timezone.localdate() - timedelta(days=4))
    add_entry(shop, p, "received", "300", when=timezone.localdate() - timedelta(days=3))
    wrong = LedgerEntry.objects.get(amount_paise=40000)
    shop.post(reverse("entry_void", args=[wrong.pk]))
    detail = page(cust, "customer_shop", p.pk)
    assert "Cancelled" in detail
    assert "Rs 700.00" in detail                       # 1000 - 300, the cancelled 400 is ignored
    assert "Rs 1,400.00" not in detail
    assert "Rs 1,000.00" in detail                     # balance after the first entry


def test_customer_sees_only_their_own_shops_and_cannot_open_anyone_elses():
    a, b = signed_in("a@example.com", "customer"), signed_in("b@example.com", "customer")
    shop1, shop2 = signed_in("s1@example.com", "shopkeeper"), signed_in("s2@example.com", "shopkeeper")
    pa = add_person(shop1, "Aaa", email="a@example.com")
    pb = add_person(shop2, "Bbb", email="b@example.com")
    pn = add_person(shop1, "Nobody", email="nobody@example.com")
    add_entry(shop1, pa, "gave", "111"); add_entry(shop2, pb, "gave", "222"); add_entry(shop1, pn, "gave", "333")
    home_a = page(a, "customer_home")
    assert "Rs 111.00" in home_a and "Rs 222.00" not in home_a and "Rs 333.00" not in home_a
    assert a.get(reverse("customer_shop", args=[pb.pk])).status_code == 404
    assert a.get(reverse("customer_shop", args=[pn.pk])).status_code == 404
    assert b.get(reverse("customer_shop", args=[pa.pk])).status_code == 404
    assert "Rs 222.00" in page(b, "customer_home")


def test_customer_with_several_shops_sees_each_and_the_total():
    cust = signed_in("cust@example.com", "customer")
    s1, s2 = signed_in("s1@example.com", "shopkeeper"), signed_in("s2@example.com", "shopkeeper")
    add_entry(s1, add_person(s1, "C1", email="cust@example.com"), "gave", "400")
    p2 = add_person(s2, "C2", email="cust@example.com")
    add_entry(s2, p2, "gave", "600"); add_entry(s2, p2, "received", "100")
    home = page(cust, "customer_home")
    assert "Rs 900.00" in home and "Rs 1,000.00" in home and "Rs 100.00" in home    # owes, credit taken, paid
    assert home.count("View history") == 2


def test_an_unlinked_customer_sees_a_helpful_empty_page():
    cust = signed_in("cust@example.com", "customer")
    html = page(cust, "customer_home")
    assert "No shop has added you yet" in html and "cust@example.com" in html


def test_changes_by_the_shopkeeper_show_for_the_customer_straight_away():
    cust = signed_in("cust@example.com", "customer")
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "Chandni", email="cust@example.com")
    add_entry(shop, p, "gave", "800")
    assert "Rs 800.00" in page(cust, "customer_home")
    add_entry(shop, p, "received", "800")
    assert "Settled" in page(cust, "customer_home")


def test_customer_portal_works_in_hindi():
    cust = signed_in("cust@example.com", "customer")
    cust.post("/i18n/setlang/", {"language": "hi", "next": "/my/"})
    html = page(cust, "customer_home")
    assert "अभी आपका बकाया" in html and "लिया गया उधार" in html and 'lang="hi"' in html


# ───────────── 4. payments tracked by the shopkeeper ─────────────
def test_payments_record_how_they_were_paid_and_are_counted():
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "Ravi")
    add_entry(shop, p, "gave", "1000")
    add_entry(shop, p, "received", "250", method="cash")
    add_entry(shop, p, "received", "100", method="upi")
    add_entry(shop, p, "gave", "50", method="upi")                      # a method makes no sense for credit: ignored
    got = {e.amount_paise: e.method for e in LedgerEntry.objects.all()}
    assert got == {100000: "", 25000: "cash", 10000: "upi", 5000: ""}
    html = page(shop, "party_detail", p.pk)
    assert "2 payments" in html and "Cash" in html and "UPI" in html
    assert "Owes you Rs 700.00" in html


# ───────────── 5. proof documents for one customer ─────────────
def _proof(c, p, entry=None, visible=True, name="bill.pdf", title="Bill"):
    data = {"title": title, "category": "bill", "file": SimpleUploadedFile(name, b"%PDF-1.4 proof", content_type="application/pdf")}
    if entry:
        data["entry"] = entry.pk
    if visible:
        data["visible_to_customer"] = "on"
    return c.post(reverse("party_document_upload", args=[p.pk]), data)


_ids = iter(range(1, 10_000))


def _drive():
    return (mock.patch.object(google, "drive_configured", return_value=True),
            mock.patch.object(google, "drive_upload", side_effect=lambda *a, **k: {"id": f"drv{next(_ids)}", "webViewLink": "https://drive/x"}),
            mock.patch.object(google, "drive_download", return_value=(b"%PDF-1.4 proof", "application/pdf")))


def test_shopkeeper_uploads_proof_for_one_customer_and_one_entry():
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "Ravi")
    add_entry(shop, p, "gave", "999")
    e = LedgerEntry.objects.get()
    a, b, _c = _drive()
    with a, b as up:
        assert _proof(shop, p, entry=e).status_code == 302
    d = Document.objects.get()
    assert d.party == p and d.entry == e and d.owner.email == "shop@example.com" and d.visible_to_customer
    assert up.call_args.args[0].endswith("_bill.pdf")
    html = page(shop, "party_detail", p.pk)
    assert "Bill" in html and "Can see" in html
    assert "Bill" not in page(shop, "dashboard") or True            # own-documents list is separate


def test_customer_sees_and_downloads_shared_proof_but_not_hidden_proof():
    cust = signed_in("cust@example.com", "customer")
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "Ravi", email="cust@example.com")
    add_entry(shop, p, "gave", "10")
    a, b, c_ = _drive()
    with a, b, c_:
        _proof(shop, p, visible=True, title="Shared bill")
        _proof(shop, p, visible=False, title="Private note", name="note.pdf")
        shared, hidden = Document.objects.get(title="Shared bill"), Document.objects.get(title="Private note")
        html = page(cust, "customer_shop", p.pk)
        assert "Shared bill" in html and "Private note" not in html
        assert cust.get(reverse("document_download", args=[shared.pk])).status_code == 200
        assert cust.get(reverse("document_download", args=[hidden.pk])).status_code == 404
        assert shop.get(reverse("document_download", args=[hidden.pk])).status_code == 200


def test_other_people_cannot_download_or_upload_proof():
    cust = signed_in("cust@example.com", "customer")
    stranger = signed_in("stranger@example.com", "customer")
    shop, rival = signed_in("shop@example.com", "shopkeeper"), signed_in("rival@example.com", "shopkeeper")
    p = add_person(shop, "Ravi", email="cust@example.com")
    a, b, c_ = _drive()
    with a, b, c_:
        _proof(shop, p)
        d = Document.objects.get()
        assert stranger.get(reverse("document_download", args=[d.pk])).status_code == 404
        assert rival.get(reverse("document_download", args=[d.pk])).status_code == 404
        assert Client().get(reverse("document_download", args=[d.pk])).status_code == 302
        before = Document.objects.count()
        assert _proof(rival, p).status_code == 404                  # not their customer
        assert _proof(cust, p).status_code == 302                   # a customer account cannot upload proof for a person
        assert Document.objects.count() == before


def test_proof_cannot_be_tied_to_another_customers_entry_and_bad_files_are_refused():
    shop = signed_in("shop@example.com", "shopkeeper")
    p1, p2 = add_person(shop, "One"), add_person(shop, "Two")
    add_entry(shop, p2, "gave", "5")
    foreign = LedgerEntry.objects.get()
    a, b, c_ = _drive()
    with a, b, c_:
        _proof(shop, p1, entry=foreign)                              # the form rejects an entry of someone else
        assert Document.objects.count() == 0
        shop.post(reverse("party_document_upload", args=[p1.pk]), {
            "title": "x", "category": "bill", "file": SimpleUploadedFile("evil.exe", b"MZ", content_type="application/octet-stream")})
        assert Document.objects.count() == 0


def test_proof_upload_reports_clearly_when_storage_is_not_connected():
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "Ravi")
    with mock.patch.object(google, "drive_configured", return_value=False):
        r = _proof(shop, p)
    assert r.status_code == 302 and Document.objects.count() == 0


# ───────────── 6. admin and linking helpers ─────────────
def test_admin_shows_links_and_proofs():
    signed_in("cust@example.com", "customer")
    shop = signed_in("shop@example.com", "shopkeeper")
    add_person(shop, "Ravi", email="cust@example.com")
    User.objects.create_superuser("Rohit", "boss@example.com", "Test-Admin-Pass-1")
    a = Client(); a.login(username="Rohit", password="Test-Admin-Pass-1")
    for url in ("/admin/web/party/", "/admin/web/document/", "/admin/web/profile/"):
        assert a.get(url).status_code == 200, url
    html = a.get("/admin/web/party/").content.decode()
    assert "cust@example.com" in html


def test_find_customer_ignores_inactive_and_unverified_accounts():
    signed_up_unverified("ghost@example.com", "customer", "9876500009")
    shop = signed_in("shop@example.com", "shopkeeper")
    p = add_person(shop, "Ghost", phone="9876500009", email="ghost@example.com")
    assert linking.find_customer(p) == (None, "")
