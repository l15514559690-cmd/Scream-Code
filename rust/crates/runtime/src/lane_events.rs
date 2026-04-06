use serde::{Deserialize, Serialize};
use serde_json::Value;

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum LaneEventName {
    #[serde(rename = "lane.started")]
    Started,
    #[serde(rename = "lane.ready")]
    Ready,
    #[serde(rename = "lane.prompt_misdelivery")]
    PromptMisdelivery,
    #[serde(rename = "lane.blocked")]
    Blocked,
    #[serde(rename = "lane.red")]
    Red,
    #[serde(rename = "lane.green")]
    Green,
    #[serde(rename = "lane.commit.created")]
    CommitCreated,
    #[serde(rename = "lane.pr.opened")]
    PrOpened,
    #[serde(rename = "lane.merge.ready")]
    MergeReady,
    #[serde(rename = "lane.finished")]
    Finished,
    #[serde(rename = "lane.failed")]
    Failed,
    #[serde(rename = "lane.reconciled")]
    Reconciled,
    #[serde(rename = "lane.merged")]
    Merged,
    #[serde(rename = "lane.superseded")]
    Superseded,
    #[serde(rename = "lane.closed")]
    Closed,
    #[serde(rename = "branch.stale_against_main")]
    BranchStaleAgainstMain,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LaneEventStatus {
    Running,
    Ready,
    Blocked,
    Red,
    Green,
    Completed,
    Failed,
    Reconciled,
    Merged,
    Superseded,
    Closed,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum LaneFailureClass {
    PromptDelivery,
    TrustGate,
    BranchDivergence,
    Compile,
    Test,
    PluginStartup,
    McpStartup,
    McpHandshake,
    GatewayRouting,
    ToolRuntime,
    Infra,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LaneEventBlocker {
    #[serde(rename = "failureClass")]
    pub failure_class: LaneFailureClass,
    pub detail: String,
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct LaneEvent {
    pub event: LaneEventName,
    pub status: LaneEventStatus,
    #[serde(rename = "emittedAt")]
    pub emitted_at: String,
    #[serde(rename = "failureClass", skip_serializing_if = "Option::is_none")]
    pub failure_class: Option<LaneFailureClass>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub detail: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub data: Option<Value>,
}

impl LaneEvent {
    #[must_use]
    pub fn new(
        event: LaneEventName,
        status: LaneEventStatus,
        emitted_at: impl Into<String>,
    ) -> Self {
        Self {
            event,
            status,
            emitted_at: emitted_at.into(),
            failure_class: None,
            detail: None,
            data: None,
        }
    }

    #[must_use]
    pub fn started(emitted_at: impl Into<String>) -> Self {
        Self::new(LaneEventName::Started, LaneEventStatus::Running, emitted_at)
    }

    #[must_use]
    pub fn finished(emitted_at: impl Into<String>, detail: Option<String>) -> Self {
        Self::new(LaneEventName::Finished, LaneEventStatus::Completed, emitted_at)
            .with_optional_detail(detail)
    }

    #[must_use]
    pub fn blocked(emitted_at: impl Into<String>, blocker: &LaneEventBlocker) -> Self {
        Self::new(LaneEventName::Blocked, LaneEventStatus::Blocked, emitted_at)
            .with_failure_class(blocker.failure_class)
            .with_detail(blocker.detail.clone())
    }

    #[must_use]
    pub fn failed(emitted_at: impl Into<String>, blocker: &LaneEventBlocker) -> Self {
        Self::new(LaneEventName::Failed, LaneEventStatus::Failed, emitted_at)
            .with_failure_class(blocker.failure_class)
            .with_detail(blocker.detail.clone())
    }

    #[must_use]
    pub fn with_failure_class(mut self, failure_class: LaneFailureClass) -> Self {
        self.failure_class = Some(failure_class);
        self
    }

    #[must_use]
    pub fn with_detail(mut self, detail: impl Into<String>) -> Self {
        self.detail = Some(detail.into());
        self
    }

    #[must_use]
    pub fn with_optional_detail(mut self, detail: Option<String>) -> Self {
        self.detail = detail;
        self
    }

    #[must_use]
    pub fn with_data(mut self, data: Value) -> Self {
        self.data = Some(data);
        self
    }
}

#[cfg(test)]
mod tests {
    use serde_json::json;

    use super::{
        LaneEvent, LaneEventBlocker, LaneEventName, LaneEventStatus, LaneFailureClass,
    };

    #[test]
    fn canonical_lane_event_names_serialize_to_expected_wire_values() {
        let cases = [
            (LaneEventName::Started, "lane.started"),
            (LaneEventName::Ready, "lane.ready"),
            (
                LaneEventName::PromptMisdelivery,
                "lane.prompt_misdelivery",
            ),
            (LaneEventName::Blocked, "lane.blocked"),
            (LaneEventName::Red, "lane.red"),
            (LaneEventName::Green, "lane.green"),
            (LaneEventName::CommitCreated, "lane.commit.created"),
            (LaneEventName::PrOpened, "lane.pr.opened"),
            (LaneEventName::MergeReady, "lane.merge.ready"),
            (LaneEventName::Finished, "lane.finished"),
            (LaneEventName::Failed, "lane.failed"),
            (LaneEventName::Reconciled, "lane.reconciled"),
            (LaneEventName::Merged, "lane.merged"),
            (LaneEventName::Superseded, "lane.superseded"),
            (LaneEventName::Closed, "lane.closed"),
            (
                LaneEventName::BranchStaleAgainstMain,
                "branch.stale_against_main",
            ),
        ];

        for (event, expected) in cases {
            assert_eq!(serde_json::to_value(event).expect("serialize event"), json!(expected));
        }
    }

    #[test]
    fn failure_classes_cover_canonical_taxonomy_wire_values() {
        let cases = [
            (LaneFailureClass::PromptDelivery, "prompt_delivery"),
            (LaneFailureClass::TrustGate, "trust_gate"),
            (LaneFailureClass::BranchDivergence, "branch_divergence"),
            (LaneFailureClass::Compile, "compile"),
            (LaneFailureClass::Test, "test"),
            (LaneFailureClass::PluginStartup, "plugin_startup"),
            (LaneFailureClass::McpStartup, "mcp_startup"),
            (LaneFailureClass::McpHandshake, "mcp_handshake"),
            (LaneFailureClass::GatewayRouting, "gateway_routing"),
            (LaneFailureClass::ToolRuntime, "tool_runtime"),
            (LaneFailureClass::Infra, "infra"),
        ];

        for (failure_class, expected) in cases {
            assert_eq!(
                serde_json::to_value(failure_class).expect("serialize failure class"),
                json!(expected)
            );
        }
    }

    #[test]
    fn blocked_and_failed_events_reuse_blocker_details() {
        let blocker = LaneEventBlocker {
            failure_class: LaneFailureClass::McpStartup,
            detail: "broken server".to_string(),
        };

        let blocked = LaneEvent::blocked("2026-04-04T00:00:00Z", &blocker);
        let failed = LaneEvent::failed("2026-04-04T00:00:01Z", &blocker);

        assert_eq!(blocked.event, LaneEventName::Blocked);
        assert_eq!(blocked.status, LaneEventStatus::Blocked);
        assert_eq!(blocked.failure_class, Some(LaneFailureClass::McpStartup));
        assert_eq!(failed.event, LaneEventName::Failed);
        assert_eq!(failed.status, LaneEventStatus::Failed);
        assert_eq!(failed.detail.as_deref(), Some("broken server"));
    }
}
