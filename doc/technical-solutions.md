# 技术方案

本文档记录已完成的技术修复方案。

## 4.1 saya_107c 冗余清理 ✓

### 问题描述

Resto 1.1.0 存在两个功能重复的脚本：
- `yozora_saya_107c.ws2` (裸名)：Resto 1.1.0 添加，跳转已修改为 `107d_H`
- `yozora_saya_107c_E.ws2` (_E 后缀)：Steam 原版，跳转为 `107e_E`

两者除跳转外，实际内容完全相同，造成脚本冗余和调用混乱。

### 解决方案

**修改内容**：

1. **删除** `yozora_saya_107c.ws2` (裸名版本)
2. **修改** `yozora_saya_107b_H.ws2`：
   - 调用改为：`0x07 YOZORA_SAYA_107C` → `0x07 YOZORA_SAYA_107C_E`
3. **修改** `yozora_saya_107c_E.ws2`：
   - 跳转改为：`0x07 YOZORA_SAYA_107E_E` → `0x07 YOZORA_SAYA_107D_H`

**最终调用链**：
```
107b_H → 107c_E → 107d_H → 107e_E
```

保证 H 场景连贯性。

**实现脚本**：`cleanup_saya107c.py`

**结果**：
- Rio.arc 成员数：368 → 367
- 新大小：9,004,688 bytes
- 备份：`Rio.arc.before_107c_cleanup`

---

## 4.2 PNA 资源引用修复（"同名冲突"）✓

### 问题描述

当移植进来的原版脚本与 Steam 版脚本同时引用了相同的 PNA（如 `COM_04L.pna`），大概率会产生渲染失败（0x00000039 错误），原因如下：

- 原版 PNA 与 Steam 版 PNA 的内容组成不完全相同
- 如果两者同名，意味着游戏内只存在能够满足一方的 PNA，另一方在调用时就会发生错误

**常见错误**：
1. 场景混乱：错误的资源被脚本组织在一起
2. 图层 id 越界：请求的 layer_id ≥ 实际 layer_count

### 解决方案：命名空间隔离

**方针**：
1. 一旦原版和 Steam 版脚本引用了同名的 PNA，就必须为原版的 PNA 重命名为带 `ORG_` 前缀的文件（或使用 9X 段位无前缀名），再加入游戏中
2. 原版 PNA 文件一旦改名，就必须在相应的原版脚本中修改原来的引用名为新的名称，否则将导致场景缺失

### 修改脚本引用（共 129 处）

| 脚本 | 修改内容 | 说明 |
|------|----------|------|
| `yozora_hika_103f.ws2` | `COM_04L` → `COM_90L` | 事件 CG 引用（9X 段位，原版 COM_04） |
| `yozora_hika_103g_H.ws2` | `COM_04L` → `COM_90L` | 事件 CG 引用（9X 段位，原版 COM_04） |
| `yozora_ori_115_H.ws2` | `ORI_11L/S` → `ORI_90L/S` | 事件 CG 引用（9X 段位，原版 ORI_11） |
| `yozora_ori_118_H.ws2` | `ORI_12L/S` → `ORI_91L/S` | 事件 CG 引用（9X 段位，原版 ORI_12）；脚本同时引用
  裸名 `ORI_13/14L/S`——Steam/原版内容一致，**未改名，无需隔离** |
| 多个 _H 脚本 | `Bさや_*` → `ORG_Bさや_*` | 角色立绘引用 |

**注意**：由于 ev01/ev02 事件槽拒绝 ORG_ 前缀，所有事件 CG 改用 9X 段位无前缀命名（如
`COM_90L.pna`, `ORI_90L.pna`, `ORI_91L.pna`）。早期方案曾用 `HIK_99L`/`ORG_COM_04L`/
`ORG_ORI_11L` 等命名，现已统一为 9X 段位格式，历史命名仅见于旧文档/旧脚本注释。

### 9X 段位资源位置

| 资源 | 位置 | 大小 | 对应原版 | 状态 |
|------|------|------|---------|------|
| `COM_90L.pna` | Chip3.arc | 18,462,890 bytes | Miazora COM_04L（29 层） | 已存在，被引用 |
| `ORI_90L.pna` | Chip3A.arc | 12,422,712 bytes | Miazora ORI_11L（20 层） | 已存在，被引用 |
| `ORI_90S.pna` | Chip3A.arc | 3,952,345 bytes | Miazora ORI_11S（20 层） | 已存在，被引用 |
| `ORI_91L.pna` | Chip3A.arc | 9,322,012 bytes | Miazora ORI_12L（16 层） | 已存在，被引用 |
| `ORI_91S.pna` | Chip3A.arc | 3,273,976 bytes | Miazora ORI_12S（16 层） | 已存在，被引用 |
| `ORG_Bさや_01L.pna` | Graphic.arc | - | 角色立绘 | 已存在，被引用 |
| `ORG_Aひかり_*` | Graphic.arc | - | 角色立绘 | 已存在，被引用 |
| `ORG_Dころな_*` | Graphic.arc | - | 角色立绘 | 已存在，被引用 |

**说明**：
- 事件 CG（进 ev01/ev02 槽）：使用 9X 段位无前缀命名
- 角色立绘（进 st* 槽）：继续使用 ORG_ 前缀

**部署校验要点**（见 `doc/lessons-learned.md` 第五类缺陷）：每次往 9X 段位部署资源，
必须回读并核对 `sha(部署结果) == sha(对应 Miazora 源文件)`，不能只看 slot 是否有内容。
本次曾出现 `ORI_91S.pna` 被错误装入 `ORI_11S` 的数据（应为 `ORI_12S`），表现为无报错的
背景黑屏，已修复。

### 检查方法

检查 _H 脚本是否错误引用 Steam 资源：
```python
if script.endswith('_H.ws2'):
    for pna_ref in extract_pna_refs(script):
        if not pna_ref.startswith('ORG_'):
            print(f'ERROR: {script} 引用非 ORG_ 资源 {pna_ref}')
```

---

## 4.3 通用 Payload 生成器 ✓

### 功能说明

自动计算 `asset/` 相对于 `backup/` 的增量，生成安装器所需的 payload。

### 路径约定

| 目录 | 用途 |
|------|------|
| `asset/` | 封装好的游戏文件（打补丁后的完整版本） |
| `backup/` | Steam 原版基线（用于计算增量，不可改动） |
| `tool/pack/payload/` | 输出增量 payload |

### 工作流程

```bash
# 1. 更新 asset（复制打好补丁的最新归档文件）
cp <打补丁后的 Rio.arc> asset/

# 2. 生成 payload
python tool/pack/generate_payload.py

# 3. 打包安装器
bash tool/pack/pack.sh
```

### 生成规则

- **Rio.arc**：全量复制（脚本归档通常全量替换）
- **其他归档**：增量模式
  - 新增的成员 → 包含在 payload
  - 修改的成员 → 包含在 payload
  - 未变的成员 → 不包含（节省空间）

---

## 4.4 资源缺失修复（Miazora 独有资源）✓

### 问题描述：第三类缺陷——"资源缺失卡死"

此前已识别两类资源缺陷：
1. **同名冲突**：Steam/原版同名 PNA 内容不同 → 渲染失败（0x39）或画错图
2. **图层 id 越界**：请求 id ≥ layer_count → 崩溃 0x39

本次实测发现第三类：**资源缺失**。原版脚本引用了 Steam 已删除的**非 PNA 资源**（转场静帧 `EST_*.png`、背景 `BG_*.png`、特效遮罩 `EFMSK_*.png`），引擎在硬载入时找不到文件，**直接无响应（卡死），不弹任何错误码**。

### 症状

saya 第一个 H 场景 `yozora_saya_102c_H` 播放到台词「沙夜一边说着不满，一边温柔地紧抱着那样的我。」结束后：

1. 画面放大正常出现（`0x34` 显示 `SAY_19L.PNA`）
2. 随后 `0x33` 硬载入 `EST_1033.PNG` —— Steam 无此文件 → **卡死**

### 定位方法（可复用）

1. **台词 → 脚本偏移**：在 `zh-CN/Rio.arc` 的 lng 中定位台词 slot，再到解码后脚本里找到对应的文本槽引用偏移
2. **偏移 → 指令**：`ws2.decode()` 后按偏移解析紧随其后的 `0x33/0x34/0x66` 资源引用
3. **三方资源审计**：枚举脚本全部 `.PNA/.PNG/.OGG/.MOS` 引用，逐一对 Steam 安装目录与 Miazora 目录求交集，筛出"仅 Miazora 存在"的资源

### 根因

Steam 删除 H 场景时，不仅删了 H 场景 CG（PNA）与语音，还删了**只被这些 H 场景使用的转场/背景/遮罩 PNG**。Steam 的 `Chip2.arc` 中 `EST_*` 编号为 `…1031, 1032, 1034…`，**唯独跳过 1033**——正是被删场景的转场静帧。

### 关键机制

| 操作码 | 含义 | 缺失时的行为 |
| :--- | :--- | :--- |
| `0x33` | 硬载入资源（转场/背景） | **卡死（无响应）** |
| `0x66` | 特效遮罩 | **容忍（静默跳过，仅画面瑕疵）** |
| `0x34` | 显示 CG 图层 | 另有 layer_id 越界风险（0x39） |

### 修复

从 Miazora 提取 9 个 Steam 缺失资源，按**裸名**补入 Steam 对应归档：

| 资源 | 补入 arc | 大小 | 修复的卡死/隐患 |
| :--- | :--- | :--- | :--- |
| `EST_1033.png` | Chip2.arc | 6.9KB | saya 102c_H 卡死主因 |
| `EST_1069/1071/1077.png` | Chip2.arc | 36KB | koro 115/121/126/131_H 同类卡死 |
| `BG_04N_X1/X2.png` | Chip1.arc | 5.3MB | hika 108g_H 同类卡死 |
| `BG_04N_L.png` | Chip1A.arc | 3.4MB | hika 108g_H 同类卡死 |
| `EFMSK_59.png` | Graphic.arc | 935KB | saya 102c_H 遮罩瑕疵 |
| `EFMSK_40.png` | Graphic.arc | 648KB | hika 108g_H 遮罩瑕疵 |

### 验证

- 全脚本 × 全资源引用（19,939 个引用）重扫：仅 Miazora 存在而 Steam 缺失的资源 = 0
- 四个重建 arc 与 Steam 逐成员比对：共有成员逐字节一致，新增成员恰为预期清单
- 102c_H 静态链：17 处 `0x33` 载入全部命中

---

## 4.5 EVRET 偏移指针修复 ✓

### 症状

原版场景如 saya_102c_H 结束后直接回主菜单，而非续接后续场景。

**影响 3 个场景**：

| 场景 | 偏差 | 来源 |
| :--- | :--- | :--- |
| `yozora_saya_102c_H` | −20 | 本次 B沙夜 改名（5×4B） |
| `yozora_ori_115_H` | −392 | 之前 ORG_ORI 改名（98×4B） |
| `yozora_hika_103g_H` | −12 | 之前 ORG_COM 改名（3×4B） |

### 根因

每个 `_H` 场景结尾是固定结构：

```
<field1 u32> 01 82 6e 00 00 00 <float> 00 00 <field2 u32> 07 EVRET 00 0b <gallery u16> 01 07 <next> 00
```

其中 `field1`（`07` 前 20 字节）与 `field2`（`07` 前 4 字节）是**绝对 u32 偏移**，指向 `0b <gallery> 01` 指令（`07` 后 7 字节处）。

**ORG_ 前缀改名在该指令前插入字节，使 `0b` 后移，但偏移指针未同步更新** → 指针失效 → EVRET 走 TITLE 分支 → 回主菜单。

### 修复

`fix_evret_offsets.py`（幂等）重算并修正 3 处偏移指针，回读验证通过（field1==field2==`0b` 偏移），其余 11 个 `_H` 场景偏移本已正确。

### 重要提醒

**任何改动脚本长度后必须跑 `fix_evret_offsets.py` 重算偏移（幂等）**；`01 82 6e` 的 0x6e82 是常量不是偏移，不用改。
