// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import type {ViewSettings} from './Preferences';

// Saved paths are history, never a command to start work. Only a session
// already owned by the running server may be reattached after page reload.
export function restoreSessionViews(ui:ViewSettings, importedPaths:string[]=[]):ViewSettings {
 return {...ui,analysis_paths:importedPaths,module2:{...ui.module2,analysis_paths:[]}};
}
