import pytest

from submissions.validation.checks.addresses import pin_format_problem, pin_state_problem
from submissions.validation.checks.emails import email_problem
from submissions.validation.checks.identifiers import id_number_problem, verhoeff_valid
from submissions.validation.checks.names import check_name
from submissions.validation.checks.phones import number_problem, valid_numbers


# ---------------------------------------------------------------- names (§6.1, Appendix A)
@pytest.mark.parametrize("name,digits,bad,descriptor_first,valid_token,words", [
    ("Haren Patel", False, "", False, True, 2),
    ("Anil 2nd Verma", True, "", False, True, 3),
    ("Ramesh Kumar S/O Suresh Kumar", False, "", False, True, 4),
    ("Ramesh S\\O Suresh", False, "", False, True, 2),
    ("S/O Suresh", False, "", True, True, 1),
    ("Mr. Rakesh", False, "", False, True, 1),            # leading salutation ignored
    ("Rakesh Mr.", False, "", False, True, 2),            # trailing salutation is part of the name
    ("Amit & Sons", False, "&", False, True, 3),
    ("C/O Amit", False, "/", False, True, 2),
    ("A. B.", False, "", False, False, 2),                # initials only
    ("O'Brien", False, "", False, True, 1),
])
def test_check_name(name, digits, bad, descriptor_first, valid_token, words):
    c = check_name(name)
    assert (c.has_digits, c.disallowed_chars, c.starts_with_descriptor, c.has_valid_token, c.word_count) == \
        (digits, bad, descriptor_first, valid_token, words)


# ---------------------------------------------------------------- identifiers (§7.1)
def test_verhoeff():
    assert verhoeff_valid("234123412346")           # known-valid sample
    assert not verhoeff_valid("234123412345")


@pytest.mark.parametrize("id_type,number,ok", [
    ("PAN", "ABCPD1234E", True), ("PAN", "abcpd 1234 e", True), ("PAN", "ABCCD1234E", False), ("PAN", "ABCPD123E", False),
    ("PASSPORT", "A-9388067", True), ("PASSPORT", "AB12345", True), ("PASSPORT", "1A234567", False), ("PASSPORT", "A12345", False),
    ("VOTER_ID", "MT/08/039/0060725", True), ("VOTER_ID", "ABC1234567", True), ("VOTER_ID", "AB12", False),
    ("AADHAAR", "2341 2341 2346", True), ("AADHAAR", "2341 2341 2345", False), ("AADHAAR", "23412341234", False),
    ("CKYC", "12345678901234", True), ("CKYC", "1234567890123456", False),
    ("G_RAM_G", "MH-12-123-123-123/123Patil", True), ("G_RAM_G", "MH-12-123-123-123/Patil", False),
    ("DRIVING_LICENCE", "anything goes", True), ("RATION_CARD", "x", True),
])
def test_id_number_problem(id_type, number, ok):
    assert (id_number_problem(id_type, number) is None) == ok


# ---------------------------------------------------------------- phones (§8.1)
@pytest.mark.parametrize("raw,phone_type,ok", [
    ("9876501234", "MOBILE", True), ("+91 98765 01234", "MOBILE", True), ("09876501234", "MOBILE", True),
    ("9876543210", "MOBILE", False),      # descending sequence
    ("1111111", "HOME", False),         # repeated digit
    ("1800123456", "OFFICE", False),      # starts with 1
    ("4876501234", "MOBILE", False),      # Indian mobile must start 5-9
    ("022-26541234", "OFFICE", True),
    ("1234", "HOME", False),            # fewer than 5 digits
    ("+44 20 7946 0958", "MOBILE", True), # ISD number
])
def test_number_problem(raw, phone_type, ok):
    assert (number_problem(raw, phone_type) is None) == ok


def test_multiple_numbers_only_for_unclassified():
    assert valid_numbers("5436734,645231,012 3", "NOT_CLASSIFIED") == ["5436734", "645231"]   # truncated last number dropped
    assert valid_numbers("876543/9123456780", "NOT_CLASSIFIED") == ["9123456780"]
    assert valid_numbers("", "MOBILE") == []


# ---------------------------------------------------------------- e-mail (Appendix E)
@pytest.mark.parametrize("email,ok", [
    ("abc@gmail.com", True), ("kumar@yahoo.co.in", True), ("A.B-c_d@Mail.COM", True),
    ("ramesh@@gmail", False), ("ab cd@yahoo.com", False), ("a@gmail.com", False), ("abc@g.com", False),
    ("abc@gmail.c", False), ("abc@gmail.", False), ("abc@gmail..com", False), ("abc@gmail", False),
    ("abc@gmail.c0m", False), ("ab#c@gmail.com", False),
])
def test_email_problem(email, ok):
    assert (email_problem(email) is None) == ok


def test_email_double_dot_configurable():
    assert email_problem("abc@gmail..com", strict_dots=False) is None
    assert email_problem("abc@gmail...com", strict_dots=False) is not None


# ---------------------------------------------------------------- PIN (§10.2, Appendix C)
@pytest.mark.parametrize("pin,state,format_ok,state_ok", [
    ("604002", "TAMIL_NADU", True, True), ("604-002", "TAMIL_NADU", True, True), ("900 000", "APO", False, True),
    ("400001", "MAHARASHTRA", True, True), ("560001", "MAHARASHTRA", True, False), ("604", "TAMIL_NADU", False, True),
    ("6040020000", "TAMIL_NADU", False, True), ("M5S2G4", "FOREIGN", True, True), ("956789", "APO", True, True),
])
def test_pin_rules(pin, state, format_ok, state_ok):
    assert (pin_format_problem(pin, state) is None) == format_ok
    assert (pin_state_problem(pin, state) is None) == state_ok
