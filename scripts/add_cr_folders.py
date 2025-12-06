import os
from pathlib import Path

BASE_DIR = Path("docs_v2/08_Features")

def main():
    if not BASE_DIR.exists():
        return

    # Iterate over features
    for feature_dir in BASE_DIR.iterdir():
        if not feature_dir.is_dir() or not feature_dir.name[0].isdigit():
            continue
            
        stories_dir = feature_dir / "stories"
        if not stories_dir.exists():
            continue
            
        # Iterate over stories
        for story_dir in stories_dir.iterdir():
            if not story_dir.is_dir():
                continue
                
            # Create change_requests folder
            cr_dir = story_dir / "change_requests"
            if not cr_dir.exists():
                cr_dir.mkdir()
                print(f"Created {cr_dir}")
                # Add a .gitkeep or placeholder README to ensure it stays?
                # User didn't ask for it, but good practice. 
                # I'll leave it empty as per requirement "subfolder called change requests".

if __name__ == "__main__":
    main()

