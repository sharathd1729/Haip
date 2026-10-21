# Third-party notices — Marketing Studio

## Ootto-AI/claude-content-skills

Source: https://github.com/Ootto-AI/claude-content-skills (read 18 Oct 2026).

Marketing Studio's `marketing-*-v2` prompts (`backend/app/services/marketing_prompts.py`) adapt techniques from these skills:
- `content-audit`: judge against the account's own median; STOP / KEEP / TEST lists; say "not enough signal" instead of guessing.
- `caption-and-hashtags`: strong first line; a first comment carrying a question.
- `carousel-builder`: a short slide 1; one idea per slide; a single ask on the last slide.
- `story-sequencer`: 5-7 frames, at most one interaction, one ask per sequence.
- `content-pillar-builder`: 3-5 pillars, a rotation, and an explicit out-of-scope list.

The wording in HAIP is rewritten for hospitality and for HAIP's rules on prices and grounding; no skill file is copied verbatim.
The upstream licence is reproduced below as a courtesy.

```
MIT License

Copyright (c) 2026 Ootto

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## coreyhaines31/marketingskills

Source: https://github.com/coreyhaines31/marketingskills (read 21 Oct 2026, commit e85f3cbc).

Agency M1 adapts techniques from these skills:
- In the deterministic checks (`backend/app/services/marketing_lint.py`):
  - `social`: the "AI tells" to avoid (contrast reveals, one sentence per line, engagement bait, emoji bullets, stock phrases) and the carousel rules (a count promised on the cover is delivered; one ask on the last slide; the caption has its own hook).
  - `copy-editing`: write `[NEED: ...]` instead of inventing a missing fact. Its edit modes credit Profound and Wispr Flow upstream.
- In `marketing-content-v4` (`backend/app/services/marketing_prompts.py`): the carousel frameworks (`social`).
- In `ad-creative`: grounding claims in evidence.

The rules are rewritten for Instagram hospitality content and for HAIP's price and grounding rules; no skill file is copied verbatim. The upstream licence is reproduced below as a courtesy.

```
MIT License

Copyright (c) 2025 Corey Haines

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
SOFTWARE.
```

## anthropics/knowledge-work-plugins (marketing plugin)

Source: https://github.com/anthropics/knowledge-work-plugins/tree/main/marketing (read 21 Oct 2026, commit bc8f6922). Licence: Apache License 2.0 (https://www.apache.org/licenses/LICENSE-2.0). The repository has no NOTICE file.

Agency M1 adapts ideas from its `brand-review` skill:
- the brand voice as "We are / We are not / Sounds like / Doesn't sound like", with tone varying by channel (`BusinessProfile.voice` and `channel_tone` in `backend/app/schemas/marketing.py`);
- review findings with a location, a severity and a suggested fix;
- compliance flags: unproven superlatives, guarantees, competitor mentions and unattributed testimonials.

These appear in `marketing_review_service.py`, `marketing_lint.py` and `marketing-review-v1`. Nothing is copied verbatim; the ideas are re-expressed for HAIP.

## Noto Sans / Noto Serif (brand-kit typefaces, agency M3)

Installed from the Debian package `fonts-noto-core` in `backend/Dockerfile`; not copied into this repository. Licence: SIL Open Font License 1.1 (https://openfontlicense.org). `marketing_render.py` and `marketing_reel.py` draw text with them onto images and videos the workspace posts; the OFL allows that, and the fonts themselves are not redistributed.

## FFmpeg (reels, agency M3)

Installed from the Debian package `ffmpeg` in `backend/Dockerfile` and called as a separate program (`marketing_reel.py`); not linked or redistributed by HAIP. Licence: LGPL 2.1+ / GPL depending on the build (https://ffmpeg.org/legal.html). Reels use only the workspace's own clips and photos; no music or sound is added.
