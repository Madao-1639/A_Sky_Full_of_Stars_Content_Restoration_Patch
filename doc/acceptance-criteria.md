# 验收标准

## 功能验收（已通过 ✓）

### 调用链完整性

- [x] `107b_H → 107c_E`：验证通过（1 处调用）
- [x] `107c_E → 107d_H`：验证通过（1 处跳转）
- [x] `107d_H → 107e_E`：验证通过（1 处跳转）

### 脚本存在性

- [x] `YOZORA_SAYA_107C_E.WS2`：存在
- [x] `YOZORA_SAYA_107D_H.WS2`：存在
- [x] `YOZORA_SAYA_107E_E.WS2`：存在

### 资源完整性（20 种 PNA，全部验证通过）

| 资源 | 位置 | 状态 |
|------|------|------|
| `Aひかり_01M.pna` | Graphic.arc | ✓ 存在 |
| `Aひかり_02M.pna` | Graphic.arc | ✓ 存在 |
| `Aひかり_03W.pna` | Graphic.arc | ✓ 存在 |
| `HIK_17L/S.pna` | Chip3.arc | ✓ 存在 |
| `HIK_18L/S.pna` | Chip3.arc | ✓ 存在 |
| `HIK_19L/S.pna` | Chip3.arc | ✓ 存在 |
| `COM_90L.pna`（9X 段位，原 ORG_COM_04L 方案已废弃） | Chip3.arc | ✓ 存在 |
| `ORI_90L/S.pna`（9X 段位，原 ORG_ORI_11 方案已废弃） | Chip3A.arc | ✓ 存在 |
| `ORI_91L/S.pna`（9X 段位，原版 ORI_12） | Chip3A.arc | ✓ 存在 |
| `SAY_20L/S.pna` | Chip3B.arc | ✓ 存在 |
| `SAY_21L/S.pna` | Chip3B.arc | ✓ 存在 |
| `SAY_22L/S.pna` | Chip3B.arc | ✓ 存在 |
| `SAY_23L/S.pna` | Chip3B.arc | ✓ 存在 |

**注**：事件 CG（ev01/ev02 槽）不能用 `ORG_` 前缀（会注册失败），已统一改用 9X 段位命名，
详见 [doc/pna-resources.md](pna-resources.md)。上面 `ORG_COM_04L`/`ORG_ORI_11L/S` 是早期
方案的历史记录，实际部署的资源名是 `COM_90L`/`ORI_90L/S`。

### 冗余检测

- [x] `COM_90L.pna`：被引用（31 次，yozora_hika_103f/103g_H）
- [x] `ORI_90L.pna`：被引用（37 次，yozora_ori_115_H）
- [x] `ORI_90S.pna`：被引用（61 次，yozora_ori_115_H）
- [x] `ORI_91L.pna`：被引用（16 次，yozora_ori_118_H）
- [x] `ORI_91S.pna`：被引用（51 次，yozora_ori_118_H）
- [x] **无冗余资源**

### 成员统计

- [x] Rio.arc：367 个成员（从 368 减少 1 个）
- [x] saya_107 系列：6 个脚本
  - yozora_saya_107_E.ws2
  - yozora_saya_107a_E.ws2
  - yozora_saya_107b_H.ws2
  - yozora_saya_107c_E.ws2（已修改跳转）
  - yozora_saya_107d_H.ws2
  - yozora_saya_107e_E.ws2

## 质量标准（已完成 ✓）

- [x] 生成 SHA256SUMS 校验文件
- [x] 最终验证脚本：`final_verification.py` 全部通过

## 验收检查清单

### 脚本层面

- [ ] 所有跳转目标脚本存在
- [ ] 调用链完整且可达
- [ ] 无冗余脚本（没有同名裸名版本）
- [ ] 后缀一致性（_H/_E/_H_E 正确配对）

### 资源层面

- [ ] 所有引用的 PNA 资源存在
- [ ] 所有引用的 PNG 资源存在（EST_*/BG_*/EFMSK_*）
- [ ] 所有引用的语音资源存在
- [ ] ORG_* 资源被至少 1 个 _H 脚本引用（无冗余）
- [ ] 9X 段位资源被正确引用

### 配对正确性

- [ ] _H 脚本 ↔ ORG_* 资源（立绘）或 9X 段位资源（事件 CG）
- [ ] _E 脚本 ↔ Steam 裸名资源
- [ ] _H_E 脚本 ↔ Steam 裸名资源

### 结构完整性

- [ ] EVRET 偏移指针正确（所有 _H 场景）
- [ ] 图层 id 不越界（所有 0x34 显示指令）
- [ ] 资源引用编码正确（Shift-JIS）

### 增量 Payload

- [ ] asset/ 与 backup/ 对比正确
- [ ] payload 包含所有新增/修改的资源
- [ ] SHA256SUMS 更新且正确

## 测试标准

### 功能测试

1. **调用链测试**：
   - 从 Steam 版入口进入每条路线
   - 确认能正常触发 H 场景
   - 确认 H 场景结束后能正常续接后续剧情

2. **资源显示测试**：
   - H 场景 CG 正常显示（无 0x39 错误）
   - 立绘正常显示
   - 转场/背景正常载入（无卡死）
   - 语音正常播放

3. **结束流程测试**：
   - H 场景结束后不回主菜单
   - 正确进入后续剧情
   - Gallery 解锁正常

### 兼容性测试

- [ ] Steam 成就系统正常工作
- [ ] Steam 版原有功能不受影响
- [ ] 可以正常保存/读取进度
- [ ] 界面和系统功能正常

## 性能标准

- [ ] 补丁安装时间 < 5 分钟
- [ ] 游戏启动时间无明显增加
- [ ] H 场景加载无明显延迟
- [ ] 内存占用在合理范围

## 文档标准

- [ ] README.md 完整且准确
- [ ] 各模块文档齐全
- [ ] 技术方案文档详细
- [ ] 问题记录完整
- [ ] 验收标准明确

## 发布标准

### 必要文件

- [ ] asset/ 目录下所有 .arc 文件
- [ ] tool/ 目录下的所有工具
- [ ] script/ 目录下的所有脚本
- [ ] payload/metadata.json 校验文件
- [ ] README.md 和文档
- [ ] VERSION 版本号标识

### 版本信息

- [ ] 版本号正确
- [ ] 更新日志完整
- [ ] 已知问题列表
- [ ] 兼容性说明

## 回归测试清单

每次修改后必须重新验证：

1. 运行 `final_verification.py`
2. 测试关键场景（至少一条路线的完整流程）
3. 验证 Steam 成就系统
4. 确认无新增错误
