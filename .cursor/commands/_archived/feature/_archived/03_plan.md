Act as a **build planner**. Convert the attached feature design document into a minimal, executable **Feature Plan** in YAML format.

---

## Folder Structure

Feature plans go in the stories folder:
```
docs_v2/08_Epics/NNN_feature_name/stories/01_implementation/NNN_01_plan.yaml
```

---

## Inputs

- Feature design file: `NNN_design.md` (provided via @file)

---

## Output

Emit ONLY one YAML document — no prose, no markdown fences.

Include the file path on the first line as a YAML comment.

---

## Repository Constraints

- Only touch files under `repo_constraints.allowed_paths`
- Never touch files under `repo_constraints.excluded_paths`

---

## Plan Schema

```yaml
# docs_v2/08_Epics/NNN_feature_name/stories/01_implementation/NNN_01_plan.yaml

version: "1.0"
feature_id: "NNN"
story_id: "NNN-01"
story_name: "implementation"
design_ref: "../../NNN_design.md"

summary: |
  <one-sentence purpose>

repo_constraints:
  allowed_paths:
    - "publisher_v2/src/"
    - "publisher_v2/tests/"
    - "docs_v2/"
  excluded_paths:
    - "code_v1/"
    - "docs_v1/"
    - ".git/"

acceptance_criteria:
  - id: AC1
    description: "<behavioral criterion>"
    test_ref: "<test file>::<test function>"

non_goals:
  - "<explicitly out of scope>"

tasks:
  - id: task_01
    type: code
    description: "<what to implement>"
    file: "publisher_v2/src/publisher_v2/path/to/file.py"
    action: "create|modify"
    depends_on: []
    acceptance_criteria: [AC1]

  - id: task_02
    type: test
    description: "<what to test>"
    file: "publisher_v2/tests/path/to/test_file.py"
    action: "create|modify"
    depends_on: [task_01]
    acceptance_criteria: [AC1]

quality_gates:
  tests_pass: true
  coverage_delta_min: 2
  no_new_lint_errors: true
  perf_budget:
    workflow_e2e_p95_ms: 5000

release:
  feature_flag: "features.<flag_name>"
  rollout_strategy: "gradual"
  rollback_plan: "Disable feature flag"
  monitoring:
    - "<metric or log to watch>"
```

---

## Task Types

- `code`: Create or modify source code
- `test`: Create or modify test files
- `config`: Update configuration
- `migration`: Data migration (must include rollback)
- `docs`: Update documentation
- `chore`: Other tasks

---

## Rules

- Use concrete paths and filenames (no placeholders)
- Keep IDs stable (namespace.task_name style)
- Prefer small, composable tasks
- Include at least one E2E test for acceptance criteria
- Migrations must include rollback
- Provide topologically ordered `depends_on`
- If design lacks info, add `TODO:` field on the task

---

## Start

Read feature design → extract requirements → generate executable YAML plan → output only YAML.
