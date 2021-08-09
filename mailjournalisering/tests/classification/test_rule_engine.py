import pytest
from classification.rule_engine import RuleEngine


class DummySender:
    def __init__(self, email_address):
        self.email_address = email_address


class DummyItem:
    def __init__(self, subject, body="", attachment_texts="", sender=""):
        self.subject = subject
        self.body = body
        self.attachment_texts = attachment_texts
        self.sender = DummySender(sender)

    def extract_text(self):
        return f"{self.subject} {self.body} {self.attachment_texts}"


@pytest.mark.parametrize("rule_type,token,item_params,should_apply,is_token", [
    ("SubjectContainsRule", "abe", ("Må jeg købe en abe?", "Jeg har ikke nogen"), True, True),
    ("SubjectContainsRule", "abe", ("Må jeg købe en ABE?", "Jeg har ikke nogen"), True, True),
    ("SubjectContainsRule", "abe", ("Må jeg købe en kat?", "Jeg har en abe"), False, True),

    ("BodyContainsRule", "kat", ("Må jeg købe en abe?", "Jeg har ikke nogen kat."), True, True),
    ("BodyContainsRule", "kat", ("Må jeg købe en ABE?", "Jeg har ikke nogen KAT."), True, True),
    ("BodyContainsRule", "kat", ("Må jeg købe en kat?", "Jeg har en abe"), False, True),

    ("AnyTextContainsRule", "kat", ("Må jeg købe en abe?", "Jeg har ikke nogen kat."), True, True),
    ("AnyTextContainsRule", "kat", ("Må jeg købe en ABE?", "Jeg har ikke nogen.", ["Jeg vil have en KAT"]), True, True),
    ("AnyTextContainsRule", "kat", ("Må jeg købe en kat?", "Jeg har en abe"), True, True),
    ("AnyTextContainsRule", "kat", ("Må jeg købe en hund?", "Jeg har en ko", ["og en hest"]), False, True),

    ("SenderContainsRule", "kat", ("Må jeg købe en kat?", "Jeg har en abe", [""], "kat@gmail.com"), True, True),
    ("SenderContainsRule", "kat", ("Må jeg købe en kat?", "Jeg har en abe", [""], "mail@KAT.com"), True, True),
    ("SenderContainsRule", "kat", ("Må jeg købe en kat?", "Jeg har en Kat", ["kat"], "mail@hund.com"), False, True),

    ("SenderEqualsRule", "kat@gmail.com", ("Må jeg købe en kat?", "Jeg har en abe", [""], "kat@gmail.com"), True, True),
    ("SenderEqualsRule", "KAT@gmail.com", ("Må jeg købe en kat?", "Jeg har en abe", [""], "kat@gmail.com"), True, True),
    ("SenderEqualsRule", "hund@gmail.com", ("Må jeg købe en kat?", "Jeg har en Kat", ["kat"], "kat@gmail.com"), False, True),

    ("SubjectRegEx", r"\d{5}", ("Må jeg købe 12345 katte?", "Jeg har en abe", [""], "kat@gmail.com"), True, False),
    ("SubjectRegEx", r"\d{5}", ("Må jeg købe en kat?", "Jeg har 12345 aber", [""], "kat@gmail.com"), False, False),
    ("SubjectRegEx", r"\d{5}", ("12345", "Jeg har en abe", [""], "kat@gmail.com"), True, False),
    ("SubjectRegEx", r"kat@gmail.com", ("Må jeg købe en kat af KAT@gmail.com", "Jeg har en abe", [""], "kat@gmail.com"), True, False),
    ("SubjectRegEx", r"\d{5}", ("Må jeg købe en kat?", "Jeg har en Kat", ["kat"], "kat@gmail.com"), False, False),

    ("AttachmenttextRegEx", r"\d{5}", ("Må jeg købe en kat?", "Jeg har en abe", ["Jeg har 12345 hunde"], "kat@gmail.com"), True, False),
    ("AttachmenttextRegEx", r"\d{5}", ("Må jeg købe 12345 katte?", "Jeg har 12345 aber", ["Jeg har en hund"], "kat@gmail.com"), False, False),
    ("AttachmenttextRegEx", r"kat@gmail.com", ("Må jeg købe en kat af 12345", "Jeg har en abe", ["Send en mail til kat@gmail.com"], "kat@gmail.com"), True, False),
    ("AttachmenttextRegEx", r"kat@gmail.com", ("Må jeg købe en kat?", "Jeg har en Kat", ["kat"], "kat@gmail.com"), False, False),

    ("AnyTextRegEx", r"\d{5}", ("Må jeg købe 12345 katte?", "Jeg har en Kat", ["kat"], "kat@gmail.com"), True, False),
    ("AnyTextRegEx", r"\d{5}", ("Må jeg købe en kat?", "Jeg har 12345 katte", ["kat"], "kat@gmail.com"), True, False),
    ("AnyTextRegEx", r"\d{5}", ("Må jeg købe en katte?", "Jeg har en Kat", ["12345 katte"], "kat@gmail.com"), True, False),
    ("AnyTextRegEx", r"\d{5}", ("Må jeg købe en katte?", "Jeg har en Kat", ["1234 hunde", "12345 katte"], "kat@gmail.com"), True, False),
    ("AnyTextRegEx", r"\d{5}", ("Må jeg købe en katte?", "Jeg har en Kat", ["1234 hunde"], "kat@gmail.com"), False, False),
])
def test_simple_rule(rule_type, token, item_params, should_apply, is_token):
    rule_name, return_address, rule_engine = "MyRule", "abe@adresse.dk", RuleEngine()
    if is_token:
        rule_engine.add_rule(rule_type, token=token, return_value=return_address, name=rule_name)
    else:
        rule_engine.add_rule(rule_type, pattern=token, return_value=return_address, name=rule_name)
    assert len(rule_engine.rules) == 1
    item = DummyItem(*item_params)
    applies, return_value, r = rule_engine.execute(item)
    assert applies == should_apply
    if should_apply:
        assert return_value == return_address
        assert r.name == rule_name


@pytest.mark.parametrize("rule_type,condition1,condition2,item_params,should_apply", [
    ("AndRule", {"condition_type": "SubjectContains", "token": "hund"},
               {"condition_type": "SenderEquals", "token": "hund@gmail.com"},
     ("Må jeg købe en hund?", "Jeg har en Kat", ["kat"], "hund@gmail.com"),
     True),
    ("AndRule", {"condition_type": "SubjectContains", "token": "hund"},
     {"condition_type": "SenderEquals", "token": "hund@gmail.com"},
     ("Må jeg købe en hund?", "Jeg har en Kat", ["kat"], "kat@gmail.com"),
     False),
    ("AndRule", {"condition_type": "SubjectContains", "token": "hund"},
     {"condition_type": "SenderEquals", "token": "hund@gmail.com"},
     ("Må jeg købe en kat?", "Jeg har en Kat", ["kat"], "hund@gmail.com"),
     False),
    ("OrRule", {"condition_type": "SubjectContains", "token": "hund"},
     {"condition_type": "SenderEquals", "token": "hund@gmail.com"},
     ("Må jeg købe en hund?", "Jeg har en Kat", ["kat"], "hund@gmail.com"),
     True),
    ("OrRule", {"condition_type": "SubjectContains", "token": "hund"},
     {"condition_type": "SenderEquals", "token": "hund@gmail.com"},
     ("Må jeg købe en hund?", "Jeg har en Kat", ["kat"], "kat@gmail.com"),
     True),
    ("OrRule", {"condition_type": "SubjectContains", "token": "hund"},
     {"condition_type": "SenderEquals", "token": "hund@gmail.com"},
     ("Må jeg købe en kat?", "Jeg har en Kat", ["kat"], "hund@gmail.com"),
     True),
    ("OrRule", {"condition_type": "SubjectContains", "token": "hund"},
     {"condition_type": "SenderEquals", "token": "hund@gmail.com"},
     ("Må jeg købe en kat?", "Jeg har en Kat", ["kat"], "kat@gmail.com"),
     False),
    ])
def test_multi_condition_rule(rule_type, condition1, condition2, item_params, should_apply):
    rule_name, return_address, rule_engine = "MyRule", "abe@adresse.dk", RuleEngine()
    rule_engine.add_rule(rule_type, condition1=condition1, condition2=condition2,
                         return_value=return_address, name=rule_name)
    assert len(rule_engine.rules) == 1
    item = DummyItem(*item_params)
    applies, return_value, r = rule_engine.execute(item)
    assert applies == should_apply
    if should_apply:
        assert return_value == return_address
        assert r.name == rule_name
