/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      colors: {
        civic: {
          50:  "#f0f4ff",
          100: "#dde6ff",
          500: "#3b5bdb",
          600: "#2f4ac7",
          700: "#243aa5",
          900: "#111e5c",
        },
      },
    },
  },
  plugins: [],
}

