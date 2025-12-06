import os
import shutil
from pathlib import Path

BASE_DIR = Path("docs_v2/08_Features")

def rename_artifact(path, new_name):
    if not path.exists():
        return
    
    target = path.parent / new_name
    if target.exists() and target != path:
        print(f"Target {target} already exists. Skipping rename of {path}.")
        return

    print(f"Renaming {path.name} -> {new_name}")
    path.rename(target)

def process_story(feature_id, story_dir):
    # Story format: bb_storyname
    parts = story_dir.name.split('_', 1)
    if len(parts) < 2:
        print(f"Skipping story dir {story_dir} - doesn't match bb_name format")
        return
    
    story_id = parts[0] # bb
    story_name = parts[1] # storyname
    
    # STORY.md -> aaa_bb_storyname.md
    rename_artifact(story_dir / "STORY.md", f"{feature_id}_{story_id}_{story_name}.md")
    
    # DESIGN.md -> aaa_bb_design.md
    rename_artifact(story_dir / "DESIGN.md", f"{feature_id}_{story_id}_design.md")
    
    # plan.yaml -> aaa_bb_plan.yaml
    rename_artifact(story_dir / "plan.yaml", f"{feature_id}_{story_id}_plan.yaml")
    
    # SUMMARY.md -> aaa_bb_summary.md (Additional handling for consistency)
    rename_artifact(story_dir / "SUMMARY.md", f"{feature_id}_{story_id}_summary.md")
    
    # Handle other miscellaneous .md files that might be part of the story?
    # For now, strictly follow the requested mappings + summary.

def process_feature(feature_dir):
    # Feature format: aaa_name
    parts = feature_dir.name.split('_', 1)
    if not parts[0].isdigit():
        return
        
    feature_id = parts[0] # aaa
    
    # Root artifacts (applying similar logic for consistency/uniqueness)
    # FEATURE_REQUEST.md -> aaa_feature.md ? User didn't specify, but "too many files with same name"
    # User specified "the artefacts in the story shold thus follow".
    # I will be conservative with root files but renaming DESIGN.md in root is probably good to avoid conflict with story DESIGN.md if flattened in search.
    # Let's rename root DESIGN.md to aaa_design.md and FEATURE_REQUEST.md to aaa_feature.md
    
    rename_artifact(feature_dir / "FEATURE_REQUEST.md", f"{feature_id}_feature.md")
    rename_artifact(feature_dir / "DESIGN.md", f"{feature_id}_design.md")
    
    stories_dir = feature_dir / "stories"
    if stories_dir.exists():
        for story_dir in stories_dir.iterdir():
            if story_dir.is_dir() and story_dir.name[0].isdigit():
                process_story(feature_id, story_dir)

def main():
    if not BASE_DIR.exists():
        print(f"Directory {BASE_DIR} does not exist.")
        return

    for feature_dir in BASE_DIR.iterdir():
        if feature_dir.is_dir():
            process_feature(feature_dir)

if __name__ == "__main__":
    main()

