# docs/media — gameplay media & how it was made

Media used in the main [`README.md`](../../README.md) gallery. Everything here is **self-captured
by the maintainer from a legally-owned copy, to demonstrate the mod** — see the demonstration-media
clause in [`../../DISCLAIMER.md`](../../DISCLAIMER.md). In-game visuals/characters are © their
rights holders and are not under this repo's MIT license.

## Contents
| File | What |
|---|---|
| `gameplay-demo.gif` | ~11 s wild battle: Fight → Thunder Shock → Pidgey faints → "got 14 Exp. Points!" → overworld. 640×360, 12 fps. |
| `screenshots/01-wild-battle.webp` | Turn-based wild battle (Rattata) with the Fight menu. |
| `screenshots/02-wild-faint.webp` | A wild Pokémon fainting. |
| `screenshots/03-native-exp.webp` | Hero shot — "Pikachu got 14 Exp. Points!". |
| `screenshots/04-evolution.webp` | Caterpie evolving (separate progression test). |
| `screenshots/05-overworld.webp` | Return to the overworld after a KO (no catch screen). |
| `screenshots/06-pidgey-battle.webp` | Additional species — wild Pidgey, both HP bars + command menu. |

The original source captures (PNG screenshots, the `.mov` recording) are **not committed** — they
live outside the repo. Everything below regenerates the committed media from those sources.

## Tools
- **ffmpeg** (`brew install ffmpeg`) — crop / scale / frame extraction / GIF palette.
- **cwebp** from libwebp (`brew install webp`) — PNG → WebP (ffmpeg here had no `libwebp` encoder).
- **rsvg-convert** from librsvg (`brew install librsvg`) — banner SVG → PNG.

## Screenshots (crop the 16:9 game content, drop the macOS title bar + black letterbox)
Each capture size has its own crop box; all are scaled to 1280×720 and encoded at WebP q88.

```sh
# Eden window 2528x1768  (01, 02, 03, 05):
ffmpeg -y -i SRC.png -vf "crop=2304:1296:112:224,scale=1280:720" /tmp/f.png && cwebp -q 88 /tmp/f.png -o OUT.webp
# Eden window 3636x2200  (04, 06):
ffmpeg -y -i SRC.png -vf "crop=3408:1917:112:150,scale=1280:720" /tmp/f.png && cwebp -q 88 /tmp/f.png -o OUT.webp
```
Aspect ratio is preserved (~16:9); no stretching or reconstruction. Each output was inspected
visually (title bar/letterbox removed, HUD and dialogue legible).

## Gameplay GIF (from the `.mov` screen recording, 2440×1680 @ 240 fps)
Crop the game content, trim to the ~13 s–24 s payoff window, 12 fps, 640 px wide, palette-optimized:

```sh
REC="Screen Recording ….mov"; CROP="crop=2284:1284:78:189"
ffmpeg -y -ss 13 -t 11 -i "$REC" -vf "$CROP,fps=12,scale=640:-1:flags=lanczos,palettegen=stats_mode=diff" /tmp/pal.png
ffmpeg -y -ss 13 -t 11 -i "$REC" -i /tmp/pal.png \
  -lavfi "$CROP,fps=12,scale=640:-1:flags=lanczos[x];[x][1:v]paletteuse=dither=bayer:bayer_scale=3" gameplay-demo.gif
```
Genuine continuous gameplay (no frames fabricated from stills). Audio dropped. ~4.8 MB.

## Banner (original art, in [`../assets/`](../assets/))
`banner.svg` is the hand-editable source; `banner.png` is its 1240×420 raster:
```sh
rsvg-convert -w 1240 -h 420 ../assets/banner.svg -o ../assets/banner.png
```
