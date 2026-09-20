Act as a **build planner**. Produce an executable **Story Plan** in YAML format.

---

## Folder Structure

Story plans are stored at:
```
docs_v2/08_Features/NNN_feature_name/stories/SS_story_name/NNN_SS_plan.yaml
```

---

## Inputs

- Story design file: `NNN_SS_design.md` (provided via @file)
- Parent feature design (optional but recommended)

---

## Process

1. Read story design completely
2. Extract requirements, constraints, acceptance criteria
3. Convert to concrete, executable tasks
4. Define dependencies between tasks
5. Specify quality gates and release info

---

## Output

Produce **only** the YAML content.

Include the file path on the first line as a comment.

---

## Plan Structure

```yaml
# docs_v2/08_Features/NNN_feature_name/stories/SS_story_name/NNN_SS_plan.yaml

version: "1.0"
feature_id: "NNN"
story_id: "NNN-SS"
story_name: "story-name"
design_ref: "NNN_SS_design.md"

summary: |
  Brief description of what this plan implements.
  Should match the story design summary.

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
    description: "Given X, when Y, then Z"
    test_ref: "publisher_v2/tests/test_file.py::test_function"
  - id: AC2
    description: "Given A, when B, then C"
    test_ref: "publisher_v2/tests/test_file.py::test_other"

non_goals:
  - "Explicitly out of scope item 1"
  - "Explicitly out of scope item 2"

tasks:
  # Code tasks
  - id: task_01
    type: code
    description: "Implement core functionality"
    file: "publisher_v2/src/publisher_v2/path/to/module.py"
    action: "create|modify"
    depends_on: []
    acceptance_criteria: [AC1]

  - id: task_02
    type: code
    description: "Update existing module"
    file: "publisher_v2/src/publisher_v2/path/to/existing.py"
    action: "modify"
    depends_on: [task_01]
    acceptance_criteria: [AC1]

  # Test tasks
  - id: task_03
    type: test
    description: "Unit tests for new functionality"
    file: "publisher_v2/tests/test_module.py"
    action: "create|modify"
    depends_on: [task_01, task_02]
    acceptance_criteria: [AC1, AC2]

  # Config tasks (if needed)
  - id: task_04
    type: config
    description: "Add configuration options"
    file: "publisher_v2/src/publisher_v2/config/schema.py"
    action: "modify"
    depends_on: []
    acceptance_criteria: []

  # Documentation tasks
  - id: task_05
    type: docs
    description: "Update feature documentation"
    file: "docs_v2/path/to/doc.md"
    action: "modify"
    depends_on: [task_01, task_02, task_03]
    acceptance_criteria: []

quality_gates:
  tests_pass: true
  coverage_delta_min: 0
  no_new_lint_errors: true
  type_check_pass: true

release:
  feature_flag: null  # or "feature_name_enabled"
  rollout_strategy: "direct"  # or "gradual", "canary"
  rollback_plan: "Revert commit and redeploy"
  monitoring:
    - "Check logs for errors related to <feature>"
    - "Monitor <metric> for anomalies"
```

---

## Task Types

- `code`: Create or modify source code
- `test`: Create or modify test files
- `config`: Update configuration files
- `docs`: Update documentation
- `migration`: Data migration scripts (if needed)

---

## Rules

- All file paths must be concrete (no placeholders)
- Tasks must have unique `id` values
- Dependencies must form a DAG (no cycles)
- Each acceptance criterion should have at least one test_ref
- Keep tasks small and focused
- Output only YAML content (no Markdown fences)

---

## Start

Read story design → extract requirements → generate executable plan → output only YAML.
