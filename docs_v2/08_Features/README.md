# Features Directory

This directory contains the feature definitions, designs, implementation stories, and change requests for the project.

## Folder Structure

The structure is feature-centric, with each feature residing in its own numbered folder.

```text
08_Features/
├── 001_caption_file/                  # Feature Folder (Numbered ID + Snake Case Name)
│   ├── 001_feature.md                 # Feature Request / Definition
│   ├── 001_design.md                  # Feature Design Document
│   └── stories/                       # Implementation Stories
│       ├── 01_implementation/         # Initial Implementation Story
│       │   ├── 001_01_implementation.md # Story Definition
│       │   ├── 001_01_plan.yaml       # Implementation Plan
│       │   ├── 001_01_summary.md      # (Optional) Completion Summary
│       │   └── change_requests/       # Change Requests against this story
│       └── 02_follow_up_story/        # Subsequent Stories
│           ├── 001_02_follow_up.md
│           ├── 001_02_design.md
│           ├── 001_02_plan.yaml
│           └── change_requests/
├── 002_another_feature/
└── ...
```

## Naming Conventions

### Feature Folder
Format: `NNN_feature_name`
- `NNN`: 3-digit unique feature ID (e.g., `001`, `012`)
- `feature_name`: Snake case name (e.g., `caption_file`)

### Feature Artifacts
- **Request**: `NNN_feature.md` (e.g., `001_feature.md`)
- **Design**: `NNN_design.md` (e.g., `001_design.md`)

### Stories
Format: `SS_story_name` (Folder name inside `stories/`)
- `SS`: 2-digit story sequence number (e.g., `01`, `02`)
- `story_name`: Snake case or kebab case name

### Story Artifacts
All files inside a story folder follow the pattern: `NNN_SS_suffix`
- **Story Definition**: `NNN_SS_storyname.md` (e.g., `001_01_implementation.md`, `001_02_sidecars-as-ai-cache.md`)
- **Design**: `NNN_SS_design.md` (e.g., `001_02_design.md`)
- **Plan**: `NNN_SS_plan.yaml` (e.g., `001_02_plan.yaml`)
- **Summary/Report**: `NNN_SS_summary.md` (e.g., `001_01_summary.md`)

## Workflow

### 1. Creating a New Feature
1.  Allocate the next available Feature ID (`NNN`).
2.  Create the folder `NNN_feature_name`.
3.  Add `NNN_feature.md` describing the request.
4.  Add `NNN_design.md` describing the high-level design.
5.  Create `stories/01_implementation/` for the initial build.

### 2. Adding a Story
1.  Create a new folder in `stories/` with the next sequence number (e.g., `02_new_capability`).
2.  Add the story definition file `NNN_02_new-capability.md`.
3.  Add specific design (`NNN_02_design.md`) and plan (`NNN_02_plan.yaml`) if required.
4.  Create an empty `change_requests/` folder.

### 3. Change Requests
Change requests are modifications to an existing story or feature.
1.  Locate the relevant story folder.
2.  Add a new change request file in the `change_requests/` subfolder.
3.  If the change request is substantial (requires its own design/plan), consider promoting it to a new Story instead.

