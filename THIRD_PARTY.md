# Third-party assets

## Lucide interface icons

Source: https://icon-sets.iconify.design/lucide/

API data: `Lib/vendor/lucide/icons.json`. SVG bodies are copied without hand-edited paths into `ui/icons.js`.

Author: Lucide Contributors. License: ISC, with upstream notices retained in `Lib/vendor/lucide/LICENSE`.

## Pantheon assets and macro base

Original macro images and helmet icon are from `ThicoModee/Pantheon-Public`, base commit `fd1d46ea0ae812468ef7cbceb40fc8b0bc0a58d3`. Macro images are byte-identical copies; the helmet PNG is a format conversion of the original ICO.

The outdated macro scripts have been removed.

## FindText matching algorithm

`pantheon/native/findtext.c` reimplements the grayscale-threshold search from FindText by FeiYue (https://www.autohotkey.com/boards/viewtopic.php?f=83&t=116471, version 9.9) so that patterns captured with upstream Pantheon remain compatible. No AutoHotkey source is included.

## Bundled in the Flatpak

- grim 1.5.0, MIT, https://gitlab.freedesktop.org/emersion/grim
- Tesseract 5.5.1, Apache-2.0, https://github.com/tesseract-ocr/tesseract
- Leptonica 1.85.0, BSD-2-Clause, https://github.com/DanBloomberg/leptonica
- tessdata_fast `eng` 4.1.0, Apache-2.0, https://github.com/tesseract-ocr/tessdata_fast

UI reference: [LeniLilac/expeditions-macro](https://github.com/LeniLilac/expeditions-macro). The hub independently implements the screenshot placement workflow and layout; no source code or media from that repository is included.
