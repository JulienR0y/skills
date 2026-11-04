import { appendFile, readFile, readdir, realpath, rename, rm, stat } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

import {
  decide,
  detailOf,
  readRerank,
  readWide,
  requestBody,
  rerankQuestions,
  shortlistOf,
  wideQuestions,
} from './jev.mjs'

export const API_URL = 'https://api.typesafe.ai/v1/systemone'
const SKIP_DIRECTORIES = new Set(['.git', 'node_modules', '__pycache__'])
const INJECTION_LIMIT = 8000
const NO_SKILL = '<skill_relevance>\nNo installed skill appears relevant to this request.\n</skill_relevance>'

function frontmatter(markdown) {
  return /^---\r?\n([\s\S]*?)\r?\n---/.exec(markdown)?.[1] ?? ''
}

function scalarField(block, name) {
  const match = new RegExp(`^${name}:\\s*(.*)$`, 'm').exec(block)
  if (!match) return ''
  const value = match[1].trim().replace(/^['"]|['"]$/g, '')
  if (!/^[>|][+-]?$/.test(value)) return value
  const lines = block.slice(match.index + match[0].length).split(/\r?\n/)
  return lines
    .filter((line) => /^\s+/.test(line))
    .map((line) => line.trim())
    .join(' ')
}

async function walkSkillFiles(root, found, visited) {
  try {
    const resolved = await realpath(root)
    if (visited.has(resolved)) return
    visited.add(resolved)
    for (const entry of await readdir(root, { withFileTypes: true })) {
      if (entry.isDirectory() && !SKIP_DIRECTORIES.has(entry.name)) {
        await walkSkillFiles(path.join(root, entry.name), found, visited)
      } else if (entry.isFile() && entry.name === 'SKILL.md') {
        found.push(path.join(root, entry.name))
      }
    }
  } catch (error) {
    if (error?.code !== 'ENOENT' && error?.code !== 'EACCES') throw error
  }
}

export function workspaceRoots(cwd) {
  const roots = []
  let current = path.resolve(cwd)
  while (true) {
    for (const folder of ['.github', '.agents', '.claude']) roots.push(path.join(current, folder, 'skills'))
    const parent = path.dirname(current)
    if (parent === current) break
    current = parent
  }
  return roots
}

// VS Code installs agent plugins as file-* folders. The vscode-synced-customization-* folders are
// per-window copies of built-in skills, so they would only add stale duplicates to the catalog.
export async function vscodePluginRoots(appData) {
  if (!appData) return []
  const base = path.join(appData, 'Code', 'agentPlugins')
  try {
    return (await readdir(base, { withFileTypes: true }))
      .filter((entry) => entry.isDirectory() && entry.name.startsWith('file-'))
      .map((entry) => path.join(base, entry.name))
  } catch (error) {
    if (error?.code === 'ENOENT') return []
    throw error
  }
}

async function implicitInvocationAllowed(file) {
  for (const name of ['openai.yaml', 'openai.yml']) {
    try {
      const yaml = await readFile(path.join(path.dirname(file), 'agents', name), 'utf8')
      if (/^\s*allow_implicit_invocation:\s*false\s*$/m.test(yaml)) return false
    } catch (error) {
      if (error?.code !== 'ENOENT') throw error
    }
  }
  return true
}

export async function discoverSkills({ home, copilotHome, appData, cwd, includeWorkspaceAncestors = true }) {
  const roots = [
    path.join(copilotHome, 'skills'),
    path.join(home, '.agents', 'skills'),
    path.join(home, '.claude', 'skills'),
    path.join(copilotHome, 'installed-plugins'),
    ...(await vscodePluginRoots(appData)),
    ...(includeWorkspaceAncestors && cwd ? workspaceRoots(cwd) : []),
  ]
  const files = []
  const visited = new Set()
  for (const root of [...new Set(roots.map((entry) => path.resolve(entry)))]) {
    await walkSkillFiles(root, files, visited)
  }

  const skills = new Map()
  for (const file of files) {
    const markdown = await readFile(file, 'utf8')
    const metadata = frontmatter(markdown)
    if (/^disable-model-invocation:\s*true\s*$/m.test(metadata)) continue
    if (!(await implicitInvocationAllowed(file))) continue
    const name = scalarField(metadata, 'name') || path.basename(path.dirname(file))
    if (!name || skills.has(name)) continue
    skills.set(name, {
      name,
      description: scalarField(metadata, 'description') || `A skill named ${name}.`,
      markdown,
      path: file.replace(/\\/g, '/'),
    })
  }
  return [...skills.values()]
}

async function query(fetchImpl, apiKey, prompt, questions, timeoutMs) {
  const response = await fetchImpl(API_URL, {
    method: 'POST',
    headers: {
      authorization: `Bearer ${apiKey}`,
      connection: 'close',
      'content-type': 'application/json',
    },
    body: requestBody(prompt, questions),
    signal: AbortSignal.timeout(timeoutMs),
  })
  if (!response.ok) throw new Error(`TypeSafe returned ${response.status ?? 'an error'}`)
  return response.text()
}

export function injectionBlock(skill, cwd, limit = INJECTION_LIMIT) {
  const directory = path.posix.dirname(skill.path)
  const body = skill.markdown
    .replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '')
    .trim()
    .replace(/\$\{CLAUDE_SKILL_DIR\}/g, directory)
    .replace(/\$\{CLAUDE_PROJECT_DIR\}/g, cwd.replace(/\\/g, '/'))
  const lead = `Relevant to the current request: ${skill.name}. Ignore this if it does not fit what the user actually asked for.`
  const inline = [
    '<skill_relevance>',
    lead,
    'Its instructions follow. Follow them now; do not load the skill again because it is already included here.',
    `<skill name="${skill.name}" dir="${directory}">`,
    body,
    '</skill>',
    '</skill_relevance>',
  ].join('\n')
  if (inline.length <= limit) return inline
  // Truncating a skill mid-procedure is worse than one extra read, so long skills are referenced instead.
  return [
    '<skill_relevance>',
    lead,
    `Its instructions are too long to include here. Read ${skill.path} and follow it before you continue.`,
    '</skill_relevance>',
  ].join('\n')
}

async function defaultLog(record, copilotHome) {
  const file = path.join(copilotHome, 'logs', 'jev-skill-suggestion.log')
  try {
    if ((await stat(file)).size > 512_000) {
      await rm(`${file}.1`, { force: true })
      await rename(file, `${file}.1`)
    }
  } catch (error) {
    if (error?.code !== 'ENOENT') return
  }
  try {
    await appendFile(file, `${JSON.stringify({ at: new Date().toISOString(), ...record })}\n`, 'utf8')
  } catch {}
}

// Copilot drops command-hook output for userPromptSubmitted, so this runs on userPromptTransformed
// and appends the skill to the model-facing content instead of returning additionalContext.
export async function runHook(input, dependencies = {}) {
  const transformedPrompt = input?.transformedPrompt
  const prompt = typeof input?.prompt === 'string' ? input.prompt.trim() : ''
  if (typeof transformedPrompt !== 'string' || !prompt || /^[/$]\S/.test(prompt)) return null

  const home = dependencies.home ?? process.env.USERPROFILE ?? process.env.HOME ?? ''
  const copilotHome = dependencies.copilotHome ?? process.env.COPILOT_HOME ?? path.join(home, '.copilot')
  const appData = dependencies.appData ?? process.env.APPDATA ?? ''
  const cwd = typeof input.cwd === 'string' && input.cwd ? input.cwd : process.cwd()
  const apiKey = dependencies.apiKey ?? process.env.TYPESAFE_API_KEY ?? ''
  const discover = dependencies.discover ?? discoverSkills
  const fetchImpl = dependencies.fetch ?? globalThis.fetch
  const log = dependencies.log ?? ((record) => defaultLog(record, copilotHome))
  const timeoutMs = dependencies.timeoutMs ?? 800
  const started = Date.now()
  if (!apiKey) {
    await log({ result: 'no-key' })
    return null
  }

  try {
    const skills = await discover({ home, copilotHome, appData, cwd })
    if (!skills.length) {
      await log({ result: 'no-skills' })
      return null
    }
    const wide = readWide(await query(fetchImpl, apiKey, prompt, wideQuestions(skills), timeoutMs))
    const shortlist = wide && (wide.gate === null || wide.gate >= 0.3) ? shortlistOf(wide, skills, 3) : []
    let rerank = null
    let rerankAttempted = false
    if (shortlist.length) {
      rerankAttempted = true
      const candidates = shortlist.map((skill) => ({ ...skill, detail: detailOf(skill) }))
      rerank = readRerank(await query(fetchImpl, apiKey, prompt, rerankQuestions(candidates), timeoutMs))
    }
    const decision = decide(wide, rerank, skills, rerankAttempted)
    const selected = decision.name ? skills.find(({ name }) => name === decision.name) : null
    await log({
      result: selected ? 'selected' : 'none',
      skill: selected?.name ?? null,
      gate: wide?.gate ?? null,
      candidates: skills.length,
      bodiesRead: shortlist.length,
      reason: decision.reason,
      sessionId: input.sessionId ?? null,
      elapsedMs: Date.now() - started,
    })
    const block = selected ? injectionBlock(selected, cwd) : NO_SKILL
    return { modifiedTransformedPrompt: `${transformedPrompt}\n\n${block}` }
  } catch (error) {
    await log({
      result: 'error',
      error: error instanceof Error ? error.message : String(error),
      sessionId: input.sessionId ?? null,
      elapsedMs: Date.now() - started,
    })
    return null
  }
}

async function main() {
  let text = ''
  for await (const chunk of process.stdin) text += chunk
  const output = await runHook(JSON.parse(text))
  await new Promise((resolve, reject) => {
    process.stdout.write(`${JSON.stringify(output ?? {})}\n`, (error) => (error ? reject(error) : resolve()))
  })
}

if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  main().catch(() => {
    process.exitCode = 0
  })
}
