/**
 * HTTP client for /api/v1 (design 16). Same-origin only; mutation requests
 * carry an Idempotency-Key and a CSRF header. Error responses are mapped to
 * stable error codes; response bodies are validated by map-dto before use.
 */
import { ReviewNotFoundError } from '../sources/review-data-source.ts'
import type { OverviewView, ReviewSummaryView } from '../../domain/index.ts'
import type {
  AuditEventFilter,
  AuditEventPageView,
  AuthSessionView,
  BypassSubmissionView,
} from '../../domain/audit.ts'
import type { ReviewRunView } from '../../domain/review.ts'
import type {
  ComputePolicyDto,
  CreateReviewRequestDto,
  CreateReviewResponseDto,
  ProviderProfileDto,
  ProviderTestResultDto,
  RegisterComputePolicyRequestDto,
  RegisterRepositoryRequestDto,
  RegisterReviewPolicyRequestDto,
  RepositoryDto,
  RepositoryStatusDto,
  ReviewListDto,
  ReviewPolicyDto,
  SaveProviderProfileRequestDto,
} from './dto.ts'
import {
  DtoValidationError,
  mapAuditEventPageDto,
  mapAuthSessionDto,
  mapBypassSubmissionDto,
  mapOverviewDto,
  mapReviewRunDto,
  mapReviewSummaryDto,
} from './map-dto.ts'

export class ApiError extends Error {
  readonly code: string
  readonly httpStatus: number

  constructor(code: string, message: string, httpStatus: number) {
    super(message)
    this.name = 'ApiError'
    this.code = code
    this.httpStatus = httpStatus
  }
}

export class ResultUnavailableError extends Error {
  readonly attemptId: string

  constructor(attemptId: string) {
    super(`Result is not available for attempt ${attemptId}`)
    this.name = 'ResultUnavailableError'
    this.attemptId = attemptId
  }
}

export class IdempotencyConflictError extends Error {
  constructor(message: string) {
    super(message)
    this.name = 'IdempotencyConflictError'
  }
}

export interface ReviewApiClientConfig {
  /** Defaults to same-origin /api/v1. */
  baseUrl?: string
  fetchFn?: typeof fetch
  /**
   * Sent as X-CSRF-Token on mutation requests (design 19.1). When omitted,
   * the client bootstraps a per-process token from the same-origin
   * GET {baseUrl}/csrf-bootstrap endpoint before the first mutation and
   * retries a mutation once after refreshing the token on a CSRF 403.
   */
  csrfToken?: string | null
}

export interface ReviewListPage {
  runs: ReviewSummaryView[]
  nextCursor: string | null
}

const CSRF_FAILURE_CODES = new Set(['missing_csrf_token', 'invalid_csrf_token', 'csrf_rejected'])

export class ReviewApiClient {
  private readonly baseUrl: string
  private readonly fetchFn: typeof fetch
  private csrfToken: string | null
  private csrfBootstrap: Promise<string> | null = null

  constructor(config: ReviewApiClientConfig = {}) {
    this.baseUrl = config.baseUrl ?? '/api/v1'
    this.fetchFn = config.fetchFn ?? fetch.bind(globalThis)
    this.csrfToken = config.csrfToken ?? null
  }

  /**
   * Mutation CSRF token for the current deployment mode. The authorized
   * deployment issues a per-session token via GET /auth/session; the default
   * local mode falls back to the per-process /csrf-bootstrap token.
   */
  private async ensureCsrfToken(): Promise<string> {
    if (this.csrfToken !== null) {
      return this.csrfToken
    }
    this.csrfBootstrap ??= this.bootstrapCsrfToken()
    try {
      return await this.csrfBootstrap
    } catch (error) {
      this.csrfBootstrap = null
      throw error
    }
  }

  private async bootstrapCsrfToken(): Promise<string> {
    try {
      const session = await this.getAuthSession()
      if (session.authenticated && session.csrfToken !== null) {
        this.csrfToken = session.csrfToken
        return session.csrfToken
      }
    } catch {
      // Older or local-only server: fall through to the process-level token.
    }
    const response = await this.fetchFn(`${this.baseUrl}/csrf-bootstrap`, {
      method: 'GET',
      headers: { Accept: 'application/json' },
      credentials: 'same-origin',
    })
    if (!response.ok) {
      throw new ApiError(
        'csrf_bootstrap_failed',
        `CSRF bootstrap failed with HTTP ${response.status}.`,
        response.status,
      )
    }
    const parsed: unknown = await response.json()
    const token =
      typeof parsed === 'object' && parsed !== null && 'csrf_token' in parsed
        ? (parsed as { csrf_token?: unknown }).csrf_token
        : undefined
    if (typeof token !== 'string' || token === '') {
      throw new ApiError('csrf_bootstrap_failed', 'CSRF bootstrap returned no token.', response.status)
    }
    this.csrfToken = token
    return token
  }

  private async request<T>(
    method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
    path: string,
    options: { body?: unknown; idempotencyKey?: string } = {},
  ): Promise<T> {
    return this.requestWithCsrfRetry(method, path, options, true)
  }

  private async requestWithCsrfRetry<T>(
    method: 'GET' | 'POST' | 'PATCH' | 'DELETE',
    path: string,
    options: { body?: unknown; idempotencyKey?: string },
    allowCsrfRetry: boolean,
  ): Promise<T> {
    const headers: Record<string, string> = {
      Accept: 'application/json',
    }
    if (options.body !== undefined) {
      headers['Content-Type'] = 'application/json'
    }
    if (method !== 'GET') {
      if (options.idempotencyKey !== undefined) {
        headers['Idempotency-Key'] = options.idempotencyKey
      }
      headers['X-CSRF-Token'] = await this.ensureCsrfToken()
    }

    let response: Response
    try {
      response = await this.fetchFn(`${this.baseUrl}${path}`, {
        method,
        headers,
        credentials: 'same-origin',
        body: options.body === undefined ? undefined : JSON.stringify(options.body),
      })
    } catch (error) {
      throw new ApiError(
        'network_unreachable',
        error instanceof Error ? error.message : 'Network request failed',
        0,
      )
    }

    if (response.status === 404) {
      if (path.startsWith('/reviews/')) {
        throw new ReviewNotFoundError(path)
      }
      throw new ApiError('not_found', `Resource not found: ${path}`, 404)
    }

    const text = await response.text()
    let parsed: unknown = null
    if (text !== '') {
      try {
        parsed = JSON.parse(text)
      } catch {
        throw new ApiError('invalid_response', 'The server returned a non-JSON response.', response.status)
      }
    }

    if (!response.ok) {
      const errorRecord =
        typeof parsed === 'object' && parsed !== null && 'error' in parsed
          ? (parsed as { error: { code?: unknown; message?: unknown } }).error
          : null
      const code = typeof errorRecord?.code === 'string' ? errorRecord.code : 'unknown_error'
      const message =
        typeof errorRecord?.message === 'string'
          ? errorRecord.message
          : `Request failed with HTTP ${response.status}.`
      if (response.status === 403 && CSRF_FAILURE_CODES.has(code) && allowCsrfRetry) {
        // The server process restarted (new token) or the cached token went
        // stale: refresh once and retry the same request, keeping the same
        // Idempotency-Key so the retry cannot duplicate the mutation.
        this.csrfToken = null
        this.csrfBootstrap = null
        return this.requestWithCsrfRetry(method, path, options, false)
      }
      if (code === 'result_unavailable') {
        throw new ResultUnavailableError(path)
      }
      // Only the local-create idempotency collision uses this type. Other 409s
      // (Bypass standing/policy/conflict) stay ApiError so callers can refresh
      // on the real conflict code and HTTP status.
      if (code === 'idempotency_conflict') {
        throw new IdempotencyConflictError(message)
      }
      throw new ApiError(code, message, response.status)
    }

    return parsed as T
  }

  async getOverview(): Promise<OverviewView> {
    const dto = await this.request<unknown>('GET', '/overview')
    return mapOverviewDto(dto)
  }

  async getReviewRun(attemptId: string): Promise<ReviewRunView> {
    const dto = await this.request<unknown>('GET', `/reviews/${encodeURIComponent(attemptId)}`)
    return mapReviewRunDto(dto)
  }

  async listReviews(cursor: string | null = null): Promise<ReviewListPage> {
    const query = cursor === null ? '' : `?cursor=${encodeURIComponent(cursor)}`
    const dto = await this.request<ReviewListDto>('GET', `/reviews${query}`)
    if (!Array.isArray(dto.runs)) {
      throw new DtoValidationError('reviews', 'expected a runs array')
    }
    return {
      runs: dto.runs.map((run, index) => mapReviewSummaryDto(run, `runs[${index}]`)),
      nextCursor: dto.next_cursor ?? null,
    }
  }

  /** 202 + attempt locator; the server persists the attempt before responding. */
  async createReview(
    requestBody: CreateReviewRequestDto,
    idempotencyKey: string,
  ): Promise<CreateReviewResponseDto> {
    return this.request<CreateReviewResponseDto>('POST', '/reviews', {
      body: requestBody,
      idempotencyKey,
    })
  }

  async retryReview(attemptId: string, idempotencyKey: string): Promise<CreateReviewResponseDto> {
    return this.request<CreateReviewResponseDto>(
      'POST',
      `/reviews/${encodeURIComponent(attemptId)}/retry`,
      { idempotencyKey },
    )
  }

  /** Versioned terminal result; throws ResultUnavailableError while running. */
  async getReviewResult(attemptId: string): Promise<unknown> {
    return this.request<unknown>('GET', `/reviews/${encodeURIComponent(attemptId)}/result`)
  }

  async listRepositories(): Promise<RepositoryDto[]> {
    return this.request<RepositoryDto[]>('GET', '/repositories')
  }

  async registerRepository(requestBody: RegisterRepositoryRequestDto): Promise<RepositoryDto> {
    return this.request<RepositoryDto>('POST', '/repositories', { body: requestBody })
  }

  async getRepositoryStatus(repositoryId: string): Promise<RepositoryStatusDto> {
    return this.request<RepositoryStatusDto>(
      'GET',
      `/repositories/${encodeURIComponent(repositoryId)}/status`,
    )
  }

  async removeRepository(repositoryId: string): Promise<void> {
    await this.request<null>('DELETE', `/repositories/${encodeURIComponent(repositoryId)}`)
  }

  async listProviderProfiles(): Promise<ProviderProfileDto[]> {
    return this.request<ProviderProfileDto[]>('GET', '/provider-profiles')
  }

  async createProviderProfile(
    requestBody: SaveProviderProfileRequestDto,
  ): Promise<ProviderProfileDto> {
    return this.request<ProviderProfileDto>('POST', '/provider-profiles', { body: requestBody })
  }

  async updateProviderProfile(
    profileId: string,
    requestBody: SaveProviderProfileRequestDto,
  ): Promise<ProviderProfileDto> {
    return this.request<ProviderProfileDto>(
      'PATCH',
      `/provider-profiles/${encodeURIComponent(profileId)}`,
      { body: requestBody },
    )
  }

  async deleteProviderProfile(profileId: string): Promise<void> {
    await this.request<null>('DELETE', `/provider-profiles/${encodeURIComponent(profileId)}`)
  }

  /** Explicit connection test; may make a network or local-cli call. */
  async testProviderProfile(profileId: string): Promise<ProviderTestResultDto> {
    return this.request<ProviderTestResultDto>(
      'POST',
      `/provider-profiles/${encodeURIComponent(profileId)}/test`,
    )
  }

  async listReviewPolicies(): Promise<ReviewPolicyDto[]> {
    return this.request<ReviewPolicyDto[]>('GET', '/review-policies')
  }

  /** Register a trusted Review Policy from a server-side path (never from repo content). */
  async registerReviewPolicy(
    requestBody: RegisterReviewPolicyRequestDto,
  ): Promise<ReviewPolicyDto> {
    return this.request<ReviewPolicyDto>('POST', '/review-policies', { body: requestBody })
  }

  /** Register a trusted Compute Policy, optionally bound to a Provider Profile. */
  async registerComputePolicy(
    requestBody: RegisterComputePolicyRequestDto,
  ): Promise<ComputePolicyDto> {
    return this.request<ComputePolicyDto>('POST', '/compute-policies', { body: requestBody })
  }

  async getReviewPolicy(policyId: string): Promise<ReviewPolicyDto> {
    return this.request<ReviewPolicyDto>('GET', `/review-policies/${encodeURIComponent(policyId)}`)
  }

  async listComputePolicies(): Promise<ComputePolicyDto[]> {
    return this.request<ComputePolicyDto[]>('GET', '/compute-policies')
  }

  async getComputePolicy(policyId: string): Promise<ComputePolicyDto> {
    return this.request<ComputePolicyDto>(
      'GET',
      `/compute-policies/${encodeURIComponent(policyId)}`,
    )
  }

  /**
   * Current deployment auth session (P3 §4). A local-mode server answers with
   * `{authenticated: false}`; a very old server may 501/404, which maps to the
   * same local-mode view.
   */
  async getAuthSession(): Promise<AuthSessionView> {
    try {
      const dto = await this.request<Record<string, unknown>>('GET', '/auth/session')
      return mapAuthSessionDto(dto)
    } catch (error) {
      if (error instanceof ApiError && (error.httpStatus === 501 || error.httpStatus === 404)) {
        return {
          mode: 'local',
          authenticated: false,
          actorId: null,
          actorLogin: null,
          expiresAt: null,
          csrfToken: null,
          capabilities: { bypass: false, audit: false },
        }
      }
      throw error
    }
  }

  /** End the current authorized-mode session. Local mode answers 501. */
  async logout(): Promise<void> {
    await this.request<null>('POST', '/auth/logout', {})
  }

  /**
   * Accept the risk of one blocking finding (P3 §8.1). The actor identity
   * comes from the verified server-side session; the body carries only the
   * reason. Error codes map straight through: authentication_required /
   * session_expired (401), csrf_rejected (403), attempt_not_found /
   * finding_not_found (404; denied looks identical to missing),
   * bypass_not_standing / bypass_gate_error / bypass_not_blocking /
   * bypass_policy_changed / bypass_conflict (409 as ApiError — not an
   * IdempotencyConflictError), bypass_reason_invalid (422),
   * github_authorization_unavailable / audit_store_unavailable (503),
   * capability_unavailable (501).
   */
  async bypassFinding(
    attemptId: string,
    fingerprint: string,
    reason: string,
    idempotencyKey?: string,
  ): Promise<BypassSubmissionView> {
    const dto = await this.request<Record<string, unknown>>(
      'POST',
      `/reviews/${encodeURIComponent(attemptId)}/findings/${encodeURIComponent(fingerprint)}/bypass`,
      { body: { reason }, ...(idempotencyKey === undefined ? {} : { idempotencyKey }) },
    )
    return mapBypassSubmissionDto(dto)
  }

  /**
   * Newest-first page of append-only audit events (P3 §8.3). The repository
   * filter is mandatory; the cursor resumes the previous page exactly.
   */
  async listAuditEvents(
    filter: AuditEventFilter,
    cursor: string | null = null,
    limit = 50,
  ): Promise<AuditEventPageView> {
    const params = new URLSearchParams({ repository: filter.repository, limit: String(limit) })
    if (filter.eventType) params.set('event_type', filter.eventType)
    if (filter.attemptId) params.set('attempt_id', filter.attemptId)
    if (filter.pullRequestNumber !== undefined) {
      params.set('pull_request_number', String(filter.pullRequestNumber))
    }
    if (cursor !== null) params.set('cursor', cursor)
    const dto = await this.request<Record<string, unknown>>(
      'GET',
      `/audit-events?${params.toString()}`,
    )
    return mapAuditEventPageDto(dto)
  }
}
