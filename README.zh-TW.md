# Iiwi

Iiwi · /ˈiː.wiː/ "ee-wee" — 為工程工作而生的 Agent Session Intelligence

探測 coding-agent 工作階段，浮現真正重要的工作。

ʻiʻiwi 是夏威夷的緋紅色旋蜜雀，彎長的喙能探到其他鳥觸及不了的花蜜。
本專案採用英語化的發音。

[![CI](https://github.com/mike840609/iiwi/actions/workflows/ci.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/ci.yml)
[![Release](https://github.com/mike840609/iiwi/actions/workflows/release.yml/badge.svg)](https://github.com/mike840609/iiwi/actions/workflows/release.yml)
[![PyPI](https://img.shields.io/pypi/v/iiwi.svg)](https://pypi.org/project/iiwi/)
[![Python](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://pypi.org/project/iiwi/)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](https://github.com/mike840609/iiwi/blob/main/LICENSE)
[![PRs Welcome](https://img.shields.io/badge/PRs-welcome-brightgreen.svg)](https://github.com/mike840609/iiwi/pulls)
[![Ask DeepWiki](https://deepwiki.com/badge.svg)](https://deepwiki.com/mike840609/iiwi)

[English](https://github.com/mike840609/iiwi/blob/main/README.md) | 繁體中文

Iiwi 把 coding-agent 的工作階段整理成給主管看的週報，替工程師省下時間。

![Agent 工作階段被分組為每週工程報告](https://github.com/mike840609/iiwi/raw/refs/heads/main/docs/assets/iiwi-overview.png)

## 特色

- **資料不會離開你的電腦。** 敘事式週報由本機安裝的 `opencode run` 撰寫，不需要網路請求，
  也不需要 API key。
- **在哪個資料夾都找得到。** 不受目前所在資料夾限制，涵蓋所有專案的工作階段。
- **依 repository 分組。** 同一個 repository 的 Git worktree 會合併成一筆，child 與
  subagent 工作階段也會歸到正確的 repository 底下。
- **寫出之前先去敏。** 產生報告或呼叫敘事式摘要之前，會先在本機檢查常見的機密字串樣式。

支援 OpenCode、Claude Code 與 Codex。

## 系統需求

- Python 3.11 以上。
- 可以用 `git` 執行的 Git。
- 一個 coding-agent harness：OpenCode（預設）、Claude Code 或 Codex。OpenCode 需要
  `opencode` 執行檔；Claude Code 與 Codex 不需要命令列工具，只需要一個可讀取的逐字紀錄
  存放處（`~/.claude/projects` 或 `~/.codex`）。

## 安裝

```bash
pipx install iiwi
```

也可以在一般的 Python 環境中使用 `pip install iiwi`。

## 快速開始

不帶任何參數執行，就會進入可以用方向鍵操作的終端選單：

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

選擇 **Generate a report** 後會先看到設定本身，游標就停在它所改動的值上，不需要從頭回答一連串
問題。**Generate report** 就排在設定下方，也可以直接按 `g`；清單底下有一行會說明游標所在那項
設定實際做什麼。按 `r` 進入 **Review sessions**：那裡會依 repository 分組，在 repository 上按
`Space` 可整組選取或取消，展開後也可以逐一切換 session。

```text
Generate Report
══════════════════════════════════════════════════════

  Harness      OpenCode
  Period       Aug 03 – Aug 10
▶ Detail       Full
  Subagents    Included
  Narrative    Enabled
  Sanitize     Off
  Dry run      Off

  Generate report

Full keeps every section. Brief drops files, sessions and usage.

↑↓ jk │ ←→ hl Change │ Enter Select │ r Review │ g Generate │ ? Help │ b Back
```

Review Sessions 會依每個 repository 在這段期間實際佔掉多少對話量排出長條，不必逐一打開
就能看出主要工作落在哪裡：

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

↑↓ jk │ ←→ hl │ Space Toggle │ a All │ g Generate │ / Search │ ? Help │ b Back
```

或直接下指令：

```bash
iiwi doctor                       # harness 準備好了嗎？
iiwi scan --period last-week      # 預覽工作階段如何分組
iiwi report --period last-week    # 產生報告
```

報告預設會在本機執行 `opencode run` 撰寫敘事式週報。加上 `--no-llm` 則產生決定性的結構化
報告，不論是否安裝 OpenCode，所有 harness 都可以使用：

```bash
iiwi report --period last-week --no-llm
```

輸出預設寫到 `reports/` 底下。要換 harness 就加上 `--harness claude-code` 或
`--harness codex`；敘事式預設對所有 harness 一致，會讀取該 harness 的工作階段，並同樣
呼叫本機的 `opencode run`。

如果仍想使用逐題詢問的線性流程，`run` 指令會依序問同樣的問題，並在寫出報告前先預覽掃描
結果：

```bash
iiwi run
```

加上 `--dry-run` 會把報告印到終端機，而不寫入檔案。

用 `iiwi --help` 查看指令清單。在腳本中請直接呼叫子指令，因為沒有終端機可以
作答時，選單會以狀態碼 3 結束，而不會去讀取 stdin。

## 文件

以下文件皆為英文版本。

| 頁面 | 內容 |
|---|---|
| [CLI reference](https://github.com/mike840609/iiwi/blob/main/docs/cli-reference.md) | 所有指令、選項與結束代碼 |
| [Configuration](https://github.com/mike840609/iiwi/blob/main/docs/configuration.md) | 設定檔、環境變數與優先順序 |
| [Privacy and security](https://github.com/mike840609/iiwi/blob/main/docs/privacy.md) | 資料流向、去敏邊界，以及報告仍會包含什麼 |
| [Usage guides](https://github.com/mike840609/iiwi/blob/main/docs/guides.md) | 統計期間、subagent、repository 分組與輸出處理 |
| [Usage statistics](https://github.com/mike840609/iiwi/blob/main/docs/usage-statistics.md) | 使用量區塊的產生方式與期間但書 |
| [Support and limits](https://github.com/mike840609/iiwi/blob/main/docs/limitations.md) | 各 harness 的完整但書清單 |
| [Releasing](https://github.com/mike840609/iiwi/blob/main/docs/releasing.md) | 發布流程 |

## 隱私

OpenCode 預設使用 raw export，讓報告保留可用的工作細節。Iiwi 會先在本機清理常見
機密，再把分組、去敏後的 transcript 交給本機安裝的 `opencode run` 撰寫敘事式週報；資料不會
離開本機，也不需要 API key。要決定性的結構化報告可用 `--no-llm`；需要 OpenCode 強力遮蔽時
可加上 `--sanitize`，但這會刻意移除大部分工作 evidence。

報告仍可能包含私人目標、檔名、指令與完整路徑，分享前請務必檢查。完整的資料流向與目前限制
請見
[Privacy and security](https://github.com/mike840609/iiwi/blob/main/docs/privacy.md)。

## 設定

每項設定的讀取順序是：環境變數、設定檔、預設值。`config init` 會逐項詢問所有設定，
`config set` 則寫入單一項目：

```bash
iiwi config init                                          # 逐項詢問
iiwi config set harnesses.opencode.cli.model deepseek-r1  # 寫入單一設定
iiwi config list                                          # 列出所有設定與來源
iiwi config unset report.timezone                         # 回到預設值
```

完整設定清單與對應的環境變數名稱，請見
[Configuration](https://github.com/mike840609/iiwi/blob/main/docs/configuration.md)。

## 架構

<!-- 這裡用 render 好的圖而非 mermaid 區塊：GitHub 手機 App 與 PyPI 會把 mermaid
     原始碼當純文字顯示。要修改請編輯 docs/assets/architecture.mmd，
     並依該檔開頭的指令重新產生 SVG。 -->

![架構圖：CLI 讀取三種工作階段來源之一，掃描並解析 repository，再擷取、去敏、摘要並寫出報告](https://github.com/mike840609/iiwi/raw/refs/heads/main/docs/assets/architecture.svg)

Iiwi 會依 harness 選用三種來源之一，只載入與指定期間重疊的工作階段，依
repository 分組，再對佐證資料做去敏與摘要，最後以僅擁有者可讀寫的權限原子性地寫出
Markdown 報告。

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
