from pathlib import Path

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from maple_tracker.glyphs import GlyphStore, parse_exp, parse_number, parse_typed_number

FONT = Path(r"C:\Windows\Fonts\arial.ttf")
pytestmark = pytest.mark.skipif(not FONT.exists(), reason="needs Arial to draw test text")


def draw(text, size=14, fg=(255, 255, 255), bg=(40, 60, 90)):
    """Text the way it sits in a game box: a few pixels of margin, one colour on another."""
    font = ImageFont.truetype(str(FONT), size)
    l, t, r, b = font.getbbox(text)
    img = Image.new("RGB", (r - l + 8, b - t + 8), bg)
    ImageDraw.Draw(img).text((4 - l, 4 - t), text, fill=fg, font=font)
    return np.asarray(img)


def test_reads_numbers_after_teaching(tmp_path):
    store = GlyphStore(tmp_path / "g.json", defaults=None)
    assert store.read("mesos", draw("1,234,567"))[0] == "?.???.???"
    assert store.learn("mesos", draw("1,234,567"), "1,234,567")[0]
    assert store.learn("mesos", draw("890"), "890")[0]
    for n in (9876543, 105, 2_000_000, 45_678):
        text, _ = store.read("mesos", draw(f"{n:,}"))
        assert parse_number(text) == n


def test_reads_bigger_text_and_dark_on_light(tmp_path):
    store = GlyphStore(tmp_path / "g.json", defaults=None)
    store.learn("text", draw("1,234,567,890"), "1234567890")     # commas may be left out
    text, _ = store.read("text", draw("3,141,592", size=20, fg=(20, 20, 20), bg=(235, 235, 220)))
    assert parse_number(text) == 3141592


def test_exp_line(tmp_path):
    store = GlyphStore(tmp_path / "g.json", defaults=None)
    assert store.learn("exp", draw("1,234 [56.78%]"), "1,234 [56.78%]")[0]
    assert store.learn("exp", draw("90 [0.00%]"), "90 [0.00%]")[0]
    text, _ = store.read("exp", draw("38,849 [61.02%]"))
    assert parse_exp(text) == (38849, 61.02)


def frame(name):
    """A real screenshot: Arial drawn by Windows with ClearType, where some neighbouring
    characters ('34', '56') share pixels."""
    return np.asarray(Image.open(Path(__file__).parent / "frames" / f"{name}.png").convert("RGB"))


def test_touching_characters_are_cut_apart(tmp_path):
    store = GlyphStore(tmp_path / "g.json", defaults=None)
    for name, text in (("cleartype_teach1", "1,234 [56.78%]"), ("cleartype_teach2", "90 [0.00%]")):
        ok, msg = store.learn("exp", frame(name), text)
        assert ok, msg
    assert parse_exp(store.read("exp", frame("cleartype_read"))[0]) == (38849, 61.02)
    assert parse_exp(store.read("exp", frame("cleartype_read2"))[0]) == (4563, 34.56)


def test_teaching_survives_reload(tmp_path):
    GlyphStore(tmp_path / "g.json", defaults=None).learn("mesos", draw("1234567890"), "1234567890")
    text, _ = GlyphStore(tmp_path / "g.json", defaults=None).read("mesos", draw("250"))
    assert parse_number(text) == 250


def test_wrong_count_is_refused(tmp_path):
    ok, msg = GlyphStore(None, defaults=None).learn("mesos", draw("1,234"), "123")
    assert not ok and "4 characters" in msg


def test_parsing():
    assert parse_exp("38.849[61.02%]") == (38849, 61.02)
    assert parse_exp("38.8?9[61.02%]") is None
    assert parse_exp("12[150.00%]") is None
    assert parse_number("1.234.567") == 1234567
    assert parse_number("") is None
    assert parse_typed_number(" 1,234 567 ") == 1234567
    assert parse_typed_number("12k") is None


def test_last_missing_digit_is_learned_without_asking(tmp_path):
    store = GlyphStore(tmp_path / "g.json", defaults=None)
    store.learn("mesos", draw("123,456,789"), "123456789")          # every digit but 0
    text, _ = store.read("mesos", draw("230,105"))
    assert parse_number(text) == 230105
    assert "0" in store.known("mesos")
    assert parse_number(store.read("mesos", draw("1,000"))[0]) == 1000
    # With two digits missing it can't know which is which, so it still asks.
    store2 = GlyphStore(None, defaults=None)
    store2.learn("mesos", draw("2,345,678"), "2345678")
    assert "?" in store2.read("mesos", draw("1,090"))[0]


def test_a_digit_without_an_example_is_not_read_as_its_neighbour():
    """The EXP and meso fonts: a 3 with no example yet must come out unread, not as an 8."""
    store = GlyphStore(None, defaults=None)
    store.learn("exp", draw("1,245 [68.90%]"), "1,245 [68.90%]")
    assert "?" in store.read("exp", draw("3"))[0]


def crop(name):
    return np.asarray(Image.open(Path(__file__).parent / "frames" / f"{name}.png").convert("RGB"))


def test_reads_numbers_from_the_players_screen():
    """Numbers cut from the player's screen during play (3440x1440), read with the fonts the
    app ships with: quickslot counts crowded enough to have stray pixels on their edges, digits
    that differ by one stroke, and meso digits drawn from Tahoma."""
    store = GlyphStore()
    assert parse_exp(store.read("exp", crop("exp_2135"))[0]) == (194097, 89.61)
    assert parse_exp(store.read("exp", crop("exp_2220"))[0]) == (19590, 8.15)
    assert parse_number(store.read("mesos", crop("mesos_2135"))[0]) == 243249
    counts = {"count_2135_lemon": 151, "count_2135_orange_potion": 108, "count_2135_blue_potion": 0,
              "count_2220_lemon": 63, "count_2220_orange_potion": 83}
    for name, want in counts.items():
        assert parse_number(store.read("potion", crop(name))[0]) == want, name


def test_meso_digits_are_drawn_from_tahoma():
    store = GlyphStore()
    assert store.known("mesos") == list("0123456789")
    # Every pair of different digits is far apart when compared pixel for pixel.
    t = [x for x in store.all("mesos") if x.mask is not None]
    from maple_tracker.glyphs import distance
    assert min(distance(a, b) for a in t for b in t if a.char != b.char) > 0.15


def test_exp_bar_works_out_its_last_missing_digit(tmp_path):
    store = GlyphStore(tmp_path / "g.json", defaults=None)
    store.learn("exp", draw("1,245 [67.89%]"), "1,245 [67.89%]")
    store.learn("exp", draw("[0.00%]"), "[0.00%]")
    store.learn("exp", draw("6"), "6")                          # every digit but 3
    assert parse_exp(store.read("exp", draw("13,579 [53.31%]"))[0]) == (13579, 53.31)
    assert "3" in store.known("exp")
