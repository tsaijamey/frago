/**
 * 浮窗关不关得掉，由谁说了算。
 *
 * 这一组用例盯的是一件很容易被"顺手加回来"的事：点窗外那片暗底不许关窗。加回来的人通常
 * 觉得自己在让界面更顺手，而代价落在填到一半的人身上——挑好的目录、打了一半的话、刚粘进
 * 去的密钥，鼠标在窗外多点一下就全没了，既没有提示也没有撤回。
 */

import { describe, expect, it, vi } from 'vitest';
import { fireEvent, render, screen } from '@testing-library/react';

import Modal from '../Modal';

function open(props: Partial<React.ComponentProps<typeof Modal>> = {}) {
  const onClose = vi.fn();
  render(
    <Modal isOpen onClose={onClose} title="要人填东西的窗" {...props}>
      <input data-testid="field" defaultValue="填到一半的东西" />
    </Modal>
  );
  return onClose;
}

/** 那片暗底是浮窗的最外层；窗体本身是它的孩子。 */
function backdrop() {
  return screen.getByText('要人填东西的窗').closest('[class*="fixed inset-0"]')!;
}

describe('Modal — 谁能关掉这扇窗', () => {
  it('点窗外那片暗底不关窗——人填到一半的东西不能这么没', () => {
    const onClose = open();
    fireEvent.click(backdrop());
    expect(onClose).not.toHaveBeenCalled();
    expect((screen.getByTestId('field') as HTMLInputElement).value).toBe('填到一半的东西');
  });

  it('按右上角的叉关得掉', () => {
    const onClose = open();
    fireEvent.click(screen.getByLabelText('Close modal'));
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('按 Esc 关得掉——那是冲着关窗去的动作，不是失手', () => {
    const onClose = open();
    fireEvent.keyDown(document, { key: 'Escape' });
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it('点窗体里面不关窗', () => {
    const onClose = open();
    fireEvent.click(screen.getByTestId('field'));
    expect(onClose).not.toHaveBeenCalled();
  });

  it('只报信、不收输入的窗可以明说要点遮罩就关', () => {
    const onClose = open({ dismissOnBackdrop: true });
    fireEvent.click(backdrop());
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
