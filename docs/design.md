# Entourage Design System

Dark, VS Code-inspired design language. Minimal but semantic use of color,
monospace typography for code and identifiers, smooth transitions throughout.

---

## Design Practices

- Never hardcode colors, spacing, or font sizes. Use CSS custom properties.
- Check contrast ratios. Body text needs 4.5:1 minimum.
- Build HTML mockups for new components. Get approval before framework implementation.
- Screenshot all affected pages/components after visual work:
  default, hover, error, empty states at desktop (1280px) and mobile (375px).

---

## Color Palette

### Backgrounds

| Token                | Value       | Purpose                        |
|----------------------|-------------|--------------------------------|
| `--bg-primary`       | `#1e1e1e`   | Main content area              |
| `--bg-sidebar`       | `#252526`   | Sidebar panel                  |
| `--bg-surface`       | `#252526`   | Cards, elevated surfaces       |
| `--bg-elevated`      | `#2d2d2d`   | Modals, overlays               |
| `--bg-hover`         | `#2a2a2a`   | Hover states                   |
| `--bg-active`        | `#37373d`   | Active / selected states       |
| `--bg-input`         | `#313131`   | Input fields                   |
| `--bg-inset`         | `#1a1a1a`   | Deeply nested / inset elements |

### Text

| Token                | Value       | Purpose                        |
|----------------------|-------------|--------------------------------|
| `--text-primary`     | `#c4c4c4`   | Main body text                 |
| `--text-secondary`   | `#858585`   | Secondary / supporting text    |
| `--text-muted`       | `#6a6a6a`   | Muted / disabled text          |
| `--text-faint`       | `#525252`   | Placeholder text (min 3:1)     |
| `--text-heading`     | `#e0e0e0`   | Headings, emphasis             |

### Borders

| Token                | Value       | Purpose                        |
|----------------------|-------------|--------------------------------|
| `--border-default`   | `#333333`   | Standard borders               |
| `--border-subtle`    | `#2a2a2a`   | Light dividers                 |
| `--border-input`     | `#3c3c3c`   | Input field borders            |
| `--border-focus`     | `#4ade80`   | Focus ring (accent green)      |

### Accent (Brand Green)

| Token                | Value                       | Purpose              |
|----------------------|-----------------------------|----------------------|
| `--accent`           | `#4ade80`                   | Primary action color |
| `--accent-hover`     | `#5ee892`                   | Hover state          |
| `--accent-muted`     | `rgba(74, 222, 128, 0.08)`  | Subtle background    |
| `--accent-glow`      | `rgba(74, 222, 128, 0.3)`   | Glow / focus ring    |

### Semantic

| Token                | Value       | Purpose                        |
|----------------------|-------------|--------------------------------|
| `--semantic-red`          | `#f14c4c`   | Error, attention needed        |
| `--semantic-orange`       | `#cca700`   | Warnings                       |
| `--semantic-yellow`       | `#e2c08d`   | Caution, pending               |
| `--semantic-green`        | `#73c991`   | Success, resolved              |
| `--semantic-blue`         | `#569cd6`   | Informational, links           |
| `--semantic-purple`       | `#a78bfa`   | Reviewers, type badges         |
| `--semantic-purple-light` | `#c084fc`   | Architects, secondary purple   |
| `--semantic-gray`         | `#555555`   | Neutral, idle, done            |

### UI Controls

| Token                | Value       | Purpose                        |
|----------------------|-------------|--------------------------------|
| `--btn-bg`           | `#cccccc`   | Button background (light)      |
| `--btn-text`         | `#1e1e1e`   | Button text (dark)             |
| `--btn-hover`        | `#aaaaaa`   | Button hover                   |
| `--scrollbar-thumb`  | `#333333`   | Scrollbar thumb                |
| `--scrollbar-hover`  | `#555555`   | Scrollbar thumb hover          |
| `--backdrop`         | `rgba(0, 0, 0, 0.55)` | Modal backdrop        |

---

## Status Colors

Three-tier semantic mapping for agent & run status:

| Meaning             | Color       | Token               | Statuses                               |
|---------------------|-------------|----------------------|-----------------------------------------|
| Needs attention     | Red         | `--status-attention` | awaiting_approval, rejected, failed     |
| Active / in-flight  | Whitish     | `--status-active`    | in_progress, in_review, merging, running|
| Idle / done         | Gray        | `--status-idle`      | todo, done, cancelled, idle             |

### Run status badges

| Status               | Dot Color  | Badge Background           |
|----------------------|------------|----------------------------|
| `draft`              | `--status-idle`      | `rgba(85, 85, 85, 0.10)`  |
| `planning`           | `--status-active`    | `rgba(176, 176, 176, 0.10)`|
| `awaiting_approval`  | `--status-attention` | `rgba(241, 76, 76, 0.10)` |
| `running`            | `--status-active`    | `rgba(176, 176, 176, 0.10)`|
| `completed`          | `--status-idle`      | `rgba(85, 85, 85, 0.10)`  |
| `failed`             | `--status-attention` | `rgba(241, 76, 76, 0.10)` |
| `cancelled`          | `--status-idle`      | `rgba(85, 85, 85, 0.10)`  |

### Agent status dots

| Status      | Color     | Animation      |
|-------------|-----------|----------------|
| `running`   | `--status-active`    | pulse (2s)     |
| `idle`      | `--status-idle`      | none           |
| `error`     | `--status-attention` | none           |
| `offline`   | `--status-idle`      | none           |

---

## Typography

### Font Stack

```css
--font-ui:   'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
--font-mono: 'JetBrains Mono', 'SF Mono', 'Fira Code', 'Cascadia Code', monospace;
```

Load weights: Inter 400, 500, 600 · JetBrains Mono 400, 500.

### Scale

| Use Case              | Size   | Weight | Font       |
|-----------------------|--------|--------|------------|
| Page title            | 16px   | 600    | UI         |
| Section heading       | 14px   | 600    | UI         |
| Body text             | 14px   | 400    | UI         |
| Secondary text        | 13px   | 400    | UI         |
| Labels / uppercase    | 11px   | 600    | UI         |
| Code / IDs / monospace| 12px   | 400    | Mono       |
| Badges / small        | 10px   | 600    | UI         |
| Timestamps            | 11px   | 400    | Mono       |

### Properties

- **Line height**: 1.5 (body), 1.4 (code), 1.35 (cards)
- **Letter spacing**: -0.01em (body), 0.05em (uppercase labels)
- **Font smoothing**: `-webkit-font-smoothing: antialiased`

---

## Spacing

8px base grid. Common values:

| Token    | Value  |
|----------|--------|
| `xxs`    | 2px    |
| `xs`     | 4px    |
| `sm`     | 8px    |
| `md`     | 12px   |
| `lg`     | 16px   |
| `xl`     | 20px   |
| `xxl`    | 24px   |
| `xxxl`   | 32px   |

### Key Dimensions

| Element            | Value     |
|--------------------|-----------|
| Sidebar width      | 220px     |
| Content max-width  | 960px     |
| Header height      | 40px      |
| Input height       | 34px      |
| Card padding       | 16px      |
| Card border-radius | 8px       |

---

## Border Radius

| Size     | Value  | Use                              |
|----------|--------|----------------------------------|
| Sharp    | 3px    | Tiny badges, inline code         |
| Small    | 4px    | Buttons, status pills            |
| Default  | 6px    | Inputs, cards, nav items         |
| Medium   | 8px    | Larger cards, panels             |
| Large    | 12px   | Modals, login card               |
| Pill     | 9999px | Role badges                      |
| Circle   | 50%    | Status dots, avatars             |

---

## Shadows

| Level      | Value                                | Use                   |
|------------|--------------------------------------|-----------------------|
| Dropdown   | `0 4px 16px rgba(0, 0, 0, 0.4)`     | Menus, popovers       |
| Panel      | `0 8px 24px rgba(0, 0, 0, 0.3)`     | Side panels           |
| Modal      | `0 20px 60px rgba(0, 0, 0, 0.5)`    | Modals, dialogs       |

---

## Transitions

| Speed   | Value            | Use                           |
|---------|------------------|-------------------------------|
| Fast    | `100ms ease`     | Hover backgrounds, borders    |
| Normal  | `150ms ease`     | Color changes, hover states   |
| Smooth  | `200ms ease`     | Transforms, opacity, modals   |

---

## Animations

### Pulse (status dots)

```css
@keyframes pulse {
  0%, 100% { opacity: 1; }
  50%      { opacity: 0.4; }
}
/* duration: 2s infinite */
```

### Skeleton Shimmer

```css
@keyframes skeleton-shimmer {
  0%   { background-position: 200% 0; }
  100% { background-position: -200% 0; }
}
/* duration: 1.5s infinite */
```

### Toast Slide-in

```css
@keyframes toast-in {
  from { opacity: 0; transform: translateY(10px); }
  to   { opacity: 1; transform: translateY(0); }
}
/* duration: 200ms ease-out */
```

---

## Component Patterns

### Cards

```
Background : var(--bg-surface)
Border     : 1px solid var(--border-default)
Radius     : 8px
Padding    : 16px
Hover      : border-color → var(--accent)
```

### Buttons

| Variant     | Background              | Text                  | Border                     |
|-------------|-------------------------|-----------------------|----------------------------|
| Primary     | `var(--accent)`         | `var(--bg-primary)`   | `var(--accent)`            |
| Secondary   | `transparent`           | `var(--text-secondary)`| `var(--border-default)`   |
| Success     | `var(--semantic-green)` | `#fff`                | `var(--semantic-green)`    |
| Danger      | `var(--semantic-red)`   | `#fff`                | `var(--semantic-red)`      |
| Ghost       | `transparent`           | `var(--text-secondary)`| `none`                    |

All buttons: `padding: 8px 16px; border-radius: 6px; font-size: 13px; font-weight: 500; transition: 150ms ease;`

### Inputs

```
Background  : var(--bg-input)
Border      : 1px solid var(--border-input)
Focus border: var(--border-focus) (accent green)
Color       : var(--text-primary)
Padding     : 8px 12px
Radius      : 6px
Font        : 14px (monospace for code inputs)
Placeholder : var(--text-faint)
```

### Badges / Pills

```
Background : var(--bg-active)
Radius     : 4px (rectangular) or 9999px (pill)
Padding    : 3px 8px
Font       : 10px, weight 600
Includes   : colored dot (6px circle) matching status
```

### Tables

```
Header     : uppercase, 11px, weight 600, color var(--text-muted)
Row border : 1px solid var(--border-subtle)
Row hover  : background var(--bg-hover)
Cell pad   : 8px 16px
Font nums  : font-variant-numeric: tabular-nums
```

### Modals

```
Background : var(--bg-elevated)
Border     : 1px solid var(--border-default)
Radius     : 12px
Shadow     : 0 20px 60px rgba(0, 0, 0, 0.5)
Backdrop   : var(--backdrop)
Header pad : 16px 20px, border-bottom: 1px solid var(--border-subtle)
Body pad   : 16px 20px
Title      : 16px, weight 600, color var(--text-heading)
```

### Scrollbars

```css
::-webkit-scrollbar          { width: 6px; }
::-webkit-scrollbar-track    { background: transparent; }
::-webkit-scrollbar-thumb    { background: var(--scrollbar-thumb); border-radius: 3px; }
::-webkit-scrollbar-thumb:hover { background: var(--scrollbar-hover); }
```

---

## Responsive Breakpoints

| Name     | Max-width | Behavior                          |
|----------|-----------|-----------------------------------|
| Desktop  | > 900px   | Full layout, sidebar visible      |
| Tablet   | ≤ 900px   | Sidebar hidden                    |
| Mobile   | ≤ 600px   | Single-column grids               |

---

## File Structure

```
styles/
├── index.css          # Master import
├── base.css           # Reset, tokens, typography, scrollbars
├── layout.css         # Sidebar, nav, main-content, dashboard
├── stats.css          # Stat cards grid
├── agents.css         # Agent grid & cards
├── tasks.css          # Task list, kanban board
├── runs.css           # Run cards, cost bars, task graph
├── analytics.css      # Charts, tables, gauges
├── login.css          # Auth page
├── manage.css         # Admin forms, org/team management
├── settings.css       # Team settings form
├── human-requests.css # Human-in-the-loop cards
├── reviews.css        # Code review panel
├── task-detail.css    # Single task page
├── costs.css          # Cost table
├── skeleton.css       # Loading skeletons, error boundary, toasts
└── utilities.css      # Empty states, loading spinner
```
