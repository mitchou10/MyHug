import { getDataset } from '../mockData'
import { modelInfo, modelsFor } from './models'
import { itemCount, makeProposal } from './preannotate'
import { addRun, CURRENT_USER, dropRunProposals, getState, patchRun, putProposal, type PreRun } from './store'

const timers = new Map<string, ReturnType<typeof setInterval>>()
const uid = () => Math.random().toString(36).slice(2, 8)
const speedOf = (model: string) => modelInfo(model)?.msPerItem ?? 700

/** Goes through one more item of a run. When there is none left, the run is done. */
function step(runId: string) {
  const run = getState().runs.find((r) => r.id === runId)
  const project = run && getState().projects.find((p) => p.id === run.projectId)
  const [owner, name] = project?.datasetKey.split('/') ?? []
  const d = getDataset(owner, name)
  if (!run || run.status !== 'running' || !project || !d) return halt(runId)
  const idx = run.queue[run.processed]
  if (idx === undefined) { patchRun(runId, { status: 'done', endedAt: Date.now() }); return halt(runId) }
  // An item answered by a human in the meantime is left alone.
  if (!getState().answers[project.id]?.[idx]) {
    const proposal = makeProposal(project, d, idx, run.model, run.id)
    if (proposal) putProposal(project.id, idx, proposal)
  }
  const processed = run.processed + 1
  patchRun(runId, processed >= run.queue.length ? { processed, status: 'done', endedAt: Date.now() } : { processed })
  if (processed >= run.queue.length) halt(runId)
}
function halt(runId: string) { const t = timers.get(runId); if (t) clearInterval(t); timers.delete(runId) }
function tick(run: PreRun) { halt(run.id); timers.set(run.id, setInterval(() => step(run.id), speedOf(run.model))) }

/** Starts a pre-annotation: the model goes through the items nobody has answered yet. */
export function startRun(projectId: string, model: string) {
  const project = getState().projects.find((p) => p.id === projectId)
  const [owner, name] = project?.datasetKey.split('/') ?? []
  const d = getDataset(owner, name)
  // A model only works for the kinds of tasks it was made for.
  if (!project || !d || !modelsFor(project.task).some((m) => m.id === model)) return
  const done = getState().answers[projectId] ?? {}
  const queue = Array.from({ length: itemCount(d) }, (_, i) => i).filter((i) => !done[i])
  const run: PreRun = { id: `r-${uid()}`, projectId, model, status: queue.length ? 'running' : 'done', total: queue.length, processed: 0, queue, startedAt: Date.now(), createdBy: CURRENT_USER }
  addRun(run)
  if (queue.length) tick(run)
}
export function stopRun(runId: string) { halt(runId); patchRun(runId, { status: 'stopped' }) }
export function resumeRun(runId: string) {
  const run = getState().runs.find((r) => r.id === runId)
  if (!run) return
  patchRun(runId, { status: 'running' })
  tick(run)
}
/** Deletes the proposals nobody decided on and stops the run. What was validated stays, and so do the statistics. */
export function deleteRun(runId: string) { halt(runId); dropRunProposals(runId); patchRun(runId, { status: 'deleted', endedAt: Date.now() }) }
