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

- **讀取來源：** OpenCode、Claude Code 或 Codex 保存在本機的 session history。
- **整理報告：** 使用你本機安裝的 `opencode run`。
- **沒有 OpenCode？** 可以使用 `--no-llm` 產生較簡單的結構化報告。

報告內容會由你本機安裝的 `opencode run` 協助整理；讀取 Claude Code 或 Codex 的紀錄
不需要安裝它們的 CLI。

```bash
pipx install iiwi                 # 或：pip install iiwi

iiwi doctor                       # 檢查環境是否準備完成
iiwi daily                        # 審閱昨天、今天與阻礙事項
iiwi report --period last-week    # 產生上週報告
```

報告預設寫到 `reports/`。加上 `--dry-run` 可以直接在終端機預覽，不會寫入檔案。

## 互動選單

不想記參數的話，直接執行 `iiwi`。主選單提供 Review Activity、Daily Standup、
Generate Report、History、Check Setup 與 Settings；想查看所有指令時可以使用 `iiwi --help`。

**Generate Report** 可以調整報告設定、確認 Iiwi 找到的 sessions，再產生報告。
**Review Sessions** 會依 repository 整理工作，讓你快速保留或排除要放進回報的內容：

```text
Review Sessions   6 / 6 selected │ 252 / 252 msgs
══════════════════════════════════════════════════════
Select sessions to include in the report:

  1. ▾ ████████████  71% ● iiwi   3 / 3    Aug 5 │ 180 msgs
▶      ████░░░░░░░░  24% ● Add the interactive menu Aug 5 │ 60 msgs
       ████░░░░░░░░  24% ● Redact before writing    Aug 5 │ 60 msgs
       ████░░░░░░░░  24% ● Group worktrees          Aug 5 │ 60 msgs
  2. ▸ ████░░░░░░░░  24% ● obsidian-wiki   2 / 2    Aug 4 │ 60 msgs
  3. ▸ █░░░░░░░░░░░   5% ● dotfiles   1 / 1         Aug 3 │ 12 msgs

↑↓ jk │ ←→ hl │ Space Toggle │ p Preview │ e Exclude │ a All │ g Generate │ / Search │ ? Help │ b Back
```

**Daily Standup**，或 `iiwi daily`，會開啟 Yesterday / Today / Blockers 的快速審閱；
**History** 則會列出 Iiwi 已經產生過的報告。

真正寫出報告前，Quick Review 讓你保留、修改、排序、拆分或新增工作項目，確保最後的 Markdown
就是你想分享的內容。完整快捷鍵、報告模式與失敗時的處理方式，請見
[Quick Review 指南](https://github.com/mike840609/iiwi/blob/main/docs/evidence-first-quick-review.md)。
Daily Standup 的完整說明請見
[Daily Standup 指南](https://github.com/mike840609/iiwi/blob/main/docs/daily-standup.md)。

## 指令

```bash
iiwi doctor                       # 檢查環境是否準備完成
iiwi daily                        # 審閱昨天、今天與阻礙事項
iiwi scan --period last-week      # 預覽 Iiwi 找到的 sessions
iiwi report --period last-week    # 產生上週報告
iiwi history                      # 列出已產生的報告
iiwi update                       # 檢查 PyPI 是否有新版
iiwi run                          # 使用逐步引導模式
```

| 參數 | 作用 |
|---|---|
| `--harness claude-code` / `--harness codex` | 改讀 Claude Code 或 Codex 的 sessions |
| `--no-llm` | 不使用 OpenCode 撰寫敘事內容，改產生結構化報告 |
| `--sanitize` | 使用更強的去敏，適合隱私優先於報告細節時 |
| `--dry-run` | 印出報告，不寫入檔案 |
| `--json` | 對支援的指令輸出去敏後的機器可讀格式 |

`iiwi --help` 會列出所有指令與選項。偏好逐步引導的話可用 `iiwi run`；腳本中則直接呼叫需要的
子指令即可。

## 設定

每項設定的讀取順序是：環境變數、設定檔、預設值。

```bash
iiwi config init                                          # 逐項詢問
iiwi config set harnesses.opencode.cli.model deepseek-r1  # 寫入單一設定
iiwi config list                                          # 列出所有設定與來源
iiwi config unset report.timezone                         # 回到預設值
```

完整設定清單與對應的環境變數名稱，請見
[Configuration](https://github.com/mike840609/iiwi/blob/main/docs/configuration.md)。

## 隱私

讀取 sessions、去敏與產生報告都在你的電腦上完成。Iiwi 會把去敏後的 session 內容交給本機安裝的
`opencode run`，不需要 API key。`iiwi update` 會連線到 PyPI 檢查是否有新版。

報告仍可能包含私人目標、檔名、指令與完整工作路徑，因此分享前請先確認內容。完整資料流向與目前限制
請見
[Privacy and security](https://github.com/mike840609/iiwi/blob/main/docs/privacy.md)。

## 文件

以下文件皆為英文版本。

| 頁面 | 內容 |
|---|---|
| [CLI reference](https://github.com/mike840609/iiwi/blob/main/docs/cli-reference.md) | 所有指令、選項與結束代碼 |
| [Daily Standup](https://github.com/mike840609/iiwi/blob/main/docs/daily-standup.md) | Yesterday／Today／Blockers 審閱、更新、警告與輸出 |
| [Quick Review 指南](https://github.com/mike840609/iiwi/blob/main/docs/evidence-first-quick-review.md) | 工作項目審閱、報告模式、失敗處理與目前限制 |
| [Configuration](https://github.com/mike840609/iiwi/blob/main/docs/configuration.md) | 設定檔、環境變數與優先順序 |
| [Privacy and security](https://github.com/mike840609/iiwi/blob/main/docs/privacy.md) | 資料流向、去敏邊界，以及報告仍會包含什麼 |
| [Security policy](https://github.com/mike840609/iiwi/blob/main/SECURITY.md) | 威脅模型與漏洞回報方式 |
| [Usage guides](https://github.com/mike840609/iiwi/blob/main/docs/guides.md) | 統計期間、subagent、repository 分組與輸出處理 |
| [Usage statistics](https://github.com/mike840609/iiwi/blob/main/docs/usage-statistics.md) | 使用量區塊的產生方式與期間但書 |
| [Support and limits](https://github.com/mike840609/iiwi/blob/main/docs/limitations.md) | 各 harness 的完整但書清單 |
| [Architecture](https://github.com/mike840609/iiwi/blob/main/docs/architecture.md) | 報告從讀取到寫出的完整流程 |
| [Releasing](https://github.com/mike840609/iiwi/blob/main/docs/releasing.md) | 發布流程 |

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
