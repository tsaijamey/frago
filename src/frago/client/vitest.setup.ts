import '@testing-library/jest-dom/vitest'
import { JSDOM } from 'jsdom'

/**
 * 把一份能用的 `localStorage` / `sessionStorage` 装回全局。
 *
 * 哪个环节出事：Node 22 起自带了一对同名全局，但**没给 `--localstorage-file` 就是
 * undefined**（跑用例时那句 ExperimentalWarning 说的就是它）。它在 globalThis 上先占了
 * 位置，vitest 的 jsdom 环境往全局铺 window 属性时就不再覆盖这一对，于是用例里一句
 * `localStorage.clear()` 读到 undefined 当场炸。现象是整个用例文件全红，报的却是
 * "Cannot read properties of undefined (reading 'clear')"，跟被测代码毫无关系——
 * uiStore / dataStore / useSessionPins 三个文件都栽在这里。
 *
 * 补的是**真的 jsdom Storage**（另起一个 JSDOM 实例把它的那份接过来），不是自己写一个
 * Map 版的假货：真 Storage 的键值一律转字符串、取不到的键返回 null、还有 `length` 与
 * `key(i)`，假货哪一条对不上，都会让某个用例在测试里过、在浏览器里错。
 *
 * 每个用例文件各跑一次这个 setup，因此各拿各的一份存储，文件之间天然不串。
 */
const storageDonor = new JSDOM('', { url: 'http://localhost' }).window

for (const name of ['localStorage', 'sessionStorage'] as const) {
  const usable = globalThis[name] as Storage | undefined
  if (usable && typeof usable.clear === 'function') continue
  const value = storageDonor[name]
  Object.defineProperty(globalThis, name, { value, configurable: true, writable: true })
  if (typeof window !== 'undefined' && window !== (globalThis as unknown as Window)) {
    Object.defineProperty(window, name, { value, configurable: true, writable: true })
  }
}
