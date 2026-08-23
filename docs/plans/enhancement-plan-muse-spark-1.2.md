# 效能優化計劃 — iiwi 運行緩慢分析與修正

> 狀態：待審核（分析完成，未開始實作）
> 觸發：用戶回報「當前的運行很慢」
> 測量時間：2026-08-19
> 分析者：Sisyphus + 2 個 explore 並行代理

---

## 1. 現況測量（實測數據）

| 場景 | 指令 | 耗時 | 結果 |
|------|------|------|------|
| 測試套件 | `pytest -q` (1407 tests) | **5.83s** | 通過，P95 單測 <0.25s，整體良好 |
| 掃描 | `iiwi scan --period last-week` | **>15s 仍未完成** | 15s 時 kill，仍在運行 |
| 掃描 verbose | `scan --period last-week --verbose` | **>15s** | 同上 |
| 報告 | `report --period last-week --dry-run --no-llm` | **>120s 超時** | 直接 timeout |
| 冷啟動 | `iiwi --help` | ~0.22s | 正常 |
| DB 體積 | `~/.local/share/opencode/opencode.db` | **990 MB** (1GB) | 極大 |

**結論**：測試本身不慢（5.83s 對 1407 測算正常），慢的是**真實數據下的 scan/report**。`--help` 很快，代表 import 成本低，瓶頸在 **I/O + 子進程 + 重複計算**，且隨 `last-week` 的 session 數量線性放大。

---

## 2. 根因分析（按影響排序）

### P0 — 直接導致 120s 超時

#### P0-1: OpenCode 每 session 一次同步子進程 + tempfile （`src/iiwi/harnesses/opencode/source.py:126-148`, `74-99`, `src/iiwi/process.py:58-92`）
- `discover()` 一次 `opencode db "<SQL>" --format json` 同步 `subprocess.run`，對 1GB DB 的 `SELECT ... WHERE time_created < X AND COALESCE(time_updated...) >= Y ORDER BY ...` 若無索引就是全表掃描。
- `load()` **每 session 一次** `opencode export <id>` → `tempfile.TemporaryDirectory` → `stdout_path` 文件 → `read_bytes().decode()` → `json.loads`。假設 last-week 有 100 sessions = 100 個 opencode 進程 + 100 次 tempfile + 100 次全量 JSON 解析。
- `CommandRunner.run()` 每次複製全量 `env={**os.environ, GIT_TERMINAL_PROMPT:0}` + `capture_output=True` 進記憶體，大 export（數 MB）全量緩衝。
- `src/iiwi/services/scan.py:34 _SESSION_LOAD_WORKERS = min(4, os.cpu_count() or 1)` 把「重型 opencode 進程」與「輕量 file-backed」混在同一 4 線程池，隊列排空慢。

#### P0-2: Claude/Codex 雙重全量讀 （`src/iiwi/harnesses/claude_code/source.py:69-148`, `src/iiwi/harnesses/codex/rollout_catalog.py:41-122`）
- `discover()` 做 `glob("*.jsonl")` + `glob("*/*/subagents/*.jsonl")` 兩次 sorted，對**每個文件** `stat().st_mtime` → `_head_hints` 再 `open().readline` 前 50 行逐行 `json.loads` → subagent 再 `meta_path.read_text + json.loads`。
- `load()` 又 `path.read_text(encoding=utf-8, errors=replace)` **全量讀**多 MB transcript + `_iter_records` 逐行 `splitlines + json.loads`。
- 即「discover 讀一半、load 再讀全量」**重複 I/O**，無快取、無 mmap、無 orjson。500 檔案 = 500 次 open + 500×50 次 JSON 解析。

#### P0-3: 報告鏈串行 + 遞歸 redaction（`src/iiwi/services/report.py:104-137`, `src/iiwi/security/redactor.py:10-47`）
- `_repository_evidence()` 對每個 session 串行：`extract_evidence()` → `model_dump(mode=json)` → `redact_value()` 遞歸 dict/list → 對**每個字串**執行 9 個 `re.sub`（`_PRIVATE_KEY` 帶 `re.DOTALL` 貪婪）→ `SessionEvidence.model_validate()`。
- 200 sessions × 100 段文字 = **18萬 次 regex**。`report --no-llm` 也必須走此路徑，與 LLM 無關。`build_grouped_transcript` 再對全量 transcript `redact_text` 一次。

### P1 — 高影響，last-week 放大成數十秒

#### P1-1: N+1 Git 熱點（`src/iiwi/repositories/resolver.py:42-95`, `155-194`, `218-281`）
- `RepositoryResolver._git()` 雖有 `dict[cwd][args]` 快取，但 `resolve()` 對每個**不同 cwd** 依序執行 `git -C <cwd> remote get-url origin` → `branch --show-current` → `rev-parse --git-common-dir`，各一次 `runner.run` 同步子進程。N 個不同 repo = 3N 次 git。
- `reattach_by_branch` 再對每個 live repo 執行 `git for-each-ref --format=%(refname) refs/heads refs/remotes`（`_branches_at`），雖有 `branch_cache` 去重，首次仍是 M 次 for-each-ref。
- `_worktree_paths_related` 對每個候選 × 每個 live 執行兩次 `Path.resolve(strict=False)`，O(C×M) 路徑解析。

#### P1-2: filter + deepcopy 三次遍歷（`src/iiwi/services/scan.py:192-209`, `src/iiwi/sessions/filtering.py:40-55`）
- 每 session 先掃描 activities 算 `missing_timestamp_count` 與 `_has_assistant_work_but_no_prompt`，再 `filter_session_to_period()` 做 `deepcopy(session)` 複製全部 activities。等同每 session 遍歷 activities **3 次 + 一次深拷貝**。

#### P1-3: Git env 複製與大 stdout 緩衝（`src/iiwi/process.py:58-92`）
- 每次 git/opencode 呼叫新建 `env={**os.environ,...}` 複製全量環境，對大 stdout 要求完整進記憶體再 `read_bytes().decode()`。

### P2 — 中影響，疊加助長

- `src/iiwi/security/redactor.py` 9 個全域 `re.compile` 常駐，每次 `redact_text` 鏈式 9 次 `.sub`。
- `src/iiwi/extraction/rules.py:50-53 is_verification_command()` 每條 command 先 `HEREDOC_PATTERN.search` 再遍歷 6 個 `TEST_COMMAND_PATTERNS`，10k 條 command = 70k 次 regex。
- `src/iiwi/summarizers/transcript.py:19-26 _session_sort_key()` 每次掃描全部 `activity.timestamp` 取 max，導致同樣 activities 被多次遍歷（scan 已遍歷過、report 又遍歷）。
- 註：`src/iiwi/extraction/pipeline.py` 的 dedup 已修復為 O(n) set 查找（見 `tests/unit/extraction/test_pipeline.py:656` 的 `test_extract_evidence_dedup_scales_linearly` 保護），**不再是主熱點**。

---

## 3. 修正計劃（分階段，風險由低到高）

### Phase 0: 儀表化（1-2 小時，不改邏輯，先讓數據說話）

**目標**：讓 `--verbose` 的 `PerformanceMetrics` 真實分佈可信，為後續優化提供基線與回歸閘門。

- [ ] 修正 `src/iiwi/services/scan.py:136` 的 `measure(EXPORT_SESSIONS)` 位置：目前在 `future.result()` 等待時計時，導致多 worker 時總時長坍縮到 wall-time 假象。改為在 `submit` 時記錄單 session wall-time 與排隊時長，或新增 `EXPORT_WAIT` stage。
- [ ] 為 `discover` / `export` 各加 `count("opencode_db_ms", ...)` 與 `count("export_p95_ms", ...)`，並在 `src/iiwi/cli.py` 的 verbose 表中輸出。
- [ ] 加 `hyperfine` / `pytest --durations` 基線：`hyperfine -w 2 'uv run iiwi scan --period last-week --harness opencode'` 分別對三 harness 計時。

**驗證**：`--verbose` 表顯示 `discover_sessions` 與 `export_sessions` 的真實佔比，`opencode.db` 查詢單次 P95。

**風險**：無。

---

### Phase 1: 快贏（Quick Wins，半天，預期 -30% ~ -50% wall-time）

**1A. 分離與放大 worker 池** (`src/iiwi/services/scan.py:34`)
- `file-backed` (claude/codex) 用 `min(16, cpu*2)`，`opencode` 保持 `min(4, cpu)` 但分池，避免重型進程阻塞輕量 I/O。
- 或：`_SESSION_LOAD_WORKERS = min(8, cpu*2)` + `opencode` 獨立 `ThreadPoolExecutor(max_workers=4)`。

**1B. 去除 discover→load 重複讀** (`src/iiwi/harnesses/claude_code/source.py`, `codex/rollout_catalog.py`)
- `_head_hints` / `_first_session_meta` 的前 50 行解析結果用 `lru_cache` 或回傳給 `load()` 重用，避免 load 再全量讀時重複解析頭部。
- `discover()` 回傳時攜帶 `file_mtime + head_hints`，`load()` 若文件未變直接重用。

**1C. Git 快取鍵優化** (`src/iiwi/repositories/resolver.py:42`)
- `_git_cache` key 目前是 `normalized_path(cwd)`，改為同時快取 `remote get-url origin` 的 `normalized_remote` 結果，避免同 remote 的不同 worktree 重複 `git remote` 調用。
- `_worktree_paths_related` 的 `Path.resolve` 結果快取到 `dict[str, Path]`，避免 O(C×M) 重複解析。

**驗證**：同數據集 `scan` 時間對比，unit test 綠。

---

### Phase 2: I/O 重點（1-2 天，預期 -50% ~ -70%）

**2A. OpenCode DB 查詢優化**
- 檢查 `opencode.db` 索引：`sqlite3 opencode.db ".indexes session" ".schema session"`，若 `time_created` / `time_updated` 無索引，提 issue 到 opencode 或本地加 `CREATE INDEX IF NOT EXISTS idx_session_time_created ON session(time_created)`。
- 若無法改 DB，改為 `SELECT id FROM session WHERE ...` 先拿 id，再按需 export，避免一次撈全 row。
- `discover()` 的 `json.loads` 改 `orjson`（若可用）或至少 `msgspec`，對 1GB DB 的 JSON 數十 MB 解析提升明顯。

**2B. 文件讀取流式化**
- `claude_code/source.py:150 load()` 與 `codex/mapper.py` 改用 `mmap` 或 `open(...).readline` 流式迭代，避免 `read_text()` 一次載入數 MB + 第二次 `splitlines()` 複製。
- `process.py:72` 的 `stdout_path` 模式已對大 export 用文件重定向，保持；但 `discover()` 的 `sessions.json` 也應保持文件模式（已是），確保不走 pipe 緩衝。

**2C. 避免 `deepcopy`**
- `src/iiwi/sessions/filtering.py:40 filter_session_to_period` 的 `deepcopy(session)` 改為只拷貝在週期內的 `activities` 子集（`copy.copy` + 切片），或直接構造新 `AgentSession`，避免複製數百條 activities 的深拷貝。

**驗證**：`pytest tests/unit/extraction/test_pipeline.py::test_extract_evidence_dedup_scales_linearly` 仍 <5s；`hyperfine` 顯示 discover 與 export 各階段顯著下降。

---

### Phase 3: Redaction 管線（半天，預期 report 階段 -40% ~ -60%）

**3A. 合併 regex**
- `src/iiwi/security/redactor.py:10-28` 的 9 個 `re.compile` 合併為單一 `re.compile("|".join(...))` 或至少用 `re.compile` 的 `sub` 一次遍歷代替 9 次鏈式 `sub`。`_PRIVATE_KEY` 的 `re.DOTALL` 單獨保留，其餘用 `re.MULTILINE` 單 pass。
- 為 `redact_text` 加 `functools.lru_cache(maxsize=4096)` 對短文本（<512 char）快取，命中率在重複命令/路徑場景高。

**3B. 減少 `redact_value` 遞歸**
- `redact_value` 在 `model_dump(mode=json)` 後對整個 dict 遞歸 redact，改為只 redact `evidence` 的 `text` 欄位（`goals/commands/outcomes` 的 `text`），而非整個序列化結構。或：`extract_evidence` 階段就對 `text` 做 redact，避免二次遍歷。
- `build_grouped_transcript` 的全量 `redact_text` 與 `report.py:121` 的二次 redact 去重，只保留一次。

**驗證**：`report --dry-run --no-llm --verbose` 的 `PREPARE_EVIDENCE` 與 `RENDER_REPORT` 階段對比。

---

### Phase 4: 並行與串行解耦（1 天）

**4A. Report 階段並行化**
- `src/iiwi/services/report.py:104 _repository_evidence` 的 `for repository_id, resolved_items` 串行改 `ThreadPoolExecutor` 或 `ProcessPool`（CPU 密集的 regex/redaction 適合多進程），或至少用 `concurrent.futures` 並行 `extract_evidence + redact`。
- `src/iiwi/services/scan.py:207 resolve()` 的 `self._resolver.resolve(filtered)` 目前串行在 load 迴圈內，改為批量：先收集所有 `filtered`，再並行 resolve（resolver 已有 cache，並行安全）。

**4B. 排序去重**
- `_session_sort_key` 在 `scan` 已計算過 max timestamp，結果應快取到 `AgentSession` 的 `computed` 欄位，避免 `transcript.py` 再掃描全部 activities。

**驗證**：多 repo (5-10) 的 report 並行效益，CPU 利用率從單核到多核。

---

### Phase 5: 長期結構（可選，視前 4 階段效果決定）

- **增量/快取層**：對 `discover` 結果按 `period` 快取到 `~/.cache/iiwi/discover-<hash>.json`，mtime 檢查失效。
- **Opencode 直連 SQLite**：若 `opencode db` CLI 始終是瓶頸，考慮直接用 `sqlite3` 讀 `opencode.db`（只讀），繞過 CLI 啟動成本。需處理 WAL 與鎖。
- **orjson/msgspec 全量替換**：`json.loads` 在大 payload 下的替換，預期 2-3x 提升。

---

## 4. 執行順序與預估收益

| 階段 | 工作量 | 預估收益（last-week） | 風險 | 優先級 |
|------|--------|------------------------|------|--------|
| Phase 0 儀表化 | 1-2h | 無直接收益，但為決策依據 | 無 | P0 |
| Phase 1 快贏 | 4h | -30%~50% | 低 | P0 |
| Phase 2 I/O | 1-2d | -50%~70%（含 Phase1 疊加可望 <15s） | 中（DB 索引需驗證） | P0 |
| Phase 3 Redaction | 4h | report 階段 -40%~60% | 低 | P1 |
| Phase 4 並行 | 1d | 多 repo 場景再 -30% | 中（並行正確性） | P1 |
| Phase 5 長期 | 2-3d | 增量後 <5s | 高 | P2 |

**目標基線**：`scan --period last-week` 從 >15s 降至 **<5s**，`report --dry-run --no-llm` 從 >120s 降至 **<10s**。

---

## 5. 驗證計劃

- **回歸閘門**：`uv run pytest --durations=10` 維持 <6s；`test_extract_evidence_dedup_scales_linearly` 維持 <5s。
- **真實數據**：`hyperfine -w 2 -r 5 'uv run iiwi scan --period last-week --verbose'` 與 `report --dry-run --no-llm --verbose` 的 `PerformanceMetrics` 表對比。
- **分 harness**：分別 `scan --harness opencode / claude-code / codex --verbose` 定位殘餘瓶頸。
- **DB 檢查**：`sqlite3 ~/.local/share/opencode/opencode.db "EXPLAIN QUERY PLAN SELECT ..."` 確認是否全表掃描。

---

## 6. 風險與不做什麼

- **不改行為**：所有優化保持輸出一致，`test` 綠為硬門檻。
- **不引入重依賴**：`orjson` 為可選，fallback 到 `json`。
- **不動 LLM 路徑**：`--no-llm` 的 structured 報告先優化，narrative (LLM) 是另一條路徑。
- **不直接改 opencode.db**：索引若由 opencode 管理，僅提議，不強行 `CREATE INDEX` 到用戶 DB（可加 `--init-db-index` 選項另議）。

---

## 7. 需要你確認

1. 是否按 **Phase 0 → 1 → 2 → 3 → 4** 順序執行？我建議先做 Phase 0+1（半天見效），再根據儀表數據決定 Phase 2 的 DB 優化是否必要。
2. 是否接受 `orjson` 作為可選依賴？或堅持標準庫 `json`？
3. 是否接受對 `opencode.db` 的只讀 `sqlite3` 直連作為長期選項（繞過 CLI）？

確認後我將按階段拆成並行子任務執行，每階段完成後用 `lsp_diagnostics` + `pytest` + `hyperfine` 驗證再進入下一階段。
