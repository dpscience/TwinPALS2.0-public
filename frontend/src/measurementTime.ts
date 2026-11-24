// SPDX-FileCopyrightText: 2026 Danny Petschke <twinpals@proton.me>
// SPDX-License-Identifier: MIT
// Scientific basis: Dominik Boras (2024), https://doi.org/10.25972/OPUS-37663

/** Physical source-clock time, never CPU elapsed time. Stored timestamps stay in ns. */
export function measurementTime(ns:number):string {
 const seconds=Math.max(0,ns)/1e9;
 const [value,unit]=seconds>=3600?[seconds/3600,'h']:seconds>=60?[seconds/60,'min']:[seconds,'s'];
 return `${value.toLocaleString('en-GB',{maximumFractionDigits:3})} ${unit}`;
}
