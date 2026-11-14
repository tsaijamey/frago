import { useRef, type ReactNode } from 'react';
import { Send } from 'lucide-react';
import { modKey } from '../../hooks/usePlatform';
import DirectoryAutocomplete from '../ui/DirectoryAutocomplete';

interface NewTaskInputProps {
  value: string;
  onChange: (value: string) => void;
  onSend: () => void;
  disabled?: boolean;
  placeholder?: string;
  /**
   * 底部控制栏左侧槽位。权限模式切换这类「这次怎么跑」的设定放这儿，
   * 与右下角的发送动作同处一条栏里，读作一句话：「按这个模式，发出去」。
   */
  controls?: ReactNode;
}

/**
 * 新建会话的主输入框。
 *
 * 面板本身是 Double-Bezel：外层一圈托盘线、内层一圈卡边、顶部一道 1px 内高光，
 * 聚焦时整块面板亮起品牌绿柔光——「现在敲的字会进这里」不需要再靠一行提示语说明。
 * 发送键从原先浮在文本框右下角的圆钮移进底部控制栏，与快捷键提示同一行，
 * 位置固定、不会随文字长短游移。
 */
export default function NewTaskInput({
  value,
  onChange,
  onSend,
  disabled = false,
  placeholder = 'Type your message...',
  controls,
}: NewTaskInputProps) {
  const textareaRef = useRef<HTMLTextAreaElement>(null);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      if (!disabled && value.trim()) {
        onSend();
      }
    }
  };

  const canSend = !disabled && Boolean(value.trim());

  return (
    <div className="nti">
      <div className="nti-frame">
        <DirectoryAutocomplete
          value={value}
          onChange={onChange}
          textareaRef={textareaRef}
        />
        <textarea
          ref={textareaRef}
          className="nti-textarea"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
          onKeyDown={handleKeyDown}
          disabled={disabled}
          aria-label="Message input"
        />
        <div className="nti-bar">
          <div className="nti-bar-controls">{controls}</div>
          <div className="nti-bar-actions">
            {value.length > 0 && <span className="nti-count">{value.length}</span>}
            <span className="nti-hint">{modKey}+Enter</span>
            <button
              type="button"
              className="nti-send"
              onClick={onSend}
              disabled={!canSend}
              aria-label="Send message"
            >
              <Send size={16} strokeWidth={1.75} />
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
