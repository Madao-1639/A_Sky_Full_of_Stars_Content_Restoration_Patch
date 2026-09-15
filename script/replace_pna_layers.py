#!/usr/bin/env python3
"""Replace Steam-censored layers inside asset/Chip3.arc's COM_04*/COM_05* PNA
members with the restored Miazora versions.

Two kinds of layers are patched, both read from resource/layer-repairs.json:

1. Full-canvas frames (layer_id=1), sourced from the Miazora archive. The box is
   already (0, 0, canvas_w, canvas_h) on both sides, so only the embedded PNG
   bytes change.

2. Local talk-animation frames, replaced one-for-one along the
   (steam_lid, miazora_lid) map. This includes groups whose bytes were already
   close to Miazora's OWN local frame -- a small diff only shows Steam left the
   group alone, not that it matches the new full-canvas frame. In-game testing
   showed those still didn't blend, so they are replaced too.

Layers with no Miazora counterpart (COM_04's lid=2 blink variant, and the
lid=29..40 frames that pair with it) are intentionally never touched.

Idempotent: skips any layer whose embedded PNG already matches the source
bytes. Re-reads the written archive to confirm every swap took effect.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from tool import arcbuild, pna, resources

REPAIRS = resources.load('layer-repairs.json')

ARC_PATH = Path(REPAIRS['target_archive'])
MIA_ARC_PATH = Path(REPAIRS['source_archive'])

FULL_CANVAS_LID = REPAIRS['full_canvas']['layer_id']

FULL_CANVAS_TARGETS = REPAIRS['full_canvas']['members']

# (pna_member, [(steam_lid, mia_lid), ...])
LOCAL_FRAME_TARGETS = [(entry['member'], entry['layers'])
                       for entry in REPAIRS['local_frames']]


def patch_full_canvas(members, by_name, mia_members):
    changed = False
    for member_name in FULL_CANVAS_TARGETS:
        idx = by_name[member_name]
        name_bytes, data = members[idx]
        p = pna.load(data)
        pm = pna.load(mia_members[member_name])
        entry_idx = pna.find_by_layer_id(p, FULL_CANVAS_LID)
        mia_entry_idx = pna.find_by_layer_id(pm, FULL_CANVAS_LID)
        box = pna.get_box(p, entry_idx)
        expect_box = (0, 0, p['canvas_w'], p['canvas_h'])
        if box != expect_box:
            raise SystemExit('%s lid=%d box %r is not full-canvas %r, refusing' %
                              (member_name, FULL_CANVAS_LID, box, expect_box))

        new_png = pm['images'][mia_entry_idx]
        if p['images'][entry_idx] == new_png:
            print('[skip] %s #%d already matches Miazora' % (member_name, FULL_CANVAS_LID))
            continue

        pna.replace_layer(p, FULL_CANVAS_LID, new_png, expect_box)
        members[idx] = (name_bytes, pna.dump(p))
        changed = True
        print('[patch] %s #%d <- Miazora (box=%r, %d bytes)' %
              (member_name, FULL_CANVAS_LID, expect_box, len(new_png)))
    return changed


def patch_local_frames(members, by_name, mia_members):
    changed = False
    for member_name, lid_pairs in LOCAL_FRAME_TARGETS:
        idx = by_name[member_name]
        name_bytes, data = members[idx]
        p = pna.load(data)
        pm = pna.load(mia_members[member_name])

        for steam_lid, mia_lid in lid_pairs:
            entry_idx = pna.find_by_layer_id(p, steam_lid)
            mia_entry_idx = pna.find_by_layer_id(pm, mia_lid)
            box = pna.get_box(p, entry_idx)
            mia_box = pna.get_box(pm, mia_entry_idx)
            if box != mia_box:
                raise SystemExit('%s steam_lid=%d box %r != mia_lid=%d box %r, refusing' %
                                  (member_name, steam_lid, box, mia_lid, mia_box))

            new_png = pm['images'][mia_entry_idx]
            if p['images'][entry_idx] == new_png:
                print('[skip] %s #%d already matches Miazora lid=%d' %
                      (member_name, steam_lid, mia_lid))
                continue

            pna.replace_layer(p, steam_lid, new_png, box)
            changed = True
            print('[patch] %s #%d <- Miazora #%d (box=%r, %d bytes)' %
                  (member_name, steam_lid, mia_lid, box, len(new_png)))

        members[idx] = (name_bytes, pna.dump(p))
    return changed


def verify_full_canvas(reloaded, mia_members):
    for member_name in FULL_CANVAS_TARGETS:
        p = pna.load(reloaded[member_name])
        pm = pna.load(mia_members[member_name])
        idx = pna.find_by_layer_id(p, FULL_CANVAS_LID)
        mia_idx = pna.find_by_layer_id(pm, FULL_CANVAS_LID)
        expect = pm['images'][mia_idx]
        got = p['images'][idx]
        box = pna.get_box(p, idx)
        assert got == expect, 'readback mismatch for %s #%d' % (member_name, FULL_CANVAS_LID)
        assert box == (0, 0, p['canvas_w'], p['canvas_h']), \
            'readback box mismatch for %s #%d: %r' % (member_name, FULL_CANVAS_LID, box)
        print('[verify] %s #%d readback OK (box=%r)' % (member_name, FULL_CANVAS_LID, box))


def verify_local_frames(reloaded, mia_members):
    for member_name, lid_pairs in LOCAL_FRAME_TARGETS:
        p = pna.load(reloaded[member_name])
        pm = pna.load(mia_members[member_name])
        for steam_lid, mia_lid in lid_pairs:
            idx = pna.find_by_layer_id(p, steam_lid)
            mia_idx = pna.find_by_layer_id(pm, mia_lid)
            got = p['images'][idx]
            expect = pm['images'][mia_idx]
            assert got == expect, 'readback mismatch for %s #%d' % (member_name, steam_lid)
        print('[verify] %s local frames (%d) readback OK' % (member_name, len(lid_pairs)))


def main():
    members = arcbuild.read_raw(ARC_PATH)
    by_name = {name.decode('utf-16le'): i for i, (name, _data) in enumerate(members)}
    all_members = set(FULL_CANVAS_TARGETS) | {m for m, _ in LOCAL_FRAME_TARGETS}
    for member_name in all_members:
        if member_name not in by_name:
            raise SystemExit('member %s not found in %s' % (member_name, ARC_PATH))

    mia_members = {name.decode('utf-16le'): data for name, data in arcbuild.read_raw(MIA_ARC_PATH)}
    for member_name in all_members:
        if member_name not in mia_members:
            raise SystemExit('member %s not found in %s' % (member_name, MIA_ARC_PATH))

    changed = patch_full_canvas(members, by_name, mia_members)
    changed = patch_local_frames(members, by_name, mia_members) or changed

    if not changed:
        print('nothing to do, Chip3.arc already up to date')
        return

    arcbuild.write_arc(members, ARC_PATH)
    arcbuild.verify(ARC_PATH, expect_count=len(members))
    print('[ok] wrote and verified %s (%d members)' % (ARC_PATH, len(members)))

    reloaded = {name.decode('utf-16le'): data for name, data in arcbuild.read_raw(ARC_PATH)}
    verify_full_canvas(reloaded, mia_members)
    verify_local_frames(reloaded, mia_members)


if __name__ == '__main__':
    main()
