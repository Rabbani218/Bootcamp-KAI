import type { Config } from 'tailwindcss';

const config: Config = {
  darkMode: 'class',
  content: [
    './pages/**/*.{js,ts,jsx,tsx,mdx}',
    './components/**/*.{js,ts,jsx,tsx,mdx}',
    './app/**/*.{js,ts,jsx,tsx,mdx}',
    './hooks/**/*.{js,ts,jsx,tsx,mdx}',
    './lib/**/*.{js,ts,jsx,tsx,mdx}',
  ],
  theme: {
    extend: {
      colors: {
        kci: {
          red:    '#ED1C24',
          blue:   '#2B2A77',
          orange: '#F7941D',
        },
        neon: {
          cyan:  '#00f5ff',
          red:   '#ff2d55',
          green: '#00ff88',
          amber: '#ffb800',
        },
        dark: {
          900: '#050d1a',
          800: '#0a1628',
          700: '#0f2040',
        },
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
        mono: ['"JetBrains Mono"', 'ui-monospace', 'Menlo', 'monospace'],
      },
      backdropBlur: {
        xs: '2px',
      },
      animation: {
        'pulse-slow':  'pulse 3s cubic-bezier(0.4,0,0.6,1) infinite',
        'neon-glow':   'neonGlow 2.5s ease-in-out infinite',
        'alert-flash': 'alertFlash 1.2s ease-in-out infinite',
        'fade-in':     'fadeSlideIn .25s ease-out',
        'dot-pulse':   'dotPulse 1.8s ease-in-out infinite',
        'slide-up':    'slideUp 0.35s ease-out',
      },
      keyframes: {
        neonGlow: {
          '0%,100%': { boxShadow: '0 0 8px rgba(0,245,255,0.3)' },
          '50%':     { boxShadow: '0 0 24px rgba(0,245,255,0.7)' },
        },
        alertFlash: {
          '0%,100%': { background: 'rgba(255,45,85,0.08)' },
          '50%':     { background: 'rgba(255,45,85,0.22)' },
        },
        fadeSlideIn: {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        slideUp: {
          from: { opacity: '0', transform: 'translateY(24px)' },
          to:   { opacity: '1', transform: 'translateY(0)' },
        },
        dotPulse: {
          '0%,100%': { opacity: '1', transform: 'scale(1)' },
          '50%':     { opacity: '0.4', transform: 'scale(0.75)' },
        },
      },
    },
  },
  plugins: [],
};

export default config;
