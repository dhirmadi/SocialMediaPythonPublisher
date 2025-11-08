# User Flows — Social Media Publisher V2

Version: 2.0  
Last Updated: November 7, 2025

## 1. Primary Flows
### 1.1 Post Now
1) User invokes CLI with config path  
2) System validates config, initializes adapters  
3) Selects image from Dropbox  
4) Analyzes and captions  
5) Publishes to enabled platforms in parallel  
6) Archives on any success (unless debug)  
7) Prints summary with per‑platform results

### 1.2 Scheduled Post
1) Cron triggers CLI entrypoint  
2) Same as Post Now; logs written to file (rotation configured)

### 1.3 Dry Run (Debug)
1) Same as Post Now through caption generation  
2) Skips archive and can skip publish (configurable)  
3) Writes full preview; returns success if pipeline executed without fatal errors

### 1.4 Preview Mode
1) Same as Post Now through AI analysis and caption generation  
2) Skips publish and archive entirely  
3) Displays human‑readable output (image details, vision analysis, caption, per‑platform formatting, email subject/placement)  
4) No state changes or Dropbox moves

## 2. Secondary Flows
- Re‑queue on partial failure (some platforms failed): do not re‑archive; next run may retry
- Manual selection: optional flag to post a specified file by name

## 3. Error Handling and Recovery
- On API transient errors: retry with backoff
- On platform hard failures: record error detail, continue others
- On configuration validation failure: exit early with actionable message

## 4. UX and CLI
CLI flags:
- `--config path/to.ini` (required)
- `--debug` (overrides config flag for quick testing)
- `--select filename.jpg` (manual target)
- `--dry-publish` (run all but skip platform publish)
- `--preview` (show human‑readable output; no publish/archive/cache updates)


