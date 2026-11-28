// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import {ConfirmationProvider} from './Confirm';
import './styles.css';
import './pmtOptics.css';
import './workbench.css';
import './module2.css';
import './plot-workbench.css';
import {PreferencesProvider} from './Preferences';
const Observer=React.lazy(()=>import('./StudyObserver'));
const workspace=location.pathname==='/observe'?<React.Suspense><Observer/></React.Suspense>:<App/>;
ReactDOM.createRoot(document.getElementById('root')!).render(<React.StrictMode><PreferencesProvider><ConfirmationProvider>{workspace}</ConfirmationProvider></PreferencesProvider></React.StrictMode>);
