"""Tests for the helpers in processor.py that guard what the browser sends in mall places mode."""

import base64

import cv2
import numpy as np
import pytest

import processor


# ── read_setting ──────────────────────────────────────────────
def test_read_setting_returns_the_default_when_the_key_is_missing():
    assert processor.read_setting({}, "stay_sec", 2.5, 0.5, 30) == 2.5


def test_read_setting_keeps_a_value_inside_the_range():
    assert processor.read_setting({"stay_sec": 4}, "stay_sec", 2.5, 0.5, 30) == 4.0


@pytest.mark.parametrize("value, expected", [(-5, 0.5), (0, 0.5), (999, 30.0), (1e308, 30.0)])
def test_read_setting_holds_a_value_inside_the_range(value, expected):
    assert processor.read_setting({"stay_sec": value}, "stay_sec", 2.5, 0.5, 30) == expected


@pytest.mark.parametrize("value", [float("nan"), float("inf"), "nan", "abc", None, [1], {}])
def test_read_setting_rejects_values_that_are_not_numbers(value):
    with pytest.raises((ValueError, TypeError)):
        processor.read_setting({"stay_sec": value}, "stay_sec", 2.5, 0.5, 30)


# ── csv_safe ──────────────────────────────────────────────────
@pytest.mark.parametrize("name", ['=HYPERLINK("http://x","click")', "+1+1", "-2+3", "@SUM(A1)", "\tcmd", "\rcmd"])
def test_csv_safe_makes_a_formula_look_name_plain_text(name):
    assert processor.csv_safe(name) == "'" + name


@pytest.mark.parametrize("name", ["Boutique", "星巴克 Café", "Shop 2", "A-B", ""])
def test_csv_safe_leaves_ordinary_names_alone(name):
    assert processor.csv_safe(name) == name


# ── preview_jpeg ──────────────────────────────────────────────
def _decode(b64):
    return cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_COLOR)


def test_the_preview_keeps_the_shape_of_the_video():
    frame = np.full((288, 384, 3), 90, np.uint8)            # 4:3, like the CAVIAR clips
    out = _decode(processor.preview_jpeg(frame, []))
    assert out.shape[1] == 640 and abs(out.shape[0] - 480) <= 1


def test_the_preview_has_no_shops_drawn_on_it():
    frame = np.full((288, 384, 3), 90, np.uint8)
    out = _decode(processor.preview_jpeg(frame, []))        # no people: a plain grey picture, so nothing was drawn on it
    assert out.std() < 2.0


def test_the_preview_draws_the_tracked_people():
    frame = np.full((288, 384, 3), 90, np.uint8)
    out = _decode(processor.preview_jpeg(frame, [(7, 100, 60, 160, 220)]))
    assert out.std() > 5.0                                  # a box and a label are on it


def test_the_shop_drawing_is_gone_from_the_backend():
    assert not hasattr(processor, "draw_places") and not hasattr(processor, "SHOP_COLORS")
