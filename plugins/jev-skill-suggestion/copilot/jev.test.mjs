import assert from 'node:assert/strict'
import test from 'node:test'

import { decide, readRerank, readRouting, readWide, wideQuestions } from './jev.mjs'

test('keeps the broad ranking catalog compact', () => {
  const description = 'x'.repeat(500)
  const questions = wideQuestions([{ name: 'debug', description }])

  assert.equal(questions.which.criteria.debug.length, 240)
})

test('batches independent routing judgments with skill ranking', () => {
  const questions = wideQuestions([{ name: 'debug', description: 'Diagnose failures.' }], true)

  assert.equal(questions['routing::substantive'].type, 'noul')
  assert.equal(questions['routing::implementation'].type, 'noul')
  assert.equal(questions['routing::testing'].type, 'noul')
  assert.equal(questions['routing::escalation'].type, 'noul')
})

test('reads routing probabilities without forcing one role', () => {
  const routing = readRouting(JSON.stringify({
    answers: {
      'routing::substantive': { noul: 0.91 },
      'routing::implementation': { noul: 0.82 },
      'routing::testing': { noul: 0.76 },
      'routing::review': { noul: 0.43 },
    },
  }))

  assert.deepEqual(routing, {
    substantive: 0.91,
    implementation: 0.82,
    testing: 0.76,
    review: 0.43,
  })
})

test('selects the reranked skill when the gate and fit pass', () => {
  const wide = readWide(JSON.stringify({
    answers: {
      which: { choice: 'debug', probabilities: { debug: 0.7, review: 0.3 } },
      'gate::acts_on_user_system': { noul: 0.9 },
      'gate::would_follow_documented_procedure': { noul: 0.8 },
      'gate::prose_suffices': { noul: 0.1 },
    },
  }))
  const rerank = readRerank(JSON.stringify({
    answers: {
      which: { choice: 'debug', confidence: 0.8 },
      'fits::debug': { noul: 0.9 },
      'fits::review': { noul: 0.2 },
    },
  }))

  assert.equal(decide(wide, rerank, [{ name: 'debug' }, { name: 'review' }], true).name, 'debug')
})

test('rejects a ranked skill when the request does not pass the gate', () => {
  const wide = {
    ranked: [{ name: 'debug', probability: 0.9 }],
    gate: 0.2,
  }

  assert.equal(decide(wide, null, [{ name: 'debug' }], false).name, null)
})
