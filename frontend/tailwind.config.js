/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      fontFamily: {
        sans: ['"IBM Plex Sans"', "system-ui", "sans-serif"],
        display: ['"Libre Baskerville"', "Georgia", "serif"],
      },
      colors: {
        ink: {
          50: "#f7f7f5",
          100: "#ecebe7",
          200: "#d8d6cf",
          500: "#6b6860",
          700: "#3a3833",
          900: "#1a1916",
          950: "#11100e",
        },
        accent: {
          DEFAULT: "#1f4b3a",
          soft: "#e8f1ed",
          mid: "#2f6b52",
        },
      },
    },
  },
  plugins: [],
}
