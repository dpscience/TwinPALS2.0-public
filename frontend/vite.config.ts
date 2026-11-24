// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';
export default defineConfig({ plugins: [react()], server: { port: 5173, proxy: { '/legal': 'http://127.0.0.1:18622', '/api': 'http://127.0.0.1:18622' } }, build: { rollupOptions: { output: { manualChunks: { three: ['three'], react: ['react', 'react-dom'] } } } } });
