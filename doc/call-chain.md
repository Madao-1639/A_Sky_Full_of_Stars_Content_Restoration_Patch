# 调用链组织

## 脚本类型分层

### 命名空间隔离方案

| 脚本类型 | 配对资源 | 用途 |
| :--- | :--- | :--- |
| *_E.ws2 | Steam 资源（裸名 PNA） | Steam 版剧情 |
| *_H.ws2 | 原版资源（ORG_ 前缀或 9X 段位） | 原版 H 场景 |
| *_H_E.ws2 | Steam 资源 | Steam 过审 H 场景 |

**PNA 资源类型**：
- **事件 CG**：`路线代码_场景编号[L/S].pna`（如 `COM_04L.pna`, `COM_90L.pna`）
- **角色立绘**：`[字母前缀]+角色日文名_差分编号[L/M/S/W/X].pna`（如 `Bさや_01L.pna`）

### 脚本数量统计（Rio.arc）

| 后缀 | 来源 | 资源配对 | 数量 |
| :--- | :--- | :--- | :--- |
| _E | Steam | 裸名 PNA | 277 |
| _H | Miazora 原版 | ORG_ PNA | 14+ |
| _H_E | Steam 过审 H | 裸名 PNA | 3 |
| 裸名 | 引擎/系统 | - | 75 |

## H 场景连续性维护

### 穿插式调用链原理

以 saya_107 为例（纱夜路线第 107 段）：

```
107b_H  →  107c_E  →  107d_H  →  107e_E
   ↓         ↓         ↓         ↓
ORG_*   Steam*    ORG_*   Steam*
```

- **107b_H**：原版 H 前半（引用 `SAY_20L/S`、`SAY_21L/S`，裸名，Steam/原版内容一致无冲突）
- **107c_E**：Steam 改写版过渡（台词被重写，引用 Steam 资源）
- **107d_H**：原版 H 后半（引用 `SAY_22L/S`、`SAY_23L/S`，裸名，同样无冲突）
- **107e_E**：Steam 版结尾

**注**：saya_107 系列不涉及 ORG_ 前缀或 9X 段位隔离——引用的 SAY_20~23 系列资源在
Steam 与 Miazora 中内容完全相同（已用 SHA256 核实），不存在同名冲突。

### 为什么要穿插？

Steam 删除了部分 H 场景但保留了前后文，必须在 Steam 段落间插入原版 H 段落，形成完整剧情。

### 演变过程

**Steam 删除前（Miazora 原版）**：
```
107 → 107a → 107b → 107c → 107d → 107e
```

**Steam 审核后（删除 107b/c/d 核心 H 内容）**：
```
107_E → 107a_E → ❌ → ❌ → ❌ → 107e_E
                  ↓直接跳到
```

**补丁还原后（Steam + 原版混合）**：
```
107_E → 107a_E → 107b_H → 107c_E → 107d_H → 107e_E
   │        │        │        │        │        │
Steam   Steam    原版H    Steam    原版H    Steam
资源     资源    裸名SAY   资源    裸名SAY   资源
```

## 跳转改写范围

| 改写位置 | 原始跳转 | 修改后跳转 | 用途 |
| :--- | :--- | :--- | :--- |
| Steam 入口脚本 | 107A_E → 107E_E | 107A_E → 107B_H | 接入 H 场景 |
| 原版 H 脚本 | 107B → 107C | 107B_H → 107C_E | 续接 Steam 过渡 |
| 原版 H 脚本 | 107D → 107E | 107D_H → 107E_E | 汇合 Steam 结尾 |
| _H 内部资源引用（hika_103） | COM_04L.PNA | COM_90L.PNA | 命名空间隔离（9X 段位） |

**改写统计**：共 129 处资源引用改写（历史记录，含 hika_103 的 COM_04L→9X 段位改写，
以及多个 _H 脚本的立绘 ORG_ 前缀改写；saya_107 系列不在此列，因其引用的 SAY_20~23
资源本身无冲突，未被改写）

## 完整性检查策略

### 基本方针

1. **待插入原版脚本必须可达**：插入位置的前一节点必须指向移植部分的开头
2. **插入部分结束后正常汇合**：除非剧情结束，移植部分的结尾必须指向汇合剧情的 Steam 版脚本
   - 可通过命名中的 `{数字}{字母}` 的顺序来简单确认汇合处是否过早

### 检查跳转目标存在性

```python
# 检查跳转目标存在性
for caller, opcode, target in call_chain:
    pattern = opcode.encode() + target.encode('ascii') + b'\x00'
    if pattern not in ws2.decode(caller_data):
        print(f'FAIL: {caller} 缺少到 {target} 的跳转')

    if target + '.WS2' not in rio_arc:
        print(f'FAIL: 目标脚本 {target}.ws2 不存在')
```

### 验收检查清单

- [ ] 调用链完整性：所有跳转目标存在且可达
- [ ] 资源配对正确：_H ↔ ORG_\*，\*_9XL/S；_E ↔ Steam 资源
- [ ] 无冗余脚本：没有同名裸名版本
- [ ] 无冗余资源：所有 ORG_* 资源被至少 1 个 _H 脚本引用
- [ ] 后缀一致性：调用链中后缀传递正确

## 新增脚本清单

来自 final_verification.py：

```python
original_scripts = [
    'yozora_hika_103f.ws2',      # 光路线 H 场景
    'yozora_hika_103g_H.ws2',    # 光路线 H 场景
    'yozora_ori_115_H.ws2',      # 織姫路线 H 场景（暖桌场景）
    'yozora_ori_118_H.ws2',      # 織姫路线 H 场景
    'yozora_saya_107b_H.ws2',    # 纱夜路线 H 前半
    'yozora_saya_107d_H.ws2',    # 纱夜路线 H 后半
]
```

### yozora_ori_115_H / yozora_ori_118_H 的 9X 段位资源

这两个脚本都引用织姫线原版事件 CG，Steam 同名资源图层数不足或缺失，按
[doc/pna-resources.md](pna-resources.md) 的 9X 段位规则隔离：

| 脚本 | 引用（9X 段位） | 对应原版资源 | 部署位置 |
|------|-----------------|-------------|---------|
| `yozora_ori_115_H.ws2` | `ORI_90L`/`ORI_90S` | Miazora `ORI_11L`/`ORI_11S`（20 层） | Chip3A.arc |
| `yozora_ori_118_H.ws2` | `ORI_91L`/`ORI_91S` | Miazora `ORI_12L`/`ORI_12S`（16 层） | Chip3A.arc |
| `yozora_ori_118_H.ws2` | `ORI_13L/S`、`ORI_14L/S`（裸名） | 与 Steam 内容一致，**无冲突**，勿改名 | Chip3A.arc（Steam 原有） |

**踩坑记录**：曾误将 `ORI_11S` 部署成 `ORI_91S`（应为 `ORI_90S`），且发现后未清理，
导致 `yozora_ori_118_H` 长期使用内容错配的 `ORI_91S`（背景黑屏但不报错）。另外一度误判
`ORI_13/14` 也需要 9X 隔离并改写脚本——SHA256 比对后确认 Steam/Miazora 内容完全相同，
已回滚。详见 [doc/lessons-learned.md](lessons-learned.md) 第五类缺陷。

## 配对保证原则

### 脚本与资源的配对规则

- `*_H.ws2` ↔ `ORG_*` 前缀资源（立绘）或 9X 段位资源（事件 CG）
- `*_E.ws2` ↔ Steam 裸名资源
- `*_H_E.ws2` ↔ Steam 裸名资源

### 检查脚本是否错误引用资源

```python
if script.endswith('_H.ws2'):
    for pna_ref in extract_pna_refs(script):
        # 事件 CG 可以是 9X 段位（无前缀）或 ORG_ 前缀
        # 立绘必须是 ORG_ 前缀
        if not (pna_ref.startswith('ORG_') or is_9x_segment(pna_ref)):
            print(f'ERROR: {script} 引用非隔离资源 {pna_ref}')
```

## 方案 1 的教训（已修复）

方案 1（Resto 1.1.0）的问题：

1. **yozora_ori_115_H** 引用 Steam `ORI_11S`（12 层）的 id 12–18 → 崩溃 0x39（图层 ID 越界）
2. **yozora_hika_103g_H** 引用 Steam `COM_04L` → id 范围够但语义位移，画错图

**根本原因**：忽略了"同名冲突"——同名 PNA 在 Steam/原版间语义不同，layer_id 是纯位置量，不能直接替换。
