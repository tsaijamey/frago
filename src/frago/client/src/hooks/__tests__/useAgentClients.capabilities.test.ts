import { describe, expect, it } from 'vitest';
import {
  DEFAULT_AGENT_CAPABILITIES,
  getAgentCapability,
  supportsBranch,
  supportsForYou,
  type AgentClient,
} from '../useAgentClients';

describe('useAgentClients 能力矩阵与特性声明', () => {
  it('DEFAULT_AGENT_CAPABILITIES 包含 5 大内核的六大正交切面', () => {
    const kernels = ['claude', 'agy', 'opencode', 'codex', 'coreagent'] as const;
    const facets = [
      'identity_probe',
      'lifecycle_action',
      'transcript_sync',
      'awaiting_input_probe',
      'context_watermark',
      'hook_injection',
    ];

    for (const k of kernels) {
      expect(DEFAULT_AGENT_CAPABILITIES[k]).toBeDefined();
      for (const f of facets) {
        expect(DEFAULT_AGENT_CAPABILITIES[k][f]).toBeDefined();
      }
    }

    expect(DEFAULT_AGENT_CAPABILITIES.claude.awaiting_input_probe).toBe('adapted');
    expect(DEFAULT_AGENT_CAPABILITIES.agy.awaiting_input_probe).toBe('fallback');
    expect(DEFAULT_AGENT_CAPABILITIES.codex.awaiting_input_probe).toBe('fallback');
    expect(DEFAULT_AGENT_CAPABILITIES.opencode.awaiting_input_probe).toBe('fallback');
    expect(DEFAULT_AGENT_CAPABILITIES.coreagent.awaiting_input_probe).toBe('unsupported');
  });

  it('优先消费服务端下发的能力切面，若缺省则回退到默认矩阵', () => {
    const serverAgent: AgentClient = {
      agent_type: 'agy',
      display_name: 'Antigravity',
      installed: true,
      path: '/bin/agy',
      family: 'antigravity',
      selectable: true,
      reason: null,
      id_origin: 'claimed',
      capabilities: {
        identity_probe: 'native',
        awaiting_input_probe: 'fallback',
      },
    };

    expect(getAgentCapability(serverAgent, 'identity_probe')).toBe('native');
    expect(getAgentCapability(serverAgent, 'awaiting_input_probe')).toBe('fallback');
    // 未显式给出的切面自动回退到 DEFAULT_AGENT_CAPABILITIES
    expect(getAgentCapability(serverAgent, 'transcript_sync')).toBe('adapted');
  });

  it('supportsBranch 正确响应特性开关与后备行为', () => {
    const claudeAgent: AgentClient = {
      agent_type: 'claude',
      display_name: 'Claude Code',
      installed: true,
      path: '/bin/claude',
      family: 'claude-code',
      selectable: true,
      reason: null,
      id_origin: 'caller',
      supports_branch: true,
    };
    const agyAgent: AgentClient = {
      agent_type: 'agy',
      display_name: 'Antigravity',
      installed: true,
      path: '/bin/agy',
      family: 'antigravity',
      selectable: true,
      reason: null,
      id_origin: 'claimed',
      supports_branch: false,
    };

    expect(supportsBranch(claudeAgent)).toBe(true);
    expect(supportsBranch(agyAgent)).toBe(false);
  });

  it('supportsForYou 支持感知多内核的待输入探针声明', () => {
    const agyAgent: AgentClient = {
      agent_type: 'agy',
      display_name: 'Antigravity',
      installed: true,
      path: '/bin/agy',
      family: 'antigravity',
      selectable: true,
      reason: null,
      id_origin: 'claimed',
      supports_for_you: true,
    };
    const coreAgent: AgentClient = {
      agent_type: 'coreagent',
      display_name: 'CoreAgent',
      installed: true,
      path: null,
      family: 'coreagent',
      selectable: true,
      reason: null,
      id_origin: 'caller',
      supports_for_you: false,
    };

    expect(supportsForYou(agyAgent)).toBe(true);
    expect(supportsForYou(coreAgent)).toBe(false);
  });
});
