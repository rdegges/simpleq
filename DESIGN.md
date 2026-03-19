# Design System — SimpleQ

## Product Context
- **What this is:** A Python SQS-based task queue library with a CLI interface
- **Who it's for:** Solo developers and indie hackers on AWS who want background jobs without managing infrastructure
- **Space/industry:** Python developer tools, task queues (peers: Celery, RQ, Dramatiq, Taskiq)
- **Project type:** CLI tool + Python library + docs site (mkdocs-material)

## Aesthetic Direction
- **Direction:** Industrial/Utilitarian with warm personality
- **Decoration level:** Minimal — typography and whitespace do all the work
- **Mood:** The reliability of a power tool, the friendliness of a good neighbor. CLI output is all business; README and docs show personality.
- **Logo direction:** Simplified, geometric snake silhouette in amber/orange. Works as favicon, CLI banner character, and README header. Not a cartoon — a mark. (Current happy-snake.jpg is placeholder, needs redo.)

## Typography
- **Display/Hero:** Cabinet Grotesk (800) — geometric, modern, slightly distinctive without being trendy
- **Body:** Instrument Sans (400/500/600) — clean, readable, excellent for technical content
- **UI/Labels:** Instrument Sans (600)
- **Data/Tables:** JetBrains Mono (tabular-nums) — industry standard for data display
- **Code:** JetBrains Mono (400/500) — ligatures, excellent at small sizes
- **Loading:**
  - Cabinet Grotesk: `https://api.fontshare.com/v2/css?f[]=cabinet-grotesk@400,500,700,800&display=swap`
  - Instrument Sans: Google Fonts `family=Instrument+Sans:wght@400;500;600;700`
  - JetBrains Mono: Google Fonts `family=JetBrains+Mono:wght@400;500;600`
- **Scale:**
  - Display: 48px / 3rem (letter-spacing: -1px)
  - H1: 32px / 2rem (letter-spacing: -0.5px)
  - H2: 24px / 1.5rem (letter-spacing: -0.3px)
  - H3: 18px / 1.125rem
  - Body: 17px / 1.0625rem (line-height: 1.7)
  - Small: 14px / 0.875rem
  - Caption: 12px / 0.75rem
  - Code: 14px / 0.875rem (line-height: 1.7)
  - CLI mono: 13px / 0.8125rem (line-height: 1.8)

## Color

### Brand Palette
- **Approach:** Restrained — amber primary is used sparingly and meaningfully
- **Primary:** `#F59E0B` (Amber 500) — warm, approachable, AWS-native. Distinctive from green/purple/teal of every other Python tool
- **Primary hover:** `#D97706` (Amber 600)
- **Secondary:** `#1E293B` (Slate 800) — professional, grounded text color
- **Accent:** `#06B6D4` (Cyan 500) — for links, interactive elements, info highlights

### Neutrals (cool grays)
- `#F8FAFC` (Slate 50) — background secondary
- `#F1F5F9` (Slate 100)
- `#E2E8F0` (Slate 200) — borders
- `#CBD5E1` (Slate 300)
- `#94A3B8` (Slate 400)
- `#64748B` (Slate 500) — secondary text
- `#475569` (Slate 600)
- `#334155` (Slate 700)
- `#1E293B` (Slate 800) — primary text
- `#0F172A` (Slate 900)
- `#020617` (Slate 950) — dark mode background

### Semantic Colors
- **Success:** `#10B981` (Emerald 500)
- **Warning:** `#F59E0B` (Amber 500, same as primary — intentional)
- **Error:** `#EF4444` (Red 500)
- **Info:** `#06B6D4` (Cyan 500, same as accent)

### Terminal Colors (ANSI mapping)
- **Green:** success, job completion (checkmark symbol)
- **Red:** errors, failures (x symbol)
- **Yellow:** warnings, caution
- **Cyan:** info, headers, queue names, key-value labels
- **Bold:** emphasis, command names, queue names in output
- **Dim:** timestamps, secondary metadata, hints

### Dark Mode Strategy
- Swap background to Slate 950 (`#020617`)
- Reduce primary saturation: use Amber 400 (`#FBBF24`) instead of 500
- Reduce accent saturation: use Cyan 400 (`#22D3EE`) instead of 500
- Text becomes Slate 200 (`#E2E8F0`)
- Borders become Slate 700 (`#334155`)
- Code blocks: `#0D1117` background (GitHub dark)

## Spacing
- **Base unit:** 8px
- **Density:** Comfortable
- **Scale:** 2xs(2px) xs(4px) sm(8px) md(16px) lg(24px) xl(32px) 2xl(48px) 3xl(64px)
- **CLI output rules:**
  - One blank line between logical groups (banner, job outputs, summary)
  - No blank lines between individual job completion lines
  - Two-space indent for nested information (startup banner metadata, error help text)

## Layout
- **Approach:** Grid-disciplined
- **Grid:** Docs site uses mkdocs-material default grid
- **Max content width:** 960px
- **Border radius:** sm(4px) md(6px) lg(8px) xl(10px)
- **CLI tables:**
  - Right-align numbers
  - Left-align text
  - Cyan headers
  - Truncate long values at terminal width with "..."

## Motion
- **Approach:** None (CLI) / Minimal-functional (docs)
- **CLI:** No animation. Ever. Spinners only for long-running operations (>2s).
- **Docs:** mkdocs-material defaults (subtle page transitions). Nothing custom.
- **Easing:** N/A for CLI. Docs: ease-out for enter, ease-in for exit.
- **Duration:** N/A for CLI. Docs: 150-250ms for transitions.

## CLI Style Guide

### Symbols
- `✓` — success (green)
- `✗` — failure (red)
- Spinner — loading/polling (only for operations >2 seconds)

### Output Format
- **Job completion:** `✓ task_name completed in 0.2s`
- **Job failure:** `✗ task_name failed: ErrorType (will retry via SQS)`
- **Worker startup banner:**
  ```
  SimpleQ v2.0.0
  Region:  us-east-1
  Queues:  emails
  Tasks:   send_email, process_signup

  Listening for jobs... (Ctrl+C to stop)
  ```

### Error Message Format
Every error must answer three questions:
1. **WHAT** happened?
2. **WHY** did it happen?
3. **WHAT DO I DO** to fix it?

Pattern: `✗ {what}.\n\n  {context and fix steps}`

### Verbosity
- Default: minimal (one line per job completion + errors)
- `--verbose`: full debug output (polling status, job start/stop, SQS API calls)

### Terminal Considerations
- **Width:** Tables reflow or truncate gracefully at <80 columns
- **NO_COLOR:** Respect `NO_COLOR` env var (plain text, no ANSI codes). Rich handles this natively.
- **CI mode:** Auto-detect CI environments, use plain output. Rich checks `$CI`, `$GITHUB_ACTIONS`, etc.
- **Piping:** When output is piped (not a TTY), use plain text. Rich handles via `Console(force_terminal=False)`.

## README Structure (Information Architecture)
1. **Hook** — one-line description + `pip install simpleq` + quickstart code block (above the fold)
2. **Why** — the problem (managing Redis/RabbitMQ sucks), the solution (SQS + zero infrastructure), who it's for
3. **Features** — progressive disclosure, each feature gets one code block + one sentence
4. **CLI** — command reference
5. **Configuration** — AWS credentials, regions, LocalStack
6. **API Reference** — link to docs site

## Decisions Log
| Date | Decision | Rationale |
|------|----------|-----------|
| 2026-03-18 | Initial design system created | Created by /design-consultation based on product context from /office-hours and /plan-design-review |
| 2026-03-18 | Amber primary (#F59E0B) | Connects to AWS, distinctive from competitors (Celery=green, RQ=red, Dramatiq=purple, FastAPI=teal) |
| 2026-03-18 | Cabinet Grotesk for display | Geometric, modern, not overused. Gives docs site an intentional feel. |
| 2026-03-18 | Instrument Sans for body | Clean readability, excellent for technical content, not overused |
| 2026-03-18 | JetBrains Mono for code | Industry standard, ligatures, tabular-nums for data |
| 2026-03-18 | Industrial/Utilitarian aesthetic | Matches "serious tool" positioning. CLI is precision instrument, docs show warmth. |
| 2026-03-18 | Minimal decoration | Developer tools with flourishes feel unserious. Typography does the work. |
| 2026-03-18 | Text-only CLI banner | ASCII art gets old fast. Compact, informational banner with version/region/queues. |
| 2026-03-18 | Error format: what/why/fix | Every error answers three questions. #1 DX differentiator. |
| 2026-03-18 | Progressive CLI verbosity | Minimal default, --verbose for debugging. Serves both use cases. |
