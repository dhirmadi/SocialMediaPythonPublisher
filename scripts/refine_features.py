import os
import shutil
import re
from pathlib import Path

BASE_DIR = Path("docs_v2/08_Features")

def get_feature_dirs():
    return [d for d in BASE_DIR.iterdir() if d.is_dir() and d.name[0].isdigit()]

def rename_root_readme(feature_dir):
    readme = feature_dir / "README.md"
    if readme.exists():
        new_path = feature_dir / "FEATURE_REQUEST.md"
        print(f"Renaming {readme} to {new_path}")
        readme.rename(new_path)

def process_existing_stories(feature_dir):
    stories_dir = feature_dir / "stories"
    if not stories_dir.exists():
        return

    for story_dir in stories_dir.iterdir():
        if not story_dir.is_dir():
            continue
        
        # Rename README.md to STORY.md
        readme = story_dir / "README.md"
        if readme.exists():
            new_path = story_dir / "STORY.md"
            print(f"Renaming {readme} to {new_path}")
            readme.rename(new_path)
        
        # Check for placeholder content
        if (story_dir / "STORY.md").exists():
            with open(story_dir / "STORY.md", 'r') as f:
                content = f.read()
            if "See plan.yaml for details" in content and len(content) < 100:
                print(f"Updating placeholder STORY.md in {story_dir}")
                with open(story_dir / "STORY.md", 'w') as f:
                    f.write(f"# Implementation Story: {story_dir.name}\n\nThis story covers the implementation defined in plan.yaml.\n")

def normalize_name(name):
    # Remove numbering if present at start for the name part
    # 001_something -> something
    parts = name.split('_')
    if parts[0].isdigit():
        return '_'.join(parts[1:])
    return name

def process_change_requests(feature_dir):
    cr_dir = feature_dir / "change_requests"
    stories_dir = feature_dir / "stories"
    if not cr_dir.exists():
        return
    
    if not stories_dir.exists():
        stories_dir.mkdir()

    # Group files by prefix (e.g., 001_)
    files = [f for f in cr_dir.iterdir() if f.is_file()]
    groups = {}
    
    for f in files:
        # distinct CRs usually start with numbers: 001_..., 002_...
        # regex to match NNN_name
        match = re.match(r"(\d{3})_(.+?)(\.|_)", f.name)
        if match:
            prefix = match.group(1) # 001
            # name might be complex. Let's group by prefix 001, 002 etc.
            if prefix not in groups:
                groups[prefix] = []
            groups[prefix].append(f)
        else:
            # Handle non-numbered or different format
            pass
            
    # Move groups to stories
    for prefix, files in groups.items():
        # Determine a name for the story folder
        # Find the "main" file to guess the name (the one without _design, _plan, _story suffix if possible, or just use the first mostly)
        # 001_servers-log.md vs 001_servers-log_design.md
        base_name = "story"
        for f in files:
            if not (f.name.endswith("_design.md") or f.name.endswith("_plan.yaml") or f.name.endswith("_story.md")):
                # This is likely the main file: 001_servers-log.md
                base_name = f.stem.replace(f"{prefix}_", "") # servers-log
                break
        else:
            # Fallback
            base_name = files[0].stem.replace(f"{prefix}_", "").split('_')[0]

        # Clean name
        clean_name = normalize_name(base_name)
        # Ensure story folder numbering continues from existing
        # This is tricky because we have 01_implementation.
        # Let's use the CR number + 1 (since 01 is taken) or just map CR 001 -> 02_...
        
        # But wait, CR 001 is logically the first change AFTER implementation? 
        # Or is 01_implementation the base, and CR 001 is the next story?
        # Let's map CR number to story number + 1. 
        # CR 001 -> Story 02
        # CR 002 -> Story 03
        
        try:
            story_num = int(prefix) + 1
        except:
            story_num = 99
            
        story_folder_name = f"{story_num:02d}_{clean_name}"
        target_dir = stories_dir / story_folder_name
        
        if not target_dir.exists():
            target_dir.mkdir()
            print(f"Created story dir {target_dir} from CR {prefix}")

        for f in files:
            # Determine new name
            new_filename = f.name
            
            if f.name.endswith("_plan.yaml"):
                new_filename = "plan.yaml"
            elif f.name.endswith("_design.md"):
                new_filename = "DESIGN.md"
            elif f.name.endswith("_story.md"):
                new_filename = "STORY.md"
            elif "_story" not in f.name and "_design" not in f.name and "_plan" not in f.name and f.suffix == ".md":
                 # Likely the request/story desc
                 new_filename = "STORY.md" # or FEATURE_REQUEST.md? Review said "STORY.md (story description)"
            
            # Avoid overwriting if multiple map to STORY.md (e.g. story.md and plain .md)
            # Prioritize _story.md
            dest = target_dir / new_filename
            if dest.exists() and new_filename == "STORY.md":
                 # If we already have a STORY.md, maybe this one is extra info?
                 # check file size or name
                 if "story" in f.name:
                      # Overwrite the previous generic one
                      pass
                 else:
                      # Keep existing, rename this to INFO.md or something
                      new_filename = f"{f.stem}.md"
                      dest = target_dir / new_filename

            print(f"Moving {f} to {target_dir / new_filename}")
            shutil.move(str(f), str(target_dir / new_filename))

    # Remove empty CR dirs
    # Check if dir is empty
    if not any(cr_dir.iterdir()):
        cr_dir.rmdir()
        print(f"Removed empty {cr_dir}")

def main():
    features = get_feature_dirs()
    for f in features:
        print(f"Processing {f.name}...")
        rename_root_readme(f)
        process_existing_stories(f)
        process_change_requests(f)

if __name__ == "__main__":
    main()

