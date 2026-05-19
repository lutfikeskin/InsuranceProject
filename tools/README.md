# tools/

Auxiliary projects that live alongside the main Python application but are **not part of the runtime**. Each subdirectory is independent and gitignored — clone/build it on demand.

## Contents

### `education-site/`

A standalone React + TypeScript + Vite site (separate from the Streamlit app). Built independently with its own `package.json`. Not deployed by the main app's runtime; not imported by any Python code.

**Why it lives here:** it is conceptually related to the Insurance Document Platform but has its own toolchain, dependencies, and build artifacts that would otherwise pollute the Python project root.

**Status:** tracked separately from the Python app. May be extracted to its own repository in the future — see `docs/ENTERPRISE_ROADMAP.md`.

## Adding a new tool

Place it under its own subdirectory and add a `.gitignore` line for its build outputs (`node_modules/`, `dist/`, etc.). Document its purpose here so future contributors know whether it's load-bearing or experimental.
