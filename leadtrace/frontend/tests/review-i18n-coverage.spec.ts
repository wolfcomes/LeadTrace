import { readFileSync, readdirSync } from 'node:fs';
import { join } from 'node:path';
import { parse } from '@vue/compiler-dom';
import ts from 'typescript';
import { expect, it } from 'vitest';
import { enReview as review } from '../src/i18n/en-review';
import { enWorkbench } from '../src/i18n/en-workbench';
const enReview = {...review,...enWorkbench};
const han = /[\u3400-\u9fff]/;
function files(path: string): string[] {
  return readdirSync(path, { withFileTypes: true }).flatMap(e => e.isDirectory() ? files(join(path, e.name)) : [join(path, e.name)]);
}
it('keeps review UI Chinese source strings covered and parameter names intact', () => {
  for (const [source, english] of Object.entries(enReview)) {
    expect(english.trim(), source).not.toBe('');
    expect(han.test(english), source).toBe(false);
    expect([...english.matchAll(/\{(\w+)\}/g)].map(x => x[1]).sort(), source)
      .toEqual([...source.matchAll(/\{(\w+)\}/g)].map(x => x[1]).sort());
  }
  for (const file of [...files('src/review'), ...files('src/pdf-viewer'), ...files('src/ketcher')]) {
    if (!/\.(ts|vue)$/.test(file)) continue;
    const source = readFileSync(file, 'utf8');
    const script = file.endsWith('.vue') ? source.match(/<script[^>]*>([\s\S]*?)<\/script>/)?.[1] ?? '' : source;
    const syntax = ts.createSourceFile(file, script, ts.ScriptTarget.Latest, true);
    function check(node: ts.Node): void {
      if (ts.isStringLiteral(node) && han.test(node.text)) expect(enReview[node.text], `${file}: ${node.text}`).toBeDefined();
      ts.forEachChild(node, check);
    }
    check(syntax);
    if (!file.endsWith('.vue')) continue;
    const template = source.slice(source.indexOf('<template>') + 10, source.lastIndexOf('</template>'));
    function inspect(node: any): void {
      if (node.type === 2) expect(han.test(node.content), `${file}: untranslated text ${node.content}`).toBe(false);
      for (const prop of node.props ?? []) if (prop.type === 6 && prop.value) {
        expect(han.test(prop.value.content), `${file}: untranslated ${prop.name}`).toBe(false);
      }
      for (const child of node.children ?? []) inspect(child);
    }
    inspect(parse(template));
  }
});
