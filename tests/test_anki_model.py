import unittest

from vocabdeck.anki import AnkiConnect, BACK, CSS, FRONT, MODEL_NAME


class RecordingAnkiConnect(AnkiConnect):
    def __init__(self):
        self.calls = []

    def invoke(self, action, **params):
        self.calls.append((action, params))
        if action == "modelNames":
            return [MODEL_NAME]
        if action == "modelFieldNames":
            return ["LexemeKey", "Expression", "Sentence"]
        return None


class AnkiModelTest(unittest.TestCase):
    def test_existing_model_gets_fields_templates_and_styling_updated(self):
        client = RecordingAnkiConnect()
        client.ensure_model()

        added = {
            params["fieldName"]
            for action, params in client.calls
            if action == "modelFieldAdd"
        }
        self.assertIn("SentenceCloze", added)
        self.assertIn("SentenceAnswer", added)
        template_call = next(
            params for action, params in client.calls if action == "updateModelTemplates"
        )
        template = template_call["model"]["templates"]["Recognition"]
        self.assertEqual(template["Front"], FRONT)
        self.assertEqual(template["Back"], BACK)
        style_call = next(
            params for action, params in client.calls if action == "updateModelStyling"
        )
        self.assertEqual(style_call["model"]["css"], CSS)


if __name__ == "__main__":
    unittest.main()
