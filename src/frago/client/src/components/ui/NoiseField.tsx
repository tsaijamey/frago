/**
 * NoiseField — 一块会自己生长的色场，用作「活着」的视觉信号。
 *
 * 做法照搬 frago desktop 的桌布（`src/frago/desktop/assets/app.js` 里的 `startWallpaper`），
 * 那一份又照搬自 stripe.com 首页那块渐变。它和「自己画几条色带再模糊」是两条完全不同的
 * 路，差别有三处，每一处都直接决定成品是高级还是廉价：
 *
 * 1. **不画任何形状。** 铺一张平面，平面上每个点的颜色由三维单纯形噪声决定，没有一条
 *    边界是人定的。手画的正弦曲线无论怎么模糊，看着都像人工吹出来的烟——因为它本来就是。
 * 2. **混色权重取噪声的高次方。** 半透明色带互相叠加在数学上必然趋向灰。取高次方让只有
 *    噪声很强的地方才上色，于是大片区域保持接近纯色，只留很窄的过渡带。桌布取四次方，
 *    这里降一档到三次方——见下面频率那一段的说明。
 * 3. **颜色同色系、明度相近。** 一组四个，不是各挑各的。
 *
 * 噪声的第三维走时间：整块色场是在**长**而不是在移动，所以看不出运动方向，只觉得它活着。
 *
 * **这里的配色只在品牌绿那一族之内。** 整套界面的规矩是只有 logo 的绿能当高亮色；
 * 一块彩虹色场再好看也是另立了一套配色。绿→翠→薄荷之间的色相差已经足够让人看出它在动。
 *
 * **画幅只有 96×24。** 这块色场永远是被拉伸、模糊之后当底用的，分辨率一点用都没有，
 * 而每帧是一个 JS 逐像素循环——把画幅当成真实尺寸会让一个输入框吃掉一颗核。
 */

import { useEffect, useRef } from 'react';

/** 三维单纯形噪声。Stefan Gustavson / Ashima Arts 的公有领域参考实现。 */
const snoise = (() => {
  const G = [
    [1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0],
    [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
    [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1],
  ];
  const P = [
    151, 160, 137, 91, 90, 15, 131, 13, 201, 95, 96, 53, 194, 233, 7, 225, 140, 36, 103, 30, 69,
    142, 8, 99, 37, 240, 21, 10, 23, 190, 6, 148, 247, 120, 234, 75, 0, 26, 197, 62, 94, 252, 219,
    203, 117, 35, 11, 32, 57, 177, 33, 88, 237, 149, 56, 87, 174, 20, 125, 136, 171, 168, 68, 175,
    74, 165, 71, 134, 139, 48, 27, 166, 77, 146, 158, 231, 83, 111, 229, 122, 60, 211, 133, 230,
    220, 105, 92, 41, 55, 46, 245, 40, 244, 102, 143, 54, 65, 25, 63, 161, 1, 216, 80, 73, 209, 76,
    132, 187, 208, 89, 18, 169, 200, 196, 135, 130, 116, 188, 159, 86, 164, 100, 109, 198, 173,
    186, 3, 64, 52, 217, 226, 250, 124, 123, 5, 202, 38, 147, 118, 126, 255, 82, 85, 212, 207, 206,
    59, 227, 47, 16, 58, 17, 182, 189, 28, 42, 223, 183, 170, 213, 119, 248, 152, 2, 44, 154, 163,
    70, 221, 153, 101, 155, 167, 43, 172, 9, 129, 22, 39, 253, 19, 98, 108, 110, 79, 113, 224, 232,
    178, 185, 112, 104, 218, 246, 97, 228, 251, 34, 242, 193, 238, 210, 144, 12, 191, 179, 162,
    241, 81, 51, 145, 235, 249, 14, 239, 107, 49, 192, 214, 31, 181, 199, 106, 157, 184, 84, 204,
    176, 115, 121, 50, 45, 127, 4, 150, 254, 138, 236, 205, 93, 222, 114, 67, 29, 24, 72, 243, 141,
    128, 195, 78, 66, 215, 61, 156, 180,
  ];
  const PP = new Uint8Array(512);
  for (let q = 0; q < 512; q++) PP[q] = P[q & 255];
  const F3 = 1 / 3;
  const G3 = 1 / 6;
  const dot = (g: number[], x: number, y: number, z: number) => g[0] * x + g[1] * y + g[2] * z;

  return (x: number, y: number, z: number): number => {
    const s = (x + y + z) * F3;
    const i = Math.floor(x + s);
    const j = Math.floor(y + s);
    const k = Math.floor(z + s);
    const t = (i + j + k) * G3;
    const x0 = x - (i - t);
    const y0 = y - (j - t);
    const z0 = z - (k - t);
    let i1: number, j1: number, k1: number, i2: number, j2: number, k2: number;
    if (x0 >= y0) {
      if (y0 >= z0) { i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 1; k2 = 0; }
      else if (x0 >= z0) { i1 = 1; j1 = 0; k1 = 0; i2 = 1; j2 = 0; k2 = 1; }
      else { i1 = 0; j1 = 0; k1 = 1; i2 = 1; j2 = 0; k2 = 1; }
    } else {
      if (y0 < z0) { i1 = 0; j1 = 0; k1 = 1; i2 = 0; j2 = 1; k2 = 1; }
      else if (x0 < z0) { i1 = 0; j1 = 1; k1 = 0; i2 = 0; j2 = 1; k2 = 1; }
      else { i1 = 0; j1 = 1; k1 = 0; i2 = 1; j2 = 1; k2 = 0; }
    }
    const x1 = x0 - i1 + G3, y1 = y0 - j1 + G3, z1 = z0 - k1 + G3;
    const x2 = x0 - i2 + 2 * G3, y2 = y0 - j2 + 2 * G3, z2 = z0 - k2 + 2 * G3;
    const x3 = x0 - 1 + 3 * G3, y3 = y0 - 1 + 3 * G3, z3 = z0 - 1 + 3 * G3;
    const ii = i & 255, jj = j & 255, kk = k & 255;
    let n = 0;
    let tt = 0.6 - x0 * x0 - y0 * y0 - z0 * z0;
    if (tt > 0) { tt *= tt; n += tt * tt * dot(G[PP[ii + PP[jj + PP[kk]]] % 12], x0, y0, z0); }
    tt = 0.6 - x1 * x1 - y1 * y1 - z1 * z1;
    if (tt > 0) { tt *= tt; n += tt * tt * dot(G[PP[ii + i1 + PP[jj + j1 + PP[kk + k1]]] % 12], x1, y1, z1); }
    tt = 0.6 - x2 * x2 - y2 * y2 - z2 * z2;
    if (tt > 0) { tt *= tt; n += tt * tt * dot(G[PP[ii + i2 + PP[jj + j2 + PP[kk + k2]]] % 12], x2, y2, z2); }
    tt = 0.6 - x3 * x3 - y3 * y3 - z3 * z3;
    if (tt > 0) { tt *= tt; n += tt * tt * dot(G[PP[ii + 1 + PP[jj + 1 + PP[kk + 1]]] % 12], x3, y3, z3); }
    return 32 * n;
  };
})();

/**
 * 配色：一组四个，base 打底，另外三个是波层。同组之内色相相邻、明度相近，
 * 混出来才不会发灰。两套主题各一组——深色底上要够亮才看得见，浅色底上要够深。
 */
const PALETTES = {
  dark: ['0f3d24', '15b34d', '0f9b6c', '3fd17f'],
  light: ['0a8f33', '18b356', '0d9668', '5ac97f'],
} as const;

const hex2rgb = (h: string): [number, number, number] => [
  parseInt(h.slice(0, 2), 16),
  parseInt(h.slice(2, 4), 16),
  parseInt(h.slice(4, 6), 16),
];

const smoothstep = (a: number, b: number, v: number) => {
  let u = (v - a) / (b - a);
  u = u < 0 ? 0 : u > 1 ? 1 : u;
  return u * u * (3 - 2 * u);
};

const W = 96;
const H = 24;

export interface NoiseFieldProps {
  /**
   * 让它动起来。
   *
   * 为假时**画一帧就停**——不是隐藏，是冻在那一帧上。一个输入框的边如果一直在动，
   * 人打字时眼角始终有东西在晃；而完全不画又浪费了这块色场本身的质感。
   * 停下来的那一帧仍然是一块有机的色场，只是不再生长。
   */
  animate?: boolean;
  className?: string;
}

export default function NoiseField({ animate = false, className = '' }: NoiseFieldProps) {
  const ref = useRef<HTMLCanvasElement>(null);
  // 时间累计存在 ref 里：动画停下再启动时从上次的位置接着长，而不是跳回开头。
  const clock = useRef(0);

  useEffect(() => {
    const cv = ref.current;
    if (!cv) return;
    const cx = cv.getContext('2d');
    if (!cx) return;

    const theme = document.documentElement.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    const pal = PALETTES[theme];
    const base = hex2rgb(pal[0]);
    const layers = [hex2rgb(pal[1]), hex2rgb(pal[2]), hex2rgb(pal[3])].map((rgb, li) => {
      const e = li + 1;
      return {
        rgb,
        fx: 2 + e / 4,
        fy: 3 + e / 4,
        speed: 11 + 0.3 * e,
        flow: 6.5 + 0.3 * e,
        seed: 5 + 10 * e,
        floor: 0.1,
        ceil: 0.63 + 0.07 * e,
      };
    });
    // 桌布用的是 14e-5 / 29e-5：整屏只跨一两个噪声单位，所以是两三团大色块。
    // 这里不行——边只有几像素宽，横跨的又是整个输入框，色团那么大的话边上从头到尾
    // 都是同一个颜色，看着就是一根均匀的绿线。频率提上去，色团变小变多，边才有起伏。
    const FX = 62e-5;
    const FY = 34e-5;
    const TSCALE = 7e-6;
    const REF_W = 1920;
    const REF_H = 1080;

    const img = cx.createImageData(W, H);
    const buf = img.data;

    const paint = () => {
      const T = clock.current * TSCALE;
      let p = 0;
      for (let py = 0; py < H; py++) {
        const ny = (((py + 0.5) / H) * 2 - 1) * REF_H * FY;
        for (let px = 0; px < W; px++) {
          const nx = (((px + 0.5) / W) * 2 - 1) * REF_W * FX;
          let r = base[0];
          let g = base[1];
          let b = base[2];
          for (const L of layers) {
            let n = snoise(nx * L.fx + T * L.flow, ny * L.fy, T * L.speed + L.seed);
            n = smoothstep(L.floor, L.ceil, n / 2 + 0.5);
            // 桌布用四次方，为的是留出大片纯色区。一条细边上「大片纯色」等于「没颜色」，
            // 所以这里降一档到三次方，过渡带宽一些，边上的颜色才走得起来。
            const w = n * n * n;
            if (w > 0.001) {
              r += (L.rgb[0] - r) * w;
              g += (L.rgb[1] - g) * w;
              b += (L.rgb[2] - b) * w;
            }
          }
          buf[p++] = r;
          buf[p++] = g;
          buf[p++] = b;
          buf[p++] = 255;
        }
      }
      cx.putImageData(img, 0, 0);
    };

    // 系统里关掉了动效就只画一帧。这不是可选的礼貌，是无障碍要求。
    const reduced =
      typeof matchMedia === 'function' && matchMedia('(prefers-reduced-motion: reduce)').matches;

    if (!animate || reduced) {
      paint();
      return;
    }

    let raf = 0;
    let last: number | null = null;
    const loop = (ts: number) => {
      if (last === null) last = ts;
      // 帧间隔钳在 1/15 秒：切后台再回来时时间不会一次跳一大段，画面不会「闪一下」。
      clock.current += Math.min(ts - last, 1000 / 15);
      last = ts;
      paint();
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [animate]);

  return <canvas ref={ref} width={W} height={H} aria-hidden="true" className={className} />;
}
