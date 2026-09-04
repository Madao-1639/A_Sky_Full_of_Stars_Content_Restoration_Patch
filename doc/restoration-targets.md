# 还原目标

## 资源维度

### 1. 原版 H 场景 CG（PNA 图层资源）

| 资源类型 | 数量 | 命名规则 | 原因 |
| :--- | :--- | :--- | :--- |
| 原版专属 CG | 59 个 PNA | ORG_ 前缀或 9X 段位 | 命名空间隔离 |
| Steam 保留 CG（裸名，多数） | 保持原样 | 裸名（如 HIK_17L） | 不改动 Steam 资源 |
| Steam 保留 CG（裸名，部分图层级阉割） | 图层级修复 | 裸名（`COM_04L/S`、`COM_05L/S`） | 全画布主图+局部动画帧替换为 Miazora 对应图层，见 `doc/technical-solutions.md` 4.6 |

#### PNA 资源分类

**事件 CG**（路线+场景编号）：
- 格式：`路线代码_场景编号[L/S].pna`
- 路线代码：COM（共通）、HIK（ひかり）、SAY（さや）、ORI（織姫）、KOR（ころな）

**补丁添加的事件 CG 分为两类**：

1. **Steam 版差分的 CG - 同名冲突**（使用 9X 段位）：
   - HIK_90L/S ← 原版 HIK_09（HIK_09S 与 Steam 冲突）
   - SAY_90L/S ← 原版 SAY_15（SAY_15S 与 Steam 冲突）
   - COM_90L ← 原版 COM_04L（COM_04L 与 Steam 冲突）
   - ORI_90L/S ← 原版 ORI_11（ORI_11S 与 Steam 冲突）
   - ORI_91L/S ← 原版 ORI_12（ORI_12L/S 与 Steam 冲突）

2. **Steam 版删除的 CG**（直接继承原版编号）：
   - HIK_15L/S - HIK_23L/S（原版编号，Steam 版不存在）
   - SAY_16L/S - SAY_23L/S（原版编号，Steam 版不存在）
   - ORI_13L/S - ORI_19L/S（原版编号，Steam 版不存在）
   - KOR_11L/S - KOR_19L/S（原版编号，Steam 版不存在）

**角色立绘**（字母前缀+角色名+差分）：
- 格式：`[字母前缀]+角色日文名_差分编号[L/M/S/W/X].pna`
- 字母前缀：A=ひかり, B=さや, C=織姫, D=ころな
- 示例：`Aひかり_01M.pna`（Steam）、`ORG_Bさや_01L.pna`（原版）

#### 覆盖路线（5 条）

##### 1. com（共通线）

**涉及场景**：yozora_hika_103g_H.ws2

**还原 CG**：
- COM_90L（真正冲突，原版 COM_04L 与 Steam 内容不同）
- HIK_17L/S, HIK_18L/S, HIK_19L/S（原版独有，Steam 版不存在）

##### 2. hika（ひかり线）

**涉及场景**：
- yozora_hika_103d_H.ws2
- yozora_hika_103g_H.ws2
- yozora_hika_110c_H.ws2

**还原 CG**：
- HIK_90L/S（真正冲突，原版 HIK_09 与 Steam 内容不同）
- HIK_15L/S - HIK_23L/S（原版独有，Steam 版不存在）
  - HIK_15L/S, HIK_16L/S（yozora_hika_103d_H）
  - HIK_17L/S, HIK_18L/S, HIK_19L/S（yozora_hika_103g_H）
  - HIK_22L/S, HIK_23L/S（yozora_hika_110c_H）

**还原立绘**：
- ORG_Aひかり_02L/M, ORG_Aひかり_03L/W（原版专属）

##### 3. saya（さや线）

**涉及场景**：
- yozora_saya_101j_H.ws2
- yozora_saya_102c_H.ws2
- yozora_saya_107b_H.ws2
- yozora_saya_107d_H.ws2

**还原 CG**：
- SAY_90L/S（真正冲突，原版 SAY_15 与 Steam 内容不同）
- SAY_16L/S - SAY_23L/S（原版独有，Steam 版不存在）
  - SAY_16L/S（yozora_saya_101j_H）
  - SAY_17L/S, SAY_18L/S, SAY_19L/S（yozora_saya_102c_H）
  - SAY_20L/S, SAY_21L/S（yozora_saya_107b_H）
  - SAY_22L/S, SAY_23L/S（yozora_saya_107d_H）

**还原立绘**：
- ORG_Bさや_01L, ORG_Bさや_02L, ORG_Bさや_03L（原版专属）

##### 4. ori（織姫线）

**涉及场景**：
- yozora_ori_115_H.ws2
- yozora_ori_118_H.ws2
- yozora_ori_123_H.ws2
- yozora_ori_129_H.ws2

**还原 CG**：
- ORI_90L/S（真正冲突，原版 ORI_11 与 Steam 内容不同）
- ORI_91L/S（真正冲突，原版 ORI_12 与 Steam 内容不同）
- ORI_13L/S - ORI_19L/S（原版独有，Steam 版不存在）
  - ORI_13L/S, ORI_14L/S（yozora_ori_118_H）
  - ORI_15L/S, ORI_16L/S（yozora_ori_123_H）
  - ORI_17L/S, ORI_18L/S, ORI_19L/S（yozora_ori_129_H）

**还原立绘**：
- ORG_C織姫_01L/W, ORG_C織姫_02W, ORG_C織姫_03L/W（原版专属）

##### 5. koro（ころな线）

**涉及场景**：
- yozora_koro_115_H.ws2
- yozora_koro_121_H.ws2
- yozora_koro_124_H.ws2
- yozora_koro_126_H.ws2
- yozora_koro_131_H.ws2

**还原 CG**：
- KOR_11L/S - KOR_19L/S（填补编号空缺，Steam 只有 01-04, 07-10）

**还原立绘**：
- ORG_Dころな_01L/X, ORG_Dころな_02L, ORG_Dころな_03L/X（原版专属）

### 2. 原版语音

- **数量**：2,423 个语音文件
- **分布**：Voice_patch.arc (1,185) + Voice1_patch.arc (1,238)
- **用途**：Steam 删除的 H 场景对白

### 3. 原版转场/背景/遮罩资源（PNG）

- **类型**：转场静帧 `EST_*.png`、背景 `BG_*.png`、特效遮罩 `EFMSK_*.png`
- **来源**：Steam 删除 H 场景时一并删除的场景专属 PNG（非 PNA CG）
- **处理**：从 Miazora 以**裸名**补入对应归档（Steam 无同名文件，无需 ORG_ 前缀）
- **数量**：本次补齐 9 个

## 调用链维度

### 穿插式调用链还原

案例：纱夜路线第 107 段

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

#### 穿插逻辑

- **107b_H**：原版 H 前半（引用 `SAY_20L/S`、`SAY_21L/S`，裸名，与 Steam 内容一致，无冲突）
- **107c_E**：Steam 保留的过渡段（台词被审核改写）
- **107d_H**：原版 H 后半（引用 `SAY_22L/S`、`SAY_23L/S`，裸名，同样无冲突）

## 还原目标的本质

让 Steam 版游戏运行原版完整剧情，通过以下手段：

1. **资源共存**：ORG_ 前缀或 9X 段位隔离两套 PNA 语义空间（仅在同名冲突时才需要，
   如 saya_107 系列引用的 SAY_20~23 本身无冲突，不隔离）
   - 事件 CG（ev01/ev02 槽）：使用 9X 段位无 ORG_ 前缀（如 `COM_90L.pna`、`ORI_90L.pna`）
   - 角色立绘（st* 槽）：使用 ORG_ 前缀（如 `ORG_Bさや_01L.pna`）
2. **脚本穿插**：在 Steam 段落（_E）间插入原版 H 段落（_H）
3. **配对保证**：_H ↔ ORG_*/9X，_E ↔ Steam 资源
4. **零破坏性**：不替换整份 Steam 资源、不修改 Steam 脚本内部逻辑（仅改跳转目标）——
   例外见下方"不做什么"的说明
5. **图层级修复**（例外情形）：极少数裸名 PNA（`COM_04L/S`、`COM_05L/S`）Steam 阉割发生
   在单个 PNA 内部的部分图层，而非整份文件，此时用 Miazora 对应图层替换那部分内容，
   不涉及改名/隔离，也不影响 `_E` 脚本对该 PNA 文件名的引用，见 `doc/technical-solutions.md` 4.6

## 不做什么

- ❌ 不整份替换 Steam 资源文件（会破坏 `_E` 脚本对文件名的引用）——但对少数确认存在图层级
  阉割残留的裸名 PNA，允许**仅替换其中部分图层的字节**，见上方"图层级修复"
- ❌ 不合并 PNA（layer_id 语义冲突无法解决）
- ❌ 不修改成就系统（gallery id 保持不变）
- ❌ 不翻译为中文（原版脚本携带 Miazora 英文化文本）

## 最终效果

玩家在 Steam 购买的游戏基础上，安装补丁后：

- 所有路线的完整 H 场景恢复
- 对应的原版 CG 和语音正常显示/播放
- Steam 成就、界面、系统功能不受影响
