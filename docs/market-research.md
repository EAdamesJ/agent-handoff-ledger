# Market-signal scan: Claude Code, Codex, DeepSeek

**Snapshot date:** 2026-11-03  
**Purpose:** choose a focused open-source repository idea with a plausible path to GitHub discovery. Star counts and platform indexing can change quickly; none of the counts below predicts future stars.

## Search method and limits

- Searched public Google/web results for phrases around connecting Claude Code, Codex, DeepSeek, MCP setup, agent handoff, shared task state, and code review.
- Queried GitHub repository search and GitHub's public REST metadata for comparable projects, then checked public issues on projects with recent Windows integration work.
- Ran site-scoped searches for X, Threads, Instagram, and Facebook. Publicly indexed results from Threads, Instagram, and Facebook did not contain enough relevant posts to support a demand estimate. Most of these feeds/groups require login or are algorithmically surfaced, so this is not evidence of no demand.
- X results included an indexed [trend summary about Claude/Codex hybrid workflows](https://x.com/i/trending/2054365194361745727). Opening the page required login and exposed only a summary that warns it can be inaccurate; treat it as a weak signal, not representative sentiment.
- Read public Reddit discussions as additional qualitative evidence. Reddit was not used as a proxy for the size of X/Threads/Instagram/Facebook audiences.

## Signals

### 1. Agent interoperability has a strong broad signal

As of this snapshot, GitHub's API reported about **34.8k stars** for [openai/codex-plugin-cc](https://github.com/openai/codex-plugin-cc), an official Claude Code plugin that runs Codex for reviews or delegated tasks. It was created on 2026-03-30. This is evidence that a simple workflow for using Codex from Claude Code can attract wide interest; it also means a generic Claude-to-Codex bridge would duplicate a mature official solution.

[farion1231/cc-switch](https://github.com/farion1231/cc-switch) had about **151.4k stars**. It combines provider switching with MCP, skills, and prompt management across coding agents. Broad configuration managers are already crowded and have a high incumbent.

### 2. DeepSeek-as-worker is real, but the direct alternatives are smaller

The GitHub API snapshot showed about **97 stars** on [dazuiba/handoff](https://github.com/dazuiba/handoff), **54** on [PsChina/deepseek-as-subagent](https://github.com/PsChina/deepseek-as-subagent), and **56** on [arizen-dev/deepseek-mcp](https://github.com/arizen-dev/deepseek-mcp). These projects already expose DeepSeek to Claude Code or Codex as a worker/sub-agent. This validates the use case while making a copycat “DeepSeek MCP server” a weak choice.

### 3. Users describe coordination as the harder part

In a public discussion titled [“Connecting Claude with Codex”](https://www.reddit.com/r/claude/comments/1wa01kp/connecting_claude_with_codex/), the question was how to connect the tools. Several replies moved beyond the transport: share a task file or state, assign different jobs, let only one agent write at a time, and avoid unbounded agent-to-agent loops. One reply said the handoff mattered more than the connection itself.

This is qualitative evidence from one thread, not a prevalence estimate. It points to a more specific product surface than another MCP wrapper: persistent handoff state, exclusive cooperative writer ownership, and an explicit hop cap.

### 4. Direct provider setup is increasingly solved by vendors

DeepSeek's current official docs cover using its API directly with both [Codex](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/) and [Claude Code](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code/). A new project whose whole value is changing a base URL would compete with first-party setup guides and provider switchers.

DeepSeek Harness also documents an [external MCP client](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md), so a single local MCP server can be shared with that host in addition to Claude Code and Codex.

### 5. Windows friction is visible in public issue trackers

Recent public issues include [a Windows Git Bash install failure](https://github.com/PsChina/deepseek-as-subagent/issues/31) in a DeepSeek sub-agent project and [PowerShell detection/reporting problems](https://github.com/openai/codex-plugin-cc/issues/832) in the official Codex plugin. These are concrete integration defects, but they do not by themselves prove that a Windows-specific product is the largest opportunity.

## Recommendation

Build **Agent Handoff Ledger**, a local MCP server for cross-agent task state rather than another model wrapper. It stores task briefs and an append-only handoff history in SQLite, serializes claims so only one participating agent holds a writer lease per workspace, and imposes a configurable handoff budget. Claude Code, Codex, and DeepSeek Harness can register the same server through stdio MCP.

This is a differentiated MVP, not an empty category. Existing tools already delegate work; this repository focuses on the coordination contract that those tools often leave to prompts, shared files, or user discipline.

## Potential and risks

- **Potential:** strong parent interest in cross-agent workflows; explicit user language around shared state, handoffs, writer conflicts, and stopping loops; one MCP server serves multiple hosts.
- **Risk:** established projects already run subagents and may add stronger coordination; star counts for narrow handoff repositories remain far below large utilities; success will depend on adoption, clear demos, and reliability.
- **No guarantee:** stars depend on distribution and execution. This research supports a testable project idea, not a forecast.

## Sources

- [Codex plugin for Claude Code](https://github.com/openai/codex-plugin-cc)
- [CC Switch](https://github.com/farion1231/cc-switch)
- [Handoff](https://github.com/dazuiba/handoff)
- [DeepSeek as sub-agent](https://github.com/PsChina/deepseek-as-subagent)
- [DeepSeek MCP worker](https://github.com/arizen-dev/deepseek-mcp)
- [Claude/Codex handoff discussion](https://www.reddit.com/r/claude/comments/1wa01kp/connecting_claude_with_codex/)
- [DeepSeek Codex integration docs](https://api-docs.deepseek.com/quick_start/agent_integrations/codex/)
- [DeepSeek Claude Code integration docs](https://api-docs.deepseek.com/quick_start/agent_integrations/claude_code/)
- [DeepSeek Harness MCP client docs](https://github.com/deepseek-ai/deepseek-harness/blob/master/packages/mcp/mcp-client/README.md)