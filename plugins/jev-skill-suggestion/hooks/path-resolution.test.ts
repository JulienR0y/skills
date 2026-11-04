import { describe, expect, test } from 'bun:test'

import { agentSkillFileCandidates, homeDirectory, pluginFileCandidates } from './policy.ts'

describe('Windows skill path resolution', () => {
  test('uses USERPROFILE when HOME is unavailable', () => {
    expect(homeDirectory(undefined, 'C:\\Users\\me')).toBe('C:/Users/me')
  })

  test('finds user skills installed under .agents', () => {
    expect(agentSkillFileCandidates('C:/Users/me', 'using-agent-skills')).toEqual([
      'C:/Users/me/.agents/skills/using-agent-skills/SKILL.md',
    ])
  })

  test('normalizes Windows plugin install paths', () => {
    expect(
      pluginFileCandidates(
        'C:\\Users\\me\\.claude\\plugins\\cache\\addy-agent-skills\\agent-skills\\0.6.7',
        'agent-skills:using-agent-skills',
        'agent-skills',
      ),
    ).toContain(
      'C:/Users/me/.claude/plugins/cache/addy-agent-skills/agent-skills/0.6.7/skills/using-agent-skills/SKILL.md',
    )
  })
})
