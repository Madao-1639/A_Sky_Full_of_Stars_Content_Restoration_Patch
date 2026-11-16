"""核查 CG 画廊 / 成就解锁位点是否被「还原覆盖」丢失（Cross_Channel 同类缺陷的回归闸）。

数据模型（实测，见 doc/file-formats.md「CG 显示的固有 id 对」）：

* 每个画廊 CG 的 `0x34 <slot> 00 <STEM>.PNA 00 01 01` 之后恒跟一对 `0b`：
  `0b <A:u16> 01 0b <B:u16> 01`。A ∈ 1120..1228（CG 组），B ∈ 1250..1659
  （画廊缩略图条目；Steam 版编号）。
* `CG_PAGE.ws2` 用 `0x01 Condition` 读 B（==1.0）决定每个画廊条目是否解锁，
  并与紧随的 `0x1c openCgBrowser <NAME>.PNA` 配对；共 410 条。
* `CG_ACHIEVEMENT.ws2` 顺序读同一批 410 个 B 旗标，把「已解锁条数」累加进旗标 55，
  再按阈值 82/164/246/328/**410** 发放 6 个 CG 成就。

还原把 Steam 的删节段换成原版内容时，原版脚本带的是**原版编号**的 id 对，Steam 那一段的
`0b`（以及 `CG_ACHIEVEMENT` 调用）随之消失 —— 画廊条目永久锁死、最后一个「全 CG」成就
（阈值 410）不可达。这正是 Cross_Channel 补丁踩过的坑：覆盖 Steam 内容时不得丢解锁位点，
且不能因为「同一个旗标别处也置位」就裁掉（会丢解锁时机/路线）。

本闸只读，不改任何文件。检查项：

1. HARD  CG_PAGE 的每个条目旗标都必须在本补丁里有至少一处 `0b` 写入
         （否则该画廊缩略图永远锁着）。
2. HARD  CG_ACHIEVEMENT 的最大阈值（410）必须 <= 本补丁能置位的条目数
         （否则「全 CG」成就不可达）。
3. HARD  每个被替换的 Steam 脚本（`<id>_E` → `<id>`，含 `_H_E` → `_H`）：
         它写过的全部旗标 id（A 与 B）都必须在替代脚本里出现
         （Cross_Channel 的「旗标位点守恒」按脚本粒度；不按全库去重，避免丢路线/时机）。
         该脚本原有 `CG_ACHIEVEMENT` 调用时，替代脚本也至少要有一个。
         注：重放的解锁组是**独立的 `0b A 01 0b B 01`**（不再带 0x34 显示），
         所以这里按旗标 id 比，而不是按「显示位点后的 id 对」比。
4. HARD  `0xf0 <id>` Steam 成就调用守恒：全局每个 id 至少出现一次；每个被替换脚本
         原有的 id 都必须在替代脚本里保留（`0xf0` 是 Steam 专属，原版 0 条，
         `replace`/`delete` 块取原版时会连成就一起丢掉）。
5. HARD  `resource/present-ops.json` 自洽：`counts.orig == 0` 的 opcode 不得标 `use_orig`
         （"取原版"却原版没有 = 必然整类丢失，见 doc/lessons-learned.md「块级取原版会整类删掉
         Steam 专属 opcode」）。
6. WARN  条目只被**其它路线**的脚本置位（Steam 在某路线解锁，本补丁只剩另一路线）
         —— 全局仍可解锁，但该路线玩家看不到对应缩略图。

用法: python script/checks/check_cg_unlock.py
"""
import struct
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
from tool import arcbuild, ws2, ws2disasm                         # noqa: E402

STEAM_RIO = ROOT / 'backup' / 'Rio.arc'
PATCH_RIO = ROOT / 'asset' / 'Rio.arc'

GALLERY_PAGE = 'CG_PAGE.WS2'
ACH_SCRIPT = 'CG_ACHIEVEMENT.WS2'
A_LO, A_HI = 1120, 1228
B_LO, B_HI = 1250, 1659

ROUTES = ('com', 'hika', 'saya', 'ori', 'koro')


def load_scripts(path):
    """{UPPER_NAME: raw}（只要 .WS2）。"""
    out = {}
    for nb, data in arcbuild.read_raw(path):
        name = nb.decode('utf-16le')
        if name.upper().endswith('.WS2'):
            out[name.upper()] = data
    return out


def flag_ids(raw):
    """脚本里所有 `0b <u16> 01` 置位的 id（含独立重放的解锁组）。"""
    out = set()
    for ins in ws2disasm.disassemble(ws2.decode(raw)):
        if ins.opcode == 0x0b and len(ins.operands) >= 3                 and ins.operands[2] == 0x01:
            fid = int.from_bytes(ins.operands[0:2], 'little')
            if A_LO <= fid <= 2300:            # 只看 CG 组 / 画廊条目域
                out.add(fid)
    return out


def achievement_ids(raw):
    """脚本里的 `0xf0 <id>` Steam 成就调用 id（去重、保序）。"""
    out = []
    for ins in ws2disasm.disassemble(ws2.decode(raw)):
        if ins.opcode == 0xf0:
            aid = ins.operands[0]
            if aid not in out:
                out.append(aid)
    return out


def ach_calls(raw):
    data = ws2.decode(raw)
    return data.count(ws2.ACH_CALL)


def flag_writes(scripts):
    """{id: {script}}：全部 `0b <u16> 01` 写入（指令级，非字节搜索）。"""
    out = defaultdict(set)
    for name, raw in scripts.items():
        for ins in ws2disasm.disassemble(ws2.decode(raw)):
            if ins.opcode != 0x0b or len(ins.operands) < 3:
                continue
            if ins.operands[2] != 0x01:            # 只统计「置位」
                continue
            fid = int.from_bytes(ins.operands[0:2], 'little')
            out[fid].add(name)
    return out


def gallery_entries(steam):
    """{B: 缩略图名}：CG_PAGE 的条目表。"""
    ins = ws2disasm.disassemble(ws2.decode(steam[GALLERY_PAGE]))
    pending, out = [], {}
    for i in ins:
        if i.opcode == 0x01:
            ops = i.operands
            fid = int.from_bytes(ops[1:3], 'little')
            val = struct.unpack('<f', ops[3:7])[0]
            if val == 1.0 and B_LO <= fid <= B_HI:
                pending.append(fid)
        elif (i.opcode == 0x1c
              and i.operands.startswith(b'openCgBrowser\x00')):
            if pending:
                out[pending[-1]] = i.operands.split(b'\x00')[1].decode('ascii')
    return out


def ach_thresholds(steam):
    """CG_ACHIEVEMENT 里对计数旗标（55）的阈值（>=2 的那些）。"""
    ins = ws2disasm.disassemble(ws2.decode(steam[ACH_SCRIPT]))
    out = []
    for i in ins:
        if i.opcode != 0x01:
            continue
        ops = i.operands
        fid = int.from_bytes(ops[1:3], 'little')
        val = struct.unpack('<f', ops[3:7])[0]
        if fid == 55 and val >= 2.0:
            out.append(val)
    return out


def route(script):
    low = script.lower()
    for r in ROUTES:
        if low.startswith('yozora_%s_' % r):
            return r
    return 'sys'


def replacement_of(steam_name):
    """`..._E.WS2` → `....WS2`；`..._H_E.WS2` → `..._H.WS2`。"""
    base = steam_name[:-4]                         # 去掉 .WS2
    if not base.endswith('_E'):
        return None
    return base[:-2] + '.WS2'


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    steam = load_scripts(STEAM_RIO)
    patch = load_scripts(PATCH_RIO)

    entries = gallery_entries(steam)
    thresholds = ach_thresholds(steam)
    writes_s = flag_writes(steam)
    writes_p = flag_writes(patch)

    fails = []
    warns = []

    # ---- 1. 每个画廊条目都必须能置位 -------------------------------------
    locked = [b for b in sorted(entries) if b not in writes_p]
    print('画廊条目 %d 个（B=%d..%d）；本补丁从未写入的 %d 个'
          % (len(entries), B_LO, B_HI, len(locked)))
    for b in locked:
        print('  [FAIL] B=%-5d %-14s  永不解锁（Steam 写入者: %s）'
              % (b, entries[b], sorted(writes_s[b])))
        fails.append('B=%d 永不置位' % b)

    # ---- 2. 「全 CG」成就阈值必须可达 -----------------------------------
    reachable = sum(1 for b in entries if b in writes_p)
    if thresholds:
        top = max(thresholds)
        print('成就计数阈值 %s；当前可置位条目 %d/%d'
              % ('/'.join('%g' % t for t in thresholds), reachable, len(entries)))
        if top > reachable:
            print('  [FAIL] 最高阈值 %g > 可置位 %d —— 「全 CG」成就不可达'
                  % (top, reachable))
            fails.append('成就阈值 %g 不可达' % top)

    # ---- 3. 被替换的 Steam 脚本：distinct id 对必须保住 -----------------
    print('\n被替换脚本的解锁位点守恒（脚本粒度）：')
    checked = 0
    for sname in sorted(steam):
        rname = replacement_of(sname)
        if rname is None or rname not in patch:
            continue
        checked += 1
        lost = sorted(flag_ids(steam[sname]) - flag_ids(patch[rname]))
        sc, pc = ach_calls(steam[sname]), ach_calls(patch[rname])
        bad = []
        if lost:
            bad.append('丢 %d 个旗标: %s' % (len(lost), lost))
            fails.append('%s 丢 %d 个旗标' % (sname, len(lost)))
        if sc and not pc:
            bad.append('CG_ACHIEVEMENT 调用 %d → 0' % sc)
            fails.append('%s 丢成就调用' % sname)
        if bad:
            print('  [FAIL] %-30s -> %-26s %s'
                  % (sname, rname, '；'.join(bad)))
    print('  共核对 %d 个被替换脚本' % checked)

    # ---- 4. 0xf0 成就调用守恒 -------------------------------------------
    print('\n0xf0 成就调用守恒：')
    f0_s = {x for raw in steam.values() for x in achievement_ids(raw)}
    f0_p = {x for raw in patch.values() for x in achievement_ids(raw)}
    print('  Steam 成就 id %s' % sorted(f0_s))
    print('  补丁成就 id   %s' % sorted(f0_p))
    lost_global = sorted(f0_s - f0_p)
    if lost_global:
        print('  [FAIL] 全库丢失成就 id %s' % lost_global)
        fails.extend('成就 id %d 全库丢失' % x for x in lost_global)
    for sname in sorted(steam):
        rname = replacement_of(sname)
        if rname is None or rname not in patch:
            continue
        want = achievement_ids(steam[sname])
        have = set(achievement_ids(patch[rname]))
        miss = [x for x in want if x not in have]
        if miss:
            print('  [FAIL] %-30s -> %-26s 丢 0xf0 %s'
                  % (sname, rname, miss))
            fails.append('%s 丢成就 %s' % (sname, miss))
    if not lost_global:
        print('  （全局无丢失）')

    # ---- 5. present-ops.json 自洽 ----------------------------------------
    print('\npresent-ops 策略自洽（orig==0 的 opcode 不得 use_orig）：')
    from tool import resources
    hazard = [o for o in resources.load('present-ops.json')['ops']
              if o['policy'] == 'use_orig'
              and o['counts'].get('orig', 0) == 0 and o['counts'].get('backup', 0) > 0]
    if hazard:
        for o in hazard:
            print('  [FAIL] %s %-18s counts=%s —— 取原版必丢整类'
                  % (o['opcode'], o['name'], o['counts']))
            fails.append('%s 策略与语料矛盾' % o['opcode'])
    else:
        print('  （无矛盾项）')

    # ---- 6. WARN：只剩其它路线置位 --------------------------------------
    print('\n路线错位（Steam 在某路线解锁，补丁只剩其它路线）：')
    nwarn = 0
    for b in sorted(entries):
        if b not in writes_p:
            continue
        rs = {route(n) for n in writes_s[b]} - {'sys'}
        rp = {route(n) for n in writes_p[b]} - {'sys'}
        if rs and rp and not (rs & rp):
            nwarn += 1
            print('  [WARN] B=%-5d %-14s Steam %s -> 补丁 %s'
                  % (b, entries[b], sorted(rs), sorted(rp)))
            warns.append('B=%d 路线错位' % b)
    if not nwarn:
        print('  （无）')

    # ---- 信息：原版编号的 id 对（无画廊条目） ---------------------------
    extra = sorted(b for b in writes_p if b > B_HI)
    print('\n补丁写入但 CG_PAGE 无条目的 B（原版编号 >%d，缩略图不显示）：%d 个'
          '（%s..%s）' % (B_HI, len(extra),
                          min(extra) if extra else '-',
                          max(extra) if extra else '-'))

    print('\n结论：FAIL %d 项，WARN %d 项' % (len(fails), len(warns)))
    if fails:
        print('（修复方向见 doc/lessons-learned.md「CG 解锁位点被还原覆盖丢失」）')
    return 1 if fails else 0


if __name__ == '__main__':
    sys.exit(main())
