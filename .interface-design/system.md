# Entourage Design System

## Direction
Linear's precision + Notion's dark mode warmth. A professional instrument that feels warm, not clinical.

## Who
Technical founder orchestrating 10+ AI agents across repos. High design taste (knows Linear, Vercel, Arc). Impatient. Switches between terminal and browser. Needs to launch, watch, review, approve — all in under 60 seconds.

## Feel
Like piloting mission control. Calm surfaces. Information appears when needed, recedes when not. Every interaction has weight. The interface knows what you're about to do.

## Palette — Notion Dark Mode (exact values)

```css
/* Backgrounds */
--bg-primary:    #191919;     /* Page background */
--bg-sidebar:    #202020;     /* Navigation rail */
--bg-surface:    #2f3437;     /* Cards, panels — Notion's "surface" gray */
--bg-elevated:   #373c3f;     /* Hover states, raised elements */
--bg-hover:      rgba(255, 255, 255, 0.055);  /* Subtle hover */
--bg-active:     rgba(255, 255, 255, 0.08);   /* Active/pressed */
--bg-input:      rgba(255, 255, 255, 0.055);  /* Input fields */
--bg-inset:      #1e1e1e;     /* Recessed areas (code blocks, diffs) */

/* Text — Notion uses white with alpha */
--text-primary:   rgba(255, 255, 255, 0.81);   /* Body text */
--text-secondary: rgba(255, 255, 255, 0.443);  /* Secondary labels */
--text-muted:     rgba(255, 255, 255, 0.282);  /* Hints, placeholders */
--text-faint:     rgba(255, 255, 255, 0.145);  /* Disabled */
--text-heading:   rgba(255, 255, 255, 0.88);   /* Headings */

/* Borders — barely visible, Notion style */
--border-default: rgba(255, 255, 255, 0.055);
--border-input:   rgba(255, 255, 255, 0.1);
--border-focus:   #2383e2;  /* Notion blue */

/* Accent — Notion blue */
--accent:       #2383e2;
--accent-hover: #3a91e8;
--accent-muted: rgba(35, 131, 226, 0.15);
```

## Semantic Colors — Notion's exact dark mode
```css
--semantic-red:     #ff7369;   /* Notion red */
--semantic-orange:  #ffa344;   /* Notion orange */
--semantic-yellow:  #ffdc49;   /* Notion yellow */
--semantic-green:   #4dab9a;   /* Notion green (teal-ish) */
--semantic-blue:    #529cca;   /* Notion blue (lighter) */
--semantic-purple:  #9a6dd7;   /* Notion purple */
```

## Typography
- Font: Inter (matches Notion)
- Body: 14px, line-height 1.5, letter-spacing -0.011em
- Headings: font-weight 600, same size as body but stronger opacity
- Labels: 11px uppercase, 0.06em letter-spacing, text-muted
- Mono: JetBrains Mono for code, diffs, IDs

## Depth — Linear style (shadows, not borders)
- Cards: no border, use `box-shadow: 0 0 0 1px rgba(255,255,255,0.055)` (ring, not border)
- Elevated: ring + subtle shadow
- Modals: darker backdrop, stronger shadow
- Sidebar: single 1px separator line, no shadow

## Spacing
- Base unit: 4px
- Component padding: 12-16px
- Section gaps: 24-32px
- Card padding: 16-20px

## Radii
- Small (buttons, inputs): 6px
- Medium (cards): 8px
- Large (modals): 12px

## Motion — Linear speed
- Hover: 80ms ease
- Transitions: 120ms ease
- Panel slides: 200ms cubic-bezier(0.32, 0.72, 0, 1)

## Patterns

### Status indication
- Left border accent (2px) on cards — colored by status
- Small dot (6px) before status text
- Active states pulse subtly (2s period)
- NO chunky badge pills. Status is text with color.

### Cards
- Ring border (box-shadow: 0 0 0 1px)
- Hover: slight background lift
- Clickable: cursor pointer, whole card is target
- Expanded state: smooth reveal, no layout shift

### Buttons
- Primary: filled with accent, white text
- Ghost: transparent, text-secondary, border on hover
- Danger: transparent, red text
- All: 6px radius, 8px 14px padding, 12px font, 500 weight

### Inputs
- Transparent background with subtle border
- Focus: accent border + glow ring
- Placeholder: text-muted opacity
