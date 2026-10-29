"""Tests for the API's input validation. Run: python3 -m unittest discover -s services/api"""
import unittest
from datetime import datetime, timedelta, timezone

import validate

NOW = datetime(2026, 10, 26, 12, 0, tzinfo=timezone.utc)

# Exactly what the room node sends (firmware/room_node/main/main.c), with a missing probe and no RSSI
FIRMWARE = {"device_id": "node1", "temp_c": 21.43, "rh": 55.10, "press_hpa": 1002.37, "rssi_dbm": None,
            "co2_ppm": 812, "scd_temp_c": 22.01, "scd_rh": 52.40, "wall_temp_c": 17.25, "outdoor_temp_c": None,
            "window_open": False, "door_open": True}


def problems(data, device="node1"):
    return validate.reading(data, device, NOW)[1]


class ReadingTest(unittest.TestCase):
    def test_firmware_payload_is_accepted(self):
        row, errs = validate.reading(FIRMWARE, "node1", NOW)
        self.assertEqual(errs, [])
        self.assertEqual(row["measured_at"], NOW)   # no device time yet: server time
        self.assertIsNone(row["outdoor_temp_c"])
        self.assertIs(row["door_open"], True)
        self.assertEqual(row["device_id"], "node1")

    def test_device_comes_from_the_token(self):
        self.assertEqual(problems(FIRMWARE, device="node2"), ["device_id: does not match the token"])
        row, errs = validate.reading({k: v for k, v in FIRMWARE.items() if k != "device_id"}, "node2", NOW)
        self.assertEqual((errs, row["device_id"]), ([], "node2"))

    def test_required_unknown_and_ranges(self):
        data = {**FIRMWARE, "rh": 101.0, "is_admin": True}
        del data["temp_c"]
        self.assertEqual(sorted(problems(data)), ["is_admin: unknown field", "rh: 101.0 outside 0..100", "temp_c: required"])

    def test_types_are_strict(self):
        # Python's bool is an int: True must not be stored as 1 °C, 1 must not mean "open", "21.5" is not a number
        self.assertEqual(problems({**FIRMWARE, "temp_c": True}), ["temp_c: expected float"])
        self.assertEqual(problems({**FIRMWARE, "window_open": 1}), ["window_open: expected bool"])
        self.assertEqual(problems({**FIRMWARE, "rh": "55.1"}), ["rh: expected float"])
        self.assertEqual(problems({**FIRMWARE, "co2_ppm": 812.5}), ["co2_ppm: expected int"])
        self.assertEqual(problems({**FIRMWARE, "temp_c": 21}), [])   # a whole number is a fine float

    def test_measured_at(self):
        ok = (NOW - timedelta(days=2)).isoformat()
        self.assertEqual(validate.reading({**FIRMWARE, "measured_at": ok}, "node1", NOW)[0]["measured_at"],
                         NOW - timedelta(days=2))
        for bad in ((NOW + timedelta(hours=1)).isoformat(), (NOW - timedelta(days=8)).isoformat(),
                    "2026-10-26T12:00:00", "yesterday", 1761480000, "9" * 100):
            self.assertEqual(len(problems({**FIRMWARE, "measured_at": bad})), 1, bad)


class ParseJsonTest(unittest.TestCase):
    def test_rejects_non_json_numbers_and_non_objects(self):
        for body in (b'{"temp_c": NaN}', b'{"temp_c": Infinity}', b'[1, 2]', b'"text"', b'{bad'):
            with self.assertRaises(ValueError, msg=body):
                validate.parse_json(body)
        self.assertEqual(validate.parse_json(b'{"a": 1}'), {"a": 1})


class QueryTest(unittest.TestCase):
    def test_defaults(self):
        q, errs = validate.query({}, NOW)
        self.assertEqual(errs, [])
        self.assertEqual((q["since"], q["until"], q["limit"], q["hourly"]), (NOW - timedelta(days=1), NOW, 1000, False))

    def test_bad_values(self):
        _, errs = validate.query({"limit": ["0"], "since": ["monday"], "order": ["drop table"], "device_id": [""]}, NOW)
        self.assertEqual(len(errs), 4, errs)
        _, errs = validate.query({"limit": ["5001"]}, NOW)
        self.assertEqual(len(errs), 1)


if __name__ == "__main__":
    unittest.main()
