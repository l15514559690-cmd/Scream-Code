//! In-memory worker-boot state machine and control registry.
//!
//! This provides a foundational control plane for reliable worker startup:
//! trust-gate detection, ready-for-prompt handshakes, and prompt-misdelivery
//! detection/recovery all live above raw terminal transport.

use std::collections::HashMap;
use std::path::{Path, PathBuf};
use std::sync::{Arc, Mutex};
use std::time::{SystemTime, UNIX_EPOCH};

use serde::{Deserialize, Serialize};

fn now_secs() -> u64 {
    SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .unwrap_or_default()
        .as_secs()
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkerStatus {
    Spawning,
    TrustRequired,
    ReadyForPrompt,
    Running,
    Finished,
    Failed,
}

impl std::fmt::Display for WorkerStatus {
    fn fmt(&self, f: &mut std::fmt::Formatter<'_>) -> std::fmt::Result {
        match self {
            Self::Spawning => write!(f, "spawning"),
            Self::TrustRequired => write!(f, "trust_required"),
            Self::ReadyForPrompt => write!(f, "ready_for_prompt"),
            Self::Running => write!(f, "running"),
            Self::Finished => write!(f, "finished"),
            Self::Failed => write!(f, "failed"),
        }
    }
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkerFailureKind {
    TrustGate,
    PromptDelivery,
    Protocol,
    Provider,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkerFailure {
    pub kind: WorkerFailureKind,
    pub message: String,
    pub created_at: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkerEventKind {
    Spawning,
    TrustRequired,
    TrustResolved,
    ReadyForPrompt,
    PromptMisdelivery,
    PromptReplayArmed,
    Running,
    Restarted,
    Finished,
    Failed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkerTrustResolution {
    AutoAllowlisted,
    ManualApproval,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkerPromptTarget {
    Shell,
    WrongTarget,
    Unknown,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum WorkerEventPayload {
    TrustPrompt {
        cwd: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        resolution: Option<WorkerTrustResolution>,
    },
    PromptDelivery {
        prompt_preview: String,
        observed_target: WorkerPromptTarget,
        #[serde(skip_serializing_if = "Option::is_none")]
        observed_cwd: Option<String>,
        recovery_armed: bool,
    },
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkerEvent {
    pub seq: u64,
    pub kind: WorkerEventKind,
    pub status: WorkerStatus,
    pub detail: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub payload: Option<WorkerEventPayload>,
    pub timestamp: u64,
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct Worker {
    pub worker_id: String,
    pub cwd: String,
    pub status: WorkerStatus,
    pub trust_auto_resolve: bool,
    pub trust_gate_cleared: bool,
    pub auto_recover_prompt_misdelivery: bool,
    pub prompt_delivery_attempts: u32,
    pub prompt_in_flight: bool,
    pub last_prompt: Option<String>,
    pub replay_prompt: Option<String>,
    pub last_error: Option<WorkerFailure>,
    pub created_at: u64,
    pub updated_at: u64,
    pub events: Vec<WorkerEvent>,
}

#[derive(Debug, Clone, Default)]
pub struct WorkerRegistry {
    inner: Arc<Mutex<WorkerRegistryInner>>,
}

#[derive(Debug, Default)]
struct WorkerRegistryInner {
    workers: HashMap<String, Worker>,
    counter: u64,
}

impl WorkerRegistry {
    #[must_use]
    pub fn new() -> Self {
        Self::default()
    }

    #[must_use]
    pub fn create(
        &self,
        cwd: &str,
        trusted_roots: &[String],
        auto_recover_prompt_misdelivery: bool,
    ) -> Worker {
        let mut inner = self.inner.lock().expect("worker registry lock poisoned");
        inner.counter += 1;
        let ts = now_secs();
        let worker_id = format!("worker_{:08x}_{}", ts, inner.counter);
        let trust_auto_resolve = trusted_roots
            .iter()
            .any(|root| path_matches_allowlist(cwd, root));
        let mut worker = Worker {
            worker_id: worker_id.clone(),
            cwd: cwd.to_owned(),
            status: WorkerStatus::Spawning,
            trust_auto_resolve,
            trust_gate_cleared: false,
            auto_recover_prompt_misdelivery,
            prompt_delivery_attempts: 0,
            prompt_in_flight: false,
            last_prompt: None,
            replay_prompt: None,
            last_error: None,
            created_at: ts,
            updated_at: ts,
            events: Vec::new(),
        };
        push_event(
            &mut worker,
            WorkerEventKind::Spawning,
            WorkerStatus::Spawning,
            Some("worker created".to_string()),
            None,
        );
        inner.workers.insert(worker_id, worker.clone());
        worker
    }

    #[must_use]
    pub fn get(&self, worker_id: &str) -> Option<Worker> {
        let inner = self.inner.lock().expect("worker registry lock poisoned");
        inner.workers.get(worker_id).cloned()
    }

    pub fn observe(&self, worker_id: &str, screen_text: &str) -> Result<Worker, String> {
        let mut inner = self.inner.lock().expect("worker registry lock poisoned");
        let worker = inner
            .workers
            .get_mut(worker_id)
            .ok_or_else(|| format!("worker not found: {worker_id}"))?;
        let lowered = screen_text.to_ascii_lowercase();

        if !worker.trust_gate_cleared && detect_trust_prompt(&lowered) {
            worker.status = WorkerStatus::TrustRequired;
            worker.last_error = Some(WorkerFailure {
                kind: WorkerFailureKind::TrustGate,
                message: "worker boot blocked on trust prompt".to_string(),
                created_at: now_secs(),
            });
            push_event(
                worker,
                WorkerEventKind::TrustRequired,
                WorkerStatus::TrustRequired,
                Some("trust prompt detected".to_string()),
                Some(WorkerEventPayload::TrustPrompt {
                    cwd: worker.cwd.clone(),
                    resolution: None,
                }),
            );

            if worker.trust_auto_resolve {
                worker.trust_gate_cleared = true;
                worker.last_error = None;
                worker.status = WorkerStatus::Spawning;
                push_event(
                    worker,
                    WorkerEventKind::TrustResolved,
                    WorkerStatus::Spawning,
                    Some("allowlisted repo auto-resolved trust prompt".to_string()),
                    Some(WorkerEventPayload::TrustPrompt {
                        cwd: worker.cwd.clone(),
                        resolution: Some(WorkerTrustResolution::AutoAllowlisted),
                    }),
                );
            } else {
                return Ok(worker.clone());
            }
        }

        if let Some(observation) = prompt_misdelivery_is_relevant(worker)
            .then(|| {
                detect_prompt_misdelivery(
                    screen_text,
                    &lowered,
                    worker.last_prompt.as_deref(),
                    &worker.cwd,
                )
            })
            .flatten()
        {
            let prompt_preview = prompt_preview(worker.last_prompt.as_deref().unwrap_or_default());
            let message = match observation.target {
                WorkerPromptTarget::Shell => {
                    format!("worker prompt landed in shell instead of coding agent: {prompt_preview}")
                }
                WorkerPromptTarget::WrongTarget => format!(
                    "worker prompt landed in the wrong target instead of {}: {}",
                    worker.cwd, prompt_preview
                ),
                WorkerPromptTarget::Unknown => format!(
                    "worker prompt delivery failed before reaching coding agent: {prompt_preview}"
                ),
            };
            worker.last_error = Some(WorkerFailure {
                kind: WorkerFailureKind::PromptDelivery,
                message,
                created_at: now_secs(),
            });
            worker.prompt_in_flight = false;
            push_event(
                worker,
                WorkerEventKind::PromptMisdelivery,
                WorkerStatus::Failed,
                Some(prompt_misdelivery_detail(&observation).to_string()),
                Some(WorkerEventPayload::PromptDelivery {
                    prompt_preview: prompt_preview.clone(),
                    observed_target: observation.target,
                    observed_cwd: observation.observed_cwd.clone(),
                    recovery_armed: false,
                }),
            );
            if worker.auto_recover_prompt_misdelivery {
                worker.replay_prompt = worker.last_prompt.clone();
                worker.status = WorkerStatus::ReadyForPrompt;
                push_event(
                    worker,
                    WorkerEventKind::PromptReplayArmed,
                    WorkerStatus::ReadyForPrompt,
                    Some("prompt replay armed after prompt misdelivery".to_string()),
                    Some(WorkerEventPayload::PromptDelivery {
                        prompt_preview,
                        observed_target: observation.target,
                        observed_cwd: observation.observed_cwd,
                        recovery_armed: true,
                    }),
                );
            } else {
                worker.status = WorkerStatus::Failed;
            }
            return Ok(worker.clone());
        }

        if detect_running_cue(&lowered) && worker.prompt_in_flight {
            worker.prompt_in_flight = false;
            worker.status = WorkerStatus::Running;
            worker.last_error = None;
        }

        if detect_ready_for_prompt(screen_text, &lowered) && worker.status != WorkerStatus::ReadyForPrompt {
            worker.status = WorkerStatus::ReadyForPrompt;
            worker.prompt_in_flight = false;
            if matches!(
                worker.last_error.as_ref().map(|failure| failure.kind),
                Some(WorkerFailureKind::TrustGate)
            ) {
                worker.last_error = None;
            }
            push_event(
                worker,
                WorkerEventKind::ReadyForPrompt,
                WorkerStatus::ReadyForPrompt,
                Some("worker is ready for prompt delivery".to_string()),
                None,
            );
        }

        Ok(worker.clone())
    }

    pub fn resolve_trust(&self, worker_id: &str) -> Result<Worker, String> {
        let mut inner = self.inner.lock().expect("worker registry lock poisoned");
        let worker = inner
            .workers
            .get_mut(worker_id)
            .ok_or_else(|| format!("worker not found: {worker_id}"))?;

        if worker.status != WorkerStatus::TrustRequired {
            return Err(format!(
                "worker {worker_id} is not waiting on trust; current status: {}",
                worker.status
            ));
        }

        worker.trust_gate_cleared = true;
        worker.last_error = None;
        worker.status = WorkerStatus::Spawning;
        push_event(
            worker,
            WorkerEventKind::TrustResolved,
            WorkerStatus::Spawning,
            Some("trust prompt resolved manually".to_string()),
            Some(WorkerEventPayload::TrustPrompt {
                cwd: worker.cwd.clone(),
                resolution: Some(WorkerTrustResolution::ManualApproval),
            }),
        );
        Ok(worker.clone())
    }

    pub fn send_prompt(&self, worker_id: &str, prompt: Option<&str>) -> Result<Worker, String> {
        let mut inner = self.inner.lock().expect("worker registry lock poisoned");
        let worker = inner
            .workers
            .get_mut(worker_id)
            .ok_or_else(|| format!("worker not found: {worker_id}"))?;

        if worker.status != WorkerStatus::ReadyForPrompt {
            return Err(format!(
                "worker {worker_id} is not ready for prompt delivery; current status: {}",
                worker.status
            ));
        }

        let next_prompt = prompt
            .map(str::trim)
            .filter(|value| !value.is_empty())
            .map(str::to_owned)
            .or_else(|| worker.replay_prompt.clone())
            .ok_or_else(|| format!("worker {worker_id} has no prompt to send or replay"))?;

        worker.prompt_delivery_attempts += 1;
        worker.prompt_in_flight = true;
        worker.last_prompt = Some(next_prompt.clone());
        worker.replay_prompt = None;
        worker.last_error = None;
        worker.status = WorkerStatus::Running;
        push_event(
            worker,
            WorkerEventKind::Running,
            WorkerStatus::Running,
            Some(format!(
                "prompt dispatched to worker: {}",
                prompt_preview(&next_prompt)
            )),
            None,
        );
        Ok(worker.clone())
    }

    pub fn await_ready(&self, worker_id: &str) -> Result<WorkerReadySnapshot, String> {
        let worker = self
            .get(worker_id)
            .ok_or_else(|| format!("worker not found: {worker_id}"))?;

        Ok(WorkerReadySnapshot {
            worker_id: worker.worker_id.clone(),
            status: worker.status,
            ready: worker.status == WorkerStatus::ReadyForPrompt,
            blocked: matches!(worker.status, WorkerStatus::TrustRequired | WorkerStatus::Failed),
            replay_prompt_ready: worker.replay_prompt.is_some(),
            last_error: worker.last_error.clone(),
        })
    }

    pub fn restart(&self, worker_id: &str) -> Result<Worker, String> {
        let mut inner = self.inner.lock().expect("worker registry lock poisoned");
        let worker = inner
            .workers
            .get_mut(worker_id)
            .ok_or_else(|| format!("worker not found: {worker_id}"))?;
        worker.status = WorkerStatus::Spawning;
        worker.trust_gate_cleared = false;
        worker.last_prompt = None;
        worker.replay_prompt = None;
        worker.last_error = None;
        worker.prompt_delivery_attempts = 0;
        worker.prompt_in_flight = false;
        push_event(
            worker,
            WorkerEventKind::Restarted,
            WorkerStatus::Spawning,
            Some("worker restarted".to_string()),
            None,
        );
        Ok(worker.clone())
    }

    pub fn terminate(&self, worker_id: &str) -> Result<Worker, String> {
        let mut inner = self.inner.lock().expect("worker registry lock poisoned");
        let worker = inner
            .workers
            .get_mut(worker_id)
            .ok_or_else(|| format!("worker not found: {worker_id}"))?;
        worker.status = WorkerStatus::Finished;
        worker.prompt_in_flight = false;
        push_event(
            worker,
            WorkerEventKind::Finished,
            WorkerStatus::Finished,
            Some("worker terminated by control plane".to_string()),
            None,
        );
        Ok(worker.clone())
    }

    /// Classify session completion and transition worker to appropriate terminal state.
    /// Detects degraded completions (finish="unknown" with zero tokens) as provider failures.
    pub fn observe_completion(
        &self,
        worker_id: &str,
        finish_reason: &str,
        tokens_output: u64,
    ) -> Result<Worker, String> {
        let mut inner = self.inner.lock().expect("worker registry lock poisoned");
        let worker = inner
            .workers
            .get_mut(worker_id)
            .ok_or_else(|| format!("worker not found: {worker_id}"))?;

        let is_provider_failure =
            (finish_reason == "unknown" && tokens_output == 0) || finish_reason == "error";

        if is_provider_failure {
            let message = if finish_reason == "unknown" && tokens_output == 0 {
                "session completed with finish='unknown' and zero output — provider degraded or context exhausted".to_string()
            } else {
                format!("session failed with finish='{finish_reason}' — provider error")
            };

            worker.last_error = Some(WorkerFailure {
                kind: WorkerFailureKind::Provider,
                message,
                created_at: now_secs(),
            });
            worker.status = WorkerStatus::Failed;
            worker.prompt_in_flight = false;
            push_event(
                worker,
                WorkerEventKind::Failed,
                WorkerStatus::Failed,
                Some("provider failure classified".to_string()),
                None,
            );
        } else {
            worker.status = WorkerStatus::Finished;
            worker.prompt_in_flight = false;
            worker.last_error = None;
            push_event(
                worker,
                WorkerEventKind::Finished,
                WorkerStatus::Finished,
                Some(format!(
                    "session completed: finish='{finish_reason}', tokens={tokens_output}"
                )),
                None,
            );
        }

        Ok(worker.clone())
    }
}

#[derive(Debug, Clone, Serialize, Deserialize, PartialEq, Eq)]
pub struct WorkerReadySnapshot {
    pub worker_id: String,
    pub status: WorkerStatus,
    pub ready: bool,
    pub blocked: bool,
    pub replay_prompt_ready: bool,
    pub last_error: Option<WorkerFailure>,
}

fn prompt_misdelivery_is_relevant(worker: &Worker) -> bool {
    worker.prompt_in_flight && worker.last_prompt.is_some()
}

#[derive(Debug, Clone, PartialEq, Eq)]
struct PromptDeliveryObservation {
    target: WorkerPromptTarget,
    observed_cwd: Option<String>,
}

fn push_event(
    worker: &mut Worker,
    kind: WorkerEventKind,
    status: WorkerStatus,
    detail: Option<String>,
    payload: Option<WorkerEventPayload>,
) {
    let timestamp = now_secs();
    let seq = worker.events.len() as u64 + 1;
    worker.updated_at = timestamp;
    worker.events.push(WorkerEvent {
        seq,
        kind,
        status,
        detail,
        payload,
        timestamp,
    });
}

fn path_matches_allowlist(cwd: &str, trusted_root: &str) -> bool {
    let cwd = normalize_path(cwd);
    let trusted_root = normalize_path(trusted_root);
    cwd == trusted_root || cwd.starts_with(&trusted_root)
}

fn normalize_path(path: &str) -> PathBuf {
    std::fs::canonicalize(path).unwrap_or_else(|_| Path::new(path).to_path_buf())
}

fn detect_trust_prompt(lowered: &str) -> bool {
    [
        "do you trust the files in this folder",
        "trust the files in this folder",
        "trust this folder",
        "allow and continue",
        "yes, proceed",
    ]
    .iter()
    .any(|needle| lowered.contains(needle))
}

fn detect_ready_for_prompt(screen_text: &str, lowered: &str) -> bool {
    if [
        "ready for input",
        "ready for your input",
        "ready for prompt",
        "send a message",
    ]
    .iter()
    .any(|needle| lowered.contains(needle))
    {
        return true;
    }

    let Some(last_non_empty) = screen_text
        .lines()
        .rev()
        .find(|line| !line.trim().is_empty())
    else {
        return false;
    };
    let trimmed = last_non_empty.trim();
    if is_shell_prompt(trimmed) {
        return false;
    }

    trimmed == ">"
        || trimmed == "›"
        || trimmed == "❯"
        || trimmed.starts_with("> ")
        || trimmed.starts_with("› ")
        || trimmed.starts_with("❯ ")
        || trimmed.contains("│ >")
        || trimmed.contains("│ ›")
        || trimmed.contains("│ ❯")
}

fn detect_running_cue(lowered: &str) -> bool {
    [
        "thinking",
        "working",
        "running tests",
        "inspecting",
        "analyzing",
    ]
    .iter()
    .any(|needle| lowered.contains(needle))
}

fn is_shell_prompt(trimmed: &str) -> bool {
    trimmed.ends_with('$')
        || trimmed.ends_with('%')
        || trimmed.ends_with('#')
        || trimmed.starts_with('$')
        || trimmed.starts_with('%')
        || trimmed.starts_with('#')
}

fn detect_prompt_misdelivery(
    screen_text: &str,
    lowered: &str,
    prompt: Option<&str>,
    expected_cwd: &str,
) -> Option<PromptDeliveryObservation> {
    let Some(prompt) = prompt else {
        return None;
    };

    let prompt_snippet = prompt
        .lines()
        .find(|line| !line.trim().is_empty())
        .map(|line| line.trim().to_ascii_lowercase())
        .unwrap_or_default();
    if prompt_snippet.is_empty() {
        return None;
    }
    let prompt_visible = lowered.contains(&prompt_snippet);

    if let Some(observed_cwd) = detect_observed_shell_cwd(screen_text) {
        if prompt_visible && !cwd_matches_observed_target(expected_cwd, &observed_cwd) {
            return Some(PromptDeliveryObservation {
                target: WorkerPromptTarget::WrongTarget,
                observed_cwd: Some(observed_cwd),
            });
        }
    }

    let shell_error = [
        "command not found",
        "syntax error near unexpected token",
        "parse error near",
        "no such file or directory",
        "unknown command",
    ]
    .iter()
    .any(|needle| lowered.contains(needle));

    (shell_error && prompt_visible).then_some(PromptDeliveryObservation {
        target: WorkerPromptTarget::Shell,
        observed_cwd: None,
    })
}

fn prompt_preview(prompt: &str) -> String {
    let trimmed = prompt.trim();
    if trimmed.chars().count() <= 48 {
        return trimmed.to_string();
    }
    let preview = trimmed.chars().take(48).collect::<String>();
    format!("{}…", preview.trim_end())
}

fn prompt_misdelivery_detail(observation: &PromptDeliveryObservation) -> &'static str {
    match observation.target {
        WorkerPromptTarget::Shell => "shell misdelivery detected",
        WorkerPromptTarget::WrongTarget => "prompt landed in wrong target",
        WorkerPromptTarget::Unknown => "prompt delivery failure detected",
    }
}

fn detect_observed_shell_cwd(screen_text: &str) -> Option<String> {
    screen_text.lines().find_map(|line| {
        let tokens = line.split_whitespace().collect::<Vec<_>>();
        tokens
            .iter()
            .position(|token| is_shell_prompt_token(token))
            .and_then(|index| index.checked_sub(1).map(|cwd_index| tokens[cwd_index]))
            .filter(|candidate| looks_like_cwd_label(candidate))
            .map(ToOwned::to_owned)
    })
}

fn is_shell_prompt_token(token: &&str) -> bool {
    matches!(*token, "$" | "%" | "#" | ">" | "›" | "❯")
}

fn looks_like_cwd_label(candidate: &str) -> bool {
    candidate.starts_with('/')
        || candidate.starts_with('~')
        || candidate.starts_with('.')
        || candidate.contains('/')
}

fn cwd_matches_observed_target(expected_cwd: &str, observed_cwd: &str) -> bool {
    let expected = normalize_path(expected_cwd);
    let expected_base = expected
        .file_name()
        .map(|segment| segment.to_string_lossy().into_owned())
        .unwrap_or_else(|| expected.to_string_lossy().into_owned());
    let observed_base = Path::new(observed_cwd)
        .file_name()
        .map(|segment| segment.to_string_lossy().into_owned())
        .unwrap_or_else(|| observed_cwd.trim_matches(':').to_string());

    expected.to_string_lossy().ends_with(observed_cwd)
        || observed_cwd.ends_with(expected.to_string_lossy().as_ref())
        || expected_base == observed_base
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn allowlisted_trust_prompt_auto_resolves_then_reaches_ready_state() {
        let registry = WorkerRegistry::new();
        let worker = registry.create(
            "/tmp/worktrees/repo-a",
            &["/tmp/worktrees".to_string()],
            true,
        );

        let after_trust = registry
            .observe(
                &worker.worker_id,
                "Do you trust the files in this folder?\n1. Yes, proceed\n2. No",
            )
            .expect("trust observe should succeed");
        assert_eq!(after_trust.status, WorkerStatus::Spawning);
        assert!(after_trust.trust_gate_cleared);
        let trust_required = after_trust
            .events
            .iter()
            .find(|event| event.kind == WorkerEventKind::TrustRequired)
            .expect("trust required event should exist");
        assert_eq!(
            trust_required.payload,
            Some(WorkerEventPayload::TrustPrompt {
                cwd: "/tmp/worktrees/repo-a".to_string(),
                resolution: None,
            })
        );
        let trust_resolved = after_trust
            .events
            .iter()
            .find(|event| event.kind == WorkerEventKind::TrustResolved)
            .expect("trust resolved event should exist");
        assert_eq!(
            trust_resolved.payload,
            Some(WorkerEventPayload::TrustPrompt {
                cwd: "/tmp/worktrees/repo-a".to_string(),
                resolution: Some(WorkerTrustResolution::AutoAllowlisted),
            })
        );

        let ready = registry
            .observe(&worker.worker_id, "Ready for your input\n>")
            .expect("ready observe should succeed");
        assert_eq!(ready.status, WorkerStatus::ReadyForPrompt);
        assert!(ready.last_error.is_none());
    }

    #[test]
    fn trust_prompt_blocks_non_allowlisted_worker_until_resolved() {
        let registry = WorkerRegistry::new();
        let worker = registry.create("/tmp/repo-b", &[], true);

        let blocked = registry
            .observe(
                &worker.worker_id,
                "Do you trust the files in this folder?\n1. Yes, proceed\n2. No",
            )
            .expect("trust observe should succeed");
        assert_eq!(blocked.status, WorkerStatus::TrustRequired);
        assert_eq!(
            blocked.last_error.expect("trust error should exist").kind,
            WorkerFailureKind::TrustGate
        );

        let send_before_resolve = registry.send_prompt(&worker.worker_id, Some("ship it"));
        assert!(send_before_resolve
            .expect_err("prompt delivery should be gated")
            .contains("not ready for prompt delivery"));

        let resolved = registry
            .resolve_trust(&worker.worker_id)
            .expect("manual trust resolution should succeed");
        assert_eq!(resolved.status, WorkerStatus::Spawning);
        assert!(resolved.trust_gate_cleared);
        let trust_resolved = resolved
            .events
            .iter()
            .find(|event| event.kind == WorkerEventKind::TrustResolved)
            .expect("manual trust resolve event should exist");
        assert_eq!(
            trust_resolved.payload,
            Some(WorkerEventPayload::TrustPrompt {
                cwd: "/tmp/repo-b".to_string(),
                resolution: Some(WorkerTrustResolution::ManualApproval),
            })
        );
    }

    #[test]
    fn ready_detection_ignores_plain_shell_prompts() {
        assert!(!detect_ready_for_prompt("bellman@host %", "bellman@host %"));
        assert!(!detect_ready_for_prompt("/tmp/repo $", "/tmp/repo $"));
        assert!(detect_ready_for_prompt("│ >", "│ >"));
    }

    #[test]
    fn prompt_misdelivery_is_detected_and_replay_can_be_rearmed() {
        let registry = WorkerRegistry::new();
        let worker = registry.create("/tmp/repo-c", &[], true);
        registry
            .observe(&worker.worker_id, "Ready for input\n>")
            .expect("ready observe should succeed");

        let running = registry
            .send_prompt(&worker.worker_id, Some("Implement worker handshake"))
            .expect("prompt send should succeed");
        assert_eq!(running.status, WorkerStatus::Running);
        assert_eq!(running.prompt_delivery_attempts, 1);
        assert!(running.prompt_in_flight);

        let recovered = registry
            .observe(
                &worker.worker_id,
                "% Implement worker handshake\nzsh: command not found: Implement",
            )
            .expect("misdelivery observe should succeed");
        assert_eq!(recovered.status, WorkerStatus::ReadyForPrompt);
        assert_eq!(
            recovered
                .last_error
                .expect("misdelivery error should exist")
                .kind,
            WorkerFailureKind::PromptDelivery
        );
        assert_eq!(
            recovered.replay_prompt.as_deref(),
            Some("Implement worker handshake")
        );
        let misdelivery = recovered
            .events
            .iter()
            .find(|event| event.kind == WorkerEventKind::PromptMisdelivery)
            .expect("misdelivery event should exist");
        assert_eq!(misdelivery.status, WorkerStatus::Failed);
        assert_eq!(
            misdelivery.payload,
            Some(WorkerEventPayload::PromptDelivery {
                prompt_preview: "Implement worker handshake".to_string(),
                observed_target: WorkerPromptTarget::Shell,
                observed_cwd: None,
                recovery_armed: false,
            })
        );
        let replay = recovered
            .events
            .iter()
            .find(|event| event.kind == WorkerEventKind::PromptReplayArmed)
            .expect("replay event should exist");
        assert_eq!(replay.status, WorkerStatus::ReadyForPrompt);
        assert_eq!(
            replay.payload,
            Some(WorkerEventPayload::PromptDelivery {
                prompt_preview: "Implement worker handshake".to_string(),
                observed_target: WorkerPromptTarget::Shell,
                observed_cwd: None,
                recovery_armed: true,
            })
        );

        let replayed = registry
            .send_prompt(&worker.worker_id, None)
            .expect("replay send should succeed");
        assert_eq!(replayed.status, WorkerStatus::Running);
        assert!(replayed.replay_prompt.is_none());
        assert_eq!(replayed.prompt_delivery_attempts, 2);
    }

    #[test]
    fn prompt_delivery_detects_wrong_target_and_replays_to_expected_worker() {
        let registry = WorkerRegistry::new();
        let worker = registry.create("/tmp/repo-target-a", &[], true);
        registry
            .observe(&worker.worker_id, "Ready for input\n>")
            .expect("ready observe should succeed");
        registry
            .send_prompt(&worker.worker_id, Some("Run the worker bootstrap tests"))
            .expect("prompt send should succeed");

        let recovered = registry
            .observe(
                &worker.worker_id,
                "/tmp/repo-target-b % Run the worker bootstrap tests\nzsh: command not found: Run",
            )
            .expect("wrong target should be detected");

        assert_eq!(recovered.status, WorkerStatus::ReadyForPrompt);
        assert_eq!(
            recovered.replay_prompt.as_deref(),
            Some("Run the worker bootstrap tests")
        );
        assert!(recovered
            .last_error
            .expect("wrong target error should exist")
            .message
            .contains("wrong target"));
        let misdelivery = recovered
            .events
            .iter()
            .find(|event| event.kind == WorkerEventKind::PromptMisdelivery)
            .expect("wrong-target event should exist");
        assert_eq!(
            misdelivery.payload,
            Some(WorkerEventPayload::PromptDelivery {
                prompt_preview: "Run the worker bootstrap tests".to_string(),
                observed_target: WorkerPromptTarget::WrongTarget,
                observed_cwd: Some("/tmp/repo-target-b".to_string()),
                recovery_armed: false,
            })
        );
    }

    #[test]
    fn await_ready_surfaces_blocked_or_ready_worker_state() {
        let registry = WorkerRegistry::new();
        let worker = registry.create("/tmp/repo-d", &[], false);

        let initial = registry
            .await_ready(&worker.worker_id)
            .expect("await should succeed");
        assert!(!initial.ready);
        assert!(!initial.blocked);

        registry
            .observe(
                &worker.worker_id,
                "Do you trust the files in this folder?\n1. Yes, proceed\n2. No",
            )
            .expect("trust observe should succeed");
        let blocked = registry
            .await_ready(&worker.worker_id)
            .expect("await should succeed");
        assert!(!blocked.ready);
        assert!(blocked.blocked);

        registry
            .resolve_trust(&worker.worker_id)
            .expect("manual trust resolution should succeed");
        registry
            .observe(&worker.worker_id, "Ready for your input\n>")
            .expect("ready observe should succeed");
        let ready = registry
            .await_ready(&worker.worker_id)
            .expect("await should succeed");
        assert!(ready.ready);
        assert!(!ready.blocked);
        assert!(ready.last_error.is_none());
    }

    #[test]
    fn restart_and_terminate_reset_or_finish_worker() {
        let registry = WorkerRegistry::new();
        let worker = registry.create("/tmp/repo-e", &[], true);
        registry
            .observe(&worker.worker_id, "Ready for input\n>")
            .expect("ready observe should succeed");
        registry
            .send_prompt(&worker.worker_id, Some("Run tests"))
            .expect("prompt send should succeed");

        let restarted = registry
            .restart(&worker.worker_id)
            .expect("restart should succeed");
        assert_eq!(restarted.status, WorkerStatus::Spawning);
        assert_eq!(restarted.prompt_delivery_attempts, 0);
        assert!(restarted.last_prompt.is_none());
        assert!(!restarted.prompt_in_flight);

        let finished = registry
            .terminate(&worker.worker_id)
            .expect("terminate should succeed");
        assert_eq!(finished.status, WorkerStatus::Finished);
        assert!(finished
            .events
            .iter()
            .any(|event| event.kind == WorkerEventKind::Finished));
    }

    #[test]
    fn observe_completion_classifies_provider_failure_on_unknown_finish_zero_tokens() {
        let registry = WorkerRegistry::new();
        let worker = registry.create("/tmp/repo-f", &[], true);
        registry
            .observe(&worker.worker_id, "Ready for input\n>")
            .expect("ready observe should succeed");
        registry
            .send_prompt(&worker.worker_id, Some("Run tests"))
            .expect("prompt send should succeed");

        let failed = registry
            .observe_completion(&worker.worker_id, "unknown", 0)
            .expect("completion observe should succeed");

        assert_eq!(failed.status, WorkerStatus::Failed);
        let error = failed.last_error.expect("provider error should exist");
        assert_eq!(error.kind, WorkerFailureKind::Provider);
        assert!(error.message.contains("provider degraded"));
        assert!(failed
            .events
            .iter()
            .any(|event| event.kind == WorkerEventKind::Failed));
    }

    #[test]
    fn observe_completion_accepts_normal_finish_with_tokens() {
        let registry = WorkerRegistry::new();
        let worker = registry.create("/tmp/repo-g", &[], true);
        registry
            .observe(&worker.worker_id, "Ready for input\n>")
            .expect("ready observe should succeed");
        registry
            .send_prompt(&worker.worker_id, Some("Run tests"))
            .expect("prompt send should succeed");

        let finished = registry
            .observe_completion(&worker.worker_id, "stop", 150)
            .expect("completion observe should succeed");

        assert_eq!(finished.status, WorkerStatus::Finished);
        assert!(finished.last_error.is_none());
        assert!(finished
            .events
            .iter()
            .any(|event| event.kind == WorkerEventKind::Finished));
    }
}
