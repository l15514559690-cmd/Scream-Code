use std::fs;
use std::path::{Path, PathBuf};
use std::process::{Command, Output};
use std::sync::atomic::{AtomicU64, Ordering};
use std::time::{SystemTime, UNIX_EPOCH};

use runtime::Session;

static TEMP_COUNTER: AtomicU64 = AtomicU64::new(0);

#[test]
fn status_command_applies_model_and_permission_mode_flags() {
    // given
    let temp_dir = unique_temp_dir("status-flags");
    fs::create_dir_all(&temp_dir).expect("temp dir should exist");

    // when
    let output = Command::new(env!("CARGO_BIN_EXE_claw"))
        .current_dir(&temp_dir)
        .args([
            "--model",
            "sonnet",
            "--permission-mode",
            "read-only",
            "status",
        ])
        .output()
        .expect("claw should launch");

    // then
    assert_success(&output);
    let stdout = String::from_utf8(output.stdout).expect("stdout should be utf8");
    assert!(stdout.contains("Status"));
    assert!(stdout.contains("Model            claude-sonnet-4-6"));
    assert!(stdout.contains("Permission mode  read-only"));

    fs::remove_dir_all(temp_dir).expect("cleanup temp dir");
}

#[test]
fn resume_flag_loads_a_saved_session_and_dispatches_status() {
    // given
    let temp_dir = unique_temp_dir("resume-status");
    fs::create_dir_all(&temp_dir).expect("temp dir should exist");
    let session_path = write_session(&temp_dir, "resume-status");

    // when
    let output = Command::new(env!("CARGO_BIN_EXE_claw"))
        .current_dir(&temp_dir)
        .args([
            "--resume",
            session_path.to_str().expect("utf8 path"),
            "/status",
        ])
        .output()
        .expect("claw should launch");

    // then
    assert_success(&output);
    let stdout = String::from_utf8(output.stdout).expect("stdout should be utf8");
    assert!(stdout.contains("Status"));
    assert!(stdout.contains("Messages         1"));
    assert!(stdout.contains("Session          "));
    assert!(stdout.contains(session_path.to_str().expect("utf8 path")));

    fs::remove_dir_all(temp_dir).expect("cleanup temp dir");
}

#[test]
fn slash_command_names_match_known_commands_and_suggest_nearby_unknown_ones() {
    // given
    let temp_dir = unique_temp_dir("slash-dispatch");
    fs::create_dir_all(&temp_dir).expect("temp dir should exist");

    // when
    let help_output = Command::new(env!("CARGO_BIN_EXE_claw"))
        .current_dir(&temp_dir)
        .arg("/help")
        .output()
        .expect("claw should launch");
    let unknown_output = Command::new(env!("CARGO_BIN_EXE_claw"))
        .current_dir(&temp_dir)
        .arg("/zstats")
        .output()
        .expect("claw should launch");

    // then
    assert_success(&help_output);
    let help_stdout = String::from_utf8(help_output.stdout).expect("stdout should be utf8");
    assert!(help_stdout.contains("Interactive slash commands:"));
    assert!(help_stdout.contains("/status"));

    assert!(
        !unknown_output.status.success(),
        "stdout:\n{}\n\nstderr:\n{}",
        String::from_utf8_lossy(&unknown_output.stdout),
        String::from_utf8_lossy(&unknown_output.stderr)
    );
    let stderr = String::from_utf8(unknown_output.stderr).expect("stderr should be utf8");
    assert!(stderr.contains("unknown slash command outside the REPL: /zstats"));
    assert!(stderr.contains("Did you mean"));
    assert!(stderr.contains("/status"));

    fs::remove_dir_all(temp_dir).expect("cleanup temp dir");
}

#[test]
fn config_command_loads_defaults_from_standard_config_locations() {
    // given
    let temp_dir = unique_temp_dir("config-defaults");
    let config_home = temp_dir.join("home").join(".claw");
    fs::create_dir_all(temp_dir.join(".claw")).expect("project config dir should exist");
    fs::create_dir_all(&config_home).expect("home config dir should exist");

    fs::write(config_home.join("settings.json"), r#"{"model":"haiku"}"#)
        .expect("write user settings");
    fs::write(temp_dir.join(".claw.json"), r#"{"model":"sonnet"}"#)
        .expect("write project settings");
    fs::write(
        temp_dir.join(".claw").join("settings.local.json"),
        r#"{"model":"opus"}"#,
    )
    .expect("write local settings");
    let session_path = write_session(&temp_dir, "config-defaults");

    // when
    let output = command_in(&temp_dir)
        .env("CLAW_CONFIG_HOME", &config_home)
        .args([
            "--resume",
            session_path.to_str().expect("utf8 path"),
            "/config",
            "model",
        ])
        .output()
        .expect("claw should launch");

    // then
    assert_success(&output);
    let stdout = String::from_utf8(output.stdout).expect("stdout should be utf8");
    assert!(stdout.contains("Config"));
    assert!(stdout.contains("Loaded files      3"));
    assert!(stdout.contains("Merged section: model"));
    assert!(stdout.contains("opus"));
    assert!(stdout.contains(
        config_home
            .join("settings.json")
            .to_str()
            .expect("utf8 path")
    ));
    assert!(stdout.contains(temp_dir.join(".claw.json").to_str().expect("utf8 path")));
    assert!(stdout.contains(
        temp_dir
            .join(".claw")
            .join("settings.local.json")
            .to_str()
            .expect("utf8 path")
    ));

    fs::remove_dir_all(temp_dir).expect("cleanup temp dir");
}

fn command_in(cwd: &Path) -> Command {
    let mut command = Command::new(env!("CARGO_BIN_EXE_claw"));
    command.current_dir(cwd);
    command
}

fn write_session(root: &Path, label: &str) -> PathBuf {
    let session_path = root.join(format!("{label}.jsonl"));
    let mut session = Session::new();
    session
        .push_user_text(format!("session fixture for {label}"))
        .expect("session write should succeed");
    session
        .save_to_path(&session_path)
        .expect("session should persist");
    session_path
}

fn assert_success(output: &Output) {
    assert!(
        output.status.success(),
        "stdout:\n{}\n\nstderr:\n{}",
        String::from_utf8_lossy(&output.stdout),
        String::from_utf8_lossy(&output.stderr)
    );
}

fn unique_temp_dir(label: &str) -> PathBuf {
    let millis = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .expect("clock should be after epoch")
        .as_millis();
    let counter = TEMP_COUNTER.fetch_add(1, Ordering::Relaxed);
    std::env::temp_dir().join(format!(
        "claw-{label}-{}-{millis}-{counter}",
        std::process::id()
    ))
}
