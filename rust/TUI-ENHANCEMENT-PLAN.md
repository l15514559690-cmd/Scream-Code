# TUI Enhancement Plan — Claw Code (`rusty-claude-cli`)

## Executive Summary

This plan covers a comprehensive analysis of the current terminal user interface and proposes phased enhancements that will transform the existing REPL/prompt CLI into a polished, modern TUI experience — while preserving the existing clean architecture and test coverage.

### **[UPDATE 2026-04] — Python TUI is canonical**

The **originally envisioned Rust-first TUI overhaul** (including optional `ratatui` full-screen work) has been **fully superseded** by a **Python TUI stack** (`rich` + `prompt_toolkit`), shipped as the default Scream Code interactive experience (`scream` → `python3 -m src.main repl --python-tui`). Rust remains a **lightweight launcher** (env injection, workspace root, `--line-repl` classic path) and **API / runtime engine**, not the primary TUI renderer.

**Phases 1–4 goals from this document are met or exceeded on the Python side**, including: status/HUD (bottom toolbar), streaming markdown with `Live`, thinking/status indicators, tool-call panels and diff visualization, enhanced `/diff` and `/sessions`, slash completion with metadata, and a deliberate “waterfall” REPL that avoids scrollback pollution.

The sections below are **retained as historical design context** and for the **Rust line-REPL** surface; treat **Phase 6 (ratatui)** as **archived** (see §2 Phase 6).

---

## 1. Current Architecture Analysis

### Crate Map

| Crate | Purpose | Lines | TUI Relevance |
|---|---|---|---|
| `rusty-claude-cli` | Main binary: REPL loop, arg parsing, rendering, API bridge | ~3,600 | **Primary TUI surface** |
| `runtime` | Session, conversation loop, config, permissions, compaction | ~5,300 | Provides data/state |
| `api` | Anthropic HTTP client + SSE streaming | ~1,500 | Provides stream events |
| `commands` | Slash command metadata/parsing/help | ~470 | Drives command dispatch |
| `tools` | 18 built-in tool implementations | ~3,500 | Tool execution display |

### Current TUI Components

| Component | File | What It Does Today | Quality |
|---|---|---|---|
| **Input** | `input.rs` (269 lines) | `rustyline`-based line editor with slash-command tab completion, Shift+Enter newline, history | ✅ Solid |
| **Rendering** | `render.rs` (641 lines) | Markdown→terminal rendering (headings, lists, tables, code blocks with syntect highlighting, blockquotes), spinner widget | ✅ Good |
| **App/REPL loop** | `main.rs` (3,159 lines) | The monolithic `LiveCli` struct: REPL loop, all slash command handlers, streaming output, tool call display, permission prompting, session management | ⚠️ Monolithic |
| **Alt App** | `app.rs` (398 lines) | An earlier `CliApp` prototype with `ConversationClient`, stream event handling, `TerminalRenderer`, output format support | ⚠️ Appears unused/legacy |

### Key Dependencies

- **crossterm 0.28** — terminal control (cursor, colors, clear)
- **pulldown-cmark 0.13** — Markdown parsing
- **syntect 5** — syntax highlighting
- **rustyline 15** — line editing with completion
- **serde_json** — tool I/O formatting

### Strengths

1. **Clean rendering pipeline**: Markdown rendering is well-structured with state tracking, table rendering, code highlighting
2. **Rich tool display**: Tool calls get box-drawing borders (`╭─ name ─╮`), results show ✓/✗ icons
3. **Comprehensive slash commands**: 15 commands covering model switching, permissions, sessions, config, diff, export
4. **Session management**: Full persistence, resume, list, switch, compaction
5. **Permission prompting**: Interactive Y/N approval for restricted tool calls
6. **Thorough tests**: Every formatting function, every parse path has unit tests

### Weaknesses & Gaps

1. **`main.rs` is a 3,159-line monolith** — all REPL logic, formatting, API bridging, session management, and tests in one file
2. **No alternate-screen / full-screen layout** — everything is inline scrolling output
3. **No progress bars** — only a single braille spinner; no indication of streaming progress or token counts during generation
4. **No visual diff rendering** — `/diff` just dumps raw git diff text
5. **No syntax highlighting in streamed output** — markdown rendering only applies to tool results, not to the main assistant response stream
6. **No status bar / HUD** — model, tokens, session info not visible during interaction
7. **No image/attachment preview** — `SendUserMessage` resolves attachments but never displays them
8. **Streaming is char-by-char with artificial delay** — `stream_markdown` sleeps 8ms per whitespace-delimited chunk
9. **No color theme customization** — hardcoded `ColorTheme::default()`
10. **No resize handling** — no terminal size awareness for wrapping, truncation, or layout
11. **Dual app structs** — `app.rs` has a separate `CliApp` that duplicates `LiveCli` from `main.rs`
12. **No pager for long outputs** — `/status`, `/config`, `/memory` can overflow the viewport
13. **Tool results not collapsible** — large bash outputs flood the screen
14. **No thinking/reasoning indicator** — when the model is in "thinking" mode, no visual distinction
15. **No auto-complete for tool arguments** — only slash command names complete

---

## 2. Enhancement Plan

### Phase 0: Structural Cleanup (Foundation)

**Goal**: Break the monolith, remove dead code, establish the module structure for TUI work.

| Task | Description | Effort |
|---|---|---|
| 0.1 | **Extract `LiveCli` into `app.rs`** — Move the entire `LiveCli` struct, its impl, and helpers (`format_*`, `render_*`, session management) out of `main.rs` into focused modules: `app.rs` (core), `format.rs` (report formatting), `session_manager.rs` (session CRUD) | M |
| 0.2 | **Remove or merge the legacy `CliApp`** — The existing `app.rs` has an unused `CliApp` with its own `ConversationClient`-based rendering. Either delete it or merge its unique features (stream event handler pattern) into the active `LiveCli` | S |
| 0.3 | **Extract `main.rs` arg parsing** — The current `parse_args()` is a hand-rolled parser that duplicates the clap-based `args.rs`. Consolidate on the hand-rolled parser (it's more feature-complete) and move it to `args.rs`, or adopt clap fully | S |
| 0.4 | ~~**Create a `tui/` module**~~ **(Obsolete)** — Was planned under Rust; **`tui/` removed** (2026-04). Equivalent concerns live in **`src/tui_app.py`** / **`repl_ui_render.py`** (Python). | — |

### Phase 1: Status Bar & Live HUD

**Goal**: Persistent information display during interaction.

| Task | Description | Effort |
|---|---|---|
| 1.1 | **Terminal-size-aware status line** — Use `crossterm::terminal::size()` to render a bottom-pinned status bar showing: model name, permission mode, session ID, cumulative token count, estimated cost | M |
| 1.2 | **Live token counter** — Update the status bar in real-time as `AssistantEvent::Usage` and `AssistantEvent::TextDelta` events arrive during streaming | M |
| 1.3 | **Turn duration timer** — Show elapsed time for the current turn (the `showTurnDuration` config already exists in Config tool but isn't wired up) | S |
| 1.4 | **Git branch indicator** — Display the current git branch in the status bar (already parsed via `parse_git_status_metadata`) | S |

### Phase 2: Enhanced Streaming Output

**Goal**: Make the main response stream visually rich and responsive.

| Task | Description | Effort |
|---|---|---|
| 2.1 | **Live markdown rendering** — Instead of raw text streaming, buffer text deltas and incrementally render Markdown as it arrives (heading detection, bold/italic, inline code). The existing `TerminalRenderer::render_markdown` can be adapted for incremental use | L |
| 2.2 | **Thinking indicator** — When extended thinking/reasoning is active, show a distinct animated indicator (e.g., `🧠 Reasoning...` with pulsing dots or a different spinner) instead of the generic `🦀 Thinking...` | S |
| 2.3 | **Streaming progress bar** — Add an optional horizontal progress indicator below the spinner showing approximate completion (based on max_tokens vs. output_tokens so far) | M |
| 2.4 | **Remove artificial stream delay** — The current `stream_markdown` sleeps 8ms per chunk. For tool results this is fine, but for the main response stream it should be immediate or configurable | S |

### Phase 3: Tool Call Visualization

**Goal**: Make tool execution legible and navigable.

| Task | Description | Effort |
|---|---|---|
| 3.1 | **Collapsible tool output** — For tool results longer than N lines (configurable, default 15), show a summary with `[+] Expand` hint; pressing a key reveals the full output. Initially implement as truncation with a "full output saved to file" fallback | M |
| 3.2 | **Syntax-highlighted tool results** — When tool results contain code (detected by tool name — `bash` stdout, `read_file` content, `REPL` output), apply syntect highlighting rather than rendering as plain text | M |
| 3.3 | **Tool call timeline** — For multi-tool turns, show a compact summary: `🔧 bash → ✓ | read_file → ✓ | edit_file → ✓ (3 tools, 1.2s)` after all tool calls complete | S |
| 3.4 | **Diff-aware edit_file display** — When `edit_file` succeeds, show a colored unified diff of the change instead of just `✓ edit_file: path` | M |
| 3.5 | **Permission prompt enhancement** — Style the approval prompt with box drawing, color the tool name, show a one-line summary of what the tool will do | S |

### Phase 4: Enhanced Slash Commands & Navigation

**Goal**: Improve information display and add missing features.

| Task | Description | Effort |
|---|---|---|
| 4.1 | **Colored `/diff` output** — Parse the git diff and render it with red/green coloring for removals/additions, similar to `delta` or `diff-so-fancy` | M |
| 4.2 | **Pager for long outputs** — When `/status`, `/config`, `/memory`, or `/diff` produce output longer than the terminal height, pipe through an internal pager (scroll with j/k/q) or external `$PAGER` | M |
| 4.3 | **`/search` command** — Add a new command to search conversation history by keyword | M |
| 4.4 | **`/undo` command** — Undo the last file edit by restoring from the `originalFile` data in `write_file`/`edit_file` tool results | M |
| 4.5 | **Interactive session picker** — Replace the text-based `/session list` with an interactive fuzzy-filterable list (up/down arrows to select, enter to switch) | L |
| 4.6 | **Tab completion for tool arguments** — Extend `SlashCommandHelper` to complete file paths after `/export`, model names after `/model`, session IDs after `/session switch` | M |

### Phase 5: Color Themes & Configuration

**Goal**: User-customizable visual appearance.

| Task | Description | Effort |
|---|---|---|
| 5.1 | **Named color themes** — Add `dark` (current default), `light`, `solarized`, `catppuccin` themes. Wire to the existing `Config` tool's `theme` setting | M |
| 5.2 | **ANSI-256 / truecolor detection** — Detect terminal capabilities and fall back gracefully (no colors → 16 colors → 256 → truecolor) | M |
| 5.3 | **Configurable spinner style** — Allow choosing between braille dots, bar, moon phases, etc. | S |
| 5.4 | **Banner customization** — Make the ASCII art banner optional or configurable via settings | S |

### Phase 6: Full-Screen TUI Mode (Stretch) — **[DEPRECATED / ARCHIVED]**

**Status (2026-04)**: This phase targeted a **Rust + `ratatui`** alternate-screen application. That direction is **not pursued**. The **`src/tui/`** tree under `rusty-claude-cli` has been **removed**; **`ratatui`** and related crates were **never adopted** as the shipping path for Scream Code 2.0.

**Goal (historical)**: Optional alternate-screen layout for power users.

| Task | Description | Effort |
|---|---|---|
| 6.1 | ~~**Add `ratatui` dependency**~~ **→ Superseded.** Full-screen or richer layouts, if ever needed, would follow a **`prompt_toolkit`-centric** Python application pattern (or similar), not a heavy Rust TUI framework in-tree. **No `ratatui` task.** | — |
| 6.2 | **Split-pane layout** — (Archived) Would have been top: conversation; bottom: input; optional sidebar | XL |
| 6.3 | **Scrollable conversation view** — (Archived) | L |
| 6.4 | **Keyboard shortcuts panel** — (Archived) | M |
| 6.5 | **Mouse support** — (Archived) | L |

**Rationale**: The **interactive Python REPL** (streaming assistant panels, bottom toolbar, `patch_stdout` avoided, `Live` + final panel) already delivers a **strong compromise**—polished visuals without pulling in a **large Rust full-screen TUI stack**. Re-introducing `ratatui` for the default experience is **explicitly out of scope** for the current architecture.

---

---

## 3. Priority Recommendation

### Immediate (High Impact, Moderate Effort)

1. **Phase 0** — Essential cleanup. The 3,159-line `main.rs` is the #1 maintenance risk and blocks clean TUI additions.
2. **Phase 1.1–1.2** — Status bar with live tokens. Highest-impact UX win: users constantly want to know token usage.
3. **Phase 2.4** — Remove artificial delay. Low effort, immediately noticeable improvement.
4. **Phase 3.1** — Collapsible tool output. Large bash outputs currently wreck readability.

### Near-Term (Next Sprint)

5. **Phase 2.1** — Live markdown rendering. Makes the core interaction feel polished.
6. **Phase 3.2** — Syntax-highlighted tool results.
7. **Phase 3.4** — Diff-aware edit display.
8. **Phase 4.1** — Colored diff for `/diff`.

### Longer-Term

9. **Phase 5** — Color themes (user demand-driven); may apply to Python TUI / Rich themes or Rust line-REPL separately.
10. **Phase 4.2–4.6** — Enhanced navigation and commands (partially addressed in Python; remainder backlog).
11. ~~**Phase 6**~~ — **Archived** (see Phase 6 section). Full-screen Rust TUI is not on the roadmap.

---

## 4. Architecture Recommendations

### Current split (2026-04): Rust launcher + Python TUI

**Primary interactive UI** lives in the repo root Python package:

- `src/tui_app.py` — `prompt_toolkit` session, bottom toolbar, welcome/status styling, slash completer
- `src/replLauncher.py` — streaming turn (`rich.Live`), `console.status` thinking line, bridge to engine
- `src/repl_ui_render.py` — tool op panels, `Syntax` diff/Markdown, final assistant `Panel`
- `src/repl_slash_commands.py` — `/diff`, `/sessions`, etc. with Rich tables/panels

**Rust `scream-cli`** (`crates/rusty-claude-cli/src/`):

- `main.rs` — Parses args; **default REPL** spawns Python TUI; **`--line-repl`** uses classic **rustyline** loop
- `render.rs` — Markdown + **Spinner** (**`crossterm`**) for the **Rust line REPL** only
- **`tui/`** — **Removed** (no `ratatui` module in-tree)

### Module structure (Rust) — historical target vs. actual

The tree below was the **Phase 0 aspiration** for a Rust-only TUI module layout. **Actual shipping layout**: no `tui/` directory; TUI features are implemented in **Python** as above.

```
crates/rusty-claude-cli/src/
├── main.rs              # Entrypoint: Python TUI launch, or run() for full CLI / line REPL
├── init.rs
├── input.rs             # rustyline (classic `--line-repl`)
├── llm_config.rs
├── render.rs            # TerminalRenderer, Spinner (crossterm) — line REPL / markdown
└── (no tui/ — deleted)
```

### Key Design Principles

1. **Default UX is Python TUI** — `scream` / `scream repl` → Python `rich` + `prompt_toolkit`; Rust full-screen TUI is **not** the product direction.
2. **Rust + Python decoupling** — Launcher sets cwd, env (UTF-8, locale, color), and stdio; **no terminal mode hacks** before spawning Python TUI.
3. **Streaming-first (Python path)** — `Live` for deltas, transient + final `Panel` for scrollback hygiene; thinking line via `console.status`.
4. **Respect `crossterm` on the Rust line-REPL path only** — Spinner and related sequences stay inside **`run_turn_line_repl`** / line REPL, not the Python spawn path.
5. ~~**Feature-gate heavy dependencies (`ratatui`)**~~ **OBSOLETE.** **Do not** re-add `ratatui` for the default stack. Any future full-screen experiment should align with **Python `prompt_toolkit`** (or a separate tool), not a second heavyweight Rust TUI framework in `rusty-claude-cli`.

---

## 5. Risk Assessment

| Risk | Mitigation |
|---|---|
| Breaking the working REPL during refactor | Phase 0 is pure restructuring with existing test coverage as safety net |
| Terminal compatibility issues (tmux, SSH, Windows) | Rely on crossterm's abstraction; test in degraded environments |
| Performance regression with rich rendering | Profile before/after; keep the fast path (raw streaming) always available |
| Scope creep into Phase 6 | **Phase 6 archived**; prefer extending Python TUI if new UX is needed |
| `app.rs` vs `main.rs` confusion | Phase 0.2 explicitly resolves this by removing the legacy `CliApp` |

---

*Generated: 2026-03-31 | Workspace: `rust/` | Branch: `dev/rust`*  
*Last architecture note: 2026-04 — Python TUI canonical; Rust `tui/` removed; Phase 6 archived.*
