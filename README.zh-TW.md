# Iiwi

**Iiwi** · /ˈiː.wiː/ "ee-wee"

**把 coding-agent 的工作紀錄整理成清楚的工程報告。**

[![CI](https://github.com/mike840609/iiwi/actions/workflows/ci.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/ci.yml)
[![Release](https://github.com/mike840609/iiwi/actions/workflows/release.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/iiwi)](https://pypi.org/project/iiwi/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://pypi.org/project/iiwi/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/mike840609/iiwi/blob/main/LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/mike840609/iiwi/pulls)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mike840609/iiwi)

[English](https://github.com/mike840609/iiwi/blob/main/README.md) | 繁體中文

![Iiwi — 看見你的 agent 做了什麼](https://github.com/mike840609/iiwi/raw/refs/heads/main/docs/assets/iiwi-banner.jpg)

你已經把工作做完了，Iiwi 幫你把它整理成可以回報的內容。

Iiwi 會讀取 OpenCode、Claude Code 與 Codex 留下的工作紀錄，找出你做過什麼，整理成報告草稿。
挑出重要內容、稍微修改後，就能產生一份可以分享給團隊的 Markdown 報告。

- **跨專案都能用。** Iiwi 會找到你在不同專案留下的 coding-agent 工作紀錄。
- **相關工作放在一起。** 同一個 repository 的工作會整理在一起。
- **分享前由你確認。** 挑出重要內容並修改後，再產生最後的報告。
- **保護敏感資訊。** 寫出報告前，會先移除常見的機密字串樣式。

## 快速開始

需要 Python 3.11 以上與 `git`，再加上一個 harness：OpenCode（預設，需要 `opencode`
執行檔），或 Claude Code / Codex（不需命令列工具，只要有可讀的逐字紀錄存放處
`~/.claude/projects` 或 `~/.codex`）。

```bash
pipx install iiwi                 # 或：pip install iiwi

iiwi doctor                       # harness 準備好了嗎？
iiwi daily                        # 審閱昨天、今天與阻礙事項
iiwi report --period last-week    # 產生報告
```

報告預設寫到 `reports/` 底下。加上 `--dry-run` 會把報告印到終端機，而不寫入檔案。

## 互動選單

不想記參數的話，直接執行 `iiwi`：

```text
$ iiwi
 ___ _        _
|_ _(_)_ __ _(_)
 | || \ V  V / |
|___|_|\_/\_/|_|                                v0.9.1
══════════════════════════════════════════════════════
Turn coding-agent sessions into engineering reports
github.com/mike840609/iiwi

▶ Review Activity
  Daily Standup
  Generate Report
  History
  Check Setup
  Settings

↑↓ jk │ Enter Select │ 1-6 │ ? Help │ q Quit
```

選擇 **Generate a report** 後會一次列出所有設定，不再逐題詢問：`↑↓` 移動，`←→` 改值，
清單下方那行會說明游標所在的設定實際做什麼。按 `g` 產生報告，或按 `r` 先進入
**Review sessions**，它會依每個 repository 在這段期間實際佔掉多少對話量排出長條：

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

選擇 **History** 會列出工具產生過的所有報告，最新的在前。
`↑↓` 移動，Enter 顯示該筆的完整輸出路徑。

選擇 **Daily Standup**，或執行 `iiwi daily`，會從本地時區的昨天午夜開始掃描所有已啟用的
harness，並開啟 Yesterday、Today、Blockers 三區的 Quick Review。Preview 與 Generate
使用同一份已審閱 Markdown，檔名為 `daily-standup-YYYY-MM-DD.md`。來源警告、Today 建議與
同日審閱狀態保留方式請見 [Daily Standup 指南](https://github.com/mike840609/iiwi/blob/main/docs/daily-standup.md)。

`Space` 切換整個 repository 或單一 session，`p` 預覽（已去敏的）逐字紀錄，`e` 把某個
repository 排除在之後所有掃描之外。你的選取會依期間記住。

## 指令

```bash
iiwi doctor                       # harness 準備好了嗎？
iiwi daily                        # 審閱昨天、今天與阻礙事項
iiwi scan --period last-week      # 預覽工作階段如何分組
iiwi report --period last-week    # 產生報告
iiwi history                      # 列出已產生過的報告
iiwi update                       # 檢查 PyPI 是否有新版
iiwi run                          # 同樣的問題，改成逐題詢問
```

| 參數 | 作用 |
|---|---|
| `--harness claude-code` / `--harness codex` | 改讀其他 harness 的工作階段，敘事內容仍由本機的 `opencode run` 撰寫 |
| `--no-llm` | 產生決定性的結構化報告，不論是否安裝 OpenCode 都可使用 |
| `--sanitize` | 使用 OpenCode 的強力遮蔽，但會刻意移除大部分工作 evidence |
| `--dry-run` | 把報告印出來而不寫入檔案 |
| `--json` | `scan`、`doctor`、`history`、`update` 的去敏機器可讀輸出（stdout 被導向時為預設） |

`iiwi --help` 會列出所有指令；偏好被逐題詢問的話就用 `run`。在腳本中請直接呼叫子指令，
因為沒有終端機可以作答時，選單會以狀態碼 3 結束，而不會去讀取 stdin。

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

一切都在本機完成：從磁碟讀取工作階段、清掉常見機密字串，再把去敏後的 transcript 交給本機
安裝的 `opencode run`。不需要 API key，唯一會用到網路的指令是 `update`。

報告仍可能包含私人目標、檔名、指令與完整路徑，分享前請務必檢查。完整資料流向與目前限制
請見
[Privacy and security](https://github.com/mike840609/iiwi/blob/main/docs/privacy.md)。

## 文件

以下文件皆為英文版本。

| 頁面 | 內容 |
|---|---|
| [CLI reference](https://github.com/mike840609/iiwi/blob/main/docs/cli-reference.md) | 所有指令、選項與結束代碼 |
| [Daily Standup](https://github.com/mike840609/iiwi/blob/main/docs/daily-standup.md) | Yesterday／Today／Blockers 審閱、更新、警告與輸出 |
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
