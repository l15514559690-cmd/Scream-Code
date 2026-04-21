//! Optional repo-root `llm_config.json` (shared with the Python stack): active model + env-based API keys.

use std::env;
use std::fs;
use std::path::{Path, PathBuf};

use serde::Deserialize;

#[derive(Debug, Deserialize)]
struct LlmConfigRoot {
    active: Option<String>,
    models: Vec<LlmModelEntry>,
}

#[derive(Debug, Deserialize)]
struct LlmModelEntry {
    id: String,
    base_url: String,
    model_name: String,
    api_key_env_name: String,
    #[serde(default = "default_protocol")]
    api_protocol: String,
}

fn default_protocol() -> String {
    "openai".to_string()
}

/// Resolved active profile when `api_key_env_name` is set in the environment (after `.env` load).
#[derive(Debug, Clone)]
pub struct ActiveLlmProfile {
    pub base_url: String,
    pub model_name: String,
    pub api_key: String,
    pub api_protocol: String,
}

fn find_llm_config_path() -> Option<PathBuf> {
    if let Ok(cwd) = env::current_dir() {
        let mut dir = Some(cwd.as_path());
        while let Some(p) = dir {
            let candidate = p.join("llm_config.json");
            if candidate.is_file() {
                return Some(candidate);
            }
            dir = p.parent();
        }
    }
    let manifest = Path::new(env!("CARGO_MANIFEST_DIR"));
    let repo_root = manifest.parent()?.parent()?.parent()?;
    let candidate = repo_root.join("llm_config.json");
    candidate.is_file().then_some(candidate)
}

fn read_active_model_entry() -> Option<LlmModelEntry> {
    let path = find_llm_config_path()?;
    let raw = fs::read_to_string(path).ok()?;
    let cfg: LlmConfigRoot = serde_json::from_str(&raw).ok()?;
    let active_id = cfg.active?;
    cfg.models.into_iter().find(|m| m.id == active_id)
}

/// If `MODEL` is unset, set it from `llm_config.json` active entry (via process env).
pub fn apply_active_model_default() {
    if env::var("MODEL").ok().is_some_and(|s| !s.trim().is_empty()) {
        return;
    }
    let Some(entry) = read_active_model_entry() else {
        return;
    };
    let name = entry.model_name.trim();
    if name.is_empty() {
        return;
    }
    let _ = env::set_var("MODEL", name);
}

/// Active profile when the configured env var holds a non-empty API key.
pub fn try_resolve_active_profile() -> Option<ActiveLlmProfile> {
    let entry = read_active_model_entry()?;
    let key_name = entry.api_key_env_name.trim();
    if key_name.is_empty() {
        return None;
    }
    let api_key = env::var(key_name).ok().filter(|s| !s.trim().is_empty())?;
    Some(ActiveLlmProfile {
        base_url: entry.base_url.trim().to_string(),
        model_name: entry.model_name.trim().to_string(),
        api_key: api_key.trim().to_string(),
        api_protocol: entry.api_protocol.trim().to_ascii_lowercase(),
    })
}
