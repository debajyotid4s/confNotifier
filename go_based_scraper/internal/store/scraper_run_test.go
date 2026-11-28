// Unit tests for scraper_runs helpers (no database).
package store

import (
	"testing"
)

func TestRunMetaFromEnvCommitSHA(t *testing.T) {
	t.Setenv("COMMIT_SHA", "abc123")
	t.Setenv("GITHUB_RUN_ID", "99")
	m := RunMetaFromEnv(false)
	if m.CommitSHA != "abc123" {
		t.Errorf("CommitSHA = %q, want abc123", m.CommitSHA)
	}
	if m.GithubRunID != "99" {
		t.Errorf("GithubRunID = %q, want 99", m.GithubRunID)
	}
	if m.TriggerSource != "github-action" {
		t.Errorf("TriggerSource = %q, want github-action", m.TriggerSource)
	}
	if m.DryRun {
		t.Error("DryRun should be false")
	}
}

func TestRunMetaFromEnvGitCommitFallback(t *testing.T) {
	t.Setenv("GIT_COMMIT", "def456")
	// No COMMIT_SHA, no GITHUB_RUN_ID -> GIT_COMMIT fallback, manual trigger.
	m := RunMetaFromEnv(false)
	if m.CommitSHA != "def456" {
		t.Errorf("CommitSHA = %q, want def456 (GIT_COMMIT fallback)", m.CommitSHA)
	}
	if m.TriggerSource != "manual" {
		t.Errorf("TriggerSource = %q, want manual", m.TriggerSource)
	}
}

func TestRunMetaFromEnvExplicitTriggerWins(t *testing.T) {
	t.Setenv("SCRAPER_TRIGGER", "manual-cutover")
	m := RunMetaFromEnv(true)
	if m.TriggerSource != "manual-cutover" {
		t.Errorf("TriggerSource = %q, want manual-cutover", m.TriggerSource)
	}
	if !m.DryRun {
		t.Error("DryRun should be true")
	}
}

func TestSqlNullStr(t *testing.T) {
	if sqlNullStr("") != nil {
		t.Error("sqlNullStr(\"\") should be nil (stores NULL)")
	}
	s := sqlNullStr("x")
	if s == nil || *s != "x" {
		t.Errorf("sqlNullStr(\"x\") = %v, want pointer to x", s)
	}
}
