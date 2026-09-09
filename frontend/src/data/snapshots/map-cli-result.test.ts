import { describe, expect, it } from 'vitest'
import { MOCK_DATA_BADGE } from '../fixtures/constants.ts'
import { blockedCase } from '../fixtures/blocked.ts'
import { PIPELINE_SNAPSHOT_BADGE, mapPipelineSnapshot } from './map-cli-result.ts'
import { getPipelineSnapshot, listPipelineSnapshots, pipelineSnapshots } from './index.ts'
import type { PipelineSnapshotFile } from './cli-result.ts'
import blockedFile from './blocked.json'
import errorFile from './error_merge_conflict.json'

describe('pipeline snapshots', () => {
  it('maps local Pipeline results without GitHub PR fields', () => {
    const blocked = mapPipelineSnapshot(blockedFile as PipelineSnapshotFile)
    expect(blocked.source.kind).toBe('local-committed-ref')
    expect(blocked.authority).toBe('local_non_authoritative')
    expect(blocked.gateState).toBe('blocked')
    if (blocked.source.kind === 'local-committed-ref') {
      expect(blocked.source.repositoryDisplayName).toBe('demo/blocked-local')
    }
    expect(JSON.stringify(blocked)).not.toContain('pullRequestNumber')
    expect(JSON.stringify(blocked)).not.toContain('github-pull-request')
  })

  it('keeps merge-conflict Error without a fabricated identity', () => {
    const errorRun = mapPipelineSnapshot(errorFile as PipelineSnapshotFile)
    expect(errorRun.gateState).toBe('error')
    expect(errorRun.identity.reviewIdentity).toBeNull()
    expect(errorRun.identity.mergeTreeOid).toBeNull()
    expect(errorRun.failure?.stage).toBe('construct-merge')
  })

  it('uses a different badge and directory from handwritten GitHub mocks', () => {
    expect(PIPELINE_SNAPSHOT_BADGE).toBe('Pipeline snapshot · local')
    expect(PIPELINE_SNAPSHOT_BADGE).not.toBe(MOCK_DATA_BADGE)
    expect(blockedCase.source.kind).toBe('github-pull-request')
    expect(listPipelineSnapshots().every((item) => item.provenance === 'pipeline-snapshot')).toBe(true)
    expect(pipelineSnapshots.every((run) => run.source.kind !== 'github-pull-request')).toBe(true)
  })

  it('replays snapshots from JSON without looking up a network attempt', () => {
    const first = pipelineSnapshots[0]
    expect(first).toBeDefined()
    if (!first) {
      return
    }
    expect(getPipelineSnapshot(first.attemptId)?.attemptId).toBe(first.attemptId)
  })
})
