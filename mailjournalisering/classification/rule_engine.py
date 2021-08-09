import re

class Condition:
    def _evaluate(self, item):
        pass

    def __call__(self, item):
        """Method for evaluating rule in a safe manner"""
        try:
            return self._evaluate(item)

        except Exception as e:
            # if something fails, return False, None
            print(e)
            import traceback
            print(traceback.format_exc(), flush=True)
            return False

class Rule:
    """Base class for rules. A rule should always be returning True/False and a return value."""

    def __init__(self, return_value, name, condition):
        if type(return_value) == list:
            self.return_value = [rv.lower() for rv in return_value]
        else:
            self.return_value = return_value.lower()
        self.name = name
        self.condition = condition

    def __call__(self, item):
        """Method for evaluating rule in a safe manner"""
        try:
            if self.condition(item):
                return True, self.return_value
            else:
                return False, None

        except Exception as e:
            # if something fails, return False, None
            print(e)
            import traceback
            print(traceback.format_exc(), flush=True)
            return False, None

    def __str__(self):
        # build list of relevant attributes
        attr = []
        for a in dir(self):
            if not callable(self.__getattribute__(a)) and not a.startswith('__'):
                attr.append(f"{a}={self.__getattribute__(a)}")
        return f"{self.__class__.__name__} ({', '.join(attr)})"

class SubjectContains(Condition):
    def __init__(self, token):
        self.token = token

    def _evaluate(self, item):
        return item.subject is not None and self.token.lower() in item.subject.lower()

class BodyContains(Condition):
    def __init__(self, token):
        self.token = token

    def _evaluate(self, item):
        return self.token.lower() in item.body.lower()

class SubjectRegEx(Condition):
    def __init__(self, pattern):
        self.pattern = pattern
        self.regex = re.compile(pattern)

    # returns True if the number of matches is 1 or more
    def _evaluate(self, item):
        if item.subject is None:
            return False
        m = self.regex.findall(item.subject.lower())
        return len(m) > 0


class AttachmentTextContains(Condition):
    def __init__(self, token):
        self.token = token

    def _evaluate(self, item):
        return any([self.token.lower() in at.lower() for at in item.attachment_texts])


class AnyTextContains(Condition):
    def __init__(self, token):
        self.token = token

    def _evaluate(self, item):
        return self.token.lower() in item.extract_text().lower()


class AnyTextRegEx(Condition):
    def __init__(self, pattern):
        self.pattern = pattern
        self.regex = re.compile(pattern)

    # returns True if the number of matches is 1 or more
    def _evaluate(self, item):
        m = self.regex.findall(item.extract_text().lower())
        return len(m) > 0


class AttachmentTextRegEx(Condition):
    def __init__(self, pattern):
        self.pattern = pattern
        self.regex = re.compile(pattern)

    # returns True if the number of matches is 1 or more
    def _evaluate(self, item):
        return any([len(self.regex.findall(at.lower())) > 0 for at in item.attachment_texts])


class SenderContains(Condition):
    def __init__(self, token):
        self.token = token

    def _evaluate(self, item):
        return self.token.lower() in item.sender.email_address.lower()


class SenderEquals(Condition):
    def __init__(self, token):
        self.token = token

    def _evaluate(self, item):
        return self.token.lower() == item.sender.email_address.lower()


condition_factory = {
    "SubjectContains": SubjectContains,
    "BodyContains": BodyContains,
    "AttachmentTextContains": AttachmentTextContains,
    "SenderContains": SenderContains,
    "AnyTextContains": AnyTextContains,
    "SenderEquals": SenderEquals,
    "SubjectRegEx": SubjectRegEx,
    "AttachmentTextRegEx": AttachmentTextRegEx,
    "AnyTextRegEx": AnyTextRegEx,
}


def parse_condition(condition):
    condition_type = condition.pop("condition_type")
    return condition_factory[condition_type](**condition)


class AndCondition(Condition):
    def __init__(self, condition1: Condition, condition2: Condition):
        self.condition1 = parse_condition(condition1)
        self.condition2 = parse_condition(condition2)

    def _evaluate(self, item):
        return self.condition1(item) and self.condition2(item)

class OrCondition(Condition):
    def __init__(self, condition1: Condition, condition2: Condition):
        self.condition1 = parse_condition(condition1)
        self.condition2 = parse_condition(condition2)

    def _evaluate(self, item):
        return self.condition1(item) or self.condition2(item)


class RuleEngine:

    def __init__(self):
        # list of rules to test against
        create_simple_rule = lambda condition, return_value, name=None, **kwargs: Rule(return_value, name, condition(**kwargs))


        self.rule_factory = {
            'SubjectContainsRule': lambda **kwargs: create_simple_rule(condition=SubjectContains, **kwargs),
            'BodyContainsRule': lambda **kwargs: create_simple_rule(condition=BodyContains, **kwargs),
            'AttachmenttextContainsRule': lambda **kwargs: create_simple_rule(condition=AttachmentTextContains, **kwargs),
            'SenderContainsRule': lambda **kwargs: create_simple_rule(condition=SenderContains, **kwargs),
            'AnyTextContainsRule': lambda **kwargs: create_simple_rule(condition=AnyTextContains, **kwargs),
            'SenderEqualsRule': lambda **kwargs: create_simple_rule(condition=SenderEquals, **kwargs),
            'SubjectRegEx': lambda **kwargs: create_simple_rule(condition=SubjectRegEx, **kwargs),
            'AttachmenttextRegEx': lambda **kwargs: create_simple_rule(condition=AttachmentTextRegEx, **kwargs),
            'AnyTextRegEx': lambda **kwargs: create_simple_rule(condition=AnyTextRegEx, **kwargs),
            'AndRule': lambda **kwargs: create_simple_rule(condition=AndCondition, **kwargs),
            'OrRule': lambda **kwargs: create_simple_rule(condition=OrCondition, **kwargs),
        }

        self.rules = []

    def add_rule(self, rule_type, **kwargs):
        """Add rule to engine, e.g. add_rule('SubjectContainsRule', token='test', return_value='test@gmail.com')"""
        if rule_type in self.rule_factory:
            self.rules.append(self.rule_factory[rule_type](**kwargs))
        else:
            print(f"'{rule_type}' is not an allowed rule type. Skipping.")

    def execute(self, item):
        # loop over rules. Returns on the first rule that is true
        for r in self.rules:
            applies, return_value = r(item)
            if applies:
                return applies, return_value, r

        # fallback, return False, None
        return False, None, None


if __name__ == "__main__":

    # dummy item for testing locally
    class item:
        def __init__(self, subject, body="", attachment_texts="", sender=""):
            self.subject = subject
            self.body = body
            self.attachment_texts = attachment_texts
            self.sender = sender

        def __str__(self):
            # build list of relevant attributes
            attr = []
            for a in dir(self):
                if not callable(self.__getattribute__(a)) and not a.startswith('__'):
                    attr.append(f"{a}={self.__getattribute__(a)}")
            return f"{self.__class__.__name__} ({', '.join(attr)})"


    re = RuleEngine()
    re.add_rule('SubjectContainsRule', token='abe', return_value='abe@adresse.dk')
    re.add_rule('BodyContainsRule', token='Elefant', return_value='elefant_body')
    re.add_rule('AndRule', return_value='hund@kat.dk', condition1={"condition_type": "SubjectContains", "token": "hund"},
                                                        condition2={"condition_type": "BodyContains", "token": "kat"})

    # abe_subject = SubjectContainsRule('abe', 'abe@adresse.dk')
    # elefant_body = BodyContainsRule('Elefant', 'elefant_body@adresse.dk')

    it = item(subject='hund', body='elefant', attachment_texts='tiger')
    it2 = item(subject='abekat', body='ewlefant', attachment_texts='tiger')
    it3 = item(subject='Jeg har en hund', body='og kan ikke lide katte', attachment_texts='tiger')
    it4 = item(subject='Jeg har en hund', body='', attachment_texts='tiger')

    print(re.execute(it))
    print(re.execute(it2))
    print(re.execute(it3))
    print(re.execute(it4))