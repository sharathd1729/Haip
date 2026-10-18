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
