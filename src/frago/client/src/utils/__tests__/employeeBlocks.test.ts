import { describe, expect, it } from 'vitest';
import { splitEmployeeBlocks } from '../employeeBlocks';

/** 与服务端 `EmployeeOntologyService.build_business_context_block` 拼出来的形状一致。 */
function empBlock(
  id: string,
  title = 'Stock 投研与策略专员',
  kernel = 'claude',
  body = '【员工身份与工作范畴】\n岗位：Stock 投研与策略专员（id: stock）\n职责：全场景投研'
) {
  return `<frago-employee id="${id}" title="${title}" kernel="${kernel}">\n${body}\n</frago-employee>`;
}

describe('splitEmployeeBlocks', () => {
  it('没有员工语境块时原样返回', () => {
    expect(splitEmployeeBlocks('你好')).toEqual({ text: '你好', employees: [] });
  });

  it('摘掉整段 <frago-employee> 块，只留员工信息与人写的话', () => {
    const out = splitEmployeeBlocks(`${empBlock('stock')}\n\n评估 159518 明天可能的走势`);
    expect(out).toEqual({
      text: '评估 159518 明天可能的走势',
      employees: [{ id: 'stock', title: 'Stock 投研与策略专员', kernel: 'claude' }],
    });
  });

  it('标签无 title 属性时从内部岗位行提取名称兜底', () => {
    const raw =
      '<frago-employee id="stock">\n' +
      '【员工身份与工作范畴】\n' +
      '岗位：Stock 投研与策略专员（id: stock）\n' +
      '</frago-employee>\n\n查询行情';
    expect(splitEmployeeBlocks(raw)).toEqual({
      text: '查询行情',
      employees: [{ id: 'stock', title: 'Stock 投研与策略专员' }],
    });
  });

  it('只有员工语境块时正文为空', () => {
    expect(splitEmployeeBlocks(empBlock('stock'))).toEqual({
      text: '',
      employees: [{ id: 'stock', title: 'Stock 投研与策略专员', kernel: 'claude' }],
    });
  });

  it('人只是提到 <frago-employee 标签名、没有完整一段时不动', () => {
    const raw = '# 任务书：排查 `<frago-employee id="stock">` 标签解析逻辑';
    expect(splitEmployeeBlocks(raw)).toEqual({ text: raw, employees: [] });
  });
});
