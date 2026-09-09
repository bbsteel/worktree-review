import { RouterProvider } from 'react-router'
import { router } from './router.tsx'
import { ThemeProvider } from './ThemeProvider.tsx'

export function App() {
  return (
    <ThemeProvider>
      <RouterProvider router={router} />
    </ThemeProvider>
  )
}
