import catalogueMarkdown from '../../../docs/COMPONENTS.md?raw';

type Family = { name: string; anchor: string; fields: string[]; rows: string[][] };
const generated = catalogueMarkdown.match(/<!-- factory-catalogue:start -->([\s\S]*?)<!-- factory-catalogue:end -->/);
if (!generated) throw new Error('The factory catalogue tables are missing from docs/COMPONENTS.md.');

export const families: Family[] = [];
for (const part of generated[1].split(/^## /m).slice(1)) {
  const [name, ...lines] = part.trim().split(/\r?\n/);
  const table = lines.filter(line => line.startsWith('|'))
    .map(line => line.slice(1, -1).split('|').map(cell => cell.trim()));
  const [columns, , ...rows] = table;
  if (columns?.[0] !== 'Entry' || !rows.length || rows.some(row => row.length !== columns.length)) {
    throw new Error(`Unexpected factory catalogue table in ${name}.`);
  }
  families.push({ name, anchor: name.toLowerCase().replaceAll(' ', '-'), fields: columns.slice(1), rows });
}

export const total = families.reduce((sum, family) => sum + family.rows.length, 0);
