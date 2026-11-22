import assert from 'node:assert/strict'
import test from 'node:test'
import { selectWorkspaceActivity } from './workspaceActivity.js'

test('includes selected-application workspace queries without mixing observations', () => {
  const recentRuns = [
    { id: 'workspace-query', source: 'workspace', application_id: 'trustassist' },
    { id: 'trustassist-observation', source: 'observation', application_id: 'trustassist' },
  ]

  assert.deepEqual(
    selectWorkspaceActivity(recentRuns).map((run) => run.id),
    ['workspace-query'],
  )
})
