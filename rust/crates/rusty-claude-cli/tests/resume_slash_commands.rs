use std::fs;
use std::path::Path;
use std::path::PathBuf;
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use runtime::ContentBlock;
use runtime::Session;

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

#[test]
fn resumed_binary_accepts_slash_commands_with_arguments() {
    // given
    let temp_dir = unique_temp_dir("resume-slash-commands");
    fs::create_dir_all(&temp_dir).expect("temp dir should exist");

    let session_path = temp_dir.join("session.jsonl");
    let export_path = temp_dir.join("notes.txt");

    let mut session = Session::new();
    session
        .push_user_text("ship the slash command harness")
        .expect("session write should succeed");
    session
        .save_to_path(&session_path)
        .expect("session should persist");

    // when
    let output = run_claw(
        &temp_dir,
        &[
            "--resume",
            session_path.to_str().expect("utf8 path"),
            "/export",
            export_path.to_str().expect("utf8 path"),
            "/clear",
            "--confirm",
        ],
    );

    // then
    assert!(
        output.status.success(),
        "stdout:\n{}\n\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    let stdout = String::from_utf8(output.stdout).expect("stdout should be utf8");
    assert!(stdout.contains("Export"));
    assert!(stdout.contains("wrote transcript"));
    assert!(stdout.contains(export_path.to_str().expect("utf8 path")));
    assert!(stdout.contains("Session cleared"));
    assert!(stdout.contains("Mode             resumed session reset"));
    assert!(stdout.contains("Previous session"));
    assert!(stdout.contains("Resume previous  scream --resume"));
    assert!(stdout.contains("Backup           "));
    assert!(stdout.contains("Session file     "));

    let export = fs::read_to_string(&export_path).expect("export file should exist");
    assert!(export.contains("# Conversation Export"));
    assert!(export.contains("ship the slash command harness"));

    let restored = Session::load_from_path(&session_path).expect("cleared session should load");
    assert!(restored.messages.is_empty());

    let backup_path = stdout
        .lines()
        .find_map(|line| line.strip_prefix("  Backup           "))
        .map(PathBuf::from)
        .expect("clear output should include backup path");
    let backup = Session::load_from_path(&backup_path).expect("backup session should load");
    assert_eq!(backup.messages.len(), 1);
    assert!(matches!(
        backup.messages[0].blocks.first(),
        Some(ContentBlock::Text { text }) if text == "ship the slash command harness"
    ));
}

#[test]
fn status_command_applies_cli_flags_end_to_end() {
    // given
    let temp_dir = unique_temp_dir("status-command-flags");
    fs::create_dir_all(&temp_dir).expect("temp dir should exist");

    // when
    let output = run_claw(
        &temp_dir,
        &[
            "--model",
            "sonnet",
            "--permission-mode",
            "read-only",
            "status",
        ],
    );

    // then
    assert!(
        output.status.success(),
        "stdout:\n{}\n\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    let stdout = String::from_utf8(output.stdout).expect("stdout should be utf8");
    assert!(stdout.contains("Status"));
    assert!(stdout.contains("Model            claude-sonnet-4-6"));
    assert!(stdout.contains("Permission mode  read-only"));
}

#[test]
fn resumed_config_command_loads_settings_files_end_to_end() {
    // given
    let temp_dir = unique_temp_dir("resume-config");
    let project_dir = temp_dir.join("project");
    let config_home = temp_dir.join("home").join(".claw");
    fs::create_dir_all(project_dir.join(".claw")).expect("project config dir should exist");
    fs::create_dir_all(&config_home).expect("config home should exist");

    let session_path = project_dir.join("session.jsonl");
    Session::new()
        .with_persistence_path(&session_path)
        .save_to_path(&session_path)
        .expect("session should persist");

    fs::write(config_home.join("settings.json"), r#"{"model":"haiku"}"#)
        .expect("user config should write");
    fs::write(
        project_dir.join(".claw").join("settings.local.json"),
        r#"{"model":"opus"}"#,
    )
    .expect("local config should write");

    // when
    let output = run_claw_with_env(
        &project_dir,
        &[
            "--resume",
            session_path.to_str().expect("utf8 path"),
            "/config",
            "model",
        ],
        &[("CLAW_CONFIG_HOME", config_home.to_str().expect("utf8 path"))],
    );

    // then
    assert!(
        output.status.success(),
        "stdout:\n{}\n\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    let stdout = String::from_utf8(output.stdout).expect("stdout should be utf8");
    assert!(stdout.contains("Config"));
    assert!(stdout.contains("Loaded files      2"));
    assert!(stdout.contains(
        config_home
            .join("settings.json")
            .to_str()
            .expect("utf8 path")
    ));
    assert!(stdout.contains(
        project_dir
            .join(".claw")
            .join("settings.local.json")
            .to_str()
            .expect("utf8 path")
    ));
    assert!(stdout.contains("Merged section: model"));
    assert!(stdout.contains("opus"));
}

#[test]
fn resume_latest_restores_the_most_recent_managed_session() {
    // given
    let temp_dir = unique_temp_dir("resume-latest");
    let project_dir = temp_dir.join("project");
    let sessions_dir = project_dir.join(".claw").join("sessions");
    fs::create_dir_all(&sessions_dir).expect("sessions dir should exist");

    let older_path = sessions_dir.join("session-older.jsonl");
    let newer_path = sessions_dir.join("session-newer.jsonl");

    let mut older = Session::new().with_persistence_path(&older_path);
    older
        .push_user_text("older session")
        .expect("older session write should succeed");
    older
        .save_to_path(&older_path)
        .expect("older session should persist");

    let mut newer = Session::new().with_persistence_path(&newer_path);
    newer
        .push_user_text("newer session")
        .expect("newer session write should succeed");
    newer
        .push_user_text("resume me")
        .expect("newer session write should succeed");
    newer
        .save_to_path(&newer_path)
        .expect("newer session should persist");

    // when
    let output = run_claw(&project_dir, &["--resume", "latest", "/status"]);

    // then
    assert!(
        output.status.success(),
        "stdout:\n{}\n\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );

    let stdout = String::from_utf8(output.stdout).expect("stdout should be utf8");
    assert!(stdout.contains("Status"));
    assert!(stdout.contains("Messages         2"));
    assert!(stdout.contains(newer_path.to_str().expect("utf8 path")));
}

fn run_claw(current_dir: &Path, args: &[&str]) -> Output {
    run_claw_with_env(current_dir, args, &[])
}

fn run_claw_with_env(current_dir: &Path, args: &[&str], envs: &[(&str, &str)]) -> Output {
    let mut command = Command::new(env!("CARGO_BIN_EXE_scream"));
    command.current_dir(current_dir).args(args);
    for (key, value) in envs {
        command.env(key, value);
    }
    command.output().expect("scream should launch")
}

fn unique_temp_dir(label: &str) -> PathBuf {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock should be after epoch")
        .as_millis();
    let counter = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!(
        "scream-{label}-{}-{millis}-{counter}",
        std::process::id()
    ))
}
