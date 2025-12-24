import os
import shutil
from pathlib import Path

BASE_DIR = Path("docs_v2/08_Epics")

def move_to_story(feature_dir, filename, new_name=None):
    src = feature_dir / filename
    if src.exists():
        dest_dir = feature_dir / "stories" / "01_implementation"
        if not dest_dir.exists():
            dest_dir.mkdir(parents=True)
        
        dest_name = new_name if new_name else filename
        dest = dest_dir / dest_name
        print(f"Moving {src} to {dest}")
        shutil.move(str(src), str(dest))

def main():
    # 006
    move_to_story(BASE_DIR / "006_core_workflow_dedup_performance", "006_core-workflow-dedup-performance.md", "SUMMARY.md") # If exists? Check list. 
    # List showed: 006.../README.md and DESIGN.md. No summary file in root for 006 in my previous `find` output.
    # Wait, `006_core-workflow-dedup-performance.md` was moved to README.md. So it's fine.

    # 007
    move_to_story(BASE_DIR / "007_cross_cutting_performance_observability", "007-cross-cutting-performance-observability.md", "SUMMARY.md")

    # 008
    move_to_story(BASE_DIR / "008_publisher_async_throughput_hygiene", "008-publisher-async-throughput-hygiene.md", "SUMMARY.md")

    # 009
    move_to_story(BASE_DIR / "009_feature_toggle", "009_feature-toggle.md", "SUMMARY.md")

    # 010
    move_to_story(BASE_DIR / "010_keep_remove_curation", "010_keep-remove-curation.md", "SUMMARY.md")

    # 011
    move_to_story(BASE_DIR / "011_heroku_hetzner_app_cloning", "011_heroku-hetzner-app-cloning.md", "SUMMARY.md")

    # 012
    feat_12 = BASE_DIR / "012_central_config_i18n_text"
    move_to_story(feat_12, "012_central-config-i18n-text.md", "SUMMARY.md")
    move_to_story(feat_12, "012_COMPLETE.md", "COMPLETION_REPORT.md")
    move_to_story(feat_12, "012_DOCUMENTATION_UPDATE_SUMMARY.md", "DOCS_UPDATE_SUMMARY.md")
    move_to_story(feat_12, "012_config_migration_guide.md", "MIGRATION_GUIDE.md")
    move_to_story(feat_12, "012_i18n_activation_summary.md", "ACTIVATION_SUMMARY.md")

    # Ensure all features have a stories folder with something in it?
    # Requirement: "create the stories based on the current implementation"
    for feature_dir in BASE_DIR.iterdir():
        if feature_dir.is_dir() and feature_dir.name[0].isdigit():
            stories_dir = feature_dir / "stories"
            if not stories_dir.exists():
                stories_dir.mkdir()
            
            # Check if empty
            if not any(stories_dir.iterdir()):
                # Create default story
                impl_dir = stories_dir / "01_implementation"
                impl_dir.mkdir()
                with open(impl_dir / "README.md", "w") as f:
                    f.write("# Feature Implementation\n\nInitial implementation of the feature.\n")

if __name__ == "__main__":
    main()

