// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

// These tests transpile the UI directly in Node. Match Vite's ?raw asset imports.
const Module = require('node:module');
const fs = require('node:fs');
const load = Module._load;
Module._load = function(name, parent, isMain) {
  if (name.endsWith('?raw')) {
    const file = Module._resolveFilename(name.slice(0, -4), parent);
    return {default: fs.readFileSync(file, 'utf8')};
  }
  return load.call(this, name, parent, isMain);
};
