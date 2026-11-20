"""scotty.json's head turn section: defaults, validation, and sections that do not overwrite each other."""

import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path[:0] = [str(Path(__file__).resolve().parents[1]), str(Path(__file__).resolve().parents[2])]

import app_config


class HeadTurnSettingsTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "scotty.json"

    def tearDown(self):
        self.folder.cleanup()

    def test_off_by_default_and_when_the_file_is_missing_or_broken(self):
        self.assertEqual(app_config.load_headturn_settings(self.path), app_config.headturn_defaults())
        self.assertFalse(app_config.headturn_defaults()["enabled"])
        self.path.write_text("{not json", encoding="utf-8")
        self.assertEqual(app_config.load_headturn_settings(self.path), app_config.headturn_defaults())

    def test_round_trip(self):
        settings = dict(app_config.headturn_defaults(), enabled=True, camera=1, dwell=0.6, cooldown=2.0,
                        calibration=[{"target": "self", "yaw": 0.0, "pitch": 0.3}])
        app_config.save_headturn_settings(self.path, settings)
        self.assertEqual(app_config.load_headturn_settings(self.path), settings)

    def test_each_invalid_value_falls_back_on_its_own(self):
        self.path.write_text(json.dumps({"headturn": {
            "enabled": "yes", "camera": 99, "calibration": "x", "dwell": 50, "cooldown": True}}), encoding="utf-8")
        self.assertEqual(app_config.load_headturn_settings(self.path), app_config.headturn_defaults())

    def test_saving_one_section_keeps_the_other(self):
        files = app_config.files_defaults()
        files["keep_days"] = 3
        app_config.save_files_settings(self.path, files)
        app_config.save_headturn_settings(self.path, dict(app_config.headturn_defaults(), enabled=True))
        self.assertEqual(app_config.load_files_settings(self.path)["keep_days"], 3)
        app_config.save_files_settings(self.path, files)
        self.assertTrue(app_config.load_headturn_settings(self.path)["enabled"])


if __name__ == "__main__":
    unittest.main()
