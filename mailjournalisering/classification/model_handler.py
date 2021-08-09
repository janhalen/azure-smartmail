import os
from .rule_engine import RuleEngine
from contentextraction.att_extractor import AttExtractor
from .model import Model

class ModelHandler:

    def __init__(self, config):
        self.config = config
        self.model = None

        # load model
        if self.config["MODEL_VERSION"] and self.config["MODEL_PATH"]:
            if not os.path.exists(self.config["MODEL_PATH"]):
                print(f"{self.config['MODEL_PATH']} is not mounted. Loading model from Droids SharePoint")
                home_dir = os.path.expanduser("~")
                self.config["MODEL_PATH"] = os.path.join(home_dir, "Droids Agency", "DataScience - Documents", "modeller")

            self.model = Model(os.path.join(self.config["MODEL_PATH"], self.config["MODEL_VERSION"]))
            self.id_to_category = {id: category for category, id in self.model.category_to_id.items()}

            # model warmup
            self.model.predict('dette er en test af opstart')

        # setup rule engine
        self.rule_engine = self._load_rule_engine(config)

        # Setup att extractor
        self.att_extractor = None
        if "RECIPIENTS" in self.config and self.config["RECIPIENTS"] and self.config["USE_ATT_EXTRACTOR"]:
            self.att_extractor = AttExtractor(self.config['RECIPIENTS'])

    def classify_item(self, prep_item):
        # classifier method referenced by mail checker service.
        text = prep_item.extract_text()

        # check rules
        applies, classification, r = self.rule_engine.execute(prep_item)

        if self.model:
            probabilities = self.model.predict(text)
            confidence = probabilities.max()
            model_classification = self.id_to_category[probabilities.argmax()]
        else:
            model_classification = None
            confidence = -1.

        # Check if mail has "att" and we find a match in our Recipients list
        match = None
        if self.att_extractor is not None:
            match = self.att_extractor.process(prep_item.subject, prep_item.body)

        # if any rules then use this value, else proceed to classification
        if applies:
            call_type = 'rule ' + r.name
            # TODO: setup auditlog to handle a rule_id

            info = f"{prep_item.subject}, classified as: {classification} with rule {r}"
        elif match:
            classification = match
            call_type = "att_extractor"
            info = f"{prep_item.subject}, classified as: {classification} using ATT extractor."

        elif not self.model:
            classification = self.config["FALLBACK_MAIL"]
            call_type = 'no_rule_nor_att_applied'
            info = f"{prep_item.subject}, didn't trigger any rule nor ATTs."
        else:
            classification = model_classification
            call_type = 'model'

            info = f"{prep_item.subject}, classified as: {classification} with conf {round(float(confidence), 2)}."
        print(info, flush=True)

        return {"classification": classification,
                "call_type": call_type,
                "conf": confidence,
                "model_classification": model_classification}

    def _load_rule_engine(self, config):
        rule_engine = RuleEngine()
        for rule in config["RULES"]:
            rule_engine.add_rule(**rule)
        return rule_engine