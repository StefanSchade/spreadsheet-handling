# CLAUDE.md - Entry Point for AI Work

This file is intentionally brief.

The canonical instructions for AI and repo-committing agents live in the
internal guide:

* `docs/internal_guide/ai_policy/ai_primer_prompt.adoc`
* `docs/internal_guide/ai_policy/git.adoc`
* `docs/internal_guide/ai_policy/project_specific_conventions.adoc`
* `docs/internal_guide/ai_policy/repo_committing_agents.adoc`
* `docs/internal_guide/dev_man/git.adoc`
* `docs/internal_guide/dev_man/ftr_workflow.adoc`

Practical summary:

* Repo-facing code, docs, and commit messages are in English.
* Use Conventional Commits; for FTR work, include the FTR ID prominently in the
  commit message, preferably as the Conventional Commit scope, and avoid vague
  commit subjects.
* Do not create repo commits for ticketed work that omit the corresponding FTR
  ID unless the user explicitly asks for a different commit style.
* Treat the internal guide, ADRs, and active FTR/review files as the source of
  truth; do not rely on this file as a standalone project summary.
* Stay inside the workspace repositories and avoid destructive or irreversible
  actions without explicit approval.
* Treat `input.json`, `out.adoc`, `.venv/`, `build/`, and similar scratch or
  generated state as non-source unless the task explicitly says otherwise.

For general agent entry, see `AGENT.md`.
