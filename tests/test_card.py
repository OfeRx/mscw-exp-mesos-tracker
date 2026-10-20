"""The overlay card: drawn as one picture, with its buttons where clicks land."""
from maple_tracker.card import KEY, W, View, hit, render


def view(**kw):
    v = View(state="tracking", state_text="Tracking", clock="1:54:12", level=37, exp=171_561, pct=79.21,
             tiles=[("Last 5 min", "+12.8k", None)] * 6, mesos=243_249,
             meso_tiles=[("Mesos / hour", "+95.2k", None)] * 3,
             details=["Lemon  206 → 151  (−55 drunk)"],
             buttons=[("main", "Stop", True, True), ("pause", "Pause", False, True),
                      ("recheck", "Recheck", False, True), ("prices", "Prices", False, True),
                      ("share", "Share", False, True)])
    for k, value in kw.items():
        setattr(v, k, value)
    return v


def test_card_draws_with_every_button_clickable():
    img, hits = render(view())
    assert img.width == W
    assert {"main", "pause", "recheck", "prices", "share", "close", "details"} <= set(hits)
    x0, y0, x1, y1 = hits["share"]
    assert hit(hits, (x0 + x1) // 2, (y0 + y1) // 2) == "share"
    assert img.getpixel((0, 0)) == KEY                    # rounded corners are see-through
    assert img.getpixel((W // 2, img.height // 2)) != KEY


def test_card_grows_for_details_and_messages():
    short, _ = render(view())
    tall, hits = render(view(expanded=True, message="Open your inventory once so I can note your mesos.",
                             message_clickable=True))
    assert tall.height > short.height and "message" in hits


def test_a_disabled_button_cant_be_clicked():
    _, hits = render(view(state="off", buttons=[("main", "Start", True, True), ("pause", "Pause", False, False)]))
    assert "main" in hits and "pause" not in hits


def test_card_without_level_or_reading():
    img, _ = render(view(level=None, exp=None, pct=None, state="off", clock=""))
    assert img.width == W


def test_hidden_parts_make_it_slimmer():
    full, _ = render(view())
    compact, hits = render(view(sections=("bar", "exp")))
    bare, _ = render(view(sections=()))
    assert bare.height < compact.height < full.height
    # Without the buttons, Start/Stop sits in the header, and only it can be clicked.
    assert "main" in hits and "pause" not in hits and "details" not in hits
    assert hits["main"][3] < 40


def test_size():
    full, hits = render(view())
    small, small_hits = render(view(), zoom=0.6)
    assert small.width == round(W * 0.6) and small.height == round(full.height * 0.6)
    x0, y0, x1, y1 = small_hits["share"]
    assert hit(small_hits, (x0 + x1) // 2, (y0 + y1) // 2) == "share"
    assert x0 == round(hits["share"][0] * 0.6)
