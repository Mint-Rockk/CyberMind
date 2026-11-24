/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: {
    extend: {
      colors: {
        ink: "#080f1c",
        panel: "#111e31",
        cyan: "#38bdf8",
        teal: "#2dd4bf",
      },
    },
  },
  plugins: [],
};
