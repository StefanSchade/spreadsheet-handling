# AGENT.md - Entry Point for Repo-Committing Agents

This file is intentionally brief.

Canonical instructions live in the internal guide:

* `docs/internal_guide/ai_policy/ai_primer_prompt.adoc`
* `docs/internal_guide/ai_policy/git.adoc`
* `docs/internal_guide/ai_policy/project_specific_conventions.adoc`
* `docs/internal_guide/ai_policy/repo_committing_agents.adoc`
* `docs/internal_guide/dev_man/git.adoc`
* `docs/internal_guide/dev_man/ftr_workflow.adoc`

Minimal operating rules:

* Follow Conventional Commits and use the active FTR ID as scope whenever the
  change maps to a backlog feature.
* Prefer informative commit subjects and short English bodies for non-trivial
  changes.
* Do not force-push, rewrite shared history, publish releases, change CI/CD, or
  delete potentially in-progress work without explicit approval.
* Stay within the workspace repositories unless the user explicitly expands the
  scope.
* Treat scratch files and local environment state as non-source unless the task
  explicitly includes them.

If a task is ambiguous, consult the internal guide and the active FTR/review
files before acting.
