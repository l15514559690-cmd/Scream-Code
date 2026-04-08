//! Full-screen REPL: **pure UI**. All LLM / `/team` / `/memo` / routing runs in the Python
//! `QueryEnginePort` stack (`python3 -m src.main repl --json-stdio`); this module only renders
//! JSON lines from stdout and sends JSON lines on stdin.

mod render;

use std::env;
use std::io::{self, stdout, BufRead, BufReader, Write};
use std::path::{Path, PathBuf};
use std::process::{Child, ChildStdin, Command, Stdio};
use std::sync::mpsc::{self, TryRecvError};
use std::thread;
use std::time::Duration;

use crossterm::{
    cursor::{Hide, Show},
    event::{
        self, DisableMouseCapture, EnableMouseCapture, Event, KeyCode, KeyEventKind, KeyModifiers,
        MouseEventKind,
    },
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    layout::{Constraint, Direction, Layout, Position},
    prelude::*,
    style::Modifier,
    widgets::{Block, Borders, Paragraph, Wrap},
};
use runtime::PermissionMode;
use serde_json::Value;
use strip_ansi_escapes::strip;
use textwrap::WordSeparator;
use tui_textarea::{CursorMove, TextArea};
use unicode_width::{UnicodeWidthChar, UnicodeWidthStr};

use super::resolve_git_branch_for;

const BG: Color = Color::Rgb(10, 14, 24);
const BORDER: Color = Color::Cyan;
const ACCENT: Color = Color::Rgb(96, 168, 255);
const TEXT: Color = Color::Rgb(170, 210, 245);
const STATUS_BG: Color = Color::Rgb(0, 140, 190);
const STATUS_FG: Color = Color::Rgb(8, 12, 20);
const INPUT_LINE_BG: Color = Color::Rgb(18, 28, 48);
/// 助手正文：亮青，与用户白字区分且对比足够
const ASSISTANT_BODY_FG: Color = Color::LightCyan;
/// 用户正文：干净白字
const USER_BODY_FG: Color = Color::White;
/// 系统 / 工具 / 错误 / 后端 正文
const META_BODY_FG: Color = Color::DarkGray;

const SPINNER_FRAMES: [&str; 10] = ["⠋", "⠙", "⠹", "⠸", "⠼", "⠴", "⠦", "⠧", "⠇", "⠏"];
/// 鼠标滚轮每次滚动的逻辑行数（折叠后）
const MOUSE_SCROLL_STEP: usize = 3;
/// 输入区最少/最多展示的逻辑行数（`tui-textarea` 0.7 无 API 软折行，由 `reflow_textarea_hard_wrap` 按宽度硬换行）
const MIN_INPUT_INNER_ROWS: usize = 3;
const MAX_INPUT_INNER_ROWS: usize = 8;

#[inline]
fn rect_contains(r: Rect, col: u16, row: u16) -> bool {
    col >= r.x
        && col < r.x.saturating_add(r.width)
        && row >= r.y
        && row < r.y.saturating_add(r.height)
}

/// 与 `draw_ui` 中纵向分区一致，便于鼠标命中与滚动计算。
struct ReplDrawLayout {
    chat_area: Rect,
    chat_scrollbar_rect: Rect,
    inner_w: usize,
    inner_h: u16,
    spinner_area: Rect,
    input_area: Rect,
    status_area: Rect,
}

fn compute_repl_draw_layout(main: Rect, input_h: u16, spinner_visible: bool) -> ReplDrawLayout {
    let spinner_h = u16::from(spinner_visible);
    let status_h = 1u16;
    let chat_h = main
        .height
        .saturating_sub(spinner_h)
        .saturating_sub(input_h)
        .saturating_sub(status_h)
        .max(1);
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(chat_h),
            Constraint::Length(spinner_h),
            Constraint::Length(input_h),
            Constraint::Length(status_h),
        ])
        .split(main);
    let chat_row = chunks[0];
    let spinner_area = chunks[1];
    let input_area = chunks[2];
    let status_area = chunks[3];

    let chat_hs = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Min(0), Constraint::Length(1)])
        .split(chat_row);
    let chat_area = chat_hs[0];
    let chat_scrollbar_rect = chat_hs[1];

    let chat_block = Block::default().borders(Borders::ALL);
    let inner = chat_block.inner(chat_area);
    let inner_w = (inner.width as usize).max(1);
    let inner_h = inner.height.max(1);

    ReplDrawLayout {
        chat_area,
        chat_scrollbar_rect,
        inner_w,
        inner_h,
        spinner_area,
        input_area,
        status_area,
    }
}

/// `scroll_up`：从「贴底」视图再向上滚动的行数（越大约看越早的内容）。
fn chat_visible_rows(
    chat: &ChatLog,
    inner_w: usize,
    visible: usize,
    scroll_up: usize,
) -> Vec<(ChatLineRole, String)> {
    let flat = flatten_wrapped_chat_lines(&chat.lines, inner_w.max(1));
    let total = flat.len();
    if total == 0 {
        return Vec::new();
    }
    let vis = visible.min(total);
    let max_start = total.saturating_sub(vis);
    let su = scroll_up.min(max_start);
    let start = max_start.saturating_sub(su);
    flat[start..start + vis].to_vec()
}

fn max_chat_scroll_up(chat: &ChatLog, inner_w: usize, visible: usize) -> usize {
    let total = flatten_wrapped_chat_lines(&chat.lines, inner_w.max(1)).len();
    total.saturating_sub(visible.min(total.max(1)))
}

fn render_chat_scrollbar(
    f: &mut Frame<'_>,
    area: Rect,
    scroll_up: usize,
    total: usize,
    visible: usize,
) {
    if area.width == 0 || area.height == 0 || total == 0 || total <= visible {
        return;
    }
    let max_start = total.saturating_sub(visible);
    let su = scroll_up.min(max_start);
    let bar_h = area.height as usize;
    let thumb_h = (bar_h / 4).max(2).min(bar_h);
    let travel = bar_h.saturating_sub(thumb_h).max(1);
    let thumb_start_u = if max_start == 0 {
        0usize
    } else {
        (su * travel) / max_start
    };
    let thumb_start_u = thumb_start_u.min(travel);
    let thumb_end_u = thumb_start_u.saturating_add(thumb_h).min(bar_h);

    let mut lines: Vec<Line<'static>> = Vec::with_capacity(bar_h);
    for r in 0..bar_h {
        let ch = if r >= thumb_start_u && r < thumb_end_u {
            "█"
        } else {
            "░"
        };
        lines.push(Line::from(Span::styled(
            ch,
            Style::default().fg(Color::DarkGray).bg(BG),
        )));
    }
    f.render_widget(
        Paragraph::new(Text::from(lines)).style(Style::default().bg(BG)),
        area,
    );
}

/// 聊天行语义，用于换行折叠后仍能对正文着色。
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
enum ChatLineRole {
    Spacer,
    HeaderUser,
    HeaderAssistant,
    HeaderMeta,
    BodyUser,
    BodyAssistant,
    BodyMeta,
}

fn strip_ansi_for_tui(s: &str) -> String {
    String::from_utf8_lossy(&strip(s.as_bytes())).to_string()
}

fn textwrap_options(content_width: usize) -> textwrap::Options<'static> {
    textwrap::Options::new(content_width)
        .word_separator(WordSeparator::UnicodeBreakProperties)
        .break_words(true)
}

fn hide_textarea_buffer_caret(textarea: &mut TextArea<'_>) {
    textarea.set_cursor_style(Style::default().add_modifier(Modifier::HIDDEN));
}

/// 在显示宽度超过 `max_w` 时拆成两行（按字符/宽字符边界，避免穿透边框）。
fn split_overflow_line(line: &str, max_w: usize) -> Option<(String, String)> {
    let max_w = max_w.max(1);
    if UnicodeWidthStr::width(line) <= max_w {
        return None;
    }
    let mut acc = 0usize;
    let mut last_fit_end = 0usize;
    for (i, c) in line.char_indices() {
        let cw = UnicodeWidthChar::width(c).unwrap_or(0);
        if acc + cw > max_w {
            if i == 0 {
                let end = i + c.len_utf8();
                return Some((line[..end].to_string(), line[end..].to_string()));
            }
            return Some((
                line[..last_fit_end].to_string(),
                line[last_fit_end..].to_string(),
            ));
        }
        acc += cw;
        last_fit_end = i + c.len_utf8();
    }
    None
}

/// 将过长的逻辑行按输入区宽度硬换行，并尽量保持光标位置。
/// （`tui-textarea` 0.7 无 `set_soft_wrap`，此处等价于可视软折行。）
fn reflow_textarea_hard_wrap(textarea: &mut TextArea<'_>, max_cols: usize) {
    let max_cols = max_cols.max(1);
    let (mut cur_r, mut cur_c) = textarea.cursor();
    let mut lines: Vec<String> = textarea.lines().to_vec();
    let mut any_split = false;

    let mut repeat = true;
    while repeat {
        repeat = false;
        let mut i = 0;
        while i < lines.len() {
            if UnicodeWidthStr::width(lines[i].as_str()) <= max_cols {
                i += 1;
                continue;
            }
            let Some((head, tail)) = split_overflow_line(&lines[i], max_cols) else {
                i += 1;
                continue;
            };
            any_split = true;
            let head_chars = head.chars().count();
            lines[i] = head;
            lines.insert(i + 1, tail);
            if cur_r == i {
                if cur_c > head_chars {
                    cur_r += 1;
                    cur_c = cur_c.saturating_sub(head_chars);
                }
            } else if cur_r > i {
                cur_r += 1;
            }
            repeat = true;
        }
    }

    if any_split {
        let mut t = TextArea::new(lines);
        configure_textarea(&mut t);
        *textarea = t;
        textarea.move_cursor(CursorMove::Jump(
            u16::try_from(cur_r).unwrap_or(u16::MAX),
            u16::try_from(cur_c).unwrap_or(u16::MAX),
        ));
    }
}

fn configure_textarea(textarea: &mut TextArea<'_>) {
    textarea.set_style(Style::default().fg(TEXT));
    textarea.set_cursor_line_style(Style::default().bg(INPUT_LINE_BG));
    textarea.set_cursor_style(Style::default().add_modifier(Modifier::HIDDEN));
    textarea
        .set_placeholder_text("尖叫> (Shift+Enter 换行，Enter 发送 · 由 Python QueryEngine 执行)");
    textarea.set_block(
        Block::default()
            .borders(Borders::ALL)
            .border_style(Style::default().fg(BORDER))
            .title(Line::from(vec![
                Span::styled(" 输入 ", Style::default().fg(ACCENT).bold()),
                Span::styled(" · Enter 发送 ", Style::default().fg(Color::DarkGray)),
            ])),
    );
}

#[inline]
fn next_scroll_top(prev_top: u16, cursor: u16, viewport_len: u16) -> u16 {
    if viewport_len == 0 {
        return prev_top;
    }
    if cursor < prev_top {
        cursor
    } else if prev_top.saturating_add(viewport_len) <= cursor {
        cursor.saturating_add(1).saturating_sub(viewport_len)
    } else {
        prev_top
    }
}

#[derive(Clone, Copy, Default)]
struct TextViewportScroll {
    top_row: u16,
    top_col: u16,
}

fn usize_to_u16_saturated(n: usize) -> u16 {
    u16::try_from(n).unwrap_or(u16::MAX)
}

fn display_width_char_range(line: &str, char_start: usize, char_end: usize) -> u16 {
    if char_end <= char_start {
        return 0;
    }
    let w: usize = line
        .chars()
        .enumerate()
        .filter(|(i, _)| *i >= char_start && *i < char_end)
        .map(|(_, c)| UnicodeWidthChar::width(c).unwrap_or(0))
        .sum();
    u16::try_from(w.min(u16::MAX as usize)).unwrap_or(u16::MAX)
}

fn textarea_cursor_absolute(
    textarea: &TextArea<'_>,
    input_area: Rect,
    prev: TextViewportScroll,
    term: Rect,
) -> Option<Position> {
    let inner = textarea
        .block()
        .map(|b| b.inner(input_area))
        .unwrap_or(input_area);
    if inner.width == 0 || inner.height == 0 {
        return None;
    }
    let (cr, cc) = textarea.cursor();
    let h = inner.height.max(1);
    let w = inner.width.max(1);
    let top_row = next_scroll_top(prev.top_row, usize_to_u16_saturated(cr), h);
    let top_col = next_scroll_top(prev.top_col, usize_to_u16_saturated(cc), w);

    let rel_y = usize_to_u16_saturated(cr).saturating_sub(top_row);
    let rel_y = rel_y.min(inner.height.saturating_sub(1));

    let line = textarea.lines().get(cr).map(String::as_str).unwrap_or("");
    let tc = top_col as usize;
    let dx = display_width_char_range(line, tc, cc);
    let rel_x = dx.min(inner.width.saturating_sub(1));

    let mut x = inner.x.saturating_add(rel_x);
    let mut y = inner.y.saturating_add(rel_y);
    let max_x = term.x.saturating_add(term.width.saturating_sub(1));
    let max_y = term.y.saturating_add(term.height.saturating_sub(1));
    x = x.max(term.x).min(max_x);
    y = y.max(term.y).min(max_y);
    Some(Position::new(x, y))
}

fn flatten_wrapped_chat_lines(
    lines: &[(ChatLineRole, String)],
    content_width: usize,
) -> Vec<(ChatLineRole, String)> {
    if content_width == 0 {
        return lines.to_vec();
    }
    let opts = textwrap_options(content_width);
    let mut out = Vec::new();
    for (role, line) in lines {
        if line.is_empty() {
            out.push((*role, String::new()));
            continue;
        }
        let wrapped = textwrap::wrap(line, &opts);
        if wrapped.is_empty() {
            out.push((*role, String::new()));
        } else {
            for w in wrapped {
                out.push((*role, w.into_owned()));
            }
        }
    }
    out
}

fn section_header_body_roles(section_title: &str) -> (ChatLineRole, ChatLineRole) {
    match section_title {
        "你" => (ChatLineRole::HeaderUser, ChatLineRole::BodyUser),
        "助手" => (ChatLineRole::HeaderAssistant, ChatLineRole::BodyAssistant),
        _ => (ChatLineRole::HeaderMeta, ChatLineRole::BodyMeta),
    }
}

fn permission_mode_zh(mode: PermissionMode) -> &'static str {
    match mode {
        PermissionMode::ReadOnly => "只读",
        PermissionMode::WorkspaceWrite => "工作区写入",
        PermissionMode::DangerFullAccess => "完全访问",
        PermissionMode::Prompt => "询问",
        PermissionMode::Allow => "允许",
    }
}

struct ChatLog {
    lines: Vec<(ChatLineRole, String)>,
    assistant_stream_line: Option<usize>,
}

impl ChatLog {
    fn new() -> Self {
        Self {
            lines: Vec::new(),
            assistant_stream_line: None,
        }
    }

    fn push_spacer_pair(&mut self) {
        self.lines.push((ChatLineRole::Spacer, String::new()));
        self.lines.push((ChatLineRole::Spacer, String::new()));
    }

    fn push_section(&mut self, title: &str, body: &str) {
        let title = strip_ansi_for_tui(title);
        let body = strip_ansi_for_tui(body);
        let (h_role, b_role) = section_header_body_roles(title.trim());
        self.lines.push((h_role, format!("— {title} —")));
        if body.is_empty() {
            self.lines.push((b_role, "∅".to_string()));
        } else {
            for line in body.lines() {
                self.lines.push((b_role, line.to_string()));
            }
        }
        self.push_spacer_pair();
    }

    fn push_plain(&mut self, line: impl Into<String>) {
        self.lines
            .push((ChatLineRole::BodyMeta, strip_ansi_for_tui(&line.into())));
        self.push_spacer_pair();
    }

    fn clear_all(&mut self) {
        self.lines.clear();
        self.assistant_stream_line = None;
    }

    fn pop_last_plain_block(&mut self) {
        let n = self.lines.len();
        if n >= 2 {
            self.lines.truncate(n.saturating_sub(2));
        }
    }

    fn begin_assistant_stream(&mut self) {
        if self.assistant_stream_line.is_none() {
            self.lines
                .push((ChatLineRole::HeaderAssistant, "— 助手 —".to_string()));
            self.lines.push((ChatLineRole::Spacer, String::new()));
            // 流式正文落在 BodyAssistant，避免写入 Spacer 导致无颜色
            self.lines
                .push((ChatLineRole::BodyAssistant, String::new()));
            self.assistant_stream_line = Some(self.lines.len() - 1);
        }
    }

    fn append_assistant_delta(&mut self, d: &str) {
        let t = strip_ansi_for_tui(d);
        if t.is_empty() {
            return;
        }
        self.begin_assistant_stream();
        if let Some(i) = self.assistant_stream_line {
            self.lines[i].1.push_str(&t);
        }
    }

    fn end_assistant_stream_if_any(&mut self) {
        if self.assistant_stream_line.take().is_some() {
            self.push_spacer_pair();
        }
    }

    /// Map Python `QueryEnginePort` / `iter_repl_assistant_events` JSON events into scrollback.
    fn handle_python_json(&mut self, v: &Value) {
        let Some(ty) = v.get("type").and_then(Value::as_str) else {
            return;
        };
        match ty {
            "text_delta" => {
                if let Some(t) = v.get("text").and_then(Value::as_str) {
                    self.append_assistant_delta(t);
                }
            }
            "api_tool_op" => {
                self.end_assistant_stream_if_any();
                let name = v.get("tool_name").and_then(Value::as_str).unwrap_or("tool");
                let args = v
                    .get("arguments")
                    .map(|x| {
                        x.as_str()
                            .map(str::to_string)
                            .unwrap_or_else(|| x.to_string())
                    })
                    .unwrap_or_default();
                self.push_section("工具", &format!("{name}\n{args}"));
            }
            "tool_phase" => {
                let label = v
                    .get("tools")
                    .and_then(|x| x.as_array())
                    .map(|a| {
                        a.iter()
                            .filter_map(|i| i.as_str().map(str::to_string))
                            .collect::<Vec<_>>()
                            .join(", ")
                    })
                    .unwrap_or_default();
                if !label.is_empty() {
                    self.push_plain(format!("⚙️ 正在执行工具: {label}"));
                }
            }
            "finished" | "non_llm" => {
                let out = v.get("output").and_then(Value::as_str).unwrap_or("");
                let had_stream = self
                    .assistant_stream_line
                    .and_then(|i| self.lines.get(i).map(|(_, s)| !s.trim().is_empty()))
                    .unwrap_or(false);
                self.end_assistant_stream_if_any();
                if !had_stream && !out.trim().is_empty() {
                    self.push_section("助手", out);
                }
            }
            "llm_error" | "blocked" => {
                self.end_assistant_stream_if_any();
                let msg = v.get("output").and_then(Value::as_str).unwrap_or("error");
                self.push_section("错误", msg);
            }
            _ => {
                // 哑终端：未单独映射的事件仍展示 Python 给出的可读片段（不做指令路由）。
                if let Some(s) = v
                    .get("text")
                    .or_else(|| v.get("output"))
                    .or_else(|| v.get("message"))
                    .and_then(Value::as_str)
                {
                    if !s.trim().is_empty() {
                        self.push_section("后端", s);
                    }
                } else if let Some(a) = v.get("agent").and_then(Value::as_str) {
                    self.push_section("后端", a);
                }
            }
        }
    }
}

#[derive(Clone)]
struct TuiSnapshot {
    model: String,
    permission: PermissionMode,
    total_tokens: u64,
    /// Python `state` / `ready` 中的 `repl_team_mode`（群狼 / 常规）。
    team_mode: bool,
}

impl Default for TuiSnapshot {
    fn default() -> Self {
        Self {
            model: String::new(),
            permission: PermissionMode::WorkspaceWrite,
            total_tokens: 0,
            team_mode: false,
        }
    }
}

impl TuiSnapshot {
    fn apply_from_json(&mut self, v: &Value) {
        if let Some(m) = v.get("model").and_then(Value::as_str) {
            self.model = m.to_string();
        }
        if let Some(b) = v.get("repl_team_mode").and_then(Value::as_bool) {
            self.team_mode = b;
        }
        let cin = v
            .get("cumulative_input_tokens")
            .and_then(|x| x.as_u64())
            .or_else(|| {
                v.get("cumulative_input_tokens")
                    .and_then(|x| x.as_i64())
                    .map(|i| i.max(0) as u64)
            })
            .unwrap_or(0);
        let cout = v
            .get("cumulative_output_tokens")
            .and_then(|x| x.as_u64())
            .or_else(|| {
                v.get("cumulative_output_tokens")
                    .and_then(|x| x.as_i64())
                    .map(|i| i.max(0) as u64)
            })
            .unwrap_or(0);
        if v.get("cumulative_input_tokens").is_some() || v.get("cumulative_output_tokens").is_some()
        {
            self.total_tokens = cin.saturating_add(cout);
        }
    }
}

fn workspace_root() -> PathBuf {
    env::var("SCREAM_WORKSPACE_ROOT")
        .ok()
        .filter(|s| !s.trim().is_empty())
        .map(PathBuf::from)
        .unwrap_or_else(|| env::current_dir().unwrap_or_default())
}

fn python_executable() -> &'static str {
    if cfg!(windows) {
        "python"
    } else {
        "python3"
    }
}

enum BackendLine {
    Stdout(String),
    Stderr(String),
}

fn spawn_python_backend() -> Result<
    (
        std::process::Child,
        mpsc::Receiver<BackendLine>,
        std::process::ChildStdin,
    ),
    Box<dyn std::error::Error>,
> {
    let mut child = Command::new(python_executable())
        .args(["-m", "src.main", "repl", "--json-stdio"])
        .current_dir(workspace_root())
        .stdin(Stdio::piped())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped())
        .env("SCREAM_REPL_JSON_STDIO", "1")
        .spawn()?;

    let stdout = child
        .stdout
        .take()
        .ok_or("python backend: missing stdout")?;
    let stderr = child
        .stderr
        .take()
        .ok_or("python backend: missing stderr")?;
    let stdin = child.stdin.take().ok_or("python backend: missing stdin")?;

    let (tx, rx) = mpsc::channel::<BackendLine>();
    let tx_out = tx.clone();
    thread::spawn(move || {
        let reader = BufReader::new(stdout);
        for line in reader.lines() {
            match line {
                Ok(l) => {
                    if tx_out.send(BackendLine::Stdout(l)).is_err() {
                        break;
                    }
                }
                Err(_) => break,
            }
        }
    });
    thread::spawn(move || {
        let r = BufReader::new(stderr);
        for line in r.lines() {
            if let Ok(l) = line {
                if tx.send(BackendLine::Stderr(l)).is_err() {
                    break;
                }
            }
        }
    });

    Ok((child, rx, stdin))
}

/// 优雅关闭 Python 后端并在必要时 `kill` + `wait`，避免僵尸/孤儿进程。
fn shutdown_python_backend(stdin: &mut ChildStdin, child: &mut Child) {
    match child.try_wait() {
        Ok(Some(_)) => return,
        Ok(None) | Err(_) => {}
    }
    let _ = writeln!(stdin, r#"{{"op":"shutdown"}}"#);
    let _ = stdin.flush();
    thread::sleep(Duration::from_millis(200));
    match child.try_wait() {
        Ok(Some(_)) => return,
        Ok(None) | Err(_) => {}
    }
    let _ = child.kill();
    let _ = child.wait();
}

fn project_label(cwd: &Path) -> String {
    cwd.file_name()
        .and_then(|s| s.to_str())
        .map(str::to_string)
        .unwrap_or_else(|| cwd.display().to_string())
}

fn status_left_line(snap: &TuiSnapshot) -> Line<'static> {
    let cwd = env::current_dir().unwrap_or_default();
    let dir = project_label(&cwd);
    let branch = resolve_git_branch_for(&cwd)
        .map(|b| format!(" · {b}"))
        .unwrap_or_default();
    let model_disp = if snap.model.trim().is_empty() {
        "—".to_string()
    } else {
        snap.model.clone()
    };
    let meta = format!(
        "  ·  Rust TUI  ·  {}  ·  模型 {}  ·  {}{}",
        dir,
        model_disp,
        permission_mode_zh(snap.permission),
        branch
    );
    Line::from(vec![
        Span::styled(
            "🚀Scream Code🚀",
            Style::default().fg(Color::Rgb(255, 255, 255)).bold(),
        ),
        Span::styled(meta, Style::default().fg(STATUS_FG)),
    ])
}

fn status_right_line(snap: &TuiSnapshot) -> Line<'static> {
    let mode_label = if snap.team_mode {
        "[模式: 群狼]"
    } else {
        "[模式: 常规]"
    };
    let tokens = format!("累计 Token {}", snap.total_tokens);
    Line::from(vec![
        Span::styled(
            mode_label,
            Style::default()
                .fg(if snap.team_mode {
                    Color::Rgb(255, 220, 140)
                } else {
                    Color::Rgb(220, 240, 255)
                })
                .bold(),
        ),
        Span::styled(format!("  ·  {tokens}"), Style::default().fg(STATUS_FG)),
    ])
}

fn style_chat_line(role: ChatLineRole, s: &str) -> Line<'static> {
    let t = s.to_string();
    let base_bg = Style::default().bg(BG);
    match role {
        ChatLineRole::Spacer => Line::from(Span::styled(t, base_bg)),
        ChatLineRole::HeaderUser => Line::from(Span::styled(
            t,
            Style::default()
                .fg(Color::Cyan)
                .add_modifier(Modifier::BOLD)
                .bg(BG),
        )),
        ChatLineRole::HeaderAssistant => Line::from(Span::styled(
            t,
            Style::default()
                .fg(Color::LightCyan)
                .add_modifier(Modifier::BOLD)
                .bg(BG),
        )),
        ChatLineRole::HeaderMeta => Line::from(Span::styled(
            t,
            Style::default()
                .fg(Color::DarkGray)
                .add_modifier(Modifier::ITALIC)
                .bg(BG),
        )),
        ChatLineRole::BodyUser => {
            Line::from(Span::styled(t, Style::default().fg(USER_BODY_FG).bg(BG)))
        }
        ChatLineRole::BodyAssistant => Line::from(Span::styled(
            t,
            Style::default().fg(ASSISTANT_BODY_FG).bg(BG),
        )),
        ChatLineRole::BodyMeta => {
            Line::from(Span::styled(t, Style::default().fg(META_BODY_FG).bg(BG)))
        }
    }
}

fn suspend(terminal: &mut Terminal<CrosstermBackend<io::Stdout>>) -> io::Result<()> {
    disable_raw_mode()?;
    execute!(
        terminal.backend_mut(),
        DisableMouseCapture,
        LeaveAlternateScreen
    )?;
    Ok(())
}

fn resume(terminal: &mut Terminal<CrosstermBackend<io::Stdout>>) -> io::Result<()> {
    execute!(
        terminal.backend_mut(),
        EnterAlternateScreen,
        EnableMouseCapture
    )?;
    enable_raw_mode()?;
    terminal.clear()?;
    Ok(())
}

fn build_textarea() -> TextArea<'static> {
    let mut textarea = TextArea::default();
    configure_textarea(&mut textarea);
    textarea
}

struct SpinnerDrawCtx {
    tick: usize,
    waiting_first_token: bool,
    after_tool: bool,
}

fn spinner_label(ctx: &SpinnerDrawCtx) -> String {
    let frame = SPINNER_FRAMES[ctx.tick % SPINNER_FRAMES.len()];
    let rest = if ctx.after_tool {
        "⚙️ Python 正在执行工具…"
    } else if ctx.waiting_first_token {
        "🧠 Python 编排中…"
    } else {
        "🧠 正在生成回复…"
    };
    format!("{frame}  {rest}")
}

fn draw_ui(
    f: &mut Frame<'_>,
    snap: &TuiSnapshot,
    chat: &ChatLog,
    textarea: &TextArea<'_>,
    main: Rect,
    input_h: u16,
    spinner_ctx: Option<&SpinnerDrawCtx>,
    textarea_viewport: &mut TextViewportScroll,
    chat_scroll_up: usize,
) {
    let term = f.area();
    f.render_widget(Block::default().style(Style::default().bg(BG)), term);

    let geom = compute_repl_draw_layout(main, input_h, spinner_ctx.is_some());
    let chat_area = geom.chat_area;
    let spinner_area = geom.spinner_area;
    let input_area = geom.input_area;
    let status_area = geom.status_area;

    let chat_block = Block::default()
        .borders(Borders::ALL)
        .border_style(Style::default().fg(BORDER))
        .title(Span::styled(" 对话 ", Style::default().fg(ACCENT).bold()));

    let visible = usize::from(geom.inner_h);

    if chat.lines.is_empty() {
        render::render_idle_splash(f, chat_area, chat_block, BG);
        f.render_widget(
            Paragraph::new(Line::from(Span::styled(
                "│",
                Style::default().fg(Color::DarkGray).bg(BG),
            )))
            .style(Style::default().bg(BG)),
            geom.chat_scrollbar_rect,
        );
    } else {
        let rows = chat_visible_rows(chat, geom.inner_w, visible, chat_scroll_up);
        let styled_lines: Vec<Line> = rows
            .iter()
            .map(|(role, s)| style_chat_line(*role, s.as_str()))
            .collect();
        let para = Paragraph::new(Text::from(styled_lines))
            .block(chat_block)
            .style(Style::default().bg(BG))
            .wrap(Wrap { trim: false });
        f.render_widget(para, chat_area);
        let total = flatten_wrapped_chat_lines(&chat.lines, geom.inner_w.max(1)).len();
        render_chat_scrollbar(f, geom.chat_scrollbar_rect, chat_scroll_up, total, visible);
    }

    if let Some(ctx) = spinner_ctx {
        let spin_line = Line::from(vec![Span::styled(
            spinner_label(ctx),
            Style::default().fg(BORDER).bg(BG),
        )]);
        f.render_widget(
            Paragraph::new(spin_line)
                .style(Style::default().bg(BG))
                .alignment(Alignment::Left),
            spinner_area,
        );
    }

    f.render_widget(textarea, input_area);

    let cols = Layout::default()
        .direction(Direction::Horizontal)
        .constraints([Constraint::Percentage(58), Constraint::Percentage(42)])
        .split(status_area);

    let status_base = Style::default().bg(STATUS_BG);
    f.render_widget(
        Paragraph::new(status_left_line(snap))
            .style(status_base)
            .alignment(Alignment::Left)
            .wrap(Wrap { trim: false }),
        cols[0],
    );
    f.render_widget(
        Paragraph::new(status_right_line(snap))
            .style(status_base)
            .alignment(Alignment::Right)
            .wrap(Wrap { trim: false }),
        cols[1],
    );

    let prev_vp = *textarea_viewport;
    let inner = textarea
        .block()
        .map(|b| b.inner(input_area))
        .unwrap_or(input_area);
    if inner.width > 0 && inner.height > 0 {
        let (cr, cc) = textarea.cursor();
        let top_row = next_scroll_top(
            prev_vp.top_row,
            usize_to_u16_saturated(cr),
            inner.height.max(1),
        );
        let top_col = next_scroll_top(
            prev_vp.top_col,
            usize_to_u16_saturated(cc),
            inner.width.max(1),
        );
        *textarea_viewport = TextViewportScroll { top_row, top_col };
        if let Some(p) = textarea_cursor_absolute(textarea, input_area, prev_vp, term) {
            f.set_cursor_position(p);
        }
    }
}

fn process_backend_line(
    line: &str,
    chat: &mut ChatLog,
    snap: &mut TuiSnapshot,
    stream_opened: &mut bool,
) -> Result<bool, Box<dyn std::error::Error>> {
    let v: Value = match serde_json::from_str(line.trim()) {
        Ok(v) => v,
        Err(e) => {
            chat.push_section(
                "后端 (非 JSON 行)",
                &format!("{e}\n{}", line.chars().take(2000).collect::<String>()),
            );
            return Ok(false);
        }
    };
    let ty = v.get("type").and_then(Value::as_str).unwrap_or("");
    match ty {
        "turn_done" => return Ok(true),
        "ready" | "state" => snap.apply_from_json(&v),
        "error" => {
            let m = v.get("message").and_then(Value::as_str).unwrap_or("error");
            chat.push_section("错误", m);
        }
        "system" => {
            let t = v.get("text").and_then(Value::as_str).unwrap_or("");
            chat.push_section("系统", t);
        }
        "shutdown_ack" => {}
        _ => {
            if ty == "text_delta" && !*stream_opened {
                chat.pop_last_plain_block();
                *stream_opened = true;
            }
            if matches!(ty, "api_tool_op" | "tool_phase") {
                *stream_opened = true;
            }
            chat.handle_python_json(&v);
        }
    }
    Ok(false)
}

/// Full-screen TUI backed by Python `repl --json-stdio` (``QueryEnginePort`` / ``llm_client``).
pub fn run_tui_repl() -> Result<(), Box<dyn std::error::Error>> {
    let (mut child, rx, mut stdin) = spawn_python_backend()?;

    let mut last_snap = TuiSnapshot::default();
    let mut pending_stderr: Vec<String> = Vec::new();
    let first_line = loop {
        match rx.recv().map_err(|_| "python backend 无输出即退出")? {
            BackendLine::Stdout(s) => break s,
            BackendLine::Stderr(s) => pending_stderr.push(s),
        }
    };

    enable_raw_mode()?;
    let mut stdout = stdout();
    execute!(stdout, EnterAlternateScreen, EnableMouseCapture, Hide)?;
    let backend = CrosstermBackend::new(stdout);
    let mut terminal = Terminal::new(backend)?;
    terminal.hide_cursor()?;
    terminal.clear()?;

    let mut chat = ChatLog::new();
    for s in pending_stderr {
        chat.push_section("Python stderr", &strip_ansi_for_tui(&s));
    }
    let mut stream_handshake = false;
    match serde_json::from_str::<Value>(first_line.trim()) {
        Ok(v) => {
            if v.get("type").and_then(Value::as_str) == Some("ready") {
                last_snap.apply_from_json(&v);
            } else {
                process_backend_line(
                    &first_line,
                    &mut chat,
                    &mut last_snap,
                    &mut stream_handshake,
                )?;
            }
        }
        Err(e) => {
            chat.push_section(
                "首行解析失败",
                &format!("{e}\n{}", first_line.chars().take(2000).collect::<String>()),
            );
        }
    }

    let mut textarea = build_textarea();
    let mut textarea_scroll = TextViewportScroll::default();
    // 上一帧输入区高度（供本帧事件命中与布局；首帧最少 3 行内容 + 上下边框）
    let mut input_height: u16 = MIN_INPUT_INNER_ROWS as u16 + 2;
    let mut busy = false;
    let mut ui_tick: usize = 0;
    const UI_FRAME_MS: u64 = 50;
    // 聊天记录从底部向上偏移的折叠行数（鼠标滚轮 / PageUp 更新）。
    let mut chat_scroll_up: usize = 0;

    let run_result = (|| -> Result<(), Box<dyn std::error::Error>> {
        let mut stream_opened = false;
        loop {
            // 先阻塞等待帧间隔或输入，避免在鼠标移动等高频事件下 draw + poll 形成忙等占满 CPU。
            let had_event = event::poll(Duration::from_millis(UI_FRAME_MS))?;
            if !had_event && busy {
                ui_tick = ui_tick.wrapping_add(1);
            }

            let mut turn_done = false;
            let mut backend_disconnected = false;
            const RX_DRAIN_CAP: usize = 4096;
            for _ in 0..RX_DRAIN_CAP {
                match rx.try_recv() {
                    Ok(msg) => {
                        let line = match msg {
                            BackendLine::Stdout(l) => l,
                            BackendLine::Stderr(l) => {
                                chat.push_section("Python stderr", &strip_ansi_for_tui(&l));
                                continue;
                            }
                        };
                        if process_backend_line(
                            &line,
                            &mut chat,
                            &mut last_snap,
                            &mut stream_opened,
                        )? {
                            turn_done = true;
                            stream_opened = false;
                            break;
                        }
                    }
                    Err(TryRecvError::Empty) => break,
                    Err(TryRecvError::Disconnected) => {
                        backend_disconnected = true;
                        break;
                    }
                }
            }
            if turn_done {
                busy = false;
                chat_scroll_up = 0;
            }
            if backend_disconnected {
                break;
            }

            let spinner_ctx = if busy {
                Some(SpinnerDrawCtx {
                    tick: ui_tick,
                    waiting_first_token: !stream_opened,
                    after_tool: chat
                        .lines
                        .iter()
                        .rev()
                        .take(8)
                        .any(|(_, l)| l.contains("工具")),
                })
            } else {
                None
            };

            let term_sz = terminal.size()?;
            let term_rect = Rect::new(0, 0, term_sz.width, term_sz.height);

            if had_event {
                let event = event::read()?;
                match event {
                    Event::Mouse(me) => {
                        let lay = compute_repl_draw_layout(
                            term_rect,
                            input_height,
                            spinner_ctx.is_some(),
                        );
                        if rect_contains(lay.chat_area, me.column, me.row) {
                            let vis = usize::from(lay.inner_h.max(1));
                            let mx = max_chat_scroll_up(&chat, lay.inner_w, vis);
                            match me.kind {
                                MouseEventKind::ScrollUp => {
                                    chat_scroll_up = (chat_scroll_up + MOUSE_SCROLL_STEP).min(mx);
                                }
                                MouseEventKind::ScrollDown => {
                                    chat_scroll_up =
                                        chat_scroll_up.saturating_sub(MOUSE_SCROLL_STEP);
                                }
                                _ => {}
                            }
                        }
                    }
                    Event::Key(key) => {
                        if key.kind != KeyEventKind::Press {
                            // ignore Release / Repeat
                        } else if key.modifiers.contains(KeyModifiers::CONTROL)
                            && key.code == KeyCode::Char('c')
                        {
                            let _ = writeln!(stdin, r#"{{"op":"shutdown"}}"#);
                            let _ = stdin.flush();
                            break;
                        } else if key.code == KeyCode::Esc {
                            let _ = writeln!(stdin, r#"{{"op":"shutdown"}}"#);
                            let _ = stdin.flush();
                            break;
                        } else {
                            let lay_k = compute_repl_draw_layout(
                                term_rect,
                                input_height,
                                spinner_ctx.is_some(),
                            );
                            let vis_k = usize::from(lay_k.inner_h.max(1));
                            let mx_k = max_chat_scroll_up(&chat, lay_k.inner_w, vis_k);
                            match key.code {
                                KeyCode::PageUp => {
                                    chat_scroll_up = (chat_scroll_up + vis_k).min(mx_k);
                                }
                                KeyCode::PageDown => {
                                    chat_scroll_up = chat_scroll_up.saturating_sub(vis_k);
                                }
                                _ => {
                                    let submit = key.code == KeyCode::Enter
                                        && !key.modifiers.contains(KeyModifiers::SHIFT);

                                    if submit {
                                        let lines: Vec<String> = textarea.lines().to_vec();
                                        let raw = lines.join("\n");
                                        let trimmed = raw.trim();
                                        if trimmed.is_empty() {
                                            // no-op
                                        } else if busy && trimmed == "/stop" {
                                            writeln!(stdin, r#"{{"op":"stop"}}"#)?;
                                            stdin.flush()?;
                                            textarea = build_textarea();
                                            textarea_scroll = TextViewportScroll::default();
                                        } else if busy {
                                            // ignore submit while busy
                                        } else if trimmed == "/stop" {
                                            let _ = writeln!(stdin, r#"{{"op":"shutdown"}}"#);
                                            let _ = stdin.flush();
                                            break;
                                        } else if matches!(trimmed, "/exit" | "/quit") {
                                            let _ = writeln!(stdin, r#"{{"op":"shutdown"}}"#);
                                            let _ = stdin.flush();
                                            break;
                                        } else {
                                            chat.push_section("你", trimmed);
                                            chat.push_plain("… 正在思考 …");
                                            chat_scroll_up = 0;
                                            let payload = serde_json::json!({ "op": "submit", "text": trimmed });
                                            writeln!(stdin, "{payload}")?;
                                            stdin.flush()?;
                                            busy = true;
                                            textarea = build_textarea();
                                            textarea_scroll = TextViewportScroll::default();
                                        }
                                    } else {
                                        textarea.input(key);
                                    }
                                }
                            }
                        }
                    }
                    _ => {}
                }
            }

            let inner_input_w = term_rect.width.saturating_sub(2).max(1) as usize;
            reflow_textarea_hard_wrap(&mut textarea, inner_input_w);
            let input_rows = textarea
                .lines()
                .len()
                .clamp(MIN_INPUT_INNER_ROWS, MAX_INPUT_INNER_ROWS);
            input_height = input_rows as u16 + 2;

            let layout_pre =
                compute_repl_draw_layout(term_rect, input_height, spinner_ctx.is_some());
            let vmax = usize::from(layout_pre.inner_h.max(1));
            chat_scroll_up =
                chat_scroll_up.min(max_chat_scroll_up(&chat, layout_pre.inner_w, vmax));

            hide_textarea_buffer_caret(&mut textarea);
            terminal.draw(|f| {
                draw_ui(
                    f,
                    &last_snap,
                    &chat,
                    &textarea,
                    f.area(),
                    input_height,
                    spinner_ctx.as_ref(),
                    &mut textarea_scroll,
                    chat_scroll_up,
                );
            })?;
        }
        Ok(())
    })();

    shutdown_python_backend(&mut stdin, &mut child);

    disable_raw_mode()?;
    execute!(
        terminal.backend_mut(),
        DisableMouseCapture,
        LeaveAlternateScreen,
        Show
    )?;
    terminal.show_cursor()?;
    run_result
}

#[cfg(test)]
mod viewport_tests {
    use super::{display_width_char_range, next_scroll_top, split_overflow_line};

    #[test]
    fn split_overflow_wraps_at_display_width() {
        let (a, b) = split_overflow_line("abcdefghij", 4).expect("split");
        assert_eq!(a, "abcd");
        assert_eq!(b, "efghij");
    }

    #[test]
    fn split_overflow_respects_wide_chars() {
        let (a, b) = split_overflow_line("你你好", 2).expect("split");
        assert_eq!(a, "你");
        assert_eq!(b, "你好");
    }

    #[test]
    fn next_scroll_top_keeps_cursor_visible() {
        assert_eq!(next_scroll_top(0, 3, 5), 0);
        assert_eq!(next_scroll_top(0, 5, 5), 1);
        assert_eq!(next_scroll_top(2, 1, 5), 1);
    }

    #[test]
    fn display_width_counts_wide_chars() {
        assert_eq!(display_width_char_range("你好", 0, 1), 2);
        assert_eq!(display_width_char_range("你好", 0, 2), 4);
        assert_eq!(display_width_char_range("a你", 0, 2), 3);
    }
}

#[cfg(test)]
mod ansi_tests {
    use super::{flatten_wrapped_chat_lines, strip_ansi_for_tui, ChatLineRole};

    #[test]
    fn wrap_splits_long_logical_line() {
        let s = "a".repeat(50);
        let lines = vec![(ChatLineRole::BodyUser, s)];
        let out = flatten_wrapped_chat_lines(&lines, 20);
        assert!(
            out.iter().all(|(_, row)| row.chars().count() <= 20),
            "each row should fit width: {out:?}"
        );
        assert!(out.len() >= 2, "expected multiple rows: {out:?}");
        assert!(
            out.iter().all(|(r, _)| *r == ChatLineRole::BodyUser),
            "role preserved per wrapped row"
        );
    }

    #[test]
    fn strips_sgr_cyan() {
        let raw = "\x1b[36mvisible\x1b[0m";
        assert_eq!(strip_ansi_for_tui(raw), "visible");
    }

    #[test]
    fn strips_bold_yellow_style() {
        let raw = "\x1b[1;33mwarn\x1b[0m";
        assert_eq!(strip_ansi_for_tui(raw), "warn");
    }
}
