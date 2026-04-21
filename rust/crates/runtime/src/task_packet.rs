use serde::{Deserialize, Serialize};
use std::fmt::{Display, Formatter};

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct TaskPacket {
    pub objective: String,
    pub scope: String,
    pub repo: String,
    pub branch_policy: String,
    pub acceptance_tests: Vec<String>,
    pub commit_policy: String,
    pub reporting_contract: String,
    pub escalation_policy: String,
}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct TaskPacketValidationError {
    errors: Vec<String>,
}

impl TaskPacketValidationError {
    #[must_use]
    pub fn new(errors: Vec<String>) -> Self {
        Self { errors }
    }

    #[must_use]
    pub fn errors(&self) -> &[String] {
        &self.errors
    }
}

impl Display for TaskPacketValidationError {
    fn fmt(&self, f: &mut Formatter<'_>) -> std::fmt::Result {
        write!(f, "{}", self.errors.join("; "))
    }
}

impl std::error::Error for TaskPacketValidationError {}

#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ValidatedPacket(TaskPacket);

impl ValidatedPacket {
    #[must_use]
    pub fn packet(&self) -> &TaskPacket {
        &self.0
    }

    #[must_use]
    pub fn into_inner(self) -> TaskPacket {
        self.0
    }
}

pub fn validate_packet(packet: TaskPacket) -> Result<ValidatedPacket, TaskPacketValidationError> {
    let mut errors = Vec::new();

    validate_required("objective", &packet.objective, &mut errors);
    validate_required("scope", &packet.scope, &mut errors);
    validate_required("repo", &packet.repo, &mut errors);
    validate_required("branch_policy", &packet.branch_policy, &mut errors);
    validate_required("commit_policy", &packet.commit_policy, &mut errors);
    validate_required(
        "reporting_contract",
        &packet.reporting_contract,
        &mut errors,
    );
    validate_required("escalation_policy", &packet.escalation_policy, &mut errors);

    for (index, test) in packet.acceptance_tests.iter().enumerate() {
        if test.trim().is_empty() {
            errors.push(format!(
                "acceptance_tests contains an empty value at index {index}"
            ));
        }
    }

    if errors.is_empty() {
        Ok(ValidatedPacket(packet))
    } else {
        Err(TaskPacketValidationError::new(errors))
    }
}

fn validate_required(field: &str, value: &str, errors: &mut Vec<String>) {
    if value.trim().is_empty() {
        errors.push(format!("{field} must not be empty"));
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    fn sample_packet() -> TaskPacket {
        TaskPacket {
            objective: "Implement typed task packet format".to_string(),
            scope: "runtime/task system".to_string(),
            repo: "claw-code-parity".to_string(),
            branch_policy: "origin/main only".to_string(),
            acceptance_tests: vec![
                "cargo build --workspace".to_string(),
                "cargo test --workspace".to_string(),
            ],
            commit_policy: "single verified commit".to_string(),
            reporting_contract: "print build result, test result, commit sha".to_string(),
            escalation_policy: "stop only on destructive ambiguity".to_string(),
        }
    }

    #[test]
    fn valid_packet_passes_validation() {
        let packet = sample_packet();
        let validated = validate_packet(packet.clone()).expect("packet should validate");
        assert_eq!(validated.packet(), &packet);
        assert_eq!(validated.into_inner(), packet);
    }

    #[test]
    fn invalid_packet_accumulates_errors() {
        let packet = TaskPacket {
            objective: " ".to_string(),
            scope: String::new(),
            repo: String::new(),
            branch_policy: "\t".to_string(),
            acceptance_tests: vec!["ok".to_string(), " ".to_string()],
            commit_policy: String::new(),
            reporting_contract: String::new(),
            escalation_policy: String::new(),
        };

        let error = validate_packet(packet).expect_err("packet should be rejected");

        assert!(error.errors().len() >= 7);
        assert!(error
            .errors()
            .contains(&"objective must not be empty".to_string()));
        assert!(error
            .errors()
            .contains(&"scope must not be empty".to_string()));
        assert!(error
            .errors()
            .contains(&"repo must not be empty".to_string()));
        assert!(error
            .errors()
            .contains(&"acceptance_tests contains an empty value at index 1".to_string()));
    }

    #[test]
    fn serialization_roundtrip_preserves_packet() {
        let packet = sample_packet();
        let serialized = serde_json::to_string(&packet).expect("packet should serialize");
        let deserialized: TaskPacket =
            serde_json::from_str(&serialized).expect("packet should deserialize");
        assert_eq!(deserialized, packet);
    }
}
