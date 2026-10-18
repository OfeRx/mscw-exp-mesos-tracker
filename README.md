# MapleStory Classic World EXP & meso tracker

A small always-on-top overlay for MapleStory Classic World that shows EXP/hour, the
last-5-minutes rate, time to level, net mesos/hour and what your potions cost. Each session is
saved when you stop, and you can copy a summary (text or a picture) to paste into Discord or
WhatsApp.

## How it reads the game

It only takes ordinary screenshots, the same kind Snipping Tool or OBS's Display Capture takes,
and reads the numbers off them. It never reads or writes the game's memory, never opens the
game's process, never touches its network traffic and never sends keys or clicks. Nexon hasn't
reviewed it, so like any third-party tool, use it at your own risk.

## Setting it up

You need **Windows** and **Python 3.14 or newer** (from [python.org](https://www.python.org);
tick "Add python.exe to PATH" when installing).

1. Get the code: `git clone` this repository, or download it as a ZIP and unzip it.
2. Double-click `run.bat`. The first time, it sets up its own Python environment (a minute or
   two), then starts the tracker.
3. On its first start the tracker downloads the potion and food list and icons from
   NiaMeowDB (a few seconds; see *Item data* below).

Play the game in **windowed or borderless** mode: exclusive fullscreen hides other windows, so
the overlay can't show. Any window size works.

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
- **Time** only counts while EXP is coming in: after 60 seconds without any (town, AFK) the
  clock stops until the next kill. **Pause** stops it too.
- **Potion cost** = potions drunk × price. Drops in the count are drinks; rises are buying
  or looting. Many gone at once (more than 15 in a couple of seconds) weren't drunk: they were
  put away, sold or misread, so they aren't counted, and if they come back they cancel out.
  The quickslot shows how many you have in total: when it shows more than the inventory, some
  stacks are scrolled out of view; when it shows fewer, it's a different item that looks the
  same (one you have none of), and it's ignored. An inventory open on another tab than Use
  says nothing about potions.
- **Net profit** = meso change + (potions now − potions at start) × price. Buying potions
  mid-session isn't a loss, since you still have them; drinking them is.

## Item data

The potion and food list and icons come from
[NiaMeowDB](https://meowdb.com/msclassic/item-db/use?subtype=Potion%2CFood)'s item database,
and NPC shop prices from its NPC shop pages. They aren't included in this repository: each copy
downloads them on first run into `data/items/` (`maple_tracker/itemdata.py`), since NiaMeowDB
asks to be contacted before its data is republished. Where no open shop sells an item, its
price is estimated as 10x what an NPC pays for it. Item icons are Nexon's.

## Development

```bash
.venv\Scripts\python.exe -m pytest
```

`maple_tracker/tracker.py` holds the session math, `glyphs.py` the character reader,
`locate.py` the finding of the numbers on screen, `screen.py` the capture, `items.py` and
`itemdata.py` the potion and food recognition and data, `share.py` the text and picture for
sharing, and `app.py` / `dialogs.py` the windows. `tools/build_assets.py` rebuilds the fonts
the app ships with (`maple_tracker/assets/fonts.json`) from the screenshots in `tests/frames/`
(cropped to the game's UI). Tests that recognise items are skipped until the item data has
been downloaded (start the app once, or run `python -m maple_tracker.itemdata`).
