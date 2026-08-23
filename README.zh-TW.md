# Iiwi

**Iiwi** · /ˈiː.wiː/ "ee-wee"

**把 AI coding 工作整理成清楚的工程報告。**

[![CI](https://github.com/mike840609/iiwi/actions/workflows/ci.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/ci.yml)
[![Release](https://github.com/mike840609/iiwi/actions/workflows/release.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/iiwi)](https://pypi.org/project/iiwi/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://pypi.org/project/iiwi/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/mike840609/iiwi/blob/main/LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/mike840609/iiwi/pulls)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mike840609/iiwi)

[English](https://github.com/mike840609/iiwi/blob/main/README.md) | 繁體中文

![Iiwi — 看見你的 agent 做了什麼](https://github.com/mike840609/iiwi/raw/refs/heads/main/docs/assets/iiwi-banner.jpg)

你已經把工作做完了，Iiwi 會把 coding agent 留下的工作紀錄整理成你可以確認、修改與分享的回報內容。

Iiwi 支援 OpenCode、Claude Code 與 Codex。它會找出你做過什麼、把相關工作整理在一起，
再產生 Markdown 報告，不用自己重新翻一遍過去的 agent 對話。

- **跨專案都能用。** Iiwi 會找到你在不同專案留下的 coding-agent 工作紀錄。
- **相關工作放在一起。** 同一個 repository 的工作會整理在一起。
- **最後內容由你決定。** 挑出重要內容並修改後，再產生最後的報告。
- **保護敏感資訊。** 寫出報告前，會先移除常見的機密字串樣式。

## 怎麼運作

1. **讀取** — Iiwi 找出 OpenCode、Claude Code 或 Codex 保存在本機的 AI coding 工作紀錄。
2. **確認** — 保留、修改、排序或移除真正重要的工作。
3. **產生** — 建立一份可以直接分享給團隊的 Markdown 報告。

## 最後會得到什麼

例如，一份確認過的報告可以長這樣：

```markdown
# 每週工程更新

## My Project
- 簡化報告操作流程，讓 review 更容易完成。
- 加入 Claude Code 與 Codex session 支援。
- 修正 CI 中的文件檢查。

## Blockers
- None
```

## 快速開始

需要 Python 3.11 以上與 `git`。

```bash
pipx install iiwi                 # 或：pip install iiwi

iiwi doctor                      # 檢查 Iiwi 是否能讀取目前環境
iiwi                             # 開啟互動選單
```

進入選單後，只要選擇你想做的事，Iiwi 會一步步帶你完成。

兩個常用捷徑：

```bash
iiwi daily                       # 準備今天的 standup 更新
iiwi report --period last-week   # 準備上週報告
```

報告預設會存到 `reports/`。

## 使用互動選單

不想記指令或參數時，直接執行 `iiwi`。

你可以從選單查看最近的 AI coding 工作、準備 standup、產生報告、查看過去的報告、
檢查環境，以及修改設定。

產生報告時，Iiwi 會先把找到的工作列出來。挑出要保留的內容、修改需要調整的地方，
最後由 Iiwi 寫出 Markdown 報告。

完整的 review 流程與快捷鍵請見
[Quick Review 指南](docs/evidence-first-quick-review.md)；Daily Standup 的完整流程請見
[Daily Standup 指南](docs/daily-standup.md)。

## 直接使用 CLI

互動選單最適合第一次使用。如果你偏好直接下指令，平常最常用的是：

```bash
iiwi doctor                       # 檢查環境
iiwi daily                        # 準備 daily standup
iiwi report --period last-week    # 產生上週報告
```

其他指令可以用 `iiwi --help` 查看；完整指令、參數、範例與 exit code 請見
[CLI reference](docs/cli-reference.md)。

## 設定

大多數情況下，不需要先改任何設定就可以開始使用 Iiwi。

如果想調整 model、timezone、路徑或預設行為，可以使用：

```bash
iiwi config init                  # 逐步調整設定
iiwi config list                  # 查看目前實際使用的設定
```

完整設定與進階用法請見 [Configuration](docs/configuration.md)。

## 隱私

Iiwi 會在你的電腦上讀取並處理 session history。如果使用 AI drafting，Iiwi 會先移除
常見的機密字串樣式，再把內容交給你設定的 CLI。之後該 CLI 如何處理內容，則取決於它自己的設定。

報告仍可能包含私人目標、檔名、指令與工作路徑，因此分享前請先確認內容。

完整資料流向、去敏方式與目前限制請見 [Privacy and security](docs/privacy.md)。

## 文件

日常使用需要的細節都放在下面的文件，不塞在 README 裡：

- [CLI reference](docs/cli-reference.md) — 指令、參數、範例與 exit code
- [Quick Review 指南](docs/evidence-first-quick-review.md) — review 操作與報告流程
- [Daily Standup](docs/daily-standup.md) — Yesterday / Today / Blockers 流程
- [Configuration](docs/configuration.md) — 設定、model、路徑與環境變數
- [Privacy and security](docs/privacy.md) — 哪些內容留在本機，以及報告仍可能包含什麼
- [Support and limits](docs/limitations.md) — 各 harness 目前的限制

以上文件目前為英文。開發與更深入的技術細節可見
[Architecture](docs/architecture.md)、[Security policy](SECURITY.md)，以及其他 [`docs/`](docs/) 文件。

## 名字的由來

ʻiʻiwi 是夏威夷的緋紅色旋蜜雀，彎長的喙能探到其他鳥觸及不了的花蜜 — 正如這個工具對 agent
留下的工作階段所做的事。發音採英語化的唸法「ee-wee」。

## 開發

```bash
git clone https://github.com/mike840609/iiwi.git
cd iiwi
uv sync --locked --extra dev                    # 安裝專案本身與開發工具

uv run iiwi                                     # 執行你目前修改中的版本
uv run pytest --cov=iiwi --cov-fail-under=80    # 測試，含 CI 要求的覆蓋率門檻
uv run ruff check .                             # lint
uv run pyright                                  # 型別檢查
```

後三行就是 CI 實際執行的指令，本機過了 PR 就會過。

### 名稱寫法

同一個名字依出現的位置決定大小寫：

| 用在哪 | 寫法 |
|---|---|
| 發行套件、CLI、URL、應用程式目錄 | `iiwi` |
| Python package 與 import | `iiwi` |
| 散文 | `Iiwi` |
| 環境變數 | `IIWI_` 前綴 |
| 錯誤基底類別 | `IiwiError` |

## 授權

MIT
