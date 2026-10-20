# MapleStory Classic World EXP & meso tracker

A small always-on-top overlay for MapleStory Classic World, styled after the game's own
windows: your level in orange number boxes, an EXP bar, and big numbers for the EXP gained in
the last 5 minutes, EXP/hour, time to the next level, this session's EXP, mesos/hour, net mesos
and what your potions cost. Each session is saved when you stop, and you can copy a summary
(text or a picture) to paste into Discord or WhatsApp.

## How it reads the game

It only takes ordinary screenshots, the same kind Snipping Tool or OBS's Display Capture takes,
and reads the numbers off them. It never reads or writes the game's memory, never opens the
game's process, never touches its network traffic and never sends keys or clicks. Nexon hasn't
reviewed it, so like any third-party tool, use it at your own risk.

## Setting it up

**The easy way (no Python needed):** download `MapleTracker-<version>-windows.zip` from this
repository's Releases, unzip it anywhere, and double-click `MapleTracker.exe`. The program
isn't signed, so the first time Windows may say "Windows protected your PC": click **More
info**, then **Run anyway**. Your sessions and settings go in a `data` folder next to the exe;
keep it when you update to a newer version.

**From source:** you need **Python 3.14 or newer** (from [python.org](https://www.python.org);
tick "Add python.exe to PATH" when installing).

1. Get the code: `git clone` this repository, or download it as a ZIP and unzip it.
2. Double-click `run.bat`. The first time, it sets up its own Python environment (a minute or
   two), then starts the tracker.

Either way, on its first start the tracker downloads the potion and food list and icons, and
the EXP table, from NiaMeowDB (a few seconds; see *Game data* below). It only runs on Windows.

Play the game in **windowed or borderless** mode: exclusive fullscreen hides other windows, so
the overlay can't show.

**The game's resolution:** the game draws its picture at the resolution chosen in its Graphics
settings and stretches it to fill the window. When the window is a whole number of times that
size, every pixel stays sharp and the tracker reads the numbers; stretched by an in-between
amount, they come out blurred and it can't. So pick a resolution that fits your window evenly:

| Your window / screen | Game resolution | Drawn at |
|---|---|---|
| 1920×1080 | 1920×1080 | 1x |
| 2560×1440 (or 3440×1440 ultrawide) | 1280×720 | 2x |
| 3840×2160 (4K) | 1920×1080 | 2x |
| 1366×768 | 1366×768 | 1x |

For example 1366×768 on a 1080p screen is stretched 1.41x and can't be read. The tracker
notices a stretched picture and says which resolution to pick. If the numbers still aren't read,
right-click the overlay and choose **Save diagnostics**, and send the zip it saves (just the EXP
bar, meso field and quickslot: no chat or names).

## Using it

1. Press **Start**, and open your inventory on the **Use** tab once, so it can note your
   mesos and every potion and food stack.
2. Grind. EXP and the potions on your quickslot are read live; opening your inventory now and
   then keeps the meso count current.
3. Press **Stop** with your inventory open (or open it after pressing Stop) and you get the
   summary.
4. To show friends, press **Copy text** or **Copy image** in the summary and paste into
   Discord or WhatsApp with Ctrl+V. **Share** on the overlay copies your stats so far mid-grind
   (or the last session's).

If the potion counts ever look wrong, open your inventory on the **Use** tab and press
**Recheck**: it reads everything again right away and believes what it sees. **Prices** shows
what each potion and food item costs (NPC shop prices) and lets you change any.

There's nothing to point out on screen. It finds the EXP bar and the meso count by looking for
the "EXP." and "MESOS" labels, and recognises potions and food by their icons, on the
quickslot and in the inventory. The overlay lists each one, with the count it started at and
the count now, so you can check it read them right. If your UI looks different and it can't
find the EXP bar, it offers to let you point it out by hand.

To make the overlay smaller and less in the way, right-click it:

- **Size** goes from 60% to 150% (or hold Ctrl and turn the mouse wheel over it).
- **Show** picks which parts to keep: the level and EXP bar, either row of EXP numbers, mesos
  and potions, and the buttons. **Compact** keeps just the bar and one row. With the buttons
  hidden, Start/Stop moves into the title bar, and every button's action is in the right-click
  menu too.
- **Opacity** lets the game show through.

It remembers all of these, and where you dragged it, for next time.

The overlay shows up in screenshots, screen sharing and streams (OBS, Discord). Right-click it
to hide it from those instead. Either way it never reads itself: it blacks its own windows out
of what it reads, so it can sit anywhere, as long as it doesn't cover the EXP bar, quickslot or
inventory.

Your sessions, settings and anything it learned are kept in the `data/` folder, which isn't
part of the repository.

### Reading the numbers

The game draws its numbers in small pixel fonts, enlarged by whole pixels to fit your window,
which general OCR reads badly. So the tracker compares each character pixel for pixel with
the fonts it comes with, drawn at the size your screen shows the game at. The meso count is
Tahoma 11; the EXP and item-count fonts are the game's own, taken from a full-resolution
screenshot. The one EXP digit missing there (3) is worked out by elimination the first time it
shows up, and a quickslot count it can't read is learned from the inventory total (the
quickslot shows how many you have in all). It only asks you, once, if none of that works.

## How the numbers are worked out

- **EXP gained** follows your EXP across level-ups (the rest of the old level is added) and
  deaths (the lost EXP is subtracted). A reading that doesn't fit, or a big jump, only counts
  once a later reading shows more EXP on top, so a misread digit adds nothing.
- **Time** is kept two ways, and EXP/hour and mesos/hour are shown for both. **Grinding** time
  only counts while EXP is coming in: after 60 seconds without any (town, AFK) that clock
  stops until the next kill. **Real time** counts every minute since Start, town trips
  included. **Pause** stops both.
- **Potion cost** = potions drunk × price. Drops in the count are drinks; rises are buying
  or looting. Many gone at once (more than 15 in a couple of seconds) weren't drunk: they were
  put away, sold or misread, so they aren't counted, and if they come back they cancel out.
  The quickslot shows how many you have in total: when it shows more than the inventory, some
  stacks are scrolled out of view; when it shows fewer, it's a different item that looks the
  same (one you have none of), and it's ignored. An inventory open on another tab than Use
  says nothing about potions.
- **Net profit** = meso change + (potions now − potions at start) × price. Buying potions
  mid-session isn't a loss, since you still have them; drinking them is.

## Game data

The potion and food list and icons come from
[NiaMeowDB](https://meowdb.com/msclassic/item-db/use?subtype=Potion%2CFood)'s item database,
NPC shop prices from its NPC shop pages, and the EXP needed for each level from its
[EXP table](https://meowdb.com/msclassic/guides/exp-table-level-1-to-100). They aren't included
in this repository: each copy downloads them on first run into `data/`
(`maple_tracker/itemdata.py`), since NiaMeowDB asks to be contacted before its data is
republished. Where no open shop sells an item, its price is estimated as 10x what an NPC pays
for it. Item icons are Nexon's.

The EXP table is how the overlay knows your level: EXP ÷ % gives the EXP your level needs,
which matches exactly one level. That also makes time to level exact.

## Development

```bash
.venv\Scripts\python.exe -m pytest
```

`maple_tracker/tracker.py` holds the session math, `glyphs.py` the character reader,
`locate.py` the finding of the numbers on screen, `screen.py` the capture, `items.py` and
`itemdata.py` the potion and food recognition and data, `share.py` the text and picture for
sharing, `card.py` the overlay's look, and `app.py` / `dialogs.py` the windows.
`tools/build_assets.py` rebuilds the fonts the app ships with (`maple_tracker/assets/fonts.json`)
from the screenshots in `tests/frames/` (cropped to the game's UI). Tests that recognise items
are skipped until the game data has been downloaded (start the app once, or run
`python -m maple_tracker.itemdata`).

### Building MapleTracker.exe

```bash
.venv\Scripts\python.exe -m pip install pyinstaller
.venv\Scripts\python.exe tools\build_exe.py
```

This makes `dist\MapleTracker\` (the exe and what it needs) and
`dist\MapleTracker-<version>-windows.zip` to upload as a release. The version is in
`maple_tracker/__init__.py`.
