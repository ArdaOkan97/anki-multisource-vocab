import csv
import json
import tempfile
import unittest
from pathlib import Path

from vocabdeck.audit import (
    attach_reviews,
    audit_rows,
    write_audit_csv,
    write_audit_json,
)
from vocabdeck.cli import build_parser
from vocabdeck.database import VocabularyDatabase
from vocabdeck.manifest import build_manifest, discover_episode_files
from vocabdeck.readings import ReadingConsensus
from vocabdeck.subtitles import Cue
from vocabdeck.tokenizer import LexemeToken


class CharacterTokenizer:
    def tokenize(self, text):
        return [
            LexemeToken(character, character, character, "名詞")
            for character in text.replace(" ", "")
        ]


class ConstantEmbedder:
    model_name = "constant"

    def similarity(self, query, passage):
        return 0.9


class AgreeingReadingValidator:
    def validate(self, text, start, end, expected):
        return ReadingConsensus(
            "agreement", expected, expected, expected,
            ("sudachi-test", "openjtalk-test"),
        )


class CalibrationTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.directory = Path(self.temp.name)
        self.db = VocabularyDatabase(self.directory / "state.sqlite3")
        self.db.initialize()
        self.source_id = self.db.add_source(
            series="Test", season=1, episode=1, title=None, video_path=None,
            japanese_subtitle_path="test.srt", english_subtitle_path="test-en.srt",
        )
        japanese = [
            Cue(1, 0, 800, "猫"), Cue(2, 1000, 1800, "犬"),
            Cue(3, 2000, 2800, "鳥"),
        ]
        english = [
            Cue(1, 0, 800, "Cat"), Cue(2, 1000, 1800, "Dog"),
            Cue(3, 2000, 2800, "Bird"),
        ]
        self.db.ingest_cues(
            self.source_id, japanese, english, CharacterTokenizer()
        )
        self.db.connection.execute(
            """UPDATE lexemes SET gloss = lemma, dictionary_status = 'matched',
                      dictionary_version = 999"""
        )
        self.db.connection.commit()

    def tearDown(self):
        self.db.close()
        self.temp.cleanup()

    def test_materialized_batch_survives_known_state_changes(self):
        result = self.db.create_calibration_batch(
            "sample", [self.source_id], 2
        )
        self.assertEqual(result["cards"], 2)
        initial = self.db.calibration_batch("sample")
        self.db.mark_known(initial["cards"][0]["lexeme_key"])
        restored = self.db.calibration_batch("sample")
        self.assertEqual(
            [card["lexeme_key"] for card in restored["cards"]],
            [card["lexeme_key"] for card in initial["cards"]],
        )
        with self.assertRaisesRegex(ValueError, "already exists"):
            self.db.create_calibration_batch("sample", [self.source_id], 2)
        growth = self.db.vocabulary_growth("Test", 1)
        self.assertEqual(growth[-1]["cumulative_eligible"], 3)

    def test_reviews_attach_and_export(self):
        self.db.create_calibration_batch("sample", [self.source_id], 2)
        self.db.record_calibration_review(
            "sample", 1, "translation_alignment", "pass", "Looks correct",
        )
        batch = self.db.calibration_batch("sample")
        report = audit_rows(
            self.db,
            batch["cards"],
            embedder=ConstantEmbedder(),
            reading_validator=AgreeingReadingValidator(),
        )
        attach_reviews(report, self.db.calibration_reviews("sample"))
        self.assertEqual(report["summary"]["reviewed_criteria"], 1)
        self.assertEqual(
            report["summary"]["review_by_criterion"]["translation_alignment"][
                "agreements"
            ],
            1,
        )
        criterion = next(
            item for item in report["cards"][0]["audit_criteria"]
            if item["code"] == "translation_alignment"
        )
        self.assertEqual(criterion["review"]["note"], "Looks correct")

        json_path = write_audit_json(report, self.directory / "audit.json")
        csv_path = write_audit_csv(report, self.directory / "audit.csv")
        self.assertEqual(json.loads(json_path.read_text())["summary"]["cards"], 2)
        with csv_path.open(encoding="utf-8", newline="") as handle:
            rows = list(csv.DictReader(handle))
        self.assertEqual(len(rows), 16)
        reviewed = next(row for row in rows if row["review_note"])
        self.assertEqual(reviewed["review_verdict"], "pass")
        self.assertEqual(reviewed["review_priority"], "pass_control")
        with self.assertRaisesRegex(ValueError, "Unsupported audit criterion"):
            self.db.record_calibration_review(
                "sample", 1, "made_up_rule", "pass"
            )

    def test_reimport_invalidates_affected_checkpoint(self):
        self.db.create_calibration_batch("sample", [self.source_id], 2)
        self.db.ingest_cues(
            self.source_id,
            [Cue(1, 0, 800, "猫")],
            [Cue(1, 0, 800, "Cat")],
            CharacterTokenizer(),
        )
        with self.assertRaisesRegex(KeyError, "Unknown calibration batch"):
            self.db.calibration_batch("sample")


class ManifestTest(unittest.TestCase):
    def test_manifest_import_can_resume(self):
        args = build_parser().parse_args([
            "ingest-manifest", "manifest.json", "--episodes", "1-148",
            "--skip-existing",
        ])
        self.assertTrue(args.skip_existing)

    def test_discovers_and_builds_complete_manifest(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            for episode in (1, 2):
                stem = f"[Subs] Show - {episode:02d} [720p]"
                (directory / f"{stem}.mkv").touch()
                (directory / f"{stem}.srt").touch()
            discovered = discover_episode_files(directory)
            self.assertEqual(set(discovered), {1, 2})
            output = build_manifest(
                directory, directory / "manifest.json", series="Show", season=1,
                episodes=[1, 2], english_track=2,
            )
            manifest = json.loads(output.read_text())
            self.assertEqual(len(manifest["episodes"]), 2)
            self.assertEqual(manifest["episodes"][1]["english"], {"track": 2})

    def test_missing_pair_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory_name:
            directory = Path(directory_name)
            (directory / "[Subs] Show - 01 [720p].srt").touch()
            with self.assertRaisesRegex(FileNotFoundError, "mkv"):
                build_manifest(
                    directory, directory / "manifest.json", series="Show", season=1,
                    episodes=[1], english_track=2,
                )


if __name__ == "__main__":
    unittest.main()
