// Install jev-skill-suggestion as a user-level VS Code Copilot hook.
// Copies hook.mjs and jev.mjs to ~/.copilot/hooks/jev-skill-suggestion/ and writes
// ~/.copilot/hooks/jev-skill-suggestion.json pointing at this Node. Re-run after each update,
// then reload VS Code. The hook reads your own key from the TYPESAFE_API_KEY environment variable.
import { copyFile, mkdir, writeFile } from 'node:fs/promises'
import os from 'node:os'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const home = process.env.COPILOT_HOME ?? path.join(os.homedir(), '.copilot')
const target = path.join(home, 'hooks', 'jev-skill-suggestion')

await mkdir(target, { recursive: true })
for (const name of ['hook.mjs', 'jev.mjs']) await copyFile(path.join(here, name), path.join(target, name))
const config = {
  version: 1,
  hooks: {
    userPromptTransformed: [
      { type: 'command', exec: process.execPath, args: [path.join(target, 'hook.mjs')], timeoutSec: 5 },
    ],
  },
}
const hookFile = path.join(home, 'hooks', 'jev-skill-suggestion.json')
await writeFile(hookFile, JSON.stringify(config, null, 2) + '\n')
console.log(`Installed: ${hookFile}\nScripts:   ${target}\nReload VS Code to load the hook.`)
