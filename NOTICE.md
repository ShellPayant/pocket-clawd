# Third-party material

Pocket Clawd itself is MIT licensed — see [LICENSE](LICENSE). One part of it
isn't mine.

## The pets in the fish tank

The little Clawds that wander around the aquarium, one per active Claude Code
session, come from **[clawd-pet](https://github.com/abderrahimghazali/clawd-pet)**
by **[@abderrahimghazali](https://github.com/abderrahimghazali)** — a collection
of 90-odd animated pixel-art Clawd SVGs, MIT licensed.

* The original SVGs are in [`assets/pets-svg/`](assets/pets-svg/), unmodified,
  alongside the author's own [`LICENSE`](assets/pets-svg/LICENSE).
* The files in `device/pets/` are **derived from those SVGs** — rendered to
  fixed-size BGRA sprites by [`tools/bake_pets.py`](tools/bake_pets.py), because
  the console has no SVG renderer. The same MIT licence covers them.

21 of them are bundled, and they map to what's happening:

| Pet | When you see it |
|---|---|
| `happy`, `working-thinking`, `mindblown` | An aquarium friend's mood, by pose |
| `sleeping` | A friend dozing, and Clawd himself when data stops arriving |
| `celebrating`, `waving`, `dancing` | Reactions to fresh data and button presses |
| `429` | Anthropic is rate-limiting the usage endpoint |
| `401` | Your credentials were rejected |
| `disconnected` | No data has ever arrived |
| `astronaut`, `pirate`, `ninja`, `yoga`, `surfing`, `coding`, `gaming`, `cool`, `love`, `shrug`, `static-base` | The pose pool that session friends are picked from |

Upstream has well over a hundred more. Dropping one into `assets/pets-svg/` and
re-running the baker is all it takes to add it.

**If you fork this and keep the pets, keep this file and
`assets/pets-svg/LICENSE` with them.** The artwork is that author's work, not
mine.

## What's mine

Everything else: the dashboard, the meters, the trend chart, the aquarium, the
network daemon, the pushers, the installer, and the big crab — which is drawn
in code, pixel by pixel, in `clawd.py`. The bitmap font is hand-built in the
same file. The anthem is synthesised from arithmetic by
[`tools/bake_chiptune.py`](tools/bake_chiptune.py).

## Not affiliated

Not affiliated with, endorsed by, or connected to Anthropic. "Claude" and the
Clawd mascot are theirs. This reads your own usage numbers, with your own
credentials, and draws a crab about it.
