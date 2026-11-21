#!/usr/bin/env python3
"""Time-lapse pictures of the address space: one row per load, a load every ten minutes.

Usage: timelapse.py <output directory>
"""
import random, sys
from m32sim import run, sizes

SPACE = 2000

def mb(pieces): return [(s / 256, n / 256) for s, n, *_ in pieces]

def trace(sizes, fixed, limit=None):
    """One record per load: the pieces of the old and the new object and the single pages, in MB."""
    loads = []
    def rec(n, space, m32, obj, size, old):
        loads.append(dict(n=n, size=size, new=mb(obj[0]), old=mb(old[0][0]) if old else [],
                          pages=sorted(s / 256 for s, l in space.maps.items() if l == 1)))
    done, space, m32, failed = run(SPACE, sizes if limit is None else sizes[:limit], fixed, record=rec)
    fail = None
    if failed:
        size, (part, npages, holes_then, maps_then, partial), old = failed
        hs = sorted((l / 256 for _, l in holes_then), reverse=True)
        fail = dict(n=done + 1, size=size, part=part, want=round(npages / 256), free=round(sum(hs)),
                    biggest=round(hs[0]), new=mb(partial), old=mb(old[0][0]),
                    pages=sorted(s / 256 for s, l in maps_then.items() if l == 1))
    return loads, fail

STYLE = '''<pattern id="tape" width="8" height="8" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
<rect width="8" height="8" fill="#d03b3b"/><rect width="3" height="8" fill="#a62626"/></pattern>
<style>
text { font-family: system-ui, -apple-system, "Segoe UI", "Helvetica Neue", sans-serif; font-size: 12.5px; fill: #52514e; }
.title { font-size: 16px; font-weight: 600; fill: #0b0b0b; }
.ink { fill: #0b0b0b; } .strong { font-weight: 600; }
.end { text-anchor: end; } .mid { text-anchor: middle; }
.free { fill: #f0efec; } .old { fill: #b5d0f5; } .new { fill: #256abf; } .page { fill: #0b0b0b; } .no { fill: url(#tape); }
.tick { stroke: #898781; stroke-width: 1; }
</style>'''

LEFT, WIDTH, ROW, GAP = 58, 470, 8, 2

def tall(o, y, load, label):
    sx = WIDTH / SPACE
    o.append(f'<rect class="free" x="{LEFT}" y="{y:.1f}" width="{WIDTH}" height="{ROW}" rx="2"/>')
    for cls in ('old', 'new'):
        for s, l in load[cls]:
            o.append(f'<rect class="{cls}" x="{LEFT + s * sx + 0.4:.1f}" y="{y:.1f}" width="{max(l * sx - 0.8, 0.8):.1f}" height="{ROW}" rx="1.5"/>')
    seen = set()
    for p in load['pages']:
        x = round(LEFT + p * sx, 1)
        if x in seen: continue
        seen.add(x)
        o.append(f'<rect class="page" x="{x - 1:.1f}" y="{y - 1:.1f}" width="2.2" height="{ROW + 2}"/>')
    if label: o.append(f'<text class="end" x="{LEFT - 8}" y="{y + ROW:.1f}">{label}</text>')
    return y + ROW + GAP

def panel(o, y, name, loads, fail, note):
    o.append(f'<text class="title" x="20" y="{y:.1f}">{name}</text>')
    y += 12
    for r in loads + ([fail] if fail else []):
        label = f"{r['n'] // 6} h" if r['n'] % 6 == 0 else ''
        y = tall(o, y, r, label)
    if fail:
        sx = WIDTH / SPACE
        y += 4
        o.append(f'<rect class="no" x="{LEFT + 0.4}" y="{y:.1f}" width="{fail["want"] * sx - 0.8:.1f}" height="{ROW}" rx="1.5"/>')
        o.append(f'<text x="{LEFT + fail["want"] * sx + 8:.1f}" y="{y + ROW:.1f}">{fail["want"]} MB of code, with no hole to go to</text>')
        y += ROW + 20
        hours = fail['n'] / 6
        when = f"{hours:.0f} hours" if hours >= 2 else f"{fail['n'] * 10} minutes"
        o.append(f'<text class="ink" x="20" y="{y:.1f}"><tspan class="strong">Load {fail["n"]}, after {when}, fails.</tspan> The object is {fail["size"]} MB.</text>')
        y += 17
        o.append(f'<text x="20" y="{y:.1f}">{fail["free"]} MB are free, and the biggest hole is {fail["biggest"]} MB.</text>')
    else:
        y += 14
        o.append(f'<text class="ink" x="20" y="{y:.1f}">{note}</text>')
    return y + 36

def figure(panels, title, desc):
    o = [f'<title id="t">{title}</title>', f'<desc id="d">{desc}</desc>', '<defs>' + STYLE + '</defs>']
    lx, ly = 20, 10
    for cls, label, w in (('new', 'the new object', 110), ('old', 'the old one, still loaded', 162), ('no', 'does not fit', 84)):
        o.append(f'<rect class="{cls}" x="{lx}" y="{ly}" width="14" height="11" rx="2"/>')
        o.append(f'<text x="{lx + 19}" y="{ly + 10}">{label}</text>')
        lx += w + 22
    o.append(f'<rect class="page" x="{lx + 3}" y="{ly - 2}" width="2.2" height="15"/>')
    o.append(f'<text x="{lx + 11}" y="{ly + 10}">a 4 KB page</text>')
    y = 48
    for m in range(0, SPACE + 1, 500):
        x = LEFT + m * WIDTH / SPACE
        cls = ' class="end"' if m == SPACE else (' class="mid"' if m else '')
        o.append(f'<text{cls} x="{x:.1f}" y="{y}">{m} MB</text>' if m else f'<text x="{x:.1f}" y="{y}">0</text>')
    y += 28
    for name, loads, fail, note in panels:
        y = panel(o, y, name, loads, fail, note)
    return f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 560 {y - 22:.0f}" role="img" aria-labelledby="t d">\n' + '\n'.join(o) + '\n</svg>\n'

if __name__ == "__main__":
    out = sys.argv[1]
    # 1. what the fix changed: sizes around 600 MB, no growth
    objects = sizes(random.Random(5), 600, 0, 400)
    before, bfail = trace(objects, False)
    whole, afail = trace(objects, True)
    assert afail is None
    after = whole[:bfail['n']]
    open(f'{out}/pages.svg', 'w').write(figure(
        [('Before the fix', before, bfail, ''),
         ('After the fix', after, None, f'The same objects. These loads succeed, and so do the next {len(whole) - len(after)}.')],
        'What the allocator fix changed',
        f'Two time-lapses of a 2000 MB address space, one row per load, with objects of about 600 MB loaded every ten minutes. Before the fix, single pages are left across the address space and load {bfail["n"]} fails with {bfail["free"]} MB free. After the fix the same loads succeed.'))
    print('before:', {k: v for k, v in bfail.items() if k not in ('new', 'old', 'pages')})
    # 2. even then: fixed allocator, sizes that vary and slowly grow
    objects = sizes(random.Random(5), 680, 0.5, 3000)
    loads, fail = trace(objects, True)
    open(f'{out}/growing.svg', 'w').write(figure(
        [('With the fix, and objects that slowly grow', loads, fail, '')],
        'Swapping in objects that slowly grow',
        f'A time-lapse of a 2000 MB address space with the fixed allocator, one row per load. The objects start at about 680 MB, vary by up to 20 MB and grow by half a megabyte per load. Load {fail["n"]} fails with {fail["free"]} MB free.'))
    print('growing:', {k: v for k, v in fail.items() if k not in ('new', 'old', 'pages')}, 'first sizes', objects[:5])
