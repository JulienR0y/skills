import assert from 'node:assert/strict'
import { mkdtemp, mkdir, rm, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import test from 'node:test'

import { API_URL, discoverSkills, runHook, workspaceRoots } from './hook.mjs'

async function tempRoot(t) {
  const root = await mkdtemp(path.join(os.tmpdir(), 'jev-copilot-test-'))
  t.after(() => rm(root, { recursive: true, force: true }))
  return root
}

async function writeSkill(dir, name, description, extraFrontmatter = '') {
  await mkdir(dir, { recursive: true })
  await writeFile(
    path.join(dir, 'SKILL.md'),
    `---\nname: ${name}\ndescription: ${description}\n${extraFrontmatter}---\n${name} instructions.\n`,
  )
}

const debugSkill = {
  name: 'debug',
  description: 'Diagnose failures.',
  markdown: '---\nname: debug\ndescription: Diagnose failures.\n---\nDebug carefully in ${CLAUDE_SKILL_DIR}.\n',
  path: 'C:/skills/debug/SKILL.md',
}

const debugSelected = [
  {
    answers: {
      which: { choice: 'debug', probabilities: { debug: 1 } },
      'gate::acts_on_user_system': { noul: 1 },
      'gate::would_follow_documented_procedure': { noul: 1 },
      'gate::prose_suffices': { noul: 0 },
    },
  },
  { answers: { which: { choice: 'debug' }, 'fits::debug': { noul: 1 } } },
]

function recordingFetch(responses) {
  const calls = []
  const fetch = async (url, init) => {
    calls.push({ url, init })
    return { ok: true, text: async () => JSON.stringify(responses[calls.length - 1]) }
  }
  return { calls, fetch }
}

const event = {
  sessionId: 'session-1',
  timestamp: 1793109400000,
  cwd: 'C:/repo',
  prompt: 'Debug this failure',
  transformedPrompt: '<current_datetime>2026-10-27</current_datetime>\n\nDebug this failure',
}

test('discovers Copilot personal and plugin skills, skipping synced copies and manual-only skills', async (t) => {
  const root = await tempRoot(t)
  const home = path.join(root, 'home')
  const copilotHome = path.join(home, '.copilot')
  const appData = path.join(root, 'AppData', 'Roaming')
  const plugins = path.join(appData, 'Code', 'agentPlugins')
  await writeSkill(path.join(copilotHome, 'skills', 'commit'), 'commit', 'Write commits.')
  await writeSkill(path.join(home, '.agents', 'skills', 'debug'), 'debug', 'Diagnose failures.')
  await writeSkill(path.join(home, '.claude', 'skills', 'review'), 'review', 'Review code.')
  await writeSkill(path.join(copilotHome, 'installed-plugins', 'market', 'tools', 'skills', 'lint'), 'lint', 'Lint code.')
  await writeSkill(path.join(plugins, 'file-c-3A-plugins-docs', '1a2b', 'skills', 'docs'), 'docs', 'Write docs.')
  await writeSkill(path.join(plugins, 'vscode-synced-customization-agent-host-copilotcli-1', '9', 'skills', 'stale'), 'stale', 'Stale.')
  await writeSkill(path.join(home, '.agents', 'skills', 'manual'), 'manual', 'Manual only.', 'disable-model-invocation: true\n')
  await writeSkill(path.join(home, '.claude', 'skills', 'debug'), 'debug', 'Duplicate name.')

  const skills = await discoverSkills({ home, copilotHome, appData, cwd: root, includeWorkspaceAncestors: false })

  assert.deepEqual(skills.map(({ name }) => name).sort(), ['commit', 'debug', 'docs', 'lint', 'review'])
  assert.equal(skills.find(({ name }) => name === 'debug').description, 'Diagnose failures.')
})

test('looks for repository skills in Copilot project folders from the working directory upward', () => {
  const repo = path.resolve('/work/repo')
  const roots = workspaceRoots(path.join(repo, 'src'))

  assert.ok(roots.indexOf(path.join(repo, 'src', '.github', 'skills')) < roots.indexOf(path.join(repo, '.github', 'skills')))
  for (const folder of ['.github', '.agents', '.claude']) assert.ok(roots.includes(path.join(repo, folder, 'skills')))
})

test('appends the selected skill to the model-facing prompt using the TypeSafe key', async () => {
  const { calls, fetch } = recordingFetch(debugSelected)

  const output = await runHook(event, { apiKey: 'test-key', discover: async () => [debugSkill], fetch, log: async () => {} })

  assert.equal(calls.length, 2)
  assert.equal(calls[0].url, API_URL)
  assert.equal(calls[0].init.headers.authorization, 'Bearer test-key')
  assert.equal(JSON.parse(calls[0].init.body).state.request, 'Debug this failure')
  assert.ok(output.modifiedTransformedPrompt.startsWith(`${event.transformedPrompt}\n\n<skill_relevance>`))
  assert.match(output.modifiedTransformedPrompt, /<skill name="debug" dir="C:\/skills\/debug">/)
  assert.match(output.modifiedTransformedPrompt, /Debug carefully in C:\/skills\/debug\./)
})

test('references a long skill by path instead of truncating its instructions', async () => {
  const longSkill = { ...debugSkill, markdown: `---\nname: debug\n---\n${'step\n'.repeat(3000)}` }
  const { fetch } = recordingFetch(debugSelected)

  const output = await runHook(event, { apiKey: 'test-key', discover: async () => [longSkill], fetch, log: async () => {} })

  assert.match(output.modifiedTransformedPrompt, /Read C:\/skills\/debug\/SKILL\.md and follow it/)
  assert.doesNotMatch(output.modifiedTransformedPrompt, /<skill name=/)
})

test('tells the model no skill applies when the request does not need one', async () => {
  const { calls, fetch } = recordingFetch([
    {
      answers: {
        which: { choice: 'debug', probabilities: { debug: 1 } },
        'gate::acts_on_user_system': { noul: 0 },
        'gate::would_follow_documented_procedure': { noul: 0.1 },
        'gate::prose_suffices': { noul: 1 },
      },
    },
  ])
  const records = []

  const output = await runHook(
    { ...event, prompt: 'What is a closure?' },
    { apiKey: 'test-key', discover: async () => [debugSkill], fetch, log: async (record) => records.push(record) },
  )

  assert.equal(calls.length, 1)
  assert.match(output.modifiedTransformedPrompt, /No installed skill appears relevant/)
  assert.equal(records[0].result, 'none')
  assert.equal(records[0].sessionId, 'session-1')
})

test('leaves slash commands and payloads without transformed content untouched', async () => {
  const { calls, fetch } = recordingFetch(debugSelected)
  const dependencies = { apiKey: 'test-key', discover: async () => [debugSkill], fetch, log: async () => {} }

  assert.equal(await runHook({ ...event, prompt: '/compact' }, dependencies), null)
  assert.equal(await runHook({ hook_event_name: 'UserPromptSubmit', prompt: 'Debug this failure' }, dependencies), null)
  assert.equal(calls.length, 0)
})

test('does not call TypeSafe without an API key', async () => {
  const { calls, fetch } = recordingFetch(debugSelected)
  const records = []

  const output = await runHook(event, {
    apiKey: '',
    discover: async () => [debugSkill],
    fetch,
    log: async (record) => records.push(record),
  })

  assert.equal(output, null)
  assert.equal(calls.length, 0)
  assert.equal(records[0].result, 'no-key')
})

test('fails open when TypeSafe is unavailable', async () => {
  const records = []

  const output = await runHook(event, {
    apiKey: 'test-key',
    discover: async () => [debugSkill],
    fetch: async () => ({ ok: false, status: 503 }),
    log: async (record) => records.push(record),
  })

  assert.equal(output, null)
  assert.equal(records[0].result, 'error')
  assert.equal(records[0].error, 'TypeSafe returned 503')
})
