/**
 * Aurora design tokens (spec 00 A2), Midnight Indigo variant: deep indigo #0B0D1F surfaces,
 * cyan #22D3EE accent, frosted-glass panels, Space Grotesk for display and Inter for body text.
 *
 * These are defined here rather than imported from a published `aurora-ui` package because this
 * repository is standalone (PLAN.md D-002). The token values are the shared ones, so the look stays
 * recognisable across the portfolio.
 *
 * The accent and the neutral ramp are the only two knobs: components reference `ink-*` for surfaces
 * and Tailwind's built-in `cyan-*` for the accent, so re-theming is a change to this file plus the
 * raw values in `src/components/aurora/tokens.ts`.
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Surface ramp, darkest first. `ink-950` is the page background.
        ink: {
          950: '#0B0D1F',
          900: '#161A38',
          800: '#1F2551',
          700: '#2B3268',
          600: '#3A4285',
        },
        // Verdict colours: teal for right, amber for partial, rose for wrong. Teal sits just off the
        // cyan accent so a committed verdict reads as distinct from ordinary interactive chrome.
        verdict: {
          right: '#2DD4BF',
          partial: '#FBBF24',
          wrong: '#FB7185',
        },
      },
      fontFamily: {
        display: ['"Space Grotesk"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        glass: '0 8px 32px rgba(6, 8, 22, 0.55)',
        'glow-cyan': '0 0 0 1px rgba(34, 211, 238, 0.4), 0 4px 20px rgba(34, 211, 238, 0.18)',
      },
      backdropBlur: {
        glass: '14px',
      },
      keyframes: {
        'fade-in': {
          from: { opacity: '0', transform: 'translateY(4px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        'flash-ok': {
          '0%': { backgroundColor: 'rgba(34, 211, 238, 0.25)' },
          '100%': { backgroundColor: 'transparent' },
        },
      },
      animation: {
        'fade-in': 'fade-in 140ms ease-out',
        'flash-ok': 'flash-ok 400ms ease-out',
      },
    },
  },
  plugins: [],
}
