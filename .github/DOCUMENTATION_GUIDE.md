# Documentation Organization Guide

This guide explains where different types of documentation should be placed in the project.

## 📁 Documentation Structure

```
SocialMediaPythonPublisher/
├── CHANGELOG.md                     # ✅ ROOT - Version history (updated as we go)
├── README.md                        # ✅ ROOT - Project overview
├── SECURITY.md                      # ✅ ROOT - Security policy
├── CONTRIBUTING.md                  # ✅ ROOT - How to contribute
├── LICENSE                          # ✅ ROOT - License file
│
├── docs/                           # 📚 Main documentation folder
│   ├── DOCUMENTATION.md            # Complete user guide
│   ├── CODE_REVIEW_REPORT.md      # Code analysis
│   ├── DESIGN_SPECIFICATIONS.md   # Architecture
│   ├── REVIEW_SUMMARY.md          # Quick reference
│   ├── SMTP_UPDATE_SUMMARY.md     # Feature documentation
│   │
│   └── reports/                    # 📊 Reports and detailed guides
│       └── SETUP_COMPLETE.md      # Setup walkthrough
│
└── .github/                        # 🤖 GitHub-specific docs
    ├── DEVELOPMENT.md              # Developer guide
    ├── PULL_REQUEST_TEMPLATE.md   # PR template
    └── ISSUE_TEMPLATE/             # Issue templates
```

---

## 📝 Documentation Placement Rules

### ✅ ROOT Level (Project root)

**What goes here:**
- **CHANGELOG.md** - Version history and release notes (update with every change)
- **README.md** - Project overview and quick start
- **SECURITY.md** - Security policy and vulnerability reporting
- **CONTRIBUTING.md** - Contribution guidelines
- **LICENSE** - Project license

**Why root?**
- High visibility for important project information
- Standard locations expected by developers
- Easy access from repository homepage
- Required by GitHub conventions

---

### 📚 docs/ Folder

**What goes here:**
- User guides and tutorials
- API documentation
- Architecture and design docs
- Feature-specific documentation
- Technical specifications
- Code review reports

**Examples:**
- `DOCUMENTATION.md` - Complete user guide
- `CODE_REVIEW_REPORT.md` - Detailed code analysis
- `DESIGN_SPECIFICATIONS.md` - System architecture
- `SMTP_UPDATE_SUMMARY.md` - Feature documentation
- Any other technical documentation

**Why docs/?**
- Keeps repository root clean
- Groups related documentation
- Standard convention across projects
- Easy to browse all docs in one place

---

### 📊 docs/reports/ Subfolder

**What goes here:**
- Setup guides and walkthroughs
- Audit reports
- Analysis reports
- Review summaries
- Project reports

**Examples:**
- `SETUP_COMPLETE.md` - Setup walkthrough
- `SECURITY_AUDIT_2025.md` - Security audit report
- `PERFORMANCE_ANALYSIS.md` - Performance reports

**Why docs/reports/?**
- Separates reports from general documentation
- Better organization for multiple report types
- Clear distinction between guides and reports

---

### 🤖 .github/ Folder

**What goes here:**
- Development guidelines
- GitHub-specific templates
- Workflow documentation
- Contribution process docs

**Examples:**
- `DEVELOPMENT.md` - Developer setup and workflow
- `PULL_REQUEST_TEMPLATE.md` - PR template
- `ISSUE_TEMPLATE/` - Issue templates
- `workflows/` - CI/CD workflows

**Why .github/?**
- GitHub-specific functionality
- Automatically recognized by GitHub
- Keeps GitHub config separate
- Standard GitHub convention

---

## 🔄 CHANGELOG.md - Special Rules

**Location:** Project root
**Update Frequency:** With every significant change

### When to Update CHANGELOG.md

**Always update for:**
- ✅ New features added
- ✅ Bug fixes
- ✅ Breaking changes
- ✅ Deprecated features
- ✅ Security updates
- ✅ Configuration changes
- ✅ API changes

**Format:**
```markdown
## [Unreleased]

### Added
- New feature description

### Changed
- Modified behavior description

### Fixed
- Bug fix description

### Security
- Security improvement description
```

**Best Practices:**
1. Update CHANGELOG.md in the same commit as the change
2. Use clear, user-focused descriptions
3. Group related changes together
4. Mark breaking changes clearly
5. Include migration instructions for major changes

---

## 📖 Quick Reference

### "Where should I put...?"

| Document Type | Location | Example |
|--------------|----------|---------|
| Version history | **Root** | CHANGELOG.md |
| Project overview | **Root** | README.md |
| Security policy | **Root** | SECURITY.md |
| Contribution guide | **Root** | CONTRIBUTING.md |
| User guides | **docs/** | DOCUMENTATION.md |
| Technical specs | **docs/** | DESIGN_SPECIFICATIONS.md |
| Feature docs | **docs/** | SMTP_UPDATE_SUMMARY.md |
| Setup guides | **docs/reports/** | SETUP_COMPLETE.md |
| Audit reports | **docs/reports/** | SECURITY_AUDIT.md |
| Dev guidelines | **.github/** | DEVELOPMENT.md |
| PR templates | **.github/** | PULL_REQUEST_TEMPLATE.md |

---

## ✨ Documentation Checklist

When creating new documentation:

- [ ] Determine the correct folder based on content type
- [ ] Use clear, descriptive filename (UPPERCASE_WITH_UNDERSCORES.md)
- [ ] Add to README.md Resources section if user-facing
- [ ] Update CHANGELOG.md if it's a new feature or significant change
- [ ] Include table of contents for documents > 100 lines
- [ ] Use proper markdown formatting
- [ ] Include examples where applicable
- [ ] Add links to related documentation

---

## 🎯 Examples

### Adding a New Feature

1. **Implement the feature** in code
2. **Update CHANGELOG.md** in root:
   ```markdown
   ### Added
   - Feature XYZ that does ABC
   ```
3. **Create feature docs** in `docs/`:
   - `docs/FEATURE_XYZ_GUIDE.md`
4. **Update README.md** with link (if user-facing)
5. **Commit all changes together**

### Creating a Report

1. **Write the report**
2. **Save to** `docs/reports/REPORT_NAME.md`
3. **Update CHANGELOG.md**:
   ```markdown
   ### Added
   - Project report in docs/reports/
   ```
4. **Optionally link from README.md** (if important)

### Updating Existing Docs

1. **Make changes** to documentation
2. **Update CHANGELOG.md**:
   ```markdown
   ### Changed
   - Updated documentation for feature XYZ
   ```
3. **Commit with descriptive message**

---

## 💡 Tips

1. **Keep it organized**: Don't mix different types of docs
2. **Use subfolders**: Create subdirectories in docs/ as needed
3. **Link liberally**: Cross-reference related documentation
4. **Update CHANGELOG**: Always update with significant changes
5. **User-focused**: Write docs for your users, not yourself
6. **Keep current**: Update docs when code changes
7. **Be consistent**: Follow the established patterns

---

## 📞 Questions?

If you're unsure where documentation should go:
1. Check this guide first
2. Look at existing documentation placement
3. Ask in pull request comments
4. When in doubt, put it in `docs/` and we can reorganize

---

**Last Updated:** October 31, 2025
**Maintained By:** Project maintainers
**Questions?** Open an issue on GitHub

---

*Remember: Good documentation is as important as good code!* 📚
