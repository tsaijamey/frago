/**
 * 圈中的那段文字，看着像不像一条文件路径。
 *
 * **只做形状判断，不碰文件系统。** 它管的是「这段字更像路径还是更像一句人话」——圈中的
 * 常常是半句话、一个词、一段带标点的正文，那些一律不认。真正的问题「这条路径在这台机器
 * 上有没有这么一份文件」由服务端答（见 `api.probeSessionPath`）：只有它知道这台机器是
 * 什么系统、`~` 该展开成什么、这一场会话的工作目录在哪。
 *
 * **不按系统分支。** 下面每一条规则对 Unix 与 Windows 同时成立——认不出的形状一律不认，
 * 不猜「现在这台机器是哪种」。界面这一侧根本不需要知道自己跑在什么系统上。
 *
 * 判不准时一律判否：多给了一颗按钮而底下没有文件，比少给一颗更糟——人按下去什么也没
 * 发生，会以为是自己哪里弄错了。
 */

export interface PathCandidate {
  /** 去掉行号后缀、外层引号之后的那个字符串，原样交给服务端去解。 */
  path: string;
  /** 以明确的根开头（`/`、`~`、盘符、UNC）。相对写法为 false。 */
  rooted: boolean;
}

/** 结尾的行号后缀：`main.ts:42`、`main.ts:42:7`。不是路径的一部分。 */
const LINE_SUFFIX = /:\d+(?::\d+)?$/;

/** Windows 上根本不能出现在文件名里的字符；散文里也少见，出现多半不是路径。 */
const ILLEGAL = /[|<>"*?]/;

/**
 * 中文标点与全角符号。
 *
 * 这些永远不进路径名，散文里却满地都是——圈中的文字里只要有一个，就不可能是路径。注意
 * 范围只到标点与全角区：路径里出现中文字（`技术方案.html` 这种）是正常的，那些字在
 * 汉字区，不在这里。
 */
const CJK_PUNCT = /[\u3000-\u303f\uff01-\uff5e\u2018\u2019\u201c\u201d\u2014\u2026]/;

/** 以明确的根开头：`/`、`~`、`C:\` 或 `C:/`、UNC 的 `\\`。 */
const ROOTED = /^(?:\/|~[\\/]|[A-Za-z]:[\\/]|\\\\)/;

/** 就是把整段剥出来的那几种包法：反引号、成对的单双引号。 */
function unwrap(text: string): string {
  let out = text.trim();
  // 反引号可能在两端各一个，也可能只有开头那个（人复制时带上的）。
  out = out.replace(/^`+/, '').replace(/`+$/, '').trim();
  const quoted = /^(['"])(.*)\1$/s.exec(out);
  if (quoted) out = quoted[2].trim();
  return out;
}

/**
 * 这段文字是不是一条路径。是就交出可以拿去问服务端的那一份，不是就交出 null。
 */
export function pathCandidateOf(raw: string): PathCandidate | null {
  // 有换行就是一句话，不是一条路径。圈选常常跨段。
  if (/[\r\n]/.test(raw)) return null;

  const text = unwrap(raw).replace(LINE_SUFFIX, '').trim();
  if (!text) return null;
  if (ILLEGAL.test(text) || CJK_PUNCT.test(text)) return null;

  const rooted = ROOTED.test(text);

  // 空格：路径可以有（`Pinnacle AI Ecosystem.pdf`），散文也有。只在**以明确的根开头**时
  // 才允许，靠相对写法又带空格的与散文无从区分，一律不认。
  if (/\s/.test(text) && !rooted) return null;

  // 光一个 `~`、`/` 说的是目录不是文件，不值得给按钮。
  if (/^(?:~|\/|\\)$/.test(text)) return null;

  if (rooted) return { path: text, rooted: true };

  // 相对写法：至少一层目录，加一个带扩展名的文件名。光一个 `a/b` 不认——那在散文里
  // 也可能是「甲/乙」这种并列写法。
  const parts = text.split(/[\\/]/).filter(Boolean);
  if (parts.length < 2) return null;
  if (!/\.[^\\/.\s]+$/.test(parts[parts.length - 1])) return null;

  return { path: text, rooted: false };
}
