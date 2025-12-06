import os
import shutil
import glob
from pathlib import Path

BASE_DIR = Path("docs_v2/08_Features")
REQUESTS_DIR = BASE_DIR / "08_01_Feature_Request"
DESIGNS_DIR = BASE_DIR / "08_02_Feature_Design"
PLANS_DIR = BASE_DIR / "08_03_Feature_plan"
PLANS_DIR_TYPO = BASE_DIR / "08_03_Feature_plam"
IMPL_DIR = BASE_DIR / "08_03_Implementation"
CR_DIR = BASE_DIR / "08_04_ChangeRequests"

# Map ID to canonical name (snake_case)
FEATURES = {
    "001": "caption_file",
    "003": "expanded_vision_analysis_json",
    "004": "caption_file_extended_metadata",
    "005": "web_interface_mvp",
    "006": "core_workflow_dedup_performance",
    "007": "cross_cutting_performance_observability",
    "008": "publisher_async_throughput_hygiene",
    "009": "feature_toggle",
    "010": "keep_remove_curation",
    "011": "heroku_hetzner_app_cloning",
    "012": "central_config_i18n_text",
    "015": "cloud_storage_dropbox",
    "016": "structured_logging_redaction",
    "017": "multi_platform_publishing",
}

def normalize_name(name):
    return name.replace("-", "_").replace(" ", "_").lower()

def ensure_dir(path):
    if not path.exists():
        path.mkdir(parents=True)

def move_file(src, dst):
    if src.exists():
        print(f"Moving {src} to {dst}")
        ensure_dir(dst.parent)
        shutil.move(str(src), str(dst))
    else:
        print(f"Source not found: {src}")

def main():
    # 1. Create Feature Dirs
    for fid, fname in FEATURES.items():
        feature_dir = BASE_DIR / f"{fid}_{fname}"
        ensure_dir(feature_dir)
        
        stories_dir = feature_dir / "stories"
        ensure_dir(stories_dir)
        
        cr_dir = feature_dir / "change_requests"
        ensure_dir(cr_dir)

        # 2. Move Feature Request -> README.md
        # Try finding the file with hyphenated name
        req_name = fname.replace("_", "-")
        # Handle exceptions in naming
        if fid == "001": req_name = "captionfile"
        
        # Glob for the request file since names vary slightly
        req_files = list(REQUESTS_DIR.glob(f"{fid}_*.md"))
        if req_files:
            move_file(req_files[0], feature_dir / "README.md")
        
        # 3. Move Design -> DESIGN.md
        design_files = list(DESIGNS_DIR.glob(f"{fid}_*_design.md"))
        if design_files:
            move_file(design_files[0], feature_dir / "DESIGN.md")
            
        # 4. Move Plans -> stories/01_implementation/plan.yaml
        # Check both plan dirs
        plan_files = list(PLANS_DIR.glob(f"{fid}_*_plan.yaml")) + \
                     list(PLANS_DIR_TYPO.glob(f"{fid}_*_plan.yaml"))
        
        if plan_files:
            story_dir = stories_dir / "01_implementation"
            ensure_dir(story_dir)
            move_file(plan_files[0], story_dir / "plan.yaml")
            # Create a README for the story
            with open(story_dir / "README.md", "w") as f:
                f.write(f"# Implementation Story for {fname}\n\nSee plan.yaml for details.\n")

        # 5. Move Change Requests
        # Existing structure: 08_04_ChangeRequests/FID/...
        src_cr_subdir = CR_DIR / fid
        if src_cr_subdir.exists():
            # Move contents to feature_dir/change_requests/
            # We want to preserve structure if it's substantial, or flatten?
            # Requirement: "subfolder called change requests where we store the change requests"
            # The existing CRs are already numbered e.g. 001, 002.
            # I will move the SUBFOLDERS of the CR dir if they exist, or files.
            # Actually, `08_04_ChangeRequests/005` contains many files.
            # I'll just move the contents of `08_04_ChangeRequests/FID` to `feature_dir/change_requests/`
            for item in src_cr_subdir.iterdir():
                 dest = cr_dir / item.name
                 if item.is_dir():
                     if dest.exists():
                         shutil.rmtree(dest) # Overwrite logic if needed, but safe to assume clean
                     shutil.copytree(item, dest)
                     shutil.rmtree(item)
                 else:
                     shutil.move(str(item), str(dest))
            # Remove empty source dir
            src_cr_subdir.rmdir()

    # 6. Handle Root Files (cleanup)
    # Move status/summary files in root if they match ID
    for item in BASE_DIR.iterdir():
        if item.is_file():
            name = item.name
            if name[:3] in FEATURES:
                fid = name[:3]
                fname = FEATURES[fid]
                # If it's not a dir we just created
                feature_dir = BASE_DIR / f"{fid}_{fname}"
                if feature_dir.exists():
                    # Check if it's the same file we just moved (unlikely as we created new dirs)
                    # Move to feature root, rename to STATUS_REPORT.md or keep name
                    move_file(item, feature_dir / item.name)

    # 7. Specific fixes
    # 08_03_Implementation/005_web-interface-mvp.md -> 005_web_interface_mvp/stories/01_implementation/IMPLEMENTATION.md
    impl_005 = IMPL_DIR / "005_web-interface-mvp.md"
    if impl_005.exists():
        dest = BASE_DIR / "005_web_interface_mvp" / "stories" / "01_implementation" / "IMPLEMENTATION.md"
        ensure_dir(dest.parent)
        move_file(impl_005, dest)
    
    print("Migration complete.")

if __name__ == "__main__":
    main()

