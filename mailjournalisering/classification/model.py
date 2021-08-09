import tensorflow as tf
import pickle
import re
from nltk.tokenize import RegexpTokenizer
from tensorflow.keras.preprocessing.sequence import pad_sequences
import string


def _clean_numbers(x):
    x = re.sub('[0-9]{5,}', '#####', x)
    x = re.sub('[0-9]{4}', '####', x)
    x = re.sub('[0-9]{3}', '###', x)
    x = re.sub('[0-9]{2}', '##', x)
    return x

trans = str.maketrans(string.punctuation, ' ' * len(string.punctuation))
mail_regex = r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+"

MAX_SEQUENCE_LENGTH = 200

class Model:
    def __init__(self, model_path):
        self.loaded_model = tf.saved_model.load(model_path)
        with open(self.loaded_model.word_index.asset_path.numpy(), 'rb') as fh:
            self.word_index = pickle.load(fh)
        with open(self.loaded_model.category_to_id.asset_path.numpy(), 'rb') as fh:
            self.category_to_id = pickle.load(fh)
        self.tokenizer = RegexpTokenizer(r'\w+|\S+')
        self._final_layer_name = list(self.loaded_model.signatures["serving_default"].structured_outputs.keys())[0]

    def _preprocess_text(self, text):
        text = re.sub(r"<.*?>", " ", text)
        text = re.sub(r"\[.*?\]", " ", text)
        text = re.sub(mail_regex, "EMAILTOKEN", text)
        text = text.translate(trans)
        text = _clean_numbers(text)
        text = text.lower()
        return self.tokenizer.tokenize(text)

    def predict(self, text):
        tokens = self._preprocess_text(text)
        ids = [self.word_index.get(t, 0) for t in tokens[:1000]]
        padded_tokens = tf.convert_to_tensor(pad_sequences([ids], maxlen=MAX_SEQUENCE_LENGTH, padding='pre', truncating='post'))
        infer = self.loaded_model.signatures["serving_default"]
        return infer(padded_tokens)[self._final_layer_name][0].numpy()

if __name__ == "__main__":
    model = Model(r"C:\Users\Thomas Ørkild\Droids Agency\DataScience - Documents\modeller\14102020_norddjurs")
    out = model.predict("Jeg skal bruge et nyt job, tak!")

    print(out)