# Iiwi

**Iiwi** · /ˈiː.wiː/ "ee-wee" — 把你的 coding-agent 工作階段整理成每週工程報告，
過程中資料完全不離開你的電腦。

[![CI](https://github.com/mike840609/iiwi/actions/workflows/ci.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/ci.yml)
[![Release](https://github.com/mike840609/iiwi/actions/workflows/release.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/iiwi.svg)](https://pypi.org/project/iiwi/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://pypi.org/project/iiwi/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/mike840609/iiwi/blob/main/LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/mike840609/iiwi/pulls)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mike840609/iiwi)

[English](https://github.com/mike840609/iiwi/blob/main/README.md) | 繁體中文

![Agent 工作階段被分組為每週工程報告](https://github.com/mike840609/iiwi/raw/refs/heads/main/docs/assets/iiwi-overview.png)

每週工作回報，其實是把已經做過的事再寫一次。Iiwi 直接讀取 coding agent 已經留下的工作階段
紀錄，依 repository 分組，替你把報告寫出來。支援 OpenCode、Claude Code 與 Codex。

- **資料不會離開你的電腦。** 敘事式週報由本機的 `opencode run` 撰寫，不需要網路，也不需要 API key。
- **在哪個資料夾都找得到。** 涵蓋所有專案，不受目前所在資料夾限制。
- **依 repository 分組。** 同一 repository 的 worktree 合併成一筆，child 與 subagent 工作階段也歸在一起。
- **先去敏再寫出。** 產生任何內容之前，先在本機清掉常見的機密字串樣式。

## 快速開始

需要 Python 3.11 以上與 `git`，再加上一個 harness：OpenCode（預設，需要 `opencode`
執行檔），或 Claude Code / Codex（不需命令列工具，只要有可讀的逐字紀錄存放處
`~/.claude/projects` 或 `~/.codex`）。

```bash
pipx install iiwi                 # 或：pip install iiwi

iiwi doctor                       # harness 準備好了嗎？
iiwi report --period last-week    # 產生報告
```

報告預設寫到 `reports/` 底下。加上 `--dry-run` 會把報告印到終端機，而不寫入檔案。

## 互動選單

不想記參數的話，直接執行 `iiwi`：

```text
$ iiwi
Iiwi
══════════════════════════════════════════════════════
Turn coding-agent sessions into engineering reports

▶ Generate Report
  Browse Sessions
  Check Setup
  Settings

↑↓ jk │ Enter Select │ 1-4 │ ? Help │ q Quit
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

`Space` 切換整個 repository 或單一 session，`p` 預覽（已去敏的）逐字紀錄，`e` 把某個
repository 排除在之後所有掃描之外。你的選取會依期間記住。

## 指令

```bash
iiwi doctor                       # harness 準備好了嗎？
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
| [Configuration](https://github.com/mike840609/iiwi/blob/main/docs/configuration.md) | 設定檔、環境變數與優先順序 |
| [Privacy and security](https://github.com/mike840609/iiwi/blob/main/docs/privacy.md) | 資料流向、去敏邊界，以及報告仍會包含什麼 |
| [Security policy](https://github.com/mike840609/iiwi/blob/main/SECURITY.md) | 威脅模型與漏洞回報方式 |
| [Usage guides](https://github.com/mike840609/iiwi/blob/main/docs/guides.md) | 統計期間、subagent、repository 分組與輸出處理 |
| [Usage statistics](https://github.com/mike840609/iiwi/blob/main/docs/usage-statistics.md) | 使用量區塊的產生方式與期間但書 |
| [Support and limits](https://github.com/mike840609/iiwi/blob/main/docs/limitations.md) | 各 harness 的完整但書清單 |
| [Releasing](https://github.com/mike840609/iiwi/blob/main/docs/releasing.md) | 發布流程 |

## 架構

<!-- 這裡用 render 好的圖而非 mermaid 區塊：GitHub 手機 App 與 PyPI 會把 mermaid
     原始碼當純文字顯示。要修改請編輯 docs/assets/architecture.mmd，
     並依該檔開頭的指令重新產生 SVG。 -->

![架構圖：CLI 讀取三種工作階段來源之一，掃描並解析 repository，再擷取、去敏、摘要並寫出報告](https://github.com/mike840609/iiwi/raw/refs/heads/main/docs/assets/architecture.svg)

Iiwi 只載入與指定期間重疊的工作階段，依 repository 分組，對佐證資料做去敏與摘要，
最後以僅擁有者可讀寫的權限原子性地寫出 Markdown 報告。

## 名字的由來

ʻiʻiwi 是夏威夷的緋紅色旋蜜雀，彎長的喙能探到其他鳥觸及不了的花蜜 — 正如這個工具對 agent
留下的工作階段所做的事。發音採英語化的唸法「ee-wee」。

## 開發

```bash
git clone https://github.com/mike840609/iiwi.git
cd iiwi
uv sync --locked --extra dev

uv run pytest --cov=iiwi --cov-fail-under=80
uv run ruff check .
uv run pyright
```

## 授權

MIT
