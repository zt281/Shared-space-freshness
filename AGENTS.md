# Repository Guidelines

## Project Structure & Module Organization

This repository is at its initial setup stage. No application source, tests, assets, or build configuration exist yet. When introducing the first implementation, group related code by responsibility and document the chosen layout in `README.md`. Use clear locations such as `src/`, `tests/`, and `assets/` when appropriate for the selected stack; these directories are suggestions, not existing paths.

## Build, Test, and Development Commands

No build, test, or local run commands are configured. Add reproducible setup instructions and project scripts alongside the first implementation. Document dependencies, required tool versions, and exact commands in `README.md`.

Useful repository checks from the root:

- `git status --short`: inspect pending changes.
- `git diff`: review unstaged edits to tracked files.
- `git diff --cached`: review staged changes before committing.
- `git diff --check`: detect whitespace errors in tracked changes.

## Coding Style & Naming Conventions

No language, formatter, or linter has been selected. Follow the chosen language's standard conventions and commit formatter or linter configuration when introducing it. Keep indentation consistent within each file, choose descriptive names, and use established framework naming patterns. Keep formatting-only edits separate from behavior changes.

## Testing Guidelines

No testing framework or coverage threshold exists yet. Introduce automated tests with executable behavior and document how to run them. Name tests after the behavior they verify and cover normal operation, boundary conditions, and failure cases relevant to the change. Run the applicable checks before submitting a pull request and report their results.

## Commit & Pull Request Guidelines

There is no commit history from which to infer a message convention. Use concise, imperative subjects such as `Add initial project scaffold`, and keep commits focused on one coherent change.

Pull requests should explain the problem, resulting behavior, and validation performed. Link related issues when available, include screenshots for visual changes, and call out setup or configuration changes.

## Agent-Specific Instructions

If a `.codegraph/` directory is introduced, use `codegraph_explore` or `codegraph explore "<question>"` before text searches or file reads to locate or understand code. Skip CodeGraph while that directory is absent.
