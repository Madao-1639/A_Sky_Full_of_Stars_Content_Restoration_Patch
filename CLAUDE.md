# A Sky Full of Stars 内容恢复补丁项目

## 项目目的

为 Steam 版游戏《A Sky Full of Stars》制作内容恢复补丁，整合原版 H 场景内容到 Steam 版本，同时修复资源冲突、调用链混乱等问题。

**核心目标**：
1. 保留 Steam 成就系统
2. 恢复完整 H 场景内容
3. 零破坏性修改（不替换 Steam 原有资源）

## 项目背景

### 技术挑战

1. **同名冲突**：Steam 版和原版的同名 PNA 资源内容不同，layer_id 是纯位置量，不能直接替换
2. **调用链混乱**：需要在 Steam 段落间穿插原版 H 段落，形成完整剧情
3. **资源缺失**：Steam 删除 H 场景时一并删除了转场/背景/遮罩资源
4. **引擎限制**：ev01/ev02 事件槽拒绝 ORG_ 前缀，需要特殊命名策略

### 解决方案

- **命名空间隔离**：使用 ORG_ 前缀（立绘）或 9X 段位（事件 CG）隔离两套资源
- **穿插式调用链**：在 Steam 脚本（_E）间插入原版脚本（_H）
- **资源补全**：从 Miazora 补入 Steam 缺失的 PNG 资源
- **配对保证**：_H ↔ ORG_*/9X，_E ↔ Steam 资源

## 工程约定

### 1. 文档同步要求

**任何大型修改都必须同步到文档中**

- 修改脚本改写逻辑 → 更新 `doc/file-formats.md`
- 新增资源命名规则 → 更新 `doc/pna-resources.md`
- 修改调用链结构 → 更新 `doc/call-chain.md`
- 发现新问题/解决方案 → 更新 `doc/lessons-learned.md`
- 修改验收标准 → 更新 `doc/acceptance-criteria.md`

### 2. 临时文件管理

**生成的临时文件存放在 `tmp/` 目录下，任务结束后清除**

临时文件包括但不限于：
- 解码后的 WS2 脚本
- 提取的资源文件
- 中间处理结果
- 调试输出文件

**清理原则**：
- 任务完成后立即清理 `tmp/` 目录
- 重要的中间结果应移动到 `releases/` 或其他持久化目录
- 不将临时文件提交到版本控制

### 3. 库和脚本组织

**tool/ 是 Python 包**（通过 `__init__.py`），提供通用库：

```
tool/
├── __init__.py      （包标记）
├── arcbuild.py      （Arc 文件读写）
├── ws2.py           （WS2 脚本编解码 + 成就注入）
├── arcstream.py     （大文件流式处理）
└── lng.py           （文本编码）
```

脚本通过 `from tool import arcbuild, ws2` 等方式导入，所有脚本使用相对于项目根的路径。从项目根执行：

```bash
python script/generate_payload.py    # 生成增量补丁到 payload/
bash script/pack.sh                  # 打包 exe 到 releases/
python script/final_verification.py  # 全量验证
```

### 4. 脚本开发规范

**幂等性**：
- 所有工具脚本必须支持重复运行，临时文件除外
- 运行前检查"已满足则跳过"
- 不因重复运行产生错误结果

**回读校验**：
- 改写资源引用后必须回读验证
- 修改偏移指针后必须验证指向正确
- 生成归档后必须验证成员完整性

**编码规范**：
- 资源名使用 Shift-JIS 编码
- 控制台输出使用 ASCII 或配置 UTF-8
- 使用 NUL 前缀的精确替换模式

**编码处理注意事项**：

*Shift-JIS 与中文字符*：
- **脚本内容**（资源名、对话）使用 **Shift-JIS** 编码
- **中文字符不能用 Shift-JIS 编码**，会抛出 `UnicodeEncodeError`
- 搜索/匹配脚本内容时：
  - 日文文本：`text.encode('shift_jis')`
  - 中文文本：**不要尝试编码**，直接在已解码的 UTF-8 字符串中搜索

*常见错误示例*：
```python
# ❌ 错误：尝试用 Shift-JIS 编码中文
search_text = '来露娜，已经是个大人了哦'  # 中文
search_bytes = search_text.encode('shift_jis')  # UnicodeEncodeError!

# ✅ 正确：中文是翻译后的，不在脚本原文中
# 应该搜索日文原文或关键词
search_text = 'ころな'  # 日文
search_bytes = search_text.encode('shift_jis')  # OK
```

*解码方法*：
```python
# 从脚本中提取文本（已是 bytes）
decoded = ws2.decode(raw)  # bytes

# 尝试解码为字符串
try:
    text = decoded.decode('shift_jis')  # 脚本内容
except UnicodeDecodeError:
    text = decoded.decode('shift_jis', errors='ignore')  # 容错模式

# 资源名提取（Shift-JIS）
resource_name = b'D\x82\xb1\x82\xeb\x82\xc8_01L'  # bytes
resource_str = resource_name.decode('shift_jis')  # 'Dころな_01L'
```

*搜索脚本内容的正确方法*：
```python
# 1. 搜索日文关键词（编码为 Shift-JIS bytes）
keyword = 'ころな'.encode('shift_jis')
if keyword in decoded:
    print('Found')

# 2. 搜索资源引用（带 NUL 上下文）
resource = 'Dころな_01L.PNA'.encode('shift_jis')
pattern = b'\x00' + resource + b'\x00'
if pattern in decoded:
    print('Found resource reference')

# 3. 搜索中文内容（在中文化文件中，不在脚本中）
# 脚本中不包含中文，中文是外部翻译文件
# 应该去 zh-CN/Rio.arc 的 lng 文件中搜索
```

*资源名大小写*：
- Arc 文件内的资源名**保留原始大小写**
- 搜索时使用 `.lower()` 进行不区分大小写匹配
- 示例：`EFBG00_01.PNG` vs `efbg00_01.png`（实际文件是 `.PNG`）

### 4. 命名规范

**脚本命名**：
- `*_E.ws2`：Steam 版脚本，引用 Steam 资源
- `*_H.ws2`：原版 H 场景脚本，引用 ORG_* 或 9X 段位资源
- `*_H_E.ws2`：Steam 过审 H 场景脚本，引用 Steam 资源

**PNA 资源命名**：

*事件 CG（路线+场景编号）*：
- 格式：`路线代码_场景编号[L/S].pna`
- 路线代码：COM（共通）、HIK（ひかり）、SAY（さや）、ORI（織姫）、KOR（ころな）
- 示例：`COM_04L.pna`, `HIK_17L.pna`, `SAY_20L.pna`

*角色立绘（字母前缀+角色名+差分）*：
- 格式：`[字母前缀]+角色日文名_差分编号[L/M/S/W/X].pna`
- 字母前缀：A=ひかり, B=さや, C=織姫, D=ころな
- 示例：`Aひかり_01M.pna`, `Bさや_01L.pna`

*补丁资源*：
- `ORG_[路线代码]_##[L/S].pna`：原版事件 CG（st* 槽可用）
- `ORG_[字母]角色名_##[L/M/S/W/X].pna`：原版立绘
- `[路线代码]_9X[L/S].pna`：补丁新增事件 CG（ev01/ev02 槽，无 ORG_ 前缀）

### 5. 验收流程

每次重大修改后必须执行：

1. 运行 `final_verification.py` 全量验证
2. 检查调用链完整性
3. 验证资源配对正确性
4. 测试关键场景功能
5. 更新 SHA256SUMS
6. 更新文档

### 6. 备份策略

**重要修改前必须备份**：
- Arc 归档修改前备份（如 `Rio.arc.before_xxx`）
- 记录备份时间和修改原因
- 验证备份文件完整性

### 7. 版本控制

**不提交的文件**：
- `tmp/` 目录下的所有文件
- 备份文件（*.before_*）
- 临时输出文件
- 大型二进制文件（使用 Git LFS 或外部存储）

**必须提交的文件**：
- 所有 Python 脚本
- 文档文件（README.md 和 doc/ 下所有文件）
- 配置文件
- SHA256SUMS

### 8. 调试规范

**日志输出**：
- 使用结构化日志（时间戳 + 级别 + 消息）
- 关键操作前后记录状态
- 错误时输出完整上下文

**错误处理**：
- 捕获并记录所有异常
- 提供清晰的错误信息
- 建议可能的解决方案

### 9. 性能要求

- 不添加冗余资源、脚本
- 生成的 payload 尽可能小（增量模式）

### 10. 安全要求

- 不修改 Steam 原版文件（仅读取用于对比）
- 验证所有输入文件的完整性
- 使用 SHA256 校验关键文件
- 谨慎处理用户路径输入

## 技术栈

- **语言**：Python （使用 mamba/conda 管理，优先使用 mamba）
- **编码**：Shift-JIS（资源名）、UTF-8（文档）
- **归档格式**：自定义 Arc 格式
- **脚本格式**：WS2 二进制格式
- **资源格式**：PNA（图层）、PNG（转场/背景）、OGG（语音）

## 参考文档

- [README.md](README.md) - 项目概述和快速开始
- [doc/file-formats.md](doc/file-formats.md) - 游戏文件格式规范
- [doc/pna-resources.md](doc/pna-resources.md) - PNA 资源机制
- [doc/call-chain.md](doc/call-chain.md) - 调用链组织
- [doc/restoration-targets.md](doc/restoration-targets.md) - 还原目标
- [doc/technical-solutions.md](doc/technical-solutions.md) - 技术方案
- [doc/engine-mechanics.md](doc/engine-mechanics.md) - 引擎机制
- [doc/lessons-learned.md](doc/lessons-learned.md) - 问题记录
- [doc/acceptance-criteria.md](doc/acceptance-criteria.md) - 验收标准
