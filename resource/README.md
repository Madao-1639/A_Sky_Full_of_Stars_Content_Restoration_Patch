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
| `scenes.json` | 补丁新引入的还原场景 | `final_verification.py`、`extract_embedded_text.py` |
| `cg-conflicts.json` | 同名冲突 CG 的 `原版名 → 9X 补丁名`、逐变体实测状态、引用它的场景 | `final_verification.py`、同步到其他补丁变体的脚本 |
| `call-chain.json` | 补丁改写的脚本跳转（`caller → target`） | `final_verification.py` |
| `layer-repairs.json` | COM_04/05 的 `(steam_lid → miazora_lid)` 图层级修复映射 | `replace_pna_layers.py` |
| `icon.ico` | 安装器打包图标 | `script/pack.sh` |

## 数据格式

每个 JSON 顶部都有 `_comment`，说明用途、字段语义与消费者；改动前先读它。主要字段：

**`scenes.json` → `scenes[]`**
- `id`：`Rio.arc` 成员名去掉 `.ws2` 后的小写 stem
- `route`：`hika` / `saya` / `ori` / `koro`
- `kind`：`H`（`_H` 场景脚本，引用 `ORG_` 立绘或 9X 段位事件 CG）/ `bare`（裸名还原脚本）
- 数组顺序即剧情先后

**`cg-conflicts.json` → `conflicts[]`**
- `original` → `patch`：Miazora 原版名 → 部署的 9X 段位名
- `archive`：部署归档
- `variants`：按 `L`/`S` 记录 `steam`（`differs` = 哈希不同 / `missing` = Steam 无此文件）与
  `deployed`（是否真的部署了——只部署脚本真正引用的变体）
- `referenced_by`：引用该补丁名的场景 `id`（同 `scenes.json`），按剧情先后

**`call-chain.json`**
- `opcode`：跳转指令（`0x07` = 调用另一脚本）
- `links[]`：`caller` / `target`（均为 `Rio.arc` 成员 stem，使用时大写并加 `.ws2`）、
  `kind`（`entry` = 由 Steam 脚本接入还原场景 / `exit` = 汇合回 Steam 脚本）

**`layer-repairs.json`**
- `source_archive` / `target_archive`：Miazora 源归档 / 待修复归档
- `full_canvas`：整层替换的 `layer_id` 与涉及的成员
- `local_frames[]`：`member` + `layers`（`[steam_layer_id, miazora_layer_id]` 显式配对）

## 改动后怎么验

`script/final_verification.py` 会把表与归档实测结果对账（场景差集、冲突部署状态、引用关系），
改完表跑一遍即可确认没有漂移：

```bash
python script/final_verification.py
```
