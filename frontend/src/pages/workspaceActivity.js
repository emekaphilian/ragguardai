export function selectWorkspaceActivity(recentRuns) {
  return recentRuns.filter((run) => run.source === 'workspace')
}
