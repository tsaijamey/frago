/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      // Breakpoint system (single source of truth mirrored in globals.css header):
      // phone ≤640px, tablet 641–1024px, desktop ≥1025px.
      // MUST live under `extend` — declaring `screens` at theme level REPLACES
      // Tailwind's defaults, which silently kills the existing
      // `md:grid-cols-2` / `lg:flex` / `xl:grid-cols-3` grids in
      // RecipeList / SkillList / CommunityRecipeList.
      screens: {
        phone: { max: '640px' },
        tablet: { min: '641px', max: '1024px' },
        desktop: { min: '1025px' },
      },
      colors: {
        // Use CSS variables to support theme switching
        // Based on Next.js-inspired design language from FRONTEND_STYLE_GUIDE.md
        'bg-primary': 'var(--bg-primary)',
        'bg-secondary': 'var(--bg-secondary)',
        'bg-tertiary': 'var(--bg-tertiary)',
        'bg-card': 'var(--bg-card)',
        'bg-subtle': 'var(--bg-subtle)',
        'bg-hover': 'var(--bg-hover)',
        'bg-elevated': 'var(--bg-elevated)',
        'text-primary': 'var(--text-primary)',
        'text-secondary': 'var(--text-secondary)',
        'text-muted': 'var(--text-muted)',
        'text-link': 'var(--text-link)',
        'border-color': 'var(--border-color)',
        'border-primary': 'var(--border-primary)',
        'border-accent': 'var(--border-accent)',
        'accent-primary': 'var(--accent-primary)',
        // The two brand-green washes already defined per theme in globals.css.
        // Exposed as tokens because Tailwind's `/opacity` modifier cannot dilute
        // a hex-valued CSS variable — without these, brand tints would have to
        // be hardcoded hexes, which breaks the light theme.
        'accent-primary-10': 'var(--accent-primary-10)',
        'accent-primary-20': 'var(--accent-primary-20)',
        'accent-secondary': 'var(--accent-secondary)',
        'accent-success': 'var(--accent-success)',
        'accent-warning': 'var(--accent-warning)',
        'accent-error': 'var(--accent-error)',
        'accent-info': 'var(--accent-info)',
      },
      backgroundImage: {
        'gradient-title': 'linear-gradient(180deg, #FFFFFF 0%, #ADADAD 100%)',
      },
    },
  },
  plugins: [],
}
