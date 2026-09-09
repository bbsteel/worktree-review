import { ReviewDetailPage } from '../pages/ReviewDetailPage.tsx'
import { useDataSource } from './data-source.ts'

/**
 * PM-010 final assembly: the detail page consumes the shell's single
 * ReviewDataSource instance (shared with the Overview, the demo case selector
 * and the environment badge) instead of constructing a second one.
 */
export function ReviewDetailRoute() {
  const { source } = useDataSource()
  return <ReviewDetailPage dataSource={source} />
}
