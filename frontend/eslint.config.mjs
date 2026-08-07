// ESLint 9 flat config. Next 16 removed `next lint`; `eslint-config-next@16`
// ships its `core-web-vitals` shareable config as a native flat-config array
// (Linter.Config[]), so we import and spread it directly — no FlatCompat shim.
import nextCoreWebVitals from "eslint-config-next/core-web-vitals";

const eslintConfig = [
  ...nextCoreWebVitals,
  { ignores: [".next/**", "node_modules/**", "coverage/**"] },
  {
    // Rules newly introduced by eslint-config-next@16 that flag pre-existing,
    // intentional patterns. Disabled to keep the Next 16 upgrade behavior- and
    // lint-preserving; addressing them is separate cleanup, out of scope here.
    //  - set-state-in-effect: existing effect-driven loading-state patterns.
    //  - no-location-assign-relative-destination: deliberate hard-navigation to
    //    hardcoded same-origin routes (login/logout data-isolation, feature 031).
    rules: {
      "react-hooks/set-state-in-effect": "off",
      "@next/next/no-location-assign-relative-destination": "off",
    },
  },
];

export default eslintConfig;
