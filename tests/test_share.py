import io

from PIL import Image

from maple_tracker.share import dib_bytes, summary_card, summary_text

RECORD = {"started": "2026-10-18T21:05:32", "ended": "2026-10-18T22:10:00", "total_seconds": 3880,
          "active_seconds": 3720, "exp_gained": 182_340, "levels": 1, "exp_per_hour": 176_458.0,
          "pct_per_hour": 81.4, "mesos_start": 228_935, "mesos_end": 371_000, "mesos_delta": 142_065,
          "potions": [
              {"name": "Lemon", "price": 150, "start": 206, "end": 151, "used": 55, "added": 0, "cost": 8250},
              {"name": "Orange Potion", "price": 150, "start": 134, "end": 108, "used": 26, "added": 0,
               "cost": 3900},
              {"name": "Meat", "price": 80, "start": 12, "end": 12, "used": 0, "added": 0, "cost": 0}],
          "potion_cost": 12_150, "net_mesos": 129_915, "net_per_hour": 125_724.0}


def test_text_to_paste():
    assert summary_text(RECORD).splitlines() == [
        "🍁 MapleStory Classic grind · 1h 02m",
        "⭐ EXP 176.5k/h (81.4%/h) · 182,340 gained · +1 level",
        "💰 Mesos +125.7k/h · +129.9k net",
        "🧪 Potions 12,150 mesos (Lemon ×55, Orange Potion ×26)",
    ]
    assert "(so far)" in summary_text(RECORD, live=True).splitlines()[0]


def test_text_without_mesos_or_potions():
    s = dict(RECORD, mesos_start=None, potions=[], potion_cost=0, levels=0)
    lines = summary_text(s).splitlines()
    assert not any("Mesos" in line for line in lines) and lines[-1] == "🧪 Potions none drunk"


def test_card_grows_for_a_long_potion_list():
    short = summary_card(RECORD)
    many = [dict(RECORD["potions"][0], name=f"Potion number {i}", used=i + 1, cost=100) for i in range(12)]
    long = summary_card(dict(RECORD, potions=many, potion_cost=1200))
    assert long.width == short.width and long.height > short.height


def test_clipboard_picture_is_a_bitmap():
    img = Image.new("RGB", (30, 20), (10, 200, 30))
    dib = dib_bytes(img)
    header = b"BM" + (14 + len(dib)).to_bytes(4, "little") + bytes(4) + (14 + 40).to_bytes(4, "little")
    back = Image.open(io.BytesIO(header + dib))
    assert back.size == (30, 20) and back.convert("RGB").getpixel((5, 5)) == (10, 200, 30)
