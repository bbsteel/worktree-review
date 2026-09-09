import { RouterProvider } from 'react-router'
import { router } from './router.tsx'

export function App() {
  return <RouterProvider router={router} />
}
