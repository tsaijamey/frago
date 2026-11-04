/**
 * 从人说的那句话里认出点员工卡片带入的业务语境块。
 *
 * 点员工卡片起会话（或交接、引用员工语境）时，服务端把该员工的岗位、工作范畴、数据底账、
 * 知识域与配方、账本嵌在正文前面，包成
 * `<frago-employee id="…" title="…" kernel="…">…</frago-employee>` 一段（见服务端
 * `frago.employee.service.EmployeeOntologyService.build_business_context_block`）。
 * agent 要读那段全文，人不用：记录流里只把员工画成顶部的引用卡片，内部正文一个字都不摆。
 */

export interface EmployeeBlockItem {
  id: string;
  title?: string;
  kernel?: string;
}

const EMPLOYEE_BLOCK_RE = /<frago-employee\s+([^>]*)>([\s\S]*?)<\/frago-employee>\s*/g;
const ID_ATTR_RE = /\bid="([^"]*)"/;
const TITLE_ATTR_RE = /\btitle="([^"]*)"/;
const KERNEL_ATTR_RE = /\bkernel="([^"]*)"/;
const BODY_TITLE_RE = /^岗位：([^\n（(]+)/m;

function unescapeAttr(value: string): string {
  return value.replace(/&quot;/g, '"').replace(/&amp;/g, '&');
}

/** 把正文拆成「人写的话」与「引用的员工列表」。没有那几段时原样返回、列表为空。 */
export function splitEmployeeBlocks(text: string): {
  text: string;
  employees: EmployeeBlockItem[];
} {
  if (!text.includes('<frago-employee')) return { text, employees: [] };
  const employees: EmployeeBlockItem[] = [];
  const rest = text.replace(EMPLOYEE_BLOCK_RE, (fullMatch, attrs: string, body: string) => {
    const idMatch = attrs.match(ID_ATTR_RE);
    const id = idMatch ? unescapeAttr(idMatch[1]).trim() : '';
    if (!id) return fullMatch;

    const titleMatch = attrs.match(TITLE_ATTR_RE);
    let title = titleMatch ? unescapeAttr(titleMatch[1]).trim() : '';
    if (!title) {
      const bodyMatch = body.match(BODY_TITLE_RE);
      if (bodyMatch) title = bodyMatch[1].trim();
    }

    const kernelMatch = attrs.match(KERNEL_ATTR_RE);
    const kernel = kernelMatch ? unescapeAttr(kernelMatch[1]).trim() : '';

    employees.push({
      id,
      ...(title ? { title } : {}),
      ...(kernel ? { kernel } : {}),
    });
    return '';
  });
  if (!employees.length) return { text, employees: [] };
  return { text: rest.trim(), employees };
}
