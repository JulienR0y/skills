const GATE_QUESTIONS = {
  acts_on_user_system:
    "Is the assistant being asked to act on the user's files, accounts, devices, or online services, rather than only to explain or advise?",
  would_follow_documented_procedure:
    'Would a careful expert answering this consult a specific documented procedure or set of commands, rather than answering from general understanding?',
  prose_suffices:
    "Could a knowledgeable generalist fully satisfy this request in prose, with no tools, no documentation, and no access to the user's files or accounts?",
}

const INVERTED_GATES = new Set(['prose_suffices'])

const ROUTING_QUESTIONS = {
  substantive:
    'Does this request require substantive implementation, debugging, testing, documentation research, or code review rather than a simple answer or trivial edit?',
  implementation:
    'Does satisfying this request require changing production code or configuration?',
  debugging:
    'Does satisfying this request require reproducing, isolating, or diagnosing a failure or unexpected behavior?',
  testing:
    'Does satisfying this request require independent verification, reproduction, or targeted test execution?',
  documentation:
    'Does implementation depend on version-specific external library, framework, or API documentation?',
  review:
    'Does satisfying this request require an independent correctness or test-gap review of code changes?',
  escalation:
    'Does this request involve difficult architecture, authorization, concurrency, data integrity, or conflicting findings that warrant escalation?',
}

function yesNo(instructions) {
  return { type: 'noul', instructions }
}

export function wideQuestions(skills, includeRouting = false) {
  const criteria = Object.fromEntries(
    skills.map((skill) => [skill.name, (skill.description || `A skill named ${skill.name}.`).slice(0, 240)]),
  )
  const questions = {
    which: {
      type: 'choice',
      instructions: "Which of these skills, if any, is the right one to load to help with the user's latest request?",
      criteria,
    },
  }
  for (const [name, instructions] of Object.entries(GATE_QUESTIONS)) {
    questions[`gate::${name}`] = yesNo(instructions)
  }
  if (includeRouting) {
    for (const [name, instructions] of Object.entries(ROUTING_QUESTIONS)) {
      questions[`routing::${name}`] = yesNo(instructions)
    }
  }
  return questions
}

export function rerankQuestions(candidates) {
  const questions = {
    which: {
      type: 'choice',
      instructions:
        "Exactly one of these skills is the right one to load for the user's latest request. Which one? Read what each actually does, not just its name.",
      criteria: Object.fromEntries(candidates.map((candidate) => [candidate.name, candidate.detail])),
    },
  }
  for (const candidate of candidates) {
    questions[`fits::${candidate.name}`] = yesNo(
      `Does the skill '${candidate.name}' do the specific thing the user's request asks for? It is described as: ${candidate.description || candidate.detail}`,
    )
  }
  return questions
}

export function requestBody(prompt, questions) {
  return JSON.stringify({
    model: 'jev-latest',
    state: { request: prompt, recent_context: '' },
    questions,
  })
}

function answersOf(text) {
  try {
    const answers = JSON.parse(text)?.answers
    return answers && typeof answers === 'object' ? answers : null
  } catch {
    return null
  }
}

function probabilityOf(answer) {
  if (typeof answer?.noul === 'number') return answer.noul
  if (typeof answer?.probability === 'number') return answer.probability
  return null
}

export function readWide(text) {
  const answers = answersOf(text)
  const which = answers?.which
  if (!answers || typeof which?.choice !== 'string') return null

  const ranked = []
  if (which.probabilities && typeof which.probabilities === 'object') {
    for (const [name, probability] of Object.entries(which.probabilities)) {
      if (typeof probability === 'number') ranked.push({ name, probability })
    }
    ranked.sort((left, right) => right.probability - left.probability)
  }
  if (ranked.length === 0) {
    ranked.push({ name: which.choice, probability: typeof which.confidence === 'number' ? which.confidence : null })
  }

  const oriented = []
  for (const name of Object.keys(GATE_QUESTIONS)) {
    const probability = probabilityOf(answers[`gate::${name}`])
    if (probability === null) continue
    oriented.push(INVERTED_GATES.has(name) ? 1 - probability : probability)
  }
  const gate = oriented.length ? oriented.reduce((sum, value) => sum + value, 0) / oriented.length : null
  return { ranked, gate }
}

export function readRouting(text) {
  const answers = answersOf(text)
  if (!answers) return null
  const routing = {}
  for (const name of Object.keys(ROUTING_QUESTIONS)) {
    const probability = probabilityOf(answers[`routing::${name}`])
    if (probability !== null) routing[name] = probability
  }
  return Object.keys(routing).length ? routing : null
}

export function readRerank(text) {
  const answers = answersOf(text)
  const which = answers?.which
  if (!answers || typeof which?.choice !== 'string') return null
  const fits = {}
  for (const [name, answer] of Object.entries(answers)) {
    if (!name.startsWith('fits::')) continue
    const probability = probabilityOf(answer)
    if (probability !== null) fits[name.slice('fits::'.length)] = probability
  }
  return {
    winner: which.choice,
    confidence: typeof which.confidence === 'number' ? which.confidence : null,
    fits,
  }
}

export function shortlistOf(wide, skills, count = 3) {
  const byName = new Map(skills.map((skill) => [skill.name, skill]))
  return wide.ranked.map(({ name }) => byName.get(name)).filter(Boolean).slice(0, count)
}

export function decide(wide, rerank, skills, rerankAttempted, config = {}) {
  const gateThreshold = config.gateThreshold ?? 0.3
  const fitsThreshold = config.fitsThreshold ?? 0.3
  const shortlist = config.shortlist ?? 3
  if (!wide) return { name: null, reason: 'no answer' }
  if (wide.gate !== null && wide.gate < gateThreshold) {
    return { name: null, reason: `needs a skill ${wide.gate.toFixed(2)} < ${gateThreshold}` }
  }
  const candidates = shortlistOf(wide, skills, shortlist)
  if (!candidates.length) return { name: null, reason: 'nothing ranked' }
  if (rerankAttempted && !rerank) return { name: null, reason: 'rerank gave no answer' }
  if (!rerank) return { name: candidates[0].name, reason: 'top ranked, no rerank' }

  const fitValues = Object.values(rerank.fits)
  const bestFit = fitValues.length ? Math.max(...fitValues) : null
  if (bestFit !== null && bestFit < fitsThreshold) {
    return { name: null, reason: `nothing fits, best ${bestFit.toFixed(2)} < ${fitsThreshold}` }
  }
  if (!candidates.some(({ name }) => name === rerank.winner)) {
    return { name: null, reason: `rerank named ${rerank.winner}, not shortlisted` }
  }
  return { name: rerank.winner, reason: `rerank of ${candidates.length}` }
}

export function detailOf(skill, excerptChars = 700) {
  const body = skill.markdown.replace(/^---\r?\n[\s\S]*?\r?\n---\r?\n?/, '').trim()
  const excerpt = body.slice(0, excerptChars)
  return excerpt ? `${skill.description || `A skill named ${skill.name}.`} — ${excerpt}` : skill.description
}
