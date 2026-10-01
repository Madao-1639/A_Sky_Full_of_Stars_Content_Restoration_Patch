# resource/

存放**可复用的资源和映射表**。这些映射只在这里定义一次——脚本不再各自硬编码，统一经
`tool/resources.py` 的 `load()` 读取：

```python
from tool import resources

scenes = resources.load('scenes.json')['scenes']
```

## 表清单

| 文件 | 内容 | 消费者 |
|---|---|---|
| `scenes.json` | 补丁新引入的场景（`_H` 场景 / 裸名还原 / 差分接缝修复） | `script/final_verification.py`、`script/tools/extract_embedded_text.py`、`script/seam/upd_scenes.py` |
| `call-chain.json` | 补丁改写的脚本跳转（`caller → target`） | `script/final_verification.py` |
| `cg-conflicts.json` | 同名冲突**事件 CG** 的 `原版名 → 9X 补丁名`、逐变体实测状态、改动它的场景 | `script/final_verification.py`、同步到其他补丁变体的脚本 |
| `resource-decisions.json` | 同名冲突的**最终取舍**（`真冲突`/`误报`/`采用Steam`/`本地化`/`待定`）与隔离名 | `script/seam/pin_translations.py`、`script/seam/apply_seam_resources.py --plan`、`script/seam/revert_isolation.py` |
| `layer-repairs.json` | COM_04/05 的 `(steam_lid → miazora_lid)` 图层级修复映射 | `script/tools/replace_pna_layers.py` |
| `present-ops.json` | 逐 opcode 的演出归属（`use_orig` / `keep_steam`）——差异处理的唯一判据 | `script/seam/build_seam.py`、`script/seam/gen_worklist.py` |
| `steam-diffs.json` | **Steam 版的差分范围**：按插入点记录入口/出口的实测状态与一句话说明 | `doc/restoration-targets.md`（引用） |
| `seam-diffs.json` | **差分接缝的差异数据**：按邻居脚本记录四来源差异（演出/文本记录级/无语音句语义/资源名） | `script/seam/gen_worklist.py`、`script/seam/build_seam_diffs.py`、`script/final_verification.py` |
| `seam-handling.json` | **分脚本的处理记录**：每个接缝还原了哪些记录、整块区间、改的名、补的资源、注入的成就 | 复查与实机验证对照 |
| `semantic-rewrites.json` | 同句数、无语音句的**语义改写**（Steam 把性内容换成中性说法），带 H/O/K 编号 | `script/seam/build_seam_diffs.py` |
| `removed-scripts.json` | **有意删除**的 Steam 成员白名单（被旁路的 `*_E`、`*_H_E` 孤儿）——"零破坏性"检查的例外 | `script/final_verification.py` |
| `cht_text/`（目录） | 民汉繁中文本池逐字原文 + 按**原版行号**归组的映射（`original/`） | 供其他开发者/后续人工翻译采纳；口径见 `cht_text/README.md` |
| `icon.ico` | 安装器打包图标 | `script/pack.sh` |

## 数据格式

每个 JSON 顶部都有 `_comment`，说明用途、字段语义与消费者；改动前先读它。主要字段：

**`scenes.json` → `scenes[]`**
- `id`：`Rio.arc` 成员名去掉 `.ws2` 后的小写 stem
- `route`：`hika` / `saya` / `ori` / `koro`
- `kind`：`H`（`_H` 场景脚本）/ `bare`（裸名还原脚本）/ `seam`（差分接缝修复脚本：成员名沿用
  Steam 名去掉 `_E`，基底为 Steam 脚本、差分段落回原版、共用部分仍用 Steam 官中）
- 数组顺序即剧情先后

**`cg-conflicts.json` → `conflicts[]`**：`original` → `patch`（原版名 → 部署的 9X 段位名）、
`archive`、`variants`（按 `L`/`S` 记 `steam`：`differs` = 哈希不同 / `missing` = Steam 无此文件，
与 `deployed`）、`referenced_by`（引用该补丁名的场景 `id`，按剧情先后）

**`resource-decisions.json`**：键 = 资源名；值 = `verdict`（五档）与 `isolation_name`。
`真冲突` 才引用隔离名；`误报`/`本地化`/`采用Steam` 一律用 Steam 裸名。本表为**权威记录**
（生成器输入已删，直接编辑）。

**`call-chain.json`**：`opcode`（`0x07` = 调用另一脚本）；`links[]` = `caller`/`target`
（`Rio.arc` 成员 stem）+ `kind`（`entry` 由 Steam 脚本接入还原场景 / `exit` 汇合回 Steam 脚本）

**`layer-repairs.json`**：`source_archive`/`target_archive`、`full_canvas`（整层替换的 `layer_id`
与成员）、`local_frames[]`（`member` + `layers` = `[steam_layer_id, miazora_layer_id]` 显式配对）

**`steam-diffs.json` → `insertions[]`**：`id`、`route`、`entry`/`exit`（各含 `neighbor` = 该侧邻居
脚本 stem，`null` 表示无此侧邻居；`status` = `pass`/`minor`/`hard`）、`note`（一句话）。
`legend` 给出三档的记号。

**`seam-diffs.json` → `scripts[]`**：`steam`/`orig`、`needs_rebuild`、`done`、`counts`
（`present`/`text`/`semantic`）、`present[]`/`text[]`/`semantic[]`（差异明细）、
`resource_refs[]`（**只存资源名**，取舍查 `resource-decisions.json`）。
顶层 `absent_both[]` = 两侧归档都没有、由游戏另处归档提供的资源名。

**`seam-handling.json` → `scripts[]`**：`new`（接缝脚本 stem）、`steam_from`、
`restored_records`（取原版文本的记录数）、`whole_blocks[]`（按原版整块重建的原版记录区间，
闭区间）、`renamed{}`（隔离改名）、`resources_added[]`（为它新增部署的原版资源）、
`achievements_injected`

**`semantic-rewrites.json` → `items[]`**：`seam`（新脚本 stem）、`label`（`H1`…`K5`）、
`position`、`orig_jp`、`orig_idx`、`steam_idx`

## 改动后怎么验

`script/final_verification.py` 会把表与归档实测结果对账（场景差集、冲突部署状态、引用关系），
改完表跑一遍即可确认没有漂移：

```bash
python script/final_verification.py
```
