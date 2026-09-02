/**
 * Aurora design tokens (spec 00 A2): dark navy #0B1E3B, emerald #10B981, frosted-glass surfaces,
 * Space Grotesk for display and Inter for body text.
 *
 * These are defined here rather than imported from a published `aurora-ui` package because this
 * repository is standalone (PLAN.md D-002). The token values are the shared ones, so the look stays
 * recognisable across the portfolio.
 */
/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        navy: {
          950: '#050F1E',
          900: '#0B1E3B',
          800: '#122A4F',
          700: '#1B3A68',
          600: '#25497E',
        },
        emerald: {
          400: '#34D399',
          500: '#10B981',
          600: '#059669',
        },
        // Verdict colours: emerald for right, amber for partial, rose for wrong.
        verdict: {
          right: '#10B981',
          partial: '#F59E0B',
          wrong: '#F43F5E',
        },
      },
      fontFamily: {
        display: ['"Space Grotesk"', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'SFMono-Regular', 'monospace'],
      },
      boxShadow: {
        glass: '0 8px 32px rgba(5, 15, 30, 0.45)',
        'glow-emerald': '0 0 0 1px rgba(16, 185, 129, 0.4), 0 4px 20px rgba(16, 185, 129, 0.18)',
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
          '0%': { backgroundColor: 'rgba(16, 185, 129, 0.25)' },
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
