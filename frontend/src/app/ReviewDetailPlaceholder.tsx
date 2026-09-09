import { useParams } from 'react-router'

export function ReviewDetailPlaceholder() {
  const { attemptId } = useParams()

  return (
    <main>
      <h1>Review Detail</h1>
      <p>Empty route owned by the frontend foundation until Agent B replaces it.</p>
      <p>
        Attempt ID: <span data-testid="attempt-id">{attemptId ?? 'missing'}</span>
      </p>
    </main>
  )
}
