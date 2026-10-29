// The standard stylelint rules, plus what this project does on purpose. Run with `npm run lint:css`.
export default {
  extends: ['stylelint-config-standard'],
  rules: {
    // Tailwind v4 and shadcn: these are its at-rules, not typos (@theme, @custom-variant, @apply, ...). Their preludes are class
    // names (`@apply border-border`), which no CSS grammar describes.
    'at-rule-no-unknown': [true, { ignoreAtRules: ['theme', 'custom-variant', 'variant', 'utility', 'apply', 'source', 'plugin', 'config', 'reference'] }],
    'at-rule-prelude-no-invalid': [true, { ignoreAtRules: ['apply', 'source', 'custom-variant', 'variant', 'utility', 'theme'] }],
    // `@import "tailwindcss";` is how Tailwind's documentation and shadcn write it
    'import-notation': 'string',
    // The colour tokens are Tailwind's and shadcn's own, in the notation they are generated in: oklch(0.556 0 0). Rewriting several dozen
    // tokens as percentages and degrees would only make the next `npx shadcn` update harder to compare.
    'lightness-notation': null,
    'hue-degree-notation': null,
  },
}
