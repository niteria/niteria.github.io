#!/usr/bin/env python3
"""GHC's linker loading and unloading objects in the low address space.

A model of rts/Linker.c from March 2016: the m32 allocator before and after
commit 82e36edc ("Reduce fragmentation from m32_allocator"), driven by the
hot-swapping pattern: load the new object, then unload the previous one.
Addresses are in pages of 4 KB. A mapping goes to the lowest address where it
fits, which is what the kernel's bottom-up search does.
"""
import random

PAGE = 4096
M32_MAX_PAGES = 32
REFCOUNT_BYTES = 8

class Space:
    def __init__(self, pages):
        self.pages = pages
        self.maps = {}                       # start -> length, in pages
    def holes(self):
        out, at = [], 0
        for start in sorted(self.maps):
            if start > at: out.append((at, start - at))
            at = start + self.maps[start]
        if at < self.pages: out.append((at, self.pages - at))
        return out
    def mmap(self, npages):
        for start, length in self.holes():
            if length >= npages:
                self.maps[start] = npages
                return start
        return None
    def munmap(self, start, npages):
        length = self.maps.pop(start)
        assert length >= npages
        if length > npages:                  # unmapping the front of a mapping
            self.maps[start + npages] = length - npages

def round_up(x, a): return (x + a - 1) // a * a

class M32:
    """m32_alloc and m32_free, as in rts/Linker.c. `fixed` selects the version."""
    def __init__(self, space, fixed):
        self.space, self.fixed = space, fixed
        self.base = [None] * M32_MAX_PAGES   # page address of each filling page
        self.size = [0] * M32_MAX_PAGES      # bytes already reserved in it
        self.refs = {}                       # page address -> reference count
        if fixed:                            # preallocate the filling area
            chunk = space.mmap(M32_MAX_PAGES)
            for i in range(M32_MAX_PAGES):
                self.base[i], self.size[i] = chunk + i, REFCOUNT_BYTES
                self.refs[chunk + i] = 1
                if i: space.maps[chunk + i] = 1   # so pages can be unmapped one by one
            space.maps[chunk] = 1
    def _unref(self, page):
        self.refs[page] -= 1
        if self.refs[page] == 0:
            del self.refs[page]
            self.space.munmap(page, 1)
    def free(self, page):
        self._unref(page)
    def alloc(self, size, alignment=8):
        empty, most_filled = -1, -1
        for i in range(M32_MAX_PAGES):
            if self.base[i] is None:
                if empty == -1: empty = i
                continue
            if self.fixed and self.refs[self.base[i]] == 1:
                self.size[i] = REFCOUNT_BYTES          # nobody else uses it: reuse it
            alsize = round_up(self.size[i], alignment)
            if size <= PAGE - alsize:
                self.size[i] = alsize + size
                self.refs[self.base[i]] += 1
                return self.base[i]
            if most_filled == -1 or self.size[most_filled] < self.size[i]:
                most_filled = i
        if empty == -1:                                # flush the most filled page
            self._unref(self.base[most_filled])
            self.base[most_filled], self.size[most_filled] = None, 0
            empty = most_filled
        page = self.space.mmap(1)
        if page is None: return None
        self.base[empty] = page
        self.size[empty] = size + round_up(REFCOUNT_BYTES, alignment)
        self.refs[page] = 2
        return page

# What one object file turns into, as fractions of its size. The symbol extras
# table (16 bytes per symbol) is allocated first, through the allocator's path
# for large requests; then every large section is mapped on its own.
PARTS = (("symbol extras", 0.04), (".text", 0.56), (".rodata", 0.12), (".data", 0.28))
SMALL = (900, 700, 1100)                     # its small sections, in bytes

def load(space, m32, mb, parts=PARTS, small=SMALL):
    """Map one object. Returns its mappings and small-section pages, or None."""
    maps = []
    for name, fraction in parts:
        npages = max(1, round(mb * fraction * 256))
        start = space.mmap(npages)
        if start is None:
            snapshot = (name, npages, space.holes(), dict(space.maps), list(maps))
            for s, n, _ in maps: space.munmap(s, n)
            return None, snapshot
        maps.append((start, npages, name))
    return (maps, [m32.alloc(s) for s in small]), None

def unload(space, m32, obj):
    maps, pages = obj
    for p in pages: m32.free(p)
    for start, npages, _ in maps: space.munmap(start, npages)

def run(space_mb, sizes_mb, fixed, parts=PARTS, small=SMALL, record=None):
    """Swap in objects of the given sizes: load the new one, then unload the old one.
    Returns (objects loaded, space, m32, None or (size, part that did not fit, old object))."""
    space = Space(space_mb * 256)
    m32 = M32(space, fixed)
    old = None
    for n, mb in enumerate(sizes_mb, 1):
        obj, failed_part = load(space, m32, mb, parts, small)
        if obj is None:
            return n - 1, space, m32, (mb, failed_part, old)
        if record: record(n, space, m32, obj, mb, old)
        if old: unload(space, m32, old[0])
        old = (obj, mb)
    return len(sizes_mb), space, m32, None

def sizes(rng, start, growth, n):
    """n object sizes in MB: start, plus growth per load, give or take 20."""
    return [round(start + growth * k + rng.uniform(-20, 20)) for k in range(n)]

def run_holding(space_mb, sizes_mb, fixed, chance, rng):
    """Like run, but with the given chance the old object stays for one more load,
    so that three objects are loaded for a moment. Returns the load that failed, or None."""
    space = Space(space_mb * 256)
    m32 = M32(space, fixed)
    live = []                                # oldest first
    for n, mb in enumerate(sizes_mb, 1):
        obj, _ = load(space, m32, mb)
        if obj is None: return n
        live.append(obj)
        hold = len(live) == 2 and rng.random() < chance
        while len(live) > (2 if hold else 1): unload(space, m32, live.pop(0))
    return None

if __name__ == "__main__":
    # The runs quoted in the post. A load every ten minutes: 6 loads an hour, 144 a day.
    SPACE, SEEDS = 2000, range(1, 13)

    print("About 600 MB, no growth, 400 loads, 12 runs")
    for fixed in (False, True):
        failed = []
        for seed in SEEDS:
            done, _, _, fail = run(SPACE, sizes(random.Random(seed), 600, 0, 400), fixed)
            if fail: failed.append(done + 1)
        line = f"  {'after ' if fixed else 'before'} the fix: {len(failed)} runs had a load that failed"
        if failed:
            line += f", at loads {sorted(failed)}, after {min(failed) / 6:.1f} to {max(failed) / 6:.1f} hours"
        print(line)

    print("About 680 MB, growing by 0.5 MB per load, after the fix, 12 runs")
    failed = []
    for seed in SEEDS:
        done, _, _, fail = run(SPACE, sizes(random.Random(seed), 680, 0.5, 3000), True)
        failed.append((done + 1, fail[0]))
    loads, mbs = [n for n, _ in failed], [mb for _, mb in failed]
    print(f"  first load that failed: {sorted(loads)}, after {min(loads) / 6:.1f} to {max(loads) / 6:.1f} hours,"
          f" with objects of {min(mbs)} to {max(mbs)} MB")

    print("About 600 MB, growing by 0.5 MB per load, after the fix, 12 runs")
    for chance, name in ((0, "never more than two objects"), (0.1, "a third object, one load in ten")):
        failed = []
        for seed in SEEDS:
            failed.append(run_holding(SPACE, sizes(random.Random(seed), 600, 0.5, 3000), True,
                                      chance, random.Random(1000 + seed)))
        print(f"  {name}: first load that failed {sorted(failed)},"
              f" after {min(failed) / 144:.1f} to {max(failed) / 144:.1f} days")
