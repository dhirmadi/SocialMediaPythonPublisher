Observations 1, 2, and 4 indicate that Instagram is no longer a supported or active platform in the SocialMediaPythonPublisher project. The documentation in `docs_v1/DESIGN_SPECIFICATIONS.md` currently includes Instagram in the multi-platform distribution flow. This PR removes the obsolete Instagram distribution target to ensure the design specifications accurately reflect the current system architecture.

```diff
--- a/docs_v1/DESIGN_SPECIFICATIONS.md
+++ b/docs_v1/DESIGN_SPECIFICATIONS.md
@@ -32,7 +32,6 @@
 ┌─────────────────────────────────────────────────────────────┐
 │              5. Multi-Platform Distribution                  │
 │                                                              │
-│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
-│  │  Instagram   │  │   Telegram   │  │    Email     │     │
-│  │   (async)    │  │   (async)    │  │   (async)    │     │
-│  └──────────────┘  └──────────────┘  └──────────────┘     │
+│  ┌──────────────┐  ┌──────────────┐                       │
+│  │   Telegram   │  │    Email     │                       │
+│  │   (async)    │  │   (async)    │                       │
+│  └──────────────┘  └──────────────┘                       │
 └─────────────────────────────────────────────────────────────┘
```
