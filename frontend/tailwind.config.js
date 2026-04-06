/** @type {import('tailwindcss').Config} */
export default {
  content: ['./index.html', './src/**/*.{js,ts,jsx,tsx}'],
  theme: {
    extend: {
      colors: {
        primary: {
          DEFAULT: '#1A3A6B',
          50:  '#EEF2F9',
          100: '#D5E3F7',
          200: '#A8C4EE',
          300: '#7AA5E5',
          400: '#4D86DC',
          500: '#2A5BAF',
          600: '#1A3A6B',
          700: '#142D53',
          800: '#0E1F3B',
          900: '#071223',
        },
        accent: {
          DEFAULT: '#F5C518',
          light: '#FDE68A',
          dark:  '#D4A017',
        },
        danger:  '#C0392B',
        success: '#27AE60',
        muted:   '#F2F2F2',
      },
      fontFamily: {
        sans: ['Plus Jakarta Sans', 'sans-serif'],
        mono: ['JetBrains Mono', 'monospace'],
      },
    },
  },
  plugins: [],
}
