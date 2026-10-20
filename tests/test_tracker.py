import pytest

from maple_tracker.tracker import ExpTracker, PotionState, Session, Stable


def reading(exp, needed):
    """What the bar shows: EXP and its % of the level, cut to two decimals."""
    return exp, int(exp / needed * 10000) / 100


def feed(t, *exps, needed=100_000):
    return sum(t.update(*reading(e, needed)) for e in exps)


def test_counts_plain_gains():
    t = ExpTracker()
    assert feed(t, 10_000, 12_000, 12_000, 15_500) == 5_500
    assert t.needed() == pytest.approx(100_000, rel=0.01)
    assert t.remaining() == pytest.approx(84_500, rel=0.01)


def test_ignores_a_one_off_misread():
    t = ExpTracker()
    feed(t, 10_000, 12_000)
    assert t.update(92_000, 12.0) == 0          # a digit misread, % didn't move
    assert feed(t, 12_500) == 500
    assert t.exp == 12_500


def test_level_up_counts_the_rest_of_the_old_level():
    t = ExpTracker()
    feed(t, 50_000, *range(58_000, 99_001, 8_000), 99_000)   # a level's worth of kills
    assert t.update(*reading(3_000, 200_000)) == 0    # waits for a second reading to agree
    # The rest of the old level is estimated from its %, so it's close rather than exact.
    assert t.update(*reading(3_500, 200_000)) == pytest.approx(1_000 + 3_000 + 500, abs=20)
    assert t.levels == 1
    assert t.needed() == pytest.approx(200_000, rel=0.05)


def test_death_is_a_loss():
    t = ExpTracker()
    feed(t, 40_000, 45_000, 50_000)
    assert feed(t, 45_000) == 0
    assert feed(t, 45_200) == -5_000 + 200
    assert t.levels == 0


def test_stable_needs_two_reads():
    s = Stable(100)
    assert s.feed(None) is None
    assert s.feed(90) is None
    assert s.feed(91) is None
    assert s.feed(91) == 91 and s.value == 91
    assert s.feed(91) is None


class Clock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t


def test_idle_time_is_capped_and_pause_stops_the_clock():
    c = Clock()
    s = Session(0, [], idle_seconds=60, clock=c)
    s.on_exp(*reading(1_000, 100_000))
    for t, e in ((10, 2_000), (20, 3_000)):
        c.t = t
        s.on_exp(*reading(e, 100_000))
    assert s.active() == 20
    c.t = 500                                   # went to town for 8 minutes
    assert s.idle() and s.active() == 80
    s.on_exp(*reading(4_000, 100_000))
    assert s.active() == 80 and s.exp_gained == 3_000
    assert s.exp_rate() == pytest.approx(3_000 / 80 * 3600)
    s.pause()
    c.t = 5_000
    assert s.active() == 80
    s.on_exp(*reading(9_000, 100_000))          # gained while paused: not counted
    assert s.exp_gained == 3_000
    s.resume()
    c.t = 5_030
    assert s.active() == 110


def test_rolling_rate_uses_the_last_five_active_minutes():
    c = Clock()
    s = Session(0, [], idle_seconds=60, clock=c)
    exp = 0
    s.on_exp(*reading(exp, 10_000_000))
    for t in range(10, 601, 10):                # 10 minutes: slow, then fast
        c.t = t
        exp += 100 if t <= 300 else 300
        s.on_exp(*reading(exp, 10_000_000))
    assert s.rolling_rate() == pytest.approx(300 / 10 * 3600, rel=0.05)
    assert s.exp_rate() == pytest.approx(exp / 600 * 3600)


def test_potions_and_net_mesos():
    c = Clock()
    red = PotionState("Red Potion", 50, start=100)
    blue = PotionState("Blue Potion", 200, start=20)
    s = Session(1_000_000, [red, blue], clock=c)
    s.set_potion("Red Potion", 90)              # drank 10
    s.set_potion("Red Potion", 200)             # bought 110 for 5,500
    s.set_potion("Blue Potion", 15)             # drank 5
    c.t = 3600
    # 20,000 looted, 5,500 spent at the shop
    s.finish(1_014_500, {"Red Potion": 195, "Blue Potion": 15})
    assert (red.used, red.added, red.count) == (15, 110, 195)
    assert s.potion_cost == 15 * 50 + 5 * 200
    assert s.mesos_delta == 14_500
    assert s.net_mesos == 20_000 - s.potion_cost
    summary = s.summary()
    assert summary["net_per_hour"] == pytest.approx(s.net_mesos / s.active() * 3600)
    assert [p["used"] for p in summary["potions"]] == [15, 5]


def test_mesos_and_potions_can_be_read_later():
    c = Clock()
    s = Session(potions=[PotionState("Red Potion", 50)], clock=c)
    assert s.net_mesos == 0 and s.potion_cost == 0
    s.set_mesos(500_000)                        # inventory opened after Start
    s.set_potion("Red Potion", 30)              # first time the count was read
    s.set_potion("Red Potion", 25)
    s.set_mesos(510_000)
    assert s.mesos_start == 500_000
    assert s.potion_cost == 250 and s.net_mesos == 10_000 - 250


def test_a_misread_repeating_on_a_still_screen_adds_nothing():
    t = ExpTracker()
    total = feed(t, 171_563, 171_600, needed=216_600)
    # A 1 read as 7 in the hundred-thousands: the same wrong reading every second while the
    # screen doesn't change, then the real number again.
    for _ in range(10):
        total += t.update(771_600, 79.21)
    total += feed(t, 171_600, 171_650, 171_700, needed=216_600)
    assert total == pytest.approx(137, abs=40)        # just the real kills


def test_a_wrong_digit_that_keeps_climbing_is_never_counted():
    t = ExpTracker()
    total = feed(t, 171_563, needed=216_600)
    # The misread sticks while EXP really climbs (171,6xx read as 771,6xx), then clears.
    for e in (171_600, 171_650, 171_700):
        total += t.update(e + 600_000, int(e / 216_600 * 10000) / 100)
    total += feed(t, 171_750, 171_800, needed=216_600)
    assert total < 1_000


def test_a_big_real_chunk_counts_once_more_exp_follows():
    t = ExpTracker()
    feed(t, 50_000, 50_100)
    assert t.update(*reading(80_000, 100_000)) == 0       # 30% at once: wait and see
    assert t.update(*reading(80_000, 100_000)) == 0       # same again: still waiting
    assert t.update(*reading(80_050, 100_000)) == 29_950  # more on top: it was real


def test_potions_gone_all_at_once_were_not_drunk():
    blue = PotionState("Blue Potion", 220, start=67)
    blue.set(0)                                      # misread, or put in storage
    assert blue.used == 0 and blue.removed == 67 and blue.cost == 0
    blue.set(67)                                     # back again: not bought either
    assert (blue.used, blue.added, blue.removed) == (0, 0, 0)
    blue.set(66)
    blue.set(65)
    assert blue.used == 2 and blue.cost == 440
    blue.set(165)                                    # bought 100
    assert blue.added == 100


# A few rows of the game's EXP table (level: EXP to next level), from NiaMeowDB.
TABLE = {36: 194_832, 37: 216_600, 38: 240_500, 39: 266_682, 59: 1_147_132, 60: 1_209_994, 61: 1_276_301}


def test_level_from_one_reading():
    from maple_tracker.tracker import level_of
    assert level_of(171_561, 79.21, TABLE) == 37
    assert level_of(19_590, 8.15, TABLE) == 38            # just after levelling up
    assert level_of(144_355, 11.93, TABLE) == 60
    assert level_of(12, 0.0, TABLE) is None               # an empty bar says nothing
    assert level_of(171_561, 79.21, {}) is None           # no table yet


def test_known_level_gives_exact_exp_needed():
    t = ExpTracker(TABLE)
    t.update(171_561, 79.21)
    assert t.level() == 37 and t.needed() == 216_600 and t.remaining() == 216_600 - 171_561
    s = Session(clock=Clock(), exp_table=TABLE)
    s.on_exp(171_561, 79.21)
    assert s.exp.level() == 37


def test_real_time_counts_town_trips_but_not_pauses():
    c = Clock()
    s = Session(idle_seconds=60, clock=c)
    s.on_exp(*reading(1_000, 100_000))
    for t in range(10, 601, 10):                # 10 minutes of kills, one every 10 seconds
        c.t = t
        s.on_exp(*reading(1_000 + t * 10, 100_000))
    c.t = 1200                                  # 10 minutes in town: grinding clock stops after 1
    s.on_exp(*reading(7_100, 100_000))
    assert s.active() == pytest.approx(600 + 60)
    assert s.real() == pytest.approx(1200)
    s.pause()
    c.t = 4800                                  # an hour paused: neither clock counts it
    s.resume()
    assert s.real() == pytest.approx(1200)
    assert s.exp_rate_real() == pytest.approx(6_100 / 1200 * 3600)
    assert s.exp_rate() > s.exp_rate_real()
    summary = s.summary()
    assert summary["real_seconds"] == 1200 and summary["exp_per_hour_real"] == pytest.approx(18_300)
