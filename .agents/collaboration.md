# Cross-Agent Collaboration

This repository is worked on by both Codex and Claude. Keep agent coordination explicit and avoid asking the user for routine execution choices.

## Required Coordination

- Codex consults tmux session `trader-claude` before starting repository work.
- Claude consults tmux session `trader-codex` before starting repository work.
- Each agent should share the intended change, relevant constraints, and verification plan before editing.
- If the other agent gives actionable feedback, incorporate it or explain why it is not being applied.

## Messaging The Other Agent Via tmux

Coordination happens by sending messages to the other agent's tmux session
(`trader-codex` for Claude, `trader-claude` for Codex). The other agent runs an
interactive TUI, so a pasted message is not submitted reliably — the `Enter`
keystroke is often swallowed right after a paste, leaving the message sitting
unsent in the input box.

Use a send-and-verify pattern:

1. Send the message body as a literal paste: `tmux send-keys -t <session> -l "<message>"`.
2. Send `Enter` as a separate call, never chained onto the paste: `tmux send-keys -t <session> Enter`.
3. Verify it was actually submitted with `tmux capture-pane -t <session> -p`: confirm the session entered a running state (`Working`, `esc to interrupt`, or the input prompt cleared). Do not assume the send worked.
4. If it was not submitted, re-send `Enter` only. Never re-send the message body — that risks a duplicate request.
5. Limit `Enter` retries to 1–2. If it still has not submitted, record the outcome as "other session not submitted" and hold the dependent work rather than guessing; surface it on the next report.

Keep messages reasonably short; very long pastes are swallowed more often.

## When To Ask The User

Ask the user only when one of these is true:

- The agents cannot reach a clear conclusion.
- A product, policy, or technical direction decision is required.
- The work needs destructive changes, external permission, paid resources, secrets, or security-sensitive access.
- The requested outcome conflicts with an existing project rule.

Otherwise, proceed with the agreed approach and report the result.

## Session Continuity

- Treat this file as persistent project instruction across new sessions and context compaction.
- If compacted context loses prior discussion, re-read this file before continuing repository work.

