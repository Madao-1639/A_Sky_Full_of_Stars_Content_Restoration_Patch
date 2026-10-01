# 待决问题记录

记录已发现但尚未处理、需要产品决策后才能继续的问题。每条问题独立成节，状态明确标注，
避免和已完成的还原工作混在一起造成"已完成"的错觉。

背景见 [doc/restoration-targets.md](restoration-targets.md)（Steam 版差分情况）与
`resource/`（差分数据与映射表）。

---

## 问题 1：Steam 官中译文的误译

**状态**：待决策（是否修正），未修复

### 问题描述

Steam 官方中文（`asset/zh-CN/Rio.arc` 的 `.lng`）中有一批句子：**英文与原版日文一致，中文却不同**——
不是 Steam 改写了剧本，而是**中文译文本身出错**。本补丁采用"Steam 官方中文原样保留"的原则，
因此这些误译目前被原样带进补丁。

判定口径：`asset/Rio.arc` 的 `.ws2` 里存的是 **Steam 英文**，官中在 `.lng` 里。

- 英文与官中**同时**偏离原版日文 ⇒ Steam 改写剧本
- **只有官中偏离**、英文与原版一致 ⇒ 官中误译（本问题）

### 已发现的条目

共 **28 条**，逐条核对日文 / Steam 英文 / 官中三方（英文取自 `asset/Rio.arc` 的 `.ws2`）。
位置格式为「脚本 原版 idx / Steam idx」。

**hika 线（13 条）**

| # | 位置 | 原版日文 | Steam 英文 | 官中 | 问题类型 |
|---|---|---|---|---|---|
| 1 | `yozora_hika_103c` 107 / 107 | ――もうこないだので、最後って**約束**だったもんな。 | `I promised you before that it was the last time.` | …我已经**说了**，之前那是最后一次。 | 约定→"说" |
| 2 | `yozora_hika_103c` 74 / 74 | あれが俺の最後の告白。そう**約束した**。 | `I'd made a promise.` | 那是我最后一次表白，至少我是这样**说**的。 | 同上 |
| 3 | `yozora_hika_103c` 73 / 73 | 「もうこないだので、最後って**約束**だったもんな」 | `'Nevermind. I promised you before…'` | “我已经**说了**，之前那是最后一次。” | 同上 |
| 4 | `yozora_hika_103c` 101 / 101 | 今日だって、**あたしなんかのために**、雨の中をここまで来てくれた。 | `Even today, he'd come all the way up here in the pouring rain…` | 今天，他也为了我这种**伤他不浅**的人顶着暴风雨跑来这里。 | 增译（"伤他不浅"原文与英文皆无） |
| 5 | `yozora_hika_103c` 157 / 157 | そう言うと**暁斗は**、辛抱できないって感じで、**あたしに**また、めちゃくちゃにキスをした。 | `…he couldn't hold himself back any longer. He pulled…` | 话音未落，**我们两人都**失去控制般地疯狂吻着彼此。 | 单方动作→双方 |
| 6 | `yozora_hika_103c` 71 / 71 | **途中まで言いかけて**、俺は言葉を飲み込んだ。 | `I caught myself and swallowed my next words.` | 我没有继续说下去。 | 漏译（"说到一半"） |
| 7 | `yozora_hika_103e` 58 / 55 | 俺も真似をしてみて気が付いた。 | `I did the same and noticed, too.` | 我也学着她的样子**看向窗外，才明白了她想表达的含义**。 | 增译 |
| 8 | `yozora_hika_103e` 46 / 43 | 「顔が可愛いのは……昔からか」 | `'Your face... That's always been cute.'` | “你长得这么可爱……**不对**，从小就很可爱。” | 凭空加自我否定 |
| 9 | `yozora_hika_108f` 103 / 103 | **だんだんと**顔を赤らめていった。 | `Her face slowly reddened.` | **看着看着**，她的脸**一下子**涨红了。 | 逐渐→一下子＋增译 |
| 10 | `yozora_hika_108f` 5 / 5 | 「カップ麺の追加と、**おにぎりならもうあるぞ**」 | `'One more cup of instant noodles, we've got enough rice balls.'` | “还可以追加杯面和饭团。” | 漏译（"已经有了"→"可以追加"） |
| 11 | `yozora_hika_108f` 87 / 87 | **鼻先**をくすぐるように近づけられるのは嫌じゃないが…いきなり「**くさっ！？**」とか言い出しそうで恐い。 | `…Hikari's nose would get tickled, but I was afraid…` | …被小光的鼻尖摩挲自己的**脖子**，但还是很担心被她**闻到什么异味**。 | 擅加"脖子"、改述（"她说好臭"→"她闻到异味"） |
| 12 | `yozora_hika_110b` 45（又 92）/ 45（又 87） | 「おまえのほっぺも**すべすべ**だっつーの」 | `'Your cheeks are smooth too, you know.'` | “我也**蹭蹭**你的小脸蛋。” | 错译（光滑→蹭） |
| 13 | `yozora_hika_110d` 54 / 55 | **じゃれついてくるひかりを抱き締める**。（我抱住她） | `I hugged her back.` | 小光半开玩笑地**抱紧了我**。 | 主客颠倒 |

**saya 线（2 条）**

| # | 位置 | 原版日文 | Steam 英文 | 官中 | 问题类型 |
|---|---|---|---|---|---|
| 14 | `yozora_saya_102d` 10 / 26 | 「**なにが**だ？」（承接上句「これでいいんだよね？」） | `'What is?'` | “**怎么了**？” | 指代丢失 |
| 15 | `yozora_saya_107e` 68 / 73 | 「**通い妻**か……」 | `'Commuter wife, eh...'` | “**小老婆**……” | 错译（通勤妻→妾） |

**ori 线（2 条）**

| # | 位置 | 原版日文 | Steam 英文 | 官中 | 问题类型 |
|---|---|---|---|---|---|
| 16 | `yozora_ori_124` 98 / 98 | 甘やかされ慣れているせいか、**レベル判定できる**らしい。 | `…she could grade people on how much…` | 早已习惯了顺从织姬的**吉冈动作张弛有度**。 | 主语错成"吉冈"、语义不通 |
| 17 | `yozora_ori_124` 110 / 110 | **両親の許可**とは、来週に迫った合宿旅行の件だ。 | `She needed permission to go on the club trip next week.` | **吉冈**指的是下周集训旅行的事情。 | 凭空添加主语"吉冈" |

**koro 线（11 条）**

| # | 位置 | 原版日文 | Steam 英文 | 官中 | 问题类型 |
|---|---|---|---|---|---|
| 18 | `yozora_koro_116` 33 / 33 | 「あのことだけじゃなくて。試験に合格発表と、目白押しだったからね」 | `'It's not just that. Remember what we talked about after seeing your test results?'` | “我指的不是那件事，而是你成功考上明光和我们一起举办**庆功宴**。” | 内容替换＋增译（"庆功宴"原文无） |
| 19 | `yozora_koro_116` 106 / 106 | 「ここは**セーフ**だから」 | `'It's safe if it's right here.'` | “这里**不算是接吻**。” | 改意（安全区→不算接吻） |
| 20 | `yozora_koro_116` 112 / 112 | 逃げようともせず、そのまま受け止める。 | `I didn't run away and just let it happen.` | 我没有逃避，而是默默承受**她的索取**。 | 增译 |
| 21 | `yozora_koro_125` 9 / 9 | 「受信機とアンテナだけは特殊だし、値段もそこそこするから仕方ないよ」 | `'I'm not surprised, both the receiver and antenna are specialized equipment…'` | “…价格也不算太低，也难怪**校方无法提供**。” | 增译 |
| 22 | `yozora_koro_125` 10 / 10 | 最初からそのへんはアテにしていなかった。 | `I knew our chances of getting the antenna were slim.` | 我从一开始就没有指望**诸美泽**能提供这些。 | 擅加专名 |
| 23 | `yozora_koro_128` 15 / 15 | 工業系の学校は上下関係に厳しいと聞いているから**尚更**だ。 | `…the older students were really tough…` | 尤其听说工业学校非常注重上下关系，就**更不必担心**什么了。 | **语义反转**（"更是如此"→"不必担心"） |
| 24 | `yozora_koro_130_ep1` 49 / 49 | …**難易度を高めに設定**したようだが、概ね好評のようだ。 | `The bar was set high because most participants were astronomy fans…` | 由于…参加者多为天文爱好者，所以**术语相对较多**，但仍旧收到了一致好评。 | 错译（难度→术语） |
| 25 | `yozora_koro_130_ep1` 145 / 145 | 「懐かしいな。そんなこともあったっけ」 | `'Wow, that brings back memories. Did we really do that?'` | “真令人怀念啊，**确实是你刻下的呢**。” | 无中生有（原文无"刻"） |
| 26 | `yozora_koro_130_ep1` 171 / 171 | 恋が**愛**になり、想いのカタチが変わっても、ずっと―― | `Even if it changed, even if our thoughts changed, may our love last.` | 即使从**爱情化作亲情**，情感的形式有所转变，也要永远持续…… | 擅加原义（"亲情"原文与英文皆无） |
| 27 | `yozora_koro_132_ep2` 78 / 76 | **あっさりとした幕切れ**。 | `Without much ado, the curtain fell.` | **该做的很快就做完了**。 | 错译（干脆收束→事情办完） |
| 28 | `yozora_koro_132_ep2` 135 / 133 | これから先、宇宙をみる**目**はどんなものに変わっていくのだろう。 | `How would we look at the universe in the future, I wondered.` | 未来，**宇宙的外观**究竟会变成什么样？ | 错译（观测视角→外观） |

### 更轻的措辞级出入（供参考）

`yozora_hika_103e` 44 / 41（「一番変わった部分はそこだけど」→ 直写"**胸部**"，属可接受的显化，可由紧邻台词确定）、`yozora_hika_103h` 45 / 45（增"一边问"）、`yozora_hika_110b` 112 / 107（「乙女心」→"作为女孩子"，英文作 `pure-hearted virgin` 亦与原文有出入）、`yozora_hika_110d` 21 / 21（「結構いいもんだな」→"真的好温暖啊"）、`yozora_koro_132_ep2` 143（增"去年"）/ 219（「見た」→"听到"）、`yozora_koro_116` 82（增"她话中的含义"）。

### 需要决策的问题

1. **是否修正？** 修正意味着改动 Steam 官方译文，与 `README.md`"Steam 原有文本保持官方译文不变"的原则冲突；不修正则这些句子会随补丁一起呈现给玩家。
2. **若修正，用词口径如何对齐？** 本补丁的还原文本与官方译文风格不同，混用可能突兀。
3. **覆盖面不完整**：发现手段是人工复核，只覆盖了差分接缝的**无语音句**；**有语音台词**、以及**非接缝区域**的句子未做同样检查。

---

## 遗留待办

- **实机验证** 31 个重建接缝（优先 6 个机制组场景：`saya_101i`、`saya_102b`、`ori_114b/116/128c/130`、`koro_114b`），对照 `resource/seam-handling.json`
- **质量 pass**：既有 6 个 koro 还原场景（`115_H/121_H/124_H/126_H/127/131_H`）里 ころな 的**自称**仍作
  `来露娜`（与旁白指代混在一起，需逐条区分）；ひかり 的 `あたし` 我们作 `人家`、官中同场景作 `我`
- `yozora_hika_103g_H` 第 196 行有一句**译注**（`（译注：…）`）会直接显示给玩家 —— 是否删除待定
- `doc/pna-resources.md` 里 `0x34` 的一句口径与 `tool/ws2disasm.py` 的解析不一致，需实测后更正
- 官方 `.lng` 自身有一处 `「……」`（`yozora_saya_103c_E` 第 160 行），按"官方原样保留"未动
