#!/usr/bin/env python3
"""Batch-generate per-word MP3 audio with Microsoft neural voices (edge-tts).

Output: words/audio/<month>/<slug>.mp3  (slug = lowercase word, non-alnum runs -> '-')

Usage:
  python3 scripts/gen_audio.py [--voice en-US-AriaNeural] [--workers 6] [--month 2026-10]

- Re-runnable: existing files larger than 500 bytes are skipped.
- Requires: pip install edge-tts pyyaml
- External access: speech.platform.bing.com (Microsoft speech service) only.
"""
import argparse
import asyncio
import re
import sys
from pathlib import Path

import yaml
from edge_tts import Communicate

REPO = Path(__file__).resolve().parent.parent


def slugify(text: str) -> str:
    s = re.sub(r'[^a-z0-9]+', '-', text.lower()).strip('-')
    return s or 'word'


def words_for(path: Path):
    data = yaml.safe_load(path.read_text(encoding='utf-8')) or []
    out = []
    for w in data:
        if isinstance(w, dict) and isinstance(w.get('en'), str):
            out.append(w['en'])
    return out


async def gen_one(word, dest: Path, voice: str, sem: asyncio.Semaphore) -> str:
    if dest.exists() and dest.stat().st_size > 500:
        return 'skip'
    for attempt in range(3):
        try:
            async with sem:
                comm = Communicate(word, voice)
                tmp = dest.with_suffix('.mp3.part')
                with open(tmp, 'wb') as f:
                    async for chunk in comm.stream():
                        if chunk.get('type') == 'audio':
                            f.write(chunk['data'])
                if tmp.stat().st_size > 500:
                    tmp.rename(dest)
                    return 'ok'
                tmp.unlink(missing_ok=True)
        except Exception:
            pass
        await asyncio.sleep(1 + attempt)
    return 'fail'


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--voice', default='en-US-AriaNeural')
    ap.add_argument('--workers', type=int, default=6)
    ap.add_argument('--month', action='append', help='restrict to one or more months')
    args = ap.parse_args()

    months_dir = REPO / 'words'
    months = args.month or sorted(p.stem for p in months_dir.glob('*.yaml'))
    sem = asyncio.Semaphore(max(1, args.workers))

    total_new = total_skip = total_fail = 0
    fails = []
    for month in months:
        yf = months_dir / f'{month}.yaml'
        if not yf.exists():
            print(f'{month}: no yaml file, skipped', flush=True)
            continue
        words = words_for(yf)
        outdir = months_dir / 'audio' / month
        outdir.mkdir(parents=True, exist_ok=True)
        results = await asyncio.gather(*(
            gen_one(w, outdir / (slugify(w) + '.mp3'), args.voice, sem) for w in words
        ))
        new = results.count('ok')
        skip = results.count('skip')
        fail = len(results) - new - skip
        total_new += new
        total_skip += skip
        total_fail += fail
        fails.extend(f'{month}/{w}' for w, r in zip(words, results) if r == 'fail')
        print(f'{month}: total={len(words)} new={new} cached={skip} failed={fail}', flush=True)

    if fails:
        print('FAILED:')
        for f in fails:
            print('  ' + f)
        return 1
    print(f'DONE new={total_new} cached={total_skip} failed={total_fail} voice={args.voice}')
    return 0


if __name__ == '__main__':
    sys.exit(asyncio.run(main()))
