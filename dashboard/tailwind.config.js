/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,jsx}"],
  theme: {
    extend: {
      // These two values reproduce the theme the original bundle was compiled with.
      // --font-sans / --radius are never defined, so they resolve to the fallbacks
      // (rounded-xl = 0.5rem + 4px = 12px, same pixel value as Tailwind's default).
      fontFamily: {
        sans: ["var(--font-sans, ui-sans-serif)", "ui-sans-serif", "system-ui", "sans-serif"],
      },
      borderRadius: {
        xl: "calc(var(--radius, 0.5rem) + 4px)",
      },
    },
  },
  plugins: [],
};
