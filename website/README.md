# TwinPALS project website

The English [TwinPALS website](https://dpscience.github.io/TwinPALS2.0-public/) presents TwinPALS Desktop, TwinPALS MCP, the component catalogue and an example shielding study.

## Build and preview

From the `website/` directory in the TwinPALS checkout, use Node.js 24 LTS and npm.

```sh
npm ci
npm run build
npm run preview -- --port 4327
```

Open the [local preview](http://127.0.0.1:4327/TwinPALS2.0-public/). Astro reads the catalogue from [the component guide](../docs/COMPONENTS.md), uses the [Desktop screenshots](../docs/screenshots/) and serves fonts and images with the site. The production output is `website/dist/`.
