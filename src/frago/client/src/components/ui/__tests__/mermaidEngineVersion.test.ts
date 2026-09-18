/**
 * 仓库里有两份 mermaid：WebUI 用前端依赖里的那份，`frago view` 与 `frago apps use mermaid`
 * 用包内 `resources/viewer/mermaid/mermaid.min.js`。两份版本一旦不同，同一段图在两边
 * 画出来就不一样，共用的样式也只对得上其中一边。
 *
 * 升级前端依赖时，把新版的 `dist/mermaid.min.js` 原样拷到包内那个位置。
 */

import { describe, expect, it } from 'vitest';
import pkg from 'mermaid/package.json';
import bundled from '../../../../../resources/viewer/mermaid/mermaid.min.js?raw';

describe('mermaid 引擎只有一个版本', () => {
  it('包内那份与前端依赖同版本', () => {
    expect(bundled).toContain(`"${pkg.version}"`);
  });
});
