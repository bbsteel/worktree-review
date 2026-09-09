import type { FixtureCaseDescriptor } from '../../domain/overview.ts'
import type { ReviewRunView } from '../../domain/review.ts'
import blockedFile from './blocked.json'
import errorFile from './error_merge_conflict.json'
import { mapPipelineSnapshot, PIPELINE_SNAPSHOT_BADGE } from './map-cli-result.ts'
import type { PipelineSnapshotFile } from './cli-result.ts'
import passedFile from './passed.json'

const passedSnapshot = mapPipelineSnapshot(passedFile as PipelineSnapshotFile)
const blockedSnapshot = mapPipelineSnapshot(blockedFile as PipelineSnapshotFile)
const errorSnapshot = mapPipelineSnapshot(errorFile as PipelineSnapshotFile)

export { PIPELINE_SNAPSHOT_BADGE }

export const pipelineSnapshots: ReviewRunView[] = [passedSnapshot, blockedSnapshot, errorSnapshot]

export function getPipelineSnapshot(attemptId: string): ReviewRunView | null {
  return pipelineSnapshots.find((run) => run.attemptId === attemptId) ?? null
}

export function listPipelineSnapshots(): FixtureCaseDescriptor[] {
  return [
    {
      caseKey: 'passed',
      attemptId: passedSnapshot.attemptId,
      gateState: passedSnapshot.gateState,
      title: 'Passed local pipeline snapshot',
      provenance: 'pipeline-snapshot',
    },
    {
      caseKey: 'blocked',
      attemptId: blockedSnapshot.attemptId,
      gateState: blockedSnapshot.gateState,
      title: 'Blocked local pipeline snapshot',
      provenance: 'pipeline-snapshot',
    },
    {
      caseKey: 'error_merge_conflict',
      attemptId: errorSnapshot.attemptId,
      gateState: errorSnapshot.gateState,
      title: 'Error merge-conflict pipeline snapshot',
      provenance: 'pipeline-snapshot',
    },
  ]
}
