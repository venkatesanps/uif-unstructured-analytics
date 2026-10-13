from uif.contracts import Page
from uif.providers.local import RegexGuard, looks_like_pan, luhn_ok
from uif.steps.resolve import resolve
from uif.steps.validate import check_rule, grounded, value_in_quote
from uif.values import normalize, to_date_range, to_money


def test_luhn():
    assert luhn_ok("4111111111111111")
    assert not luhn_ok("4111111111111112")


def test_pan_detection_respects_context_and_prefix():
    assert looks_like_pan("4111 1111 1111 1111")
    assert not looks_like_pan("4111 1111 1111 1111", preceding="Merchant ID (MID): ")
    assert not looks_like_pan("800012345678")          # MID-shaped, not a card prefix
    assert not looks_like_pan("4111111111111112")      # fails Luhn


def test_guard_tokenizes_and_removes_raw_values():
    g = RegexGuard("salt")
    pages = [Page(page=1, text="Card 4111-1111-1111-1111, SSN 123-45-6789, call 214-555-0187, "
                                "mail a.b@example.com, Merchant ID (MID): 4111111111111111")]
    out, findings = g.scan(pages)
    text = out[0].text
    assert "4111-1111-1111-1111" not in text and "123-45-6789" not in text
    assert "214-555-0187" not in text and "a.b@example.com" not in text
    assert text.endswith("4111111111111111")  # labelled MID survives
    assert sorted(f.kind for f in findings) == ["email", "pan", "phone", "ssn"]


def test_tokens_are_deterministic_so_documents_stay_joinable():
    g = RegexGuard("salt")
    assert g.token("pan", "4111 1111 1111 1111") == g.token("pan", "4111111111111111")
    assert RegexGuard("other").token("pan", "4111111111111111") != g.token("pan", "4111111111111111")


def test_value_normalizers():
    assert to_money("($1,234.50)") == -1234.5
    assert to_money("$12,000") == 12000.0
    assert to_date_range("Aug 1, 2026 through Aug 31, 2026") == {"start": "2026-08-01", "end": "2026-08-31"}
    assert to_date_range("08/01/2026 to 08/31/2026") == {"start": "2026-08-01", "end": "2026-08-31"}
    assert normalize("integer", "12,345") == 12345
    assert normalize("string_list", "Card Testing; volume spike") == ["card testing", "volume spike"]


def test_rules():
    v = {"chargeback_count": 5, "transaction_count": 3, "gross_volume": 10.0}
    assert check_rule({"check": "lte", "left": "chargeback_count", "right": "transaction_count"}, v) is False
    assert check_rule({"check": "gte", "left": "gross_volume", "value": 0}, v) is True
    assert check_rule({"check": "lte", "left": "refund_volume", "right": "gross_volume"}, v) is None


def test_grounding_and_value_in_quote():
    page = "Total Gross Sales: $1,234.56\nTotal Fees: $40.00"
    assert grounded("total gross sales:  $1,234.56", page)
    assert not grounded("Total Gross Sales: $9,999.99", page)
    assert value_in_quote("money", 1234.56, "Total Gross Sales: $1,234.56")
    assert not value_in_quote("money", 1234.65, "Total Gross Sales: $1,234.56")


def test_resolver_mid_first_then_fuzzy_name():
    master = [{"merchant_id": "M1", "mid": "800012345678", "legal_name": "Blue Harbor Coffee LLC",
               "dba": "Blue Harbor Coffee"}]
    assert resolve(master, "8000 1234 5678", [])[1] == "mid_exact"
    row, method, _ = resolve(master, None, ["BLUE HARBOR COFFEE, L.L.C."])
    assert row["merchant_id"] == "M1" and method == "name_fuzzy"
    assert resolve(master, None, ["Harbor Freight Tools"])[0] is None
