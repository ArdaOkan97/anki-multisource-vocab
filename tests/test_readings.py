import unittest

from vocabdeck.readings import (
    ContextualReadingValidator,
    OpenJTalkContextualReader,
    SudachiContextualReader,
)


class FixedReader:
    def __init__(self, name, value):
        self.name = name
        self.value = value

    def reading(self, text, start, end):
        return self.value


class ContextualReadingTest(unittest.TestCase):
    def test_consensus_accepts_contextual_nen(self):
        validator = ContextualReadingValidator(readers=(
            FixedReader("sudachi-test", "ネン"),
            FixedReader("openjtalk", "ネン"),
        ))
        result = validator.validate("３年に１人", 1, 2, "ネン")
        self.assertEqual(result.status, "agreement")
        self.assertEqual((result.sudachi, result.openjtalk), ("ネン", "ネン"))

    def test_consensus_reports_real_disagreement(self):
        validator = ContextualReadingValidator(readers=(
            FixedReader("sudachi-test", "トシ"),
            FixedReader("openjtalk", "トシ"),
        ))
        result = validator.validate("その年", 2, 3, "ネン")
        self.assertEqual(result.status, "disagreement")

    def test_one_dissenting_analyzer_does_not_override_majority(self):
        validator = ContextualReadingValidator(readers=(
            FixedReader("sudachi-test", "ナン"),
            FixedReader("openjtalk", "ナニ"),
        ))
        result = validator.validate("何だ？", 0, 1, "ナン")
        self.assertEqual(result.status, "agreement")

    def test_real_analyzers_read_counter_context_as_nen(self):
        text = "３年に１人だそうだ。"
        self.assertEqual(SudachiContextualReader().reading(text, 1, 2), "ネン")
        self.assertEqual(OpenJTalkContextualReader().reading(text, 1, 2), "ネン")


if __name__ == "__main__":
    unittest.main()
